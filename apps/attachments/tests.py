"""Attachments module tests (gap §3.4; Spec A §6.13).

Covers: exactly-one-owner DB constraint, upload validation, role rules
(technician/admin for assets+transfers, the requester for their own request),
authorized download, and private storage (files never web-servable).
Scope/IDOR behaviour lives in tests/test_scopes.py row 23.
"""

import pytest
from django.contrib.auth.models import Group
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from rest_framework.test import APIClient

from apps.assets.models import Asset, AssetRequest, Category
from apps.people.models import Site

from .models import Attachment

pytestmark = pytest.mark.django_db

API = "/api/v1/attachments/"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def site(db):
    return Site.objects.create(name="Attach Site", code="att-site")


@pytest.fixture
def category(db):
    return Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]


@pytest.fixture
def asset(db, site, category):
    return Asset.objects.create(asset_tag="ATT-1", category=category, site=site)


def _user(django_user_model, username, *groups):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(username, f"{username}@itasset.dev", "pass12345!")
    for name in groups:
        g, _ = Group.objects.get_or_create(name=name)
        u.groups.add(g)
    # Feature tests, not scope tests: a GLOBAL scope keeps scope enforcement
    # transparent (deny-by-default users are covered in tests/test_scopes.py
    # row 23, where these same gates are asserted on purpose).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


def _file(name="invoice.pdf", content=b"%PDF-1.4 test payload"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


# ---------------------------------------------------------------- model layer
def test_exactly_one_owner_enforced(db, django_user_model, asset, category, site):
    user = django_user_model.objects.create_superuser("root-att", "root@itasset.dev", "pw12345!")
    req = AssetRequest.objects.create(requester=user, category=category, site=site)

    with pytest.raises(IntegrityError), transaction.atomic():
        Attachment.objects.create(asset=asset, request=req, file=_file())
    with pytest.raises(IntegrityError), transaction.atomic():
        Attachment.objects.create(file=_file())  # no owner at all


def test_upload_records_metadata(db, django_user_model, asset):
    from django.conf import settings

    att = Attachment.objects.create(asset=asset, file=_file("Invoice 2026.pdf"))
    assert att.original_name == "Invoice 2026.pdf"
    assert att.size > 0 and att.content_type == "application/pdf"
    assert att.file.path.startswith(str(settings.PRIVATE_MEDIA_ROOT))


def test_files_are_not_web_servable(db, asset):
    from django.conf import settings

    att = Attachment.objects.create(asset=asset, file=_file())
    path = att.file.path
    assert path.startswith(str(settings.PRIVATE_MEDIA_ROOT))
    assert not path.startswith(str(settings.MEDIA_ROOT))
    with pytest.raises(ValueError):  # no base_url → Django refuses to build a URL
        _ = att.file.url


# ------------------------------------------------------------------ API layer
def test_upload_role_rules(api, django_user_model, asset):
    tech = _user(django_user_model, "att-tech", "technician")
    viewer = _user(django_user_model, "att-view", "viewer")

    api.force_authenticate(viewer)
    r = api.post(API, {"asset": asset.pk, "file": _file()}, format="multipart")
    assert r.status_code == 403  # uploads need technician+

    api.force_authenticate(tech)
    r = api.post(API, {"asset": asset.pk, "file": _file()}, format="multipart")
    assert r.status_code == 201, r.data
    att = Attachment.objects.get(pk=r.data["id"])
    assert att.original_name == "invoice.pdf" and att.uploaded_by == tech
    assert r.data["owner"] == {"type": "asset", "id": asset.pk}


def test_upload_requires_exactly_one_owner(api, django_user_model, asset):
    tech = _user(django_user_model, "att-tech2", "technician")
    api.force_authenticate(tech)
    assert api.post(API, {"file": _file()}, format="multipart").status_code == 400
    # two owners in one payload is equally invalid
    assert (
        api.post(
            API, {"asset": asset.pk, "request": 1, "file": _file()}, format="multipart"
        ).status_code
        == 400
    )


def test_upload_validation_rejects_type(api, django_user_model, asset):
    tech = _user(django_user_model, "att-tech3", "technician")
    api.force_authenticate(tech)
    r = api.post(API, {"asset": asset.pk, "file": _file("payload.exe")}, format="multipart")
    assert r.status_code == 400
    assert "not allowed" in str(r.data)


def test_requester_may_attach_to_own_request(api, django_user_model, site, category):
    requester = _user(django_user_model, "att-req")
    stranger = _user(django_user_model, "att-stranger", "viewer")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site)

    api.force_authenticate(requester)
    r = api.post(API, {"request": req.pk, "file": _file("quote.pdf")}, format="multipart")
    assert r.status_code == 201, r.data

    api.force_authenticate(stranger)
    r = api.post(API, {"request": req.pk, "file": _file("other.pdf")}, format="multipart")
    assert r.status_code == 403


def test_download_serves_the_file_with_its_original_name(api, django_user_model, asset):
    tech = _user(django_user_model, "att-dl", "technician")
    api.force_authenticate(tech)
    pk = api.post(API, {"asset": asset.pk, "file": _file()}, format="multipart").data["id"]

    r = api.get(f"{API}{pk}/download/")
    assert r.status_code == 200
    assert r["Content-Disposition"].startswith("attachment")
    assert "invoice.pdf" in r["Content-Disposition"]
    assert b"%PDF" in b"".join(r.streaming_content)
    assert Attachment.objects.filter(pk=pk).exists()


def test_missing_attachment_is_404(api, django_user_model):
    tech = _user(django_user_model, "att-404", "technician")
    api.force_authenticate(tech)
    assert api.get(f"{API}999999/download/").status_code == 404
