"""Self-service password change (every signed-in role, no admin needed)."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user("pw_user", "pw_user@example.com", "old-pass-12345")


def test_password_change_requires_sign_in(client):
    r = client.get(reverse("password_change"))
    assert r.status_code == 302
    assert reverse("login") in r["Location"]


def test_form_renders_for_a_signed_in_user(client, user):
    client.force_login(user)
    r = client.get(reverse("password_change"))
    assert r.status_code == 200
    assert "old_password" in r.content.decode()
    assert "new_password1" in r.content.decode()


def test_changes_the_password_and_keeps_the_session(client, user):
    client.force_login(user)
    r = client.post(
        reverse("password_change"),
        {
            "old_password": "old-pass-12345",
            "new_password1": "brand-new-pass-67890",
            "new_password2": "brand-new-pass-67890",
        },
    )
    assert r.status_code == 302
    assert r["Location"] == reverse("password_change_done")
    user.refresh_from_db()
    assert user.check_password("brand-new-pass-67890")

    # the session survives the change, so the done page is reachable
    assert client.get(reverse("password_change_done")).status_code == 200
    # and the old password no longer works
    client.logout()
    assert not client.login(username="pw_user", password="old-pass-12345")
    assert client.login(username="pw_user", password="brand-new-pass-67890")


def test_wrong_current_password_is_rejected(client, user):
    client.force_login(user)
    r = client.post(
        reverse("password_change"),
        {
            "old_password": "not-the-password",
            "new_password1": "brand-new-pass-67890",
            "new_password2": "brand-new-pass-67890",
        },
    )
    assert r.status_code == 200  # form redisplayed with an error
    user.refresh_from_db()
    assert user.check_password("old-pass-12345")
