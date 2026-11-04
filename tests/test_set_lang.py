"""Language switch must be POST-only and must not redirect off-site."""

import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_language_switch_is_post_only(client):
    url = reverse("set-lang")

    assert client.get(url, {"lang": "my"}).status_code == 405
    r = client.post(url, {"lang": "my"})
    assert r.status_code == 302
    assert client.session["lang"] == "my"


def test_language_switch_ignores_an_offsite_referer(client):
    url = reverse("set-lang")

    r = client.post(url, {"lang": "en"}, HTTP_REFERER="https://evil.example/steal")
    assert r.status_code == 302
    assert r["Location"] == "/"


def test_language_switch_returns_to_a_same_host_referer(client):
    url = reverse("set-lang")

    r = client.post(url, {"lang": "en"}, HTTP_REFERER="http://testserver/assets/")
    assert r.status_code == 302
    assert r["Location"].endswith("/assets/")
