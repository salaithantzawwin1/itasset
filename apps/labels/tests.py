"""Label tests (M3; DEVELOPMENT.md §13 barcode policy, §11 roles).

Covers: QR PNG bytes for an asset, label PDF header + page count, role guard
(anonymous → login redirect; viewer → 403; technician+ → PDF), preview PNG.
"""

import pytest

pytestmark = pytest.mark.django_db

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
PDF_MAGIC = b"%PDF"


def _user(django_user_model, group_setup, name):
    u = django_user_model.objects.create_user(f"lbl_{name}", f"{name}@x.com", "pass12345!")
    u.groups.add(group_setup[name])
    return u


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {
        n: Group.objects.get_or_create(name=n)[0]
        for n in ("admin", "technician", "auditor", "viewer")
    }


def test_qr_png_bytes(asset_factory):
    from apps.labels import services

    asset = asset_factory()
    data = services.qr_png(asset)
    assert data.startswith(PNG_MAGIC)
    assert len(data) > 200  # a real QR image, not an empty shell


def test_label_pdf_bytes_and_pages(asset_factory):
    from apps.labels import services

    assets = [asset_factory() for _ in range(3)]
    data = services.label_pdf(assets)
    assert data.startswith(PDF_MAGIC)
    assert data.count(b"/Type /Page") >= 1  # at least one page rendered


def test_print_requires_login(client, asset_factory):
    asset = asset_factory()
    r = client.get(f"/labels/print/?ids={asset.pk}")
    assert r.status_code == 302 and "login" in r.headers["Location"]


def test_viewer_cannot_print(client, django_user_model, group_setup, asset_factory):
    asset = asset_factory()
    client.force_login(_user(django_user_model, group_setup, "viewer"))
    r = client.get(f"/labels/print/?ids={asset.pk}")
    assert r.status_code == 403


@pytest.mark.parametrize("role", ["technician", "admin"])
def test_technician_and_admin_can_print(
    client, django_user_model, group_setup, asset_factory, role
):
    asset = asset_factory()
    client.force_login(_user(django_user_model, group_setup, role))
    r = client.get(f"/labels/print/?ids={asset.pk}")
    assert r.status_code == 200
    assert r["Content-Type"] == "application/pdf"
    assert r.content.startswith(PDF_MAGIC)


def test_preview_png(client, django_user_model, group_setup, asset_factory):
    asset = asset_factory()
    client.force_login(_user(django_user_model, group_setup, "auditor"))
    r = client.get(f"/labels/{asset.pk}/")
    assert r.status_code == 200
    assert r["Content-Type"] == "image/png"
    assert r.content.startswith(PNG_MAGIC)
