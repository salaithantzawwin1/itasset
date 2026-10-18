"""M5 tests (DEVELOPMENT.md §11 roles, §25 audit readiness).

Covers: LDAP role-mapping logic (group CN → Django role, viewer fallback),
ActivityLog list access (admin/auditor only), audit session lifecycle
(start → scan → duplicate → close → found/missing/unexpected report) and its
role guards.
"""

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.django_db


@pytest.fixture
def groups(db):
    from django.contrib.auth.models import Group

    roles = ("admin", "technician", "auditor", "viewer")
    return {n: Group.objects.get_or_create(name=n)[0] for n in roles}


def _user(django_user_model, groups, username, role):
    u = django_user_model.objects.create_user(username, f"{username}@x.com", "pass12345!")
    u.groups.add(groups[role])
    return u


# ---------------------------------------------------------------- LDAP mapping
# These test `rolesync` (pure logic) so they run without python-ldap, which
# needs OS build tools and is only installed on the Ubuntu deploy target.
LDAP_SETTINGS = SimpleNamespace(
    LDAP_GROUP_ADMIN="IT-Admins",
    LDAP_GROUP_TECHNICIAN="IT-Technicians",
    LDAP_GROUP_AUDITOR="IT-Auditors",
    LDAP_GROUP_VIEWER="IT-Users",
)


def test_ldap_role_mapping_basic():
    from apps.accounts.rolesync import wanted_roles

    got = wanted_roles({"it-admins", "cn=something,dc=example"}, LDAP_SETTINGS)
    assert got == {"admin"}


def test_ldap_role_mapping_nested_falls_to_technician():
    from apps.accounts.rolesync import wanted_roles

    assert wanted_roles({"it-technicians"}, LDAP_SETTINGS) == {"technician"}  # case-insensitive


def test_ldap_unmapped_user_gets_viewer():
    from apps.accounts.rolesync import wanted_roles

    assert wanted_roles({"some-other-group"}, LDAP_SETTINGS) == {"viewer"}  # least privilege


def test_ldap_backend_glue_importable_only_when_enabled(settings):
    """The glue module needs python-ldap; it must NOT be imported when off."""
    assert settings.LDAP_ENABLED is False
    import sys

    assert "apps.accounts.ldap" not in sys.modules  # never imported with LDAP off


# ---------------------------------------------------------------- ActivityLog UI
def test_activity_log_requires_admin_or_auditor(client, django_user_model, groups):
    from apps.audit.models import ActivityLog

    ActivityLog.objects.create(action="check_out", object_repr="X")

    client.force_login(_user(django_user_model, groups, "au_viewer", "viewer"))
    assert client.get("/activity/").status_code == 403

    client.force_login(_user(django_user_model, groups, "au_auditor", "auditor"))
    r = client.get("/activity/")
    assert r.status_code == 200
    assert "X" in r.content.decode()

    client.force_login(_user(django_user_model, groups, "au_admin", "admin"))
    assert client.get("/activity/").status_code == 200


def test_activity_log_filter_by_action(client, django_user_model, groups):
    from apps.audit.models import ActivityLog

    ActivityLog.objects.create(action="check_out", object_repr="KEEP")
    ActivityLog.objects.create(action="import", object_repr="SKIP")
    client.force_login(_user(django_user_model, groups, "au_f", "auditor"))
    r = client.get("/activity/?action=import")
    body = r.content.decode()
    assert "SKIP" in body and "KEEP" not in body


# ---------------------------------------------------------------- audit sessions
def test_audit_session_lifecycle(client, django_user_model, groups, site, asset_factory):
    from apps.assets.models import Asset
    from apps.audit.models import AuditSession
    from apps.people.models import Site

    tech = _user(django_user_model, groups, "aud_tech", "technician")
    expected = asset_factory(site=site)  # at the user's site
    other_site = Site.objects.create(name="Other", code="other")
    Asset.objects.create(
        asset_tag="FOREIGN-1", category=expected.category, site=other_site, status="AVAILABLE"
    )

    client.force_login(tech)
    # start (site defaults to the user's person site; site passed explicitly here)
    r = client.post("/audits/start/", {"site": site.pk})
    session = AuditSession.objects.first()
    assert session is not None and session.status == "OPEN"
    assert r.status_code == 302

    # scan: expected asset, a duplicate, and an unknown tag
    client.post(f"/audits/{session.pk}/scan/", {"asset_tag": expected.asset_tag})
    client.post(f"/audits/{session.pk}/scan/", {"asset_tag": expected.asset_tag})  # dup
    client.post(f"/audits/{session.pk}/scan/", {"asset_tag": "FOREIGN-1"})  # other site
    client.post(f"/audits/{session.pk}/scan/", {"asset_tag": "GHOST-9"})  # unknown
    assert session.items.count() == 3  # dup is idempotent

    # close → report
    client.post(f"/audits/{session.pk}/close/")
    session.refresh_from_db()
    assert session.status == "CLOSED" and session.closed_at

    r = client.get(f"/audits/{session.pk}/report/")
    body = r.content.decode()
    assert expected.asset_tag in body  # found row listed
    assert "FOREIGN-1" in body  # unexpected (wrong site)
    assert "GHOST-9" in body  # unexpected (unknown)


def test_audit_scan_readonly_denied(client, django_user_model, groups, site, asset_factory):
    viewer = _user(django_user_model, groups, "aud_v", "viewer")
    from apps.audit.models import AuditSession

    session = AuditSession.objects.create(site=site)
    client.force_login(viewer)
    assert client.get(f"/audits/{session.pk}/").status_code == 403
    assert client.post(f"/audits/{session.pk}/scan/", {"asset_tag": "X"}).status_code == 403


def test_audit_missing_assets_reported(client, django_user_model, groups, site):
    from apps.assets.models import Asset, Category
    from apps.audit.models import AuditSession

    cat, _ = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})
    a1 = Asset.objects.create(asset_tag="M-1", category=cat, site=site, status="AVAILABLE")
    Asset.objects.create(asset_tag="M-2", category=cat, site=site, status="AVAILABLE")
    session = AuditSession.objects.create(site=site)
    session.items.create(asset_tag="M-1", asset=a1)

    client.force_login(_user(django_user_model, groups, "aud_r", "auditor"))
    body = client.get(f"/audits/{session.pk}/report/").content.decode()
    assert "M-2" in body  # missing shows up
    assert "M-1" not in body.split("Missing")[1].split("Unexpected")[0]  # not in missing table
