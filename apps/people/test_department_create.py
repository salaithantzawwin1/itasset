"""New department in the shared modal (main-app create view).

The Departments list had no create button — rows could only be made in the
Django admin. This covers the main-app create view behind the same
``data-modal`` link the People/Assets lists use, and keeps the shared
department form working for both create and edit.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.models import Department


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("dept-boss", "dept-boss@example.com", "x")
    client.force_login(user)
    return client


def _payload(site, **over):
    data = {"name": "New Dept", "site": site.pk, "head": ""}
    data.update(over)
    return data


def test_list_page_offers_the_create_button_in_the_modal(admin_client, db, site):
    body = admin_client.get(reverse("department-list")).content.decode()

    assert 'href="/departments/new/"' in body
    assert "data-modal" in body  # opens in the shared dialog, not a page hop
    assert "+ New department" in body


def test_create_page_renders_the_new_department_form(admin_client, db, site):
    resp = admin_client.get(reverse("department-create"))

    assert resp.status_code == 200
    body = resp.content.decode()
    assert "New department" in body
    assert "Edit department" not in body
    # cancel on a create goes back to the list, never to a department detail
    assert 'href="/departments/"' in body


def test_post_creates_the_department_and_returns_to_the_list(admin_client, db, site):
    resp = admin_client.post(reverse("department-create"), _payload(site))

    assert resp.status_code == 302
    assert resp["Location"] == reverse("department-list")
    dept = Department.objects.get(name="New Dept")
    assert dept.site == site
    assert dept.head is None  # optional on create


def test_duplicate_name_on_the_same_site_is_rejected(admin_client, db, site):
    Department.objects.create(name="Twin", site=site)

    resp = admin_client.post(reverse("department-create"), _payload(site, name="Twin"))

    assert resp.status_code == 200  # re-rendered with the error
    assert resp.context["form"].errors


def test_non_admin_cannot_open_the_create_form(client, db, site):
    user = get_user_model().objects.create_user("dept-viewer", "viewer@example.com", "x")
    client.force_login(user)

    assert client.get(reverse("department-create")).status_code == 403


def test_create_requires_login(client, db, site):
    resp = client.get(reverse("department-create"))

    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_edit_still_uses_the_edit_title_and_cancels_to_the_detail(admin_client, db, site):
    dept = Department.objects.create(name="Kept", site=site)

    body = admin_client.get(reverse("department-update", args=[dept.pk])).content.decode()

    assert "Edit department" in body
    assert reverse("department-detail", args=[dept.pk]) in body
