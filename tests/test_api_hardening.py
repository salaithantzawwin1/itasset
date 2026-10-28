"""API hardening (gap §3.5 / workstream 7, shipped 2026-10-17).

Covers: the optimistic `version` lock on /assets/{tag}/ (409 on stale
writes), lifecycle services bumping the version, `Idempotency-Key` replay
protection on /api/v1/ writes, and the fixed asset-create endpoint
(category_id/site_id — it used to 500 on the NOT NULL columns).
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {n: Group.objects.get_or_create(name=n)[0] for n in ("admin", "technician", "viewer")}


PASSWORD = "Str0ngPass!23"


def _login_as(api, django_user_model, group_setup, name):
    """Create *name* and sign them in via a real session (middleware-visible)."""
    u = _user(django_user_model, group_setup, name)
    api.login(username=u.username, password=PASSWORD)
    return u


def _user(django_user_model, group_setup, name):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(f"hard_{name}", f"{name}@x.com", PASSWORD)
    u.groups.add(group_setup[name])
    # feature test, not a scope test: GLOBAL keeps scope enforcement transparent
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="hardening-test fixture",
        created_by=u,
    )
    return u


# --------------------------------------------------------------------------- create


def test_asset_create_fills_fks_and_starts_at_version_1(
    api, django_user_model, group_setup, site, category
):
    _login_as(api, django_user_model, group_setup, "technician")
    r = api.post(
        "/api/v1/assets/",
        {"asset_tag": "IT-HW-LAP-7001", "category_id": category.id, "site_id": site.id},
        format="json",
    )
    assert r.status_code == 201
    body = r.json()
    assert body["version"] == 1
    assert body["status"] == "IN_STOCK"  # stage ④ default
    assert body["category"]["code"] == "IT-HW-LAP"  # nested read shape intact
    assert body["site"]["code"] == "yangon"


def test_asset_create_without_site_is_400_not_500(api, django_user_model, group_setup, category):
    _login_as(api, django_user_model, group_setup, "technician")
    r = api.post(
        "/api/v1/assets/",
        {"asset_tag": "IT-HW-LAP-7002", "category_id": category.id},
        format="json",
    )
    assert r.status_code == 400
    assert "site_id" in r.json()


def test_asset_create_rejects_a_tag_from_another_category(
    api, django_user_model, group_setup, site, category
):
    """DRF never calls the model's full_clean, so the tag ↔ category rule
    (§13) is repeated in the serializer: a Desktop tag under the Laptop
    category — the production `IT-HW-DSK-0010` — answers 400, not a bad row.
    """
    from apps.assets.models import Asset, Category

    Category.objects.get_or_create(code="IT-HW-DSK", defaults={"name": "Desktop / Workstation"})
    _login_as(api, django_user_model, group_setup, "technician")
    r = api.post(
        "/api/v1/assets/",
        {"asset_tag": "IT-HW-DSK-7099", "category_id": category.id, "site_id": site.id},
        format="json",
    )
    assert r.status_code == 400
    assert "asset_tag" in r.json()
    assert "IT-HW-DSK" in str(r.json()["asset_tag"])
    assert not Asset.objects.filter(asset_tag="IT-HW-DSK-7099").exists()


# --------------------------------------------------------------------------- version lock


def test_patch_with_current_version_increments(api, django_user_model, group_setup, asset_factory):
    _login_as(api, django_user_model, group_setup, "technician")
    asset = asset_factory(asset_tag="IT-HW-LAP-7010")
    v = api.get(f"/api/v1/assets/{asset.asset_tag}/").json()["version"]

    r = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/",
        {"model_name": "ThinkPad T14", "version": v},
        format="json",
    )
    assert r.status_code == 200
    assert r.json()["version"] == v + 1
    assert r.json()["model_name"] == "ThinkPad T14"


def test_patch_with_stale_version_409_and_row_untouched(
    api, django_user_model, group_setup, asset_factory
):
    _login_as(api, django_user_model, group_setup, "technician")
    asset = asset_factory(asset_tag="IT-HW-LAP-7011")
    stale = api.get(f"/api/v1/assets/{asset.asset_tag}/").json()["version"]

    first = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/",
        {"model_name": "First writer", "version": stale},
        format="json",
    )
    assert first.status_code == 200

    second = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/",
        {"model_name": "Second writer", "version": stale},  # now stale
        format="json",
    )
    assert second.status_code == 409
    assert "version conflict" in second.json()["detail"]

    asset.refresh_from_db()
    assert asset.model_name == "First writer"  # the second write never landed
    assert asset.version == stale + 1


def test_patch_without_version_still_works_and_increments(
    api, django_user_model, group_setup, asset_factory
):
    """Payloads without `version` keep last-write-wins (simple clients)."""
    _login_as(api, django_user_model, group_setup, "technician")
    asset = asset_factory(asset_tag="IT-HW-LAP-7012")
    v = asset.version

    r = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/", {"remarks": "no version sent"}, format="json"
    )
    assert r.status_code == 200
    assert r.json()["version"] == v + 1


def test_patch_non_integer_version_400(api, django_user_model, group_setup, asset_factory):
    _login_as(api, django_user_model, group_setup, "technician")
    asset = asset_factory(asset_tag="IT-HW-LAP-7013")
    r = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/", {"remarks": "x", "version": "abc"}, format="json"
    )
    assert r.status_code == 400
    assert "version" in r.json()["detail"]


def test_lifecycle_services_bump_version(
    django_user_model, group_setup, asset_factory, person_factory
):
    from apps.assets import services

    asset = asset_factory(status="AVAILABLE", asset_tag="IT-HW-LAP-7014")
    person = person_factory(employee_no="E7014")
    v0 = asset.version

    services.check_out(asset, person, actor=None)
    assert asset.version == v0 + 1
    services.check_in(asset, actor=None)
    assert asset.version == v0 + 2


# --------------------------------------------------------------------------- idempotency


def test_idempotent_create_replays_and_never_duplicates(
    api, django_user_model, group_setup, site, category
):
    from apps.assets.models import Asset

    _login_as(api, django_user_model, group_setup, "technician")
    payload = {"asset_tag": "IT-HW-LAP-7020", "category_id": category.id, "site_id": site.id}

    first = api.post("/api/v1/assets/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-7020")
    assert first.status_code == 201
    assert "Idempotency-Replayed" not in first.headers

    replay = api.post("/api/v1/assets/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-7020")
    assert replay.status_code == 201
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()
    assert Asset.objects.filter(asset_tag="IT-HW-LAP-7020").count() == 1


def test_idempotent_replay_of_a_validation_error(api, django_user_model, group_setup, category):
    """A stored 400 replays as the same 400 — deterministic retries (§10.1)."""
    _login_as(api, django_user_model, group_setup, "technician")
    bad = {"asset_tag": "IT-HW-LAP-7021", "category_id": category.id}  # no site_id

    first = api.post("/api/v1/assets/", bad, format="json", HTTP_IDEMPOTENCY_KEY="key-7021")
    assert first.status_code == 400
    replay = api.post("/api/v1/assets/", bad, format="json", HTTP_IDEMPOTENCY_KEY="key-7021")
    assert replay.status_code == 400
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()


def test_idempotency_key_reuse_with_different_payload_409(
    api, django_user_model, group_setup, site, category
):
    _login_as(api, django_user_model, group_setup, "technician")
    base = {"category_id": category.id, "site_id": site.id}

    ok = api.post(
        "/api/v1/assets/",
        {**base, "asset_tag": "IT-HW-LAP-7022"},
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-7022",
    )
    assert ok.status_code == 201

    misuse = api.post(
        "/api/v1/assets/",
        {**base, "asset_tag": "IT-HW-LAP-9999"},  # same key, different body
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-7022",
    )
    assert misuse.status_code == 409
    assert "reused" in misuse.json()["detail"]


def test_idempotency_duplicate_while_in_progress_409(
    api, django_user_model, group_setup, site, category
):
    from apps.core.models import IdempotencyRecord

    user = _user(django_user_model, group_setup, "technician")
    api.login(username=user.username, password=PASSWORD)
    payload = {"asset_tag": "IT-HW-LAP-7023", "category_id": category.id, "site_id": site.id}

    assert (
        api.post(
            "/api/v1/assets/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-7023"
        ).status_code
        == 201
    )
    # simulate the original still running: the stored row has no response yet
    record = IdempotencyRecord.objects.get(user=user, key="key-7023")
    record.status_code = None
    record.save(update_fields=["status_code"])

    dupe = api.post("/api/v1/assets/", payload, format="json", HTTP_IDEMPOTENCY_KEY="key-7023")
    assert dupe.status_code == 409
    assert "still in progress" in dupe.json()["detail"]


def test_idempotency_keys_are_scoped_per_user(api, django_user_model, group_setup, site, category):
    from apps.assets.models import Asset

    _login_as(api, django_user_model, group_setup, "technician")
    other = _user(django_user_model, group_setup, "admin")

    mine = api.post(
        "/api/v1/assets/",
        {"asset_tag": "IT-HW-LAP-7024", "category_id": category.id, "site_id": site.id},
        format="json",
        HTTP_IDEMPOTENCY_KEY="shared-key",
    )
    assert mine.status_code == 201

    # another user reuses the same key string — their own scope, no replay
    api.logout()
    api.login(username=other.username, password=PASSWORD)
    theirs = api.post(
        "/api/v1/assets/",
        {"asset_tag": "IT-HW-LAP-7025", "category_id": category.id, "site_id": site.id},
        format="json",
        HTTP_IDEMPOTENCY_KEY="shared-key",
    )
    assert theirs.status_code == 201
    assert "Idempotency-Replayed" not in theirs.headers
    assert Asset.objects.filter(asset_tag__in=["IT-HW-LAP-7024", "IT-HW-LAP-7025"]).count() == 2


def test_idempotent_patch_replay_runs_nothing_twice(
    api, django_user_model, group_setup, asset_factory
):
    _login_as(api, django_user_model, group_setup, "technician")
    asset = asset_factory(asset_tag="IT-HW-LAP-7026")
    v = asset.version
    payload = {"remarks": "idempotent edit", "version": v}

    first = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-7026",
    )
    assert first.status_code == 200

    replay = api.patch(
        f"/api/v1/assets/{asset.asset_tag}/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="key-7026",
    )
    assert replay.status_code == 200
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert replay.json() == first.json()

    asset.refresh_from_db()
    assert asset.version == v + 1  # the view ran exactly once
    assert asset.remarks == "idempotent edit"


def test_requests_without_the_header_are_unaffected(
    api, django_user_model, group_setup, site, category
):
    from apps.assets.models import Asset

    _login_as(api, django_user_model, group_setup, "technician")
    for tag in ("IT-HW-LAP-7030", "IT-HW-LAP-7031"):
        r = api.post(
            "/api/v1/assets/",
            {"asset_tag": tag, "category_id": category.id, "site_id": site.id},
            format="json",
        )
        assert r.status_code == 201
    assert Asset.objects.filter(asset_tag__startswith="IT-HW-LAP-703").count() == 2
