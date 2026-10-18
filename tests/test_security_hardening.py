"""Security hardening (gap step 8 — Spec A §11.2, §11.3).

Covers: CSP/nosniff headers, per-IP credential throttling (429), admin-only
OpenAPI schema, the login audit trail, and break-glass alerting.
"""

import pytest
from django.contrib.auth.models import Group
from django.core import mail
from django.urls import reverse
from rest_framework.test import APIClient

from apps.audit.models import ActivityLog

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _clean_throttle_cache():
    """Throttle counters live in the shared cache — isolate every test."""
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def groups(db):
    return {n: Group.objects.get_or_create(name=n)[0] for n in ("admin", "technician", "viewer")}


def _user(django_user_model, groups, username, role=None, password="Str0ngPass!23"):
    u = django_user_model.objects.create_user(username, f"{username}@example.com", password)
    if role:
        u.groups.add(groups[role])
    return u


# --------------------------------------------------------------------------- OpenAPI gating


def test_openapi_schema_requires_admin(db, django_user_model, groups):
    """Gap §3.5 finding: the schema must not be served anonymously (§11.3)."""
    viewer = _user(django_user_model, groups, "sec_viewer", "viewer")
    boss = _user(django_user_model, groups, "sec_boss", "admin")
    api = APIClient()

    anon = api.get("/api/v1/schema/")
    assert anon.status_code != 200, "schema leaked to an anonymous caller"
    assert anon.status_code in (401, 403)

    api.force_authenticate(viewer)  # authenticated, wrong role → denied
    assert api.get("/api/v1/schema/").status_code == 403

    api.force_authenticate(boss)
    schema = api.get("/api/v1/schema/")
    assert schema.status_code == 200
    assert b"openapi" in schema.content

    docs = api.get("/api/v1/docs/")
    assert docs.status_code == 200  # Swagger UI for admins only


# --------------------------------------------------------------------------- headers


def test_html_responses_carry_csp_and_nosniff(client):
    r = client.get("/accounts/login/")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'self'" in csp
    assert "object-src 'none'" in csp
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") in ("DENY", "SAMEORIGIN")  # project default: DENY
    assert r.headers.get("Referrer-Policy") == "same-origin"


def test_json_responses_have_nosniff_but_no_csp(client):
    r = client.get("/api/v1/assets/")  # anonymous → 401 JSON
    assert r.status_code == 401
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert "Content-Security-Policy" not in r.headers  # CSP is an HTML policy


# --------------------------------------------------------------------------- throttle


def test_failed_logins_are_capped_per_ip(client, django_user_model, groups, settings):
    settings.LOGIN_THROTTLE_ATTEMPTS = 3
    settings.LOGIN_THROTTLE_WINDOW = 60
    _user(django_user_model, groups, "sec_target")
    url = reverse("login")
    payload = {"username": "sec_target", "password": "wrong-password"}

    # three failures go through (form re-render each time)…
    assert [client.post(url, payload).status_code for _ in range(3)] == [200, 200, 200]
    # …the fourth is throttled
    blocked = client.post(url, payload)
    assert blocked.status_code == 429
    assert blocked.headers.get("Retry-After") == "60"


def test_admin_login_and_token_endpoint_are_throttled(client, django_user_model, groups, settings):
    # ATTEMPTS=1 → the first attempt is processed, the second is blocked
    settings.LOGIN_THROTTLE_ATTEMPTS = 1
    settings.LOGIN_THROTTLE_WINDOW = 60
    _user(django_user_model, groups, "sec_tok")
    payload = {"username": "sec_tok", "password": "wrong-password"}

    assert client.post("/admin/login/", payload).status_code == 200
    assert client.post("/admin/login/", payload).status_code == 429

    assert client.post("/api/v1/auth/token/", payload, format="json").status_code == 401
    assert client.post("/api/v1/auth/token/", payload, format="json").status_code == 429


def test_success_clears_the_throttle_counter(client, django_user_model, groups, settings):
    settings.LOGIN_THROTTLE_ATTEMPTS = 3
    settings.LOGIN_THROTTLE_WINDOW = 60
    _user(django_user_model, groups, "sec_good")
    url = reverse("login")

    client.post(url, {"username": "sec_good", "password": "nope"})
    client.post(url, {"username": "sec_good", "password": "nope"})
    ok = client.post(url, {"username": "sec_good", "password": "Str0ngPass!23"})
    assert ok.status_code == 302

    # budget was reset by the success → a later failure is not throttled
    assert client.post(url, {"username": "sec_good", "password": "nope"}).status_code == 200


