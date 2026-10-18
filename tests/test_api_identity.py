"""Identity + observability (gap §3.5: /api/v1/me, correlation id, error
envelope) and §3.6 disabled-account session revocation."""

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


def _user(django_user_model, group_setup, name, scope="GLOBAL"):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(f"id_{name}", f"{name}@x.com", PASSWORD)
    u.groups.add(group_setup[name])
    if scope == "GLOBAL":
        UserAccessScope.objects.create(
            user=u,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="identity-test fixture",
            created_by=u,
        )
    return u


def _login(api, user):
    api.login(username=user.username, password=PASSWORD)
    return user


# --------------------------------------------------------------------------- /api/v1/me/


def test_me_anonymous_401_with_envelope(api):
    r = api.get("/api/v1/me/")
    assert r.status_code == 401
    body = r.json()
    assert "detail" in body
    assert body["code"] == "not_authenticated"
    assert body["correlationId"] == r.headers["X-Correlation-ID"]


def test_me_returns_identity_roles_and_scopes(api, django_user_model, group_setup):
    _login(api, _user(django_user_model, group_setup, "viewer"))
    body = api.get("/api/v1/me/").json()
    assert body["username"] == "id_viewer"
    assert body["roles"] == ["viewer"]
    assert body["is_active"] is True
    assert body["scopes"] == {"global_access": True, "sites": [], "departments": []}


def test_me_shows_site_scopes(api, django_user_model, group_setup, site):
    from apps.core.models import UserAccessScope

    u = _user(django_user_model, group_setup, "technician", scope=None)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=site,
        reason="site fixture",
        created_by=u,
    )
    _login(api, u)
    scopes = api.get("/api/v1/me/").json()["scopes"]
    assert scopes["global_access"] is False
    assert scopes["sites"] == [{"id": site.id, "code": site.code, "name": site.name}]


# --------------------------------------------------------------------------- correlation id


def test_correlation_id_minted_when_absent(api, django_user_model, group_setup):
    _login(api, _user(django_user_model, group_setup, "viewer"))
    cid = api.get("/api/v1/me/").headers["X-Correlation-ID"]
    assert len(cid) == 32 and all(c in "0123456789abcdef" for c in cid)


def test_correlation_id_echoed_and_sanitized(api, django_user_model, group_setup):
    _login(api, _user(django_user_model, group_setup, "viewer"))
    r = api.get("/api/v1/me/", HTTP_X_CORRELATION_ID="ticket-123.abc")
    assert r.headers["X-Correlation-ID"] == "ticket-123.abc"

    # untrusted input becomes a response header — newlines must never survive
    evil = api.get("/api/v1/me/", HTTP_X_CORRELATION_ID="bad\nvalue:1")
    assert evil.headers["X-Correlation-ID"] == "badvalue1"


# --------------------------------------------------------------------------- error envelope


def test_404_envelope_has_code_and_matching_correlation_id(
    api, django_user_model, group_setup, asset_factory
):
    _login(api, _user(django_user_model, group_setup, "viewer"))
    asset_factory(asset_tag="IT-HW-LAP-8001")
    r = api.get("/api/v1/assets/NOPE-123/")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["correlationId"] == r.headers["X-Correlation-ID"]


def test_hand_rolled_409_envelope_carries_code_and_correlation_id(
    api, django_user_model, group_setup, asset_factory
):
    _login(api, _user(django_user_model, group_setup, "technician"))
    asset_factory(asset_tag="IT-HW-LAP-8002", status="AVAILABLE")  # no assignment
    r = api.post("/api/v1/assets/IT-HW-LAP-8002/check-in/", {}, format="json")
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "conflict"
    assert body["correlationId"] == r.headers["X-Correlation-ID"]


def test_field_level_validation_errors_stay_field_maps(api, django_user_model, group_setup):
    """Field errors keep DRF's {field: [messages]} shape — clients iterate them."""
    _login(api, _user(django_user_model, group_setup, "technician"))
    r = api.post("/api/v1/assets/", {"asset_tag": "IT-HW-LAP-8003"}, format="json")
    assert r.status_code == 400
    body = r.json()
    assert "site_id" in body and isinstance(body["site_id"], list)


# --------------------------------------------------------------------------- §3.6 revocation


def test_deactivated_account_loses_its_session_on_the_next_request(
    api, django_user_model, group_setup
):
    from django.contrib.sessions.models import Session

    u = _login(api, _user(django_user_model, group_setup, "technician"))
    assert api.get("/api/v1/assets/").status_code == 200
    old_key = api.session.session_key

    u.is_active = False
    u.save(update_fields=["is_active"])

    assert api.get("/api/v1/assets/").status_code == 401  # revoked immediately
    assert api.get("/api/v1/assets/").status_code == 401  # stays revoked
    # the orphaned server-side session row is flushed, not just ignored
    assert not Session.objects.filter(session_key=old_key).exists()


def test_deactivated_accounts_token_is_refused(api, django_user_model, group_setup):
    from rest_framework.authtoken.models import Token

    u = _user(django_user_model, group_setup, "technician")
    token = Token.objects.create(user=u)
    api.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")
    assert api.get("/api/v1/assets/").status_code == 200

    u.is_active = False
    u.save(update_fields=["is_active"])
    assert api.get("/api/v1/assets/").status_code == 401  # DRF refuses the token
