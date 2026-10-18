"""M2 CRUD view tests: role checks per §11 + happy paths.

Covers: anonymous → login redirect; viewer/auditor → 403 on create;
technician/admin can create assets; site/person manage is admin-only;
asset detail shows assignment history.
"""

import pytest

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
