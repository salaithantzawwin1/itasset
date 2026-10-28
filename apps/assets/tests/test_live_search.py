"""Search-as-you-type on the asset list (live search).

The search box debounces keystrokes and fetches the SAME url with
`_fragment=1`; the server answers the three swappable regions (count,
rows, pagination) as JSON, rendered from the same partials the full page
includes, and the JS swaps them in place — no navigation, so focus and
scroll survive. Coverage:

1. The full page wires the region ids and the debounced input listener.
2. The fragment is JSON, applies the same q/status filters, paginates
   like the full page (same link contract), and honours the session
   language (the partials render through `{% t %}` with the request).
3. Anonymous still gets the login redirect on the fragment URL.
"""

import pytest

from apps.assets.models import Asset

pytestmark = pytest.mark.django_db

URL = "/assets/"


@pytest.fixture
def viewer_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="viewer")
    u = django_user_model.objects.create_user(
        "viewer_livesearch", "viewer_livesearch@itasset.dev", "pw1234567!"
    )
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


# 1. page wiring ---------------------------------------------------------------


def test_full_page_wires_regions_and_debounce(client, viewer_user, asset_factory):
    asset_factory(asset_tag="IT-LS-7001")
    client.force_login(viewer_user)
    body = client.get(URL).content.decode()
    # the three regions the fragment swaps
    assert 'id="asset-count"' in body
    assert 'id="asset-rows"' in body
    assert 'id="asset-pagination"' in body
    assert "IT-LS-7001" in body  # rows rendered via the shared partial
    # debounce + fragment fetch wired to the q input
    assert 'addEventListener("input"' in body
    assert "var DELAY = 300" in body
    assert '"_fragment"' in body


# 2. fragment contract ---------------------------------------------------------


def test_fragment_returns_filtered_rows_as_json(client, viewer_user, asset_factory):
    asset_factory(asset_tag="IT-LS-7002")
    asset_factory(asset_tag="IT-LS-7003")

    client.force_login(viewer_user)
    resp = client.get(URL, {"_fragment": "1", "q": "LS-7002"})
    assert resp["Content-Type"].startswith("application/json")
    data = resp.json()
    assert set(data) == {"count", "rows", "pagination"}
    assert "IT-LS-7002" in data["rows"]
    assert "IT-LS-7003" not in data["rows"]
    assert "1 total" in data["count"]
    assert not data["pagination"].strip()  # one page → no controls


def test_fragment_rides_along_with_other_filters(client, viewer_user, asset_factory):
    asset_factory(asset_tag="IT-LS-AV", status=Asset.Status.AVAILABLE)
    asset_factory(asset_tag="IT-LS-AS", status=Asset.Status.ASSIGNED)

    client.force_login(viewer_user)
    # no status filter → both rows
    data = client.get(URL, {"_fragment": "1"}).json()
    assert "IT-LS-AV" in data["rows"] and "IT-LS-AS" in data["rows"]
    # status select rides along exactly as it does in the full GET
    data = client.get(URL, {"_fragment": "1", "status": Asset.Status.AVAILABLE.value}).json()
    assert "IT-LS-AV" in data["rows"]
    assert "IT-LS-AS" not in data["rows"]
    assert "1 total" in data["count"]


def test_fragment_empty_result_shows_empty_row(client, viewer_user, asset_factory):
    asset_factory(asset_tag="IT-LS-7100")
    client.force_login(viewer_user)
    data = client.get(URL, {"_fragment": "1", "q": "nothing-matches-this"}).json()
    assert 'class="empty-row"' in data["rows"]
    assert "0 total" in data["count"]


def test_fragment_paginates_like_the_full_page(client, viewer_user, asset_factory):
    for i in range(51):
        asset_factory(asset_tag=f"LS-{i:03d}")

    client.force_login(viewer_user)
    data = client.get(URL, {"_fragment": "1", "q": "LS-"}).json()
    assert data["rows"].count("<tr>") == 50  # page 1 of 51
    assert "51 total" in data["count"]
    # same pagination link contract as the full page (regression: keeps q)
    assert 'href="?page=2&q=LS-' in data["pagination"]

    page2 = client.get(URL, {"_fragment": "1", "q": "LS-", "page": 2}).json()
    assert page2["rows"].count("<tr>") == 1


def test_fragment_honours_session_language(client, viewer_user, asset_factory):
    asset_factory(asset_tag="IT-LS-7009")
    client.force_login(viewer_user)
    session = client.session
    session["lang"] = "my"
    session.save()
    data = client.get(URL, {"_fragment": "1"}).json()
    assert "စုစုပေါင်း 1" in data["count"]  # `{% t %}` saw the request session


# 3. access gate ---------------------------------------------------------------


def test_fragment_requires_login(client):
    resp = client.get(URL, {"_fragment": "1", "q": "x"})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]
