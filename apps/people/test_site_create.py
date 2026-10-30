"""New site in the shared modal (main-app create view).

The Sites list had no create button although ``SiteCreate`` existed — rows
could only be made by typing the URL or through the Django admin. This covers
the ``data-modal`` button on the list and the create/edit titles sharing one
form template.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.models import Site


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("site-boss", "site-boss@example.com", "x")
    client.force_login(user)
    return client


def _payload(**over):
    data = {"name": "Kalaw Office", "code": "kalaw", "address": "", "is_active": "on"}
    data.update(over)
    return data


def test_list_page_offers_the_create_button_in_the_modal(admin_client, db, site):
    body = admin_client.get(reverse("site-list")).content.decode()

    assert 'href="/sites/new/"' in body
    assert "data-modal" in body  # opens in the shared dialog, not a page hop
    assert "+ New site" in body


def test_create_page_renders_the_new_site_form(admin_client, db, site):
    resp = admin_client.get(reverse("site-create"))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "New site" in body
    assert "Edit site" not in body
    assert 'href="/sites/"' in body  # cancel goes back to the list


def test_post_creates_the_site_and_returns_to_the_list(admin_client, db, site):
    resp = admin_client.post(reverse("site-create"), _payload())

    assert resp.status_code == 302
    assert resp["Location"] == reverse("site-list")
    assert Site.objects.filter(code="kalaw", name="Kalaw Office").exists()


def test_duplicate_code_is_rejected(admin_client, db, site):
    resp = admin_client.post(reverse("site-create"), _payload(code=site.code))

    assert resp.status_code == 200  # re-rendered with the error
    assert resp.context["form"].errors


def test_non_admin_cannot_open_the_create_form(client, db, site):
    user = get_user_model().objects.create_user("site-viewer", "viewer@example.com", "x")
    client.force_login(user)

    assert client.get(reverse("site-create")).status_code == 403


def test_create_requires_login(client, db, site):
    resp = client.get(reverse("site-create"))

    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_edit_still_uses_the_edit_title(admin_client, db, site):
    body = admin_client.get(reverse("site-update", args=[site.pk])).content.decode()

    assert "Edit site" in body
