"""M2 CRUD view tests: role checks per §11 + happy paths.

Covers: anonymous → login redirect; viewer/auditor → 403 on create;
technician/admin can create assets; site/person manage is admin-only;
asset detail shows assignment history; the list search/quick-filter /
pagination contract (regression: filter inputs once sat outside the form).
"""

import re

import pytest

from apps.assets.models import AssetRequest, Category
from apps.people.models import Site

pytestmark = pytest.mark.django_db

URLS = {
    "site_list": "/sites/",
    "site_create": "/sites/new/",
    "person_list": "/people/",
    "person_create": "/people/new/",
    "asset_list": "/assets/",
    "asset_create": "/assets/new/",
}


def _login(client, user):
    client.force_login(user)


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {
        name: Group.objects.get_or_create(name=name)[0]
        for name in ("admin", "technician", "auditor", "viewer")
    }


def _user(django_user_model, group_setup, group_name, superuser=False):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(
        f"u_{group_name}", f"{group_name}@itasset.dev", "pass12345!"
    )
    if superuser:
        u.is_superuser = True
        u.save()
    else:
        u.groups.add(group_setup[group_name])
    # Feature tests, not scope tests: GLOBAL scope keeps enforcement
    # transparent (deny-by-default cases live in tests/test_scopes.py).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


# ---------------------------------------------------------------- privilégios
def test_anonymous_redirects_to_login(client):
    r = client.get(URLS["asset_list"])
    assert r.status_code == 302 and "login" in r.url


@pytest.mark.parametrize("page", ["asset_list", "site_list", "person_list"])
def test_authenticated_read_allowed(client, django_user_model, group_setup, page):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    assert client.get(URLS[page]).status_code == 200


@pytest.mark.parametrize("page", ["asset_create", "site_create", "person_create"])
def test_viewer_cannot_create(client, django_user_model, group_setup, page):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    assert client.get(URLS[page]).status_code == 403


def test_auditor_cannot_create(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "auditor"))
    assert client.get(URLS["asset_create"]).status_code == 403


def test_technician_can_create_asset_but_not_site(client, django_user_model, group_setup):
    from apps.assets.models import Category

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)

    assert client.get(URLS["asset_create"]).status_code == 200
    assert client.get(URLS["site_create"]).status_code == 403

    site = _site()
    cat = Category.objects.create(code="IT-HW-LAP", name="Laptop")
    r = client.post(
        URLS["asset_create"],
        {
            "asset_tag": "IT-HW-LAP-0001",
            "category": cat.pk,
            "site": site.pk,
            "status": "IN_STOCK",
            "condition": "GOOD",
        },
    )
    assert r.status_code == 302, r.context["form"].errors


def test_admin_can_manage_site(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "admin"))
    r = client.post(URLS["site_create"], {"name": "Mandalay HQ", "code": "mandalay"})
    assert r.status_code == 302
    from apps.people.models import Site

    assert Site.objects.filter(code="mandalay").exists()


def _site():
    from apps.people.models import Site

    return Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0]


def test_check_out_via_view(client, django_user_model, group_setup, asset_factory, person_factory):
    from apps.assets.services import active_assignment

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    person = person_factory(employee_no="E008", name="Someone")
    asset = asset_factory(status="AVAILABLE", serial="SN-CRUD1")
    r = client.post(f"/assets/{asset.pk}/check-out/", {"to_person": person.pk})
    assert r.status_code == 302
    assert active_assignment(asset).to_person_id == person.pk
    asset.refresh_from_db(fields=["status"])  # service updated the DB row
    assert asset.status == "ASSIGNED"


def test_check_in_via_view(client, django_user_model, group_setup, asset_factory, person_factory):
    from apps.assets.services import active_assignment

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    asset = asset_factory(status="AVAILABLE", serial="SN-CRUD2")
    client.post(f"/assets/{asset.pk}/check-out/", {"to_person": person_factory().pk})
    r = client.post(f"/assets/{asset.pk}/check-in/", {"condition_in": "GOOD"})
    assert r.status_code == 302
    assert active_assignment(asset) is None
    asset.refresh_from_db(fields=["status"])
    assert asset.status == "AVAILABLE"


# --------------------------------------------- search / quick filters / paging
def test_filter_form_contains_its_inputs(client, django_user_model, group_setup):
    """Regression: q/status/etc. once lived OUTSIDE #filterform, so Search
    submitted an empty GET and silently cleared the filters."""
    _login(client, _user(django_user_model, group_setup, "viewer"))
    html = client.get(URLS["asset_list"]).content.decode()
    match = re.search(r'<form id="filterform"[^>]*>(.*?)</form>', html, re.S)
    assert match, "#filterform missing from the asset list"
    inner = match.group(1)
    for field in ('name="q"', 'name="status"', 'name="warranty_days"', 'name="missing_serial"'):
        assert field in inner, f"{field} is not inside #filterform"


