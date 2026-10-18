"""API surface additions (gap §3.5): org reference tree + ordering allowlist."""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPass!23"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {n: Group.objects.get_or_create(name=n)[0] for n in ("admin", "technician", "viewer")}


def _login(api, django_user_model, group_setup, name="viewer"):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(f"surf_{name}", f"{name}@x.com", PASSWORD)
    u.groups.add(group_setup[name])
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="api-surface-test fixture",
        created_by=u,
    )
    api.login(username=u.username, password=PASSWORD)
    return u


# --------------------------------------------------------------------------- org tree


def test_org_sites_anonymous_401(api):
    assert api.get("/api/v1/org/sites/").status_code == 401


def test_org_sites_returns_tree_sorted_with_departments(api, django_user_model, group_setup, site):
    from apps.people.models import Department, Site

    Department.objects.create(name="Finance", site=site)
    Department.objects.create(name="IT", site=site)
    mandalay = Site.objects.create(name="Mandalay", code="mandalay")
    Department.objects.create(name="Ops", site=mandalay)

    _login(api, django_user_model, group_setup)
    body = api.get("/api/v1/org/sites/").json()

    assert [s["code"] for s in body] == ["mandalay", "yangon"]
    assert [d["name"] for d in body[0]["departments"]] == ["Ops"]
    assert [d["name"] for d in body[1]["departments"]] == ["Finance", "IT"]
    assert body[1]["name"] == "Yangon HQ" and body[1]["is_active"] is True


# --------------------------------------------------------------------------- ordering allowlist


def test_asset_list_default_order_unchanged(api, django_user_model, group_setup, asset_factory):
    _login(api, django_user_model, group_setup)
    asset_factory(asset_tag="IT-HW-LAP-9003")
    asset_factory(asset_tag="IT-HW-LAP-9001")
    asset_factory(asset_tag="IT-HW-LAP-9002")

    tags = [a["asset_tag"] for a in api.get("/api/v1/assets/").json()["results"]]
    assert tags == ["IT-HW-LAP-9001", "IT-HW-LAP-9002", "IT-HW-LAP-9003"]


def test_asset_list_ordering_allowlist_applies(api, django_user_model, group_setup, asset_factory):
    _login(api, django_user_model, group_setup)
    asset_factory(asset_tag="IT-HW-LAP-9011")
    asset_factory(asset_tag="IT-HW-LAP-9012")
    asset_factory(asset_tag="IT-HW-LAP-9013")

    desc_url = "/api/v1/assets/?ordering=-asset_tag"
    desc = [a["asset_tag"] for a in api.get(desc_url).json()["results"]]
    assert desc == ["IT-HW-LAP-9013", "IT-HW-LAP-9012", "IT-HW-LAP-9011"]

    # multi-field: primary + descending secondary
    multi = api.get("/api/v1/assets/?ordering=status,-asset_tag").json()["results"]
    assert multi[0]["asset_tag"] == "IT-HW-LAP-9013"


def test_asset_list_ordering_invalid_field_400(api, django_user_model, group_setup):
    _login(api, django_user_model, group_setup)
    r = api.get("/api/v1/assets/?ordering=evil_field")
    assert r.status_code == 400
    body = r.json()
    detail = body["detail"]
    message = detail[0] if isinstance(detail, list) else detail
    assert "invalid ordering field(s): evil_field" in message
    assert "asset_tag" in message  # the allowed list is in the error
    assert body["code"] and body["correlationId"]  # envelope still applies