def test_throttle_fails_open_when_cache_is_down(
    client, django_user_model, groups, settings, monkeypatch
):
    """A cache outage must degrade the cap, never 500 or block login (§11.3)."""

    class BrokenCache:
        def _down(self, *args, **kwargs):
            raise ConnectionError("cache backend unreachable")

        get = add = incr = set = delete = clear = _down

    monkeypatch.setattr("apps.core.middleware.cache", BrokenCache())
    settings.LOGIN_THROTTLE_ATTEMPTS = 1
    _user(django_user_model, groups, "sec_open")
    url = reverse("login")

    # way past the cap: requests still process — no 429, no 500
    bad = {"username": "sec_open", "password": "nope"}
    codes = [client.post(url, bad).status_code for _ in range(3)]
    assert codes == [200, 200, 200]
    # and a valid password still signs in
    ok = client.post(url, {"username": "sec_open", "password": "Str0ngPass!23"})
    assert ok.status_code == 302


# --------------------------------------------------------------------------- login audit


def test_failed_login_is_audited_without_the_password(client, django_user_model, groups):
    client.post(reverse("login"), {"username": "ghost", "password": "hunter2-secret"})
    event = ActivityLog.objects.get(action="login_failed")
    assert event.actor_id is None
    assert event.details["username"] == "ghost"
    assert event.details["ip"]
    assert "hunter2-secret" not in str(event.details) and "hunter2-secret" not in event.object_repr


def test_successful_login_is_audited(client, django_user_model, groups):
    user = _user(django_user_model, groups, "sec_solid", "viewer")
    r = client.post(reverse("login"), {"username": "sec_solid", "password": "Str0ngPass!23"})
    assert r.status_code == 302

    event = ActivityLog.objects.get(action="login")
    assert event.actor == user
    assert event.details["backend"].endswith("ModelBackend")
    assert event.details["ip"]


# --------------------------------------------------------------------------- CSRF (workstream 13)


def test_session_writes_require_a_csrf_token(django_user_model, groups):
    """The test client disables CSRF checks by default — pin the real browser
    behaviour: a session-authenticated POST without the token is refused
    (403), and with cookie + header it goes through (workstream 13)."""
    from django.test import Client
    from django.urls import reverse

    _user(django_user_model, groups, "sec_csrf", "technician")
    csrf_client = Client(enforce_csrf_checks=True)
    assert csrf_client.login(username="sec_csrf", password="Str0ngPass!23")
    url = reverse("login")
    payload = {"username": "ghost", "password": "nope"}

    assert csrf_client.post(url, payload).status_code == 403  # no token

    csrf_client.cookies["csrftoken"] = "1" * 32
    ok = csrf_client.post(url, payload, HTTP_X_CSRFTOKEN="1" * 32)
    assert ok.status_code == 200  # token accepted (bad creds → form re-render)


def test_breakglass_login_alerts_the_it_lead(client, django_user_model, groups, settings):
    """§11.2: with LDAP as the normal path, a local-backend login alerts."""
    settings.LDAP_ENABLED = True
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    settings.IT_LEAD_EMAIL = "itlead@example.com"
    if hasattr(mail, "outbox"):
        mail.outbox.clear()
    _user(django_user_model, groups, "sec_break")
    url = reverse("login")

    first = client.post(url, {"username": "sec_break", "password": "Str0ngPass!23"})
    assert first.status_code == 302
    assert len(mail.outbox) == 1
    assert "Break-glass" in mail.outbox[0].subject
    assert "sec_break" in mail.outbox[0].body
    assert ActivityLog.objects.filter(action="login").count() == 1

    # LDAP off → the local backend is the *normal* path, no alert
    settings.LDAP_ENABLED = False
    mail.outbox.clear()
    client.logout()
    second = client.post(url, {"username": "sec_break", "password": "Str0ngPass!23"})
    assert second.status_code == 302
    assert mail.outbox == []
