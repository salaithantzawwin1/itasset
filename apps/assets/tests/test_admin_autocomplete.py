"""Admin asset autocomplete used by Add repair ticket.

The picker must answer *who holds this asset* — otherwise two assigned
machines look identical (tag + status only), and a technician who knows only
the employee name cannot find the asset at all.
"""

import pytest
from django.urls import reverse

from apps.assets.models import Asset, Assignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_user(django_user_model):
    return django_user_model.objects.create_superuser(
        "ac_admin", "ac_admin@itasset.dev", "pass12345!"
    )


def _autocomplete(client, term):
    return client.get(
        reverse("admin:autocomplete"),
        {
            "app_label": "assets",
            "model_name": "repairticket",
            "field_name": "asset",
            "term": term,
        },
    )


def test_asset_picker_appends_holder_name(client, admin_user, asset_factory, person_factory):
    person = person_factory(name="Daw Thida")
    asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HW-DSK-7777")
    Assignment.objects.create(asset=asset, to_person=person)
    client.force_login(admin_user)

    resp = _autocomplete(client, "IT-HW-DSK-7777")

    assert resp.status_code == 200
    [row] = resp.json()["results"]
    assert row["id"] == str(asset.pk)
    assert "Daw Thida" in row["text"]
    assert row["text"].startswith(str(asset))


def test_asset_picker_finds_asset_by_holder_name(client, admin_user, asset_factory, person_factory):
    person = person_factory(name="Mg Kyaw Zin")
    asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HW-LAP-7788")
    Assignment.objects.create(asset=asset, to_person=person)
    client.force_login(admin_user)

    resp = _autocomplete(client, "Kyaw Zin")

    assert resp.status_code == 200
    # holder fields join assignments → the autocomplete asks for distinct rows
    assert [row["id"] for row in resp.json()["results"]] == [str(asset.pk)]


def test_unassigned_asset_keeps_its_plain_label(client, admin_user, asset_factory):
    asset = asset_factory(status=Asset.Status.IN_STOCK, asset_tag="IT-HW-RAM-7789")
    client.force_login(admin_user)

    resp = _autocomplete(client, "IT-HW-RAM-7789")

    assert resp.status_code == 200
    [row] = resp.json()["results"]
    assert row["text"] == str(asset)
    assert "—" not in row["text"]
