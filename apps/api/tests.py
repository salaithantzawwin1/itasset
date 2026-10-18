"""API tests (M3; DEVELOPMENT.md §10/§11/§16).

Covers: auth matrix (anonymous 401, viewer read-only, technician+ mutations),
token auth for scanner clients, list filters (?site/?status/?q), lookup by
asset_tag, check-out/check-in/receive via service layer, conflict → 409,
scan payload.
"""

import pytest
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {
        n: Group.objects.get_or_create(name=n)[0]
        for n in ("admin", "technician", "auditor", "viewer")
    }


def _user(django_user_model, group_setup, name):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(f"api_{name}", f"{name}@x.com", "pass12345!")
    u.groups.add(group_setup[name])
    # These are feature tests, not scope tests: a GLOBAL scope keeps scope
    # enforcement transparent (deny-by-default users are covered in
    # tests/test_scopes.py).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


# ---------------------------------------------------------------- auth matrix
def test_anonymous_get_assets_401(api):
    assert api.get("/api/v1/assets/").status_code == 401


def test_token_auth_flow(api, django_user_model, group_setup, asset_factory):
    u = _user(django_user_model, group_setup, "viewer")
    r = api.post(
        "/api/v1/auth/token/", {"username": u.username, "password": "pass12345!"}, format="json"
    )
    assert r.status_code == 200 and "token" in r.json()

    api.credentials(HTTP_AUTHORIZATION=f"Token {r.json()['token']}")
    assert api.get("/api/v1/assets/").status_code == 200


def test_bad_credentials_401(api):
    r = api.post("/api/v1/auth/token/", {"username": "nope", "password": "wrong"}, format="json")
    assert r.status_code == 401


def test_viewer_can_read_but_not_mutate(api, django_user_model, group_setup, asset_factory):
    u = _user(django_user_model, group_setup, "viewer")
    api.force_authenticate(u)
    asset = asset_factory(status="AVAILABLE")
    assert api.get("/api/v1/assets/").status_code == 200
    r = api.post(
        f"/api/v1/assets/{asset.asset_tag}/check-out/", {"employee_no": "E999"}, format="json"
    )
    assert r.status_code == 403


# ---------------------------------------------------------------- list + lookup
def test_list_filters(api, django_user_model, group_setup, asset_factory, site):
    from apps.people.models import Site

    other = Site.objects.create(name="Mandalay", code="mandalay")
    api.force_authenticate(_user(django_user_model, group_setup, "viewer"))
    asset_factory(asset_tag="IT-HW-LAP-9301", status="AVAILABLE", site=site)
    asset_factory(asset_tag="IT-HW-LAP-9302", status="ASSIGNED", site=other)

    assert api.get("/api/v1/assets/?status=AVAILABLE").json()["count"] == 1
    assert api.get(f"/api/v1/assets/?site={other.code}").json()["count"] == 1
    assert api.get("/api/v1/assets/?q=9301").json()["count"] == 1


def test_detail_by_asset_tag(api, django_user_model, group_setup, asset_factory):
    api.force_authenticate(_user(django_user_model, group_setup, "viewer"))
    asset = asset_factory(asset_tag="IT-HW-LAP-9303")
    r = api.get(f"/api/v1/assets/{asset.asset_tag}/")
    assert r.status_code == 200
    assert r.json()["asset_tag"] == "IT-HW-LAP-9303"


