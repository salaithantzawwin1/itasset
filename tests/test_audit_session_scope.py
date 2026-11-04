"""Audit-session scope/IDOR tests (design §5.2, §6).

The session screens used to fetch by pk with no scope check, so a technician
scoped to one site could open, scan into, close or read the report of another
site's session. These pin the enforced behaviour: out-of-scope sessions are
HTTP 404 (identical to missing), and a session cannot be started for a site
outside the caller's scope.
"""

from datetime import date

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

from apps.audit.models import AuditItem, AuditSession
from apps.core.models import UserAccessScope
from apps.people.models import Person, Site

pytestmark = pytest.mark.django_db


@pytest.fixture
def sites(db):
    return (
        Site.objects.create(name="Site A", code="site-a"),
        Site.objects.create(name="Site B", code="site-b"),
    )


@pytest.fixture
def sessions(sites):
    site_a, site_b = sites
    return (
        AuditSession.objects.create(site=site_a, status=AuditSession.Status.OPEN),
        AuditSession.objects.create(site=site_b, status=AuditSession.Status.OPEN),
    )


def _scoped_tech(django_user_model, site, username="tech_a"):
    user = django_user_model.objects.create_user(username, f"{username}@x.com", "pass12345!")
    user.groups.add(Group.objects.get_or_create(name="technician")[0])
    UserAccessScope.objects.create(
        user=user,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=site,
        valid_from=date(2020, 1, 1),
        reason="audit scope test",
        created_by=user,
    )
    return user


@pytest.fixture(autouse=True)
def _enforced(settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True


def test_session_detail_is_404_out_of_scope(client, django_user_model, sites, sessions):
    site_a, site_b = sites
    client.force_login(_scoped_tech(django_user_model, site_a))
    in_scope, out_of_scope = sessions

    assert client.get(reverse("audit-session", args=[in_scope.pk])).status_code == 200
    assert client.get(reverse("audit-session", args=[out_of_scope.pk])).status_code == 404


def test_scan_and_close_are_404_out_of_scope(client, django_user_model, sites, sessions):
    site_a, site_b = sites
    client.force_login(_scoped_tech(django_user_model, site_a))
    _, foreign = sessions

    scan = client.post(reverse("audit-scan", args=[foreign.pk]), {"asset_tag": "X-1"})
    assert scan.status_code == 404
    assert not AuditItem.objects.filter(session=foreign, asset_tag="X-1").exists()

    close = client.post(reverse("audit-close", args=[foreign.pk]))
    assert close.status_code == 404
    foreign.refresh_from_db()
    assert foreign.status == AuditSession.Status.OPEN


def test_report_is_404_out_of_scope(client, django_user_model, sites, sessions):
    site_a, site_b = sites
    client.force_login(_scoped_tech(django_user_model, site_a))
    _, foreign = sessions

    assert client.get(reverse("audit-report", args=[foreign.pk])).status_code == 404


def test_cannot_start_a_session_for_an_out_of_scope_site(client, django_user_model, sites):
    site_a, site_b = sites
    user = _scoped_tech(django_user_model, site_a)
    Person.objects.create(employee_no="E-1", name="Tech A", site=site_a, user=user)
    client.force_login(user)

    blocked = client.post(reverse("audit-start"), {"site": site_b.pk})
    assert blocked.status_code == 404
    assert not AuditSession.objects.filter(site=site_b).exists()

    allowed = client.post(reverse("audit-start"), {"site": site_a.pk})
    assert allowed.status_code == 302
    assert AuditSession.objects.filter(site=site_a).exists()


def test_list_only_shows_own_scope(client, django_user_model, sites, sessions):
    site_a, site_b = sites
    user = _scoped_tech(django_user_model, site_a)
    Person.objects.create(employee_no="E-1", name="Tech A", site=site_a, user=user)
    client.force_login(user)

    body = client.get(reverse("audit-sessions")).content.decode()
    assert "site-a" in body or "Site A" in body
    assert "Site B" not in body