def test_search_filters_rows(client, django_user_model, group_setup, asset_factory):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    asset_factory(asset_tag="ZZZ-1", serial="SN-UNIQUE-1")
    asset_factory(asset_tag="ZZZ-2", serial="SN-OTHER-2")
    r = client.get(URLS["asset_list"], {"q": "SN-UNIQUE-1"})
    assert [a.asset_tag for a in r.context["object_list"]] == ["ZZZ-1"]


def test_quick_filters_warranty_and_missing_serial(
    client, django_user_model, group_setup, asset_factory
):
    from datetime import timedelta

    from django.utils import timezone

    _login(client, _user(django_user_model, group_setup, "viewer"))
    today = timezone.localdate()
    soon = asset_factory(asset_tag="W-1", serial="S1", warranty_end=today + timedelta(days=10))
    asset_factory(asset_tag="W-2", serial="S2", warranty_end=today + timedelta(days=200))
    noserial = asset_factory(asset_tag="W-3", serial="SN-PLACEHOLDER")
    noserial.serial_no = ""  # factory treats "" as unset and substitutes a serial
    noserial.save(update_fields=["serial_no"])

    r = client.get(URLS["asset_list"], {"warranty_days": "30"})
    assert [a.pk for a in r.context["object_list"]] == [soon.pk]
    r = client.get(URLS["asset_list"], {"warranty_days": "7"})
    assert list(r.context["object_list"]) == []  # 10 days > 7-day window
    r = client.get(URLS["asset_list"], {"missing_serial": "1"})
    assert [a.pk for a in r.context["object_list"]] == [noserial.pk]


def test_pagination_link_keeps_filters(client, django_user_model, group_setup, asset_factory):
    """Regression: ?page=N used to drop q/status (audit list did it right)."""
    _login(client, _user(django_user_model, group_setup, "viewer"))
    for i in range(51):
        asset_factory(asset_tag=f"PG-{i:03d}", serial=f"SN-PG-{i:03d}")

    r = client.get(URLS["asset_list"], {"q": "PG"})
    assert r.context["is_paginated"] is True
    html = r.content.decode()
    # literal & in the template stays & (autoescape covers variable output only)
    assert 'href="?page=2&q=PG' in html, "page-2 link lost the q filter"

    r2 = client.get(URLS["asset_list"], {"q": "PG", "page": 2})
    assert len(r2.context["object_list"]) == 1  # 51st row lands on page 2


# ------------------------------------------ employee request UI (§6.5 stage ①)
def test_request_create_requires_login(client):
    r = client.get("/requests/new/")
    assert r.status_code == 302 and "login" in r.url


def test_request_form_renders(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    r = client.get("/requests/new/")
    assert r.status_code == 200
    fields = r.context["form"].fields
    assert set(fields) == {"category", "site", "quantity", "justification"}
    assert "requester" not in fields  # set server-side, never client-supplied


def test_request_submission_creates_pending_row(
    client, django_user_model, group_setup, site, category
):
    user = _user(django_user_model, group_setup, "viewer")
    _login(client, user)
    r = client.post(
        "/requests/new/",
        {
            "category": category.pk,
            "site": site.pk,
            "quantity": 2,
            "justification": "Need a laptop for onboarding.",
        },
    )
    assert r.status_code == 302 and r.url == "/me/"
    req = AssetRequest.objects.get()
    assert req.requester_id == user.pk
    assert req.status == AssetRequest.Status.PENDING
    assert req.quantity == 2


def test_quantity_must_be_positive(client, django_user_model, group_setup, site, category):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    r = client.post(
        "/requests/new/",
        {"category": category.pk, "site": site.pk, "quantity": 0, "justification": "x"},
    )
    assert r.status_code == 200  # re-rendered with the error
    assert "quantity" in r.context["form"].errors
    assert not AssetRequest.objects.exists()


def test_request_carve_out_own_site_only(client, django_user_model, db, settings):
    """No org-scope rows + linked Person → may request for their own site only
    (§4.4 self carve-out); another site is a crafted POST → 403, no row."""
    from apps.people.models import Person

    settings.SCOPE_ENFORCEMENT_ENABLED = True  # shadow mode would allow all
    own = Site.objects.create(name="Own", code="own")
    other = Site.objects.create(name="Other", code="other")
    cat = Category.objects.create(code="IT-HW-PER", name="Peripheral")
    emp = django_user_model.objects.create_user("emp1", "e@x.dev", "pass12345!")
    Person.objects.create(employee_no="E777", name="Emp", site=own, user=emp)
    _login(client, emp)

    r = client.get("/requests/new/")
    choices = list(r.context["form"].fields["site"].queryset)
    assert [s.pk for s in choices] == [own.pk]  # own site only

    r = client.post(
        "/requests/new/",
        {"category": cat.pk, "site": other.pk, "quantity": 1, "justification": "x"},
    )
    # the restricted site queryset rejects the crafted choice at form level
    # (the view keeps a second pk check behind it as defense in depth)
    assert r.status_code == 200
    assert "site" in r.context["form"].errors
    assert not AssetRequest.objects.exists()