# ---------------------------------------------------------------- lifecycle
def test_check_out_then_conflict_then_check_in(
    api, django_user_model, group_setup, asset_factory, person_factory
):
    tech = _user(django_user_model, group_setup, "technician")
    api.force_authenticate(tech)
    person = person_factory(employee_no="E9401")
    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9401")

    r = api.post(
        f"/api/v1/assets/{asset.asset_tag}/check-out/",
        {"employee_no": person.employee_no},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["status"] == "ASSIGNED"
    assert r.json()["holder"]["employee_no"] == "E9401"

    # double check-out → 409 conflict (service-layer guard, RFC7807-ish body)
    r2 = api.post(
        f"/api/v1/assets/{asset.asset_tag}/check-out/",
        {"employee_no": person.employee_no},
        format="json",
    )
    assert r2.status_code == 409
    assert "detail" in r2.json()

    r3 = api.post(f"/api/v1/assets/{asset.asset_tag}/check-in/", {}, format="json")
    assert r3.status_code == 200
    assert r3.json()["status"] == "AVAILABLE"
    assert r3.json()["holder"] is None


def test_check_in_without_assignment_409(api, django_user_model, group_setup, asset_factory):
    api.force_authenticate(_user(django_user_model, group_setup, "technician"))
    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9402")
    r = api.post(f"/api/v1/assets/{asset.asset_tag}/check-in/", {}, format="json")
    assert r.status_code == 409


def test_receive_in_stock_to_available(api, django_user_model, group_setup, asset_factory):
    api.force_authenticate(_user(django_user_model, group_setup, "technician"))
    asset = asset_factory(status="IN_STOCK", asset_tag="IT-HW-LAP-9403")
    r = api.post(f"/api/v1/assets/{asset.asset_tag}/receive/", {}, format="json")
    assert r.status_code == 200
    assert r.json()["status"] == "AVAILABLE"


def test_technician_cannot_delete_403(api, django_user_model, group_setup, asset_factory):
    """§11: delete is admin-only, even on the API (web UI matches)."""
    api.force_authenticate(_user(django_user_model, group_setup, "technician"))
    asset = asset_factory(asset_tag="IT-HW-LAP-9601")
    assert api.delete(f"/api/v1/assets/{asset.asset_tag}/").status_code == 403
    assert api.get(f"/api/v1/assets/{asset.asset_tag}/").status_code == 200  # still there


def test_admin_delete_conflict_with_history_then_success(
    api, django_user_model, group_setup, asset_factory, person_factory
):
    from apps.assets import services

    api.force_authenticate(_user(django_user_model, group_setup, "admin"))
    person = person_factory(employee_no="E9611")
    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9611")

    # with assignment history: PROTECT → 409, asset survives
    services.check_out(asset, person, actor=None)
    services.check_in(asset)
    r = api.delete(f"/api/v1/assets/{asset.asset_tag}/")
    assert r.status_code == 409
    assert api.get(f"/api/v1/assets/{asset.asset_tag}/").status_code == 200

    # clean asset (no history): delete succeeds
    fresh = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9612")
    assert api.delete(f"/api/v1/assets/{fresh.asset_tag}/").status_code == 204
    assert api.get(f"/api/v1/assets/{fresh.asset_tag}/").status_code == 404


def test_unknown_person_404(api, django_user_model, group_setup, asset_factory):
    api.force_authenticate(_user(django_user_model, group_setup, "technician"))
    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9404")
    r = api.post(
        f"/api/v1/assets/{asset.asset_tag}/check-out/", {"employee_no": "NOBODY"}, format="json"
    )
    assert r.status_code == 404


# ---------------------------------------------------------------- scanner
def test_scan_payload(api, django_user_model, group_setup, asset_factory, person_factory):
    from apps.assets import services

    api.force_authenticate(_user(django_user_model, group_setup, "technician"))
    person = person_factory(employee_no="E9501")
    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-9501")
    services.check_out(asset, person, actor=None)

    r = api.get("/api/v1/scan/IT-HW-LAP-9501/")
    assert r.status_code == 200
    body = r.json()
    assert body["holder"]["employee_no"] == "E9501"
    assert body["can_check_out"] is False
    assert body["can_check_in"] is True


def test_scan_unknown_tag_404(api, django_user_model, group_setup):
    api.force_authenticate(_user(django_user_model, group_setup, "viewer"))
    assert api.get("/api/v1/scan/NOPE-123/").status_code == 404


def test_scan_anonymous_401(api):
    assert api.get("/api/v1/scan/ANY/").status_code == 401


def test_token_revocation_denies_access(api, django_user_model, group_setup, asset_factory):
    u = _user(django_user_model, group_setup, "viewer")
    token = Token.objects.create(user=u)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    assert api.get("/api/v1/assets/").status_code == 200
    token.delete()  # admin revokes a lost scanner device (§16)
    assert api.get("/api/v1/assets/").status_code == 401
