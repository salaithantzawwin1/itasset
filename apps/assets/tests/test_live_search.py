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
4. Match highlighting: every q hit is wrapped in <mark> — case-insensitive,
   original casing kept, HTML escaped on both sides; without a query the
   rows render exactly as before (no <mark> anywhere).
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
    assert "IT-<mark>LS-7002</mark>" in data["rows"]  # row present, match highlighted
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


def test_fragment_finds_the_holder_as_you_type(
    client, viewer_user, asset_factory, person_factory, site
):
    """The typing path answers the holder question too: an open assignment's
    person name, that person's department, or the department the asset is
    checked out to matches through `_fragment=1`, so typing a name replaces
    the rows without a Search click."""
    from apps.assets.models import Assignment
    from apps.people.models import Department

    held = asset_factory(asset_tag="IT-LS-HOLD", status=Asset.Status.ASSIGNED)
    member = person_factory(name="Thandar Aung")
    member.department = Department.objects.create(site=site, name="Shared Services")
    member.save(update_fields=["department"])
    Assignment.objects.create(asset=held, to_person=member)
    dept_asset = asset_factory(asset_tag="IT-LS-DEPT", status=Asset.Status.ASSIGNED)
    Assignment.objects.create(
        asset=dept_asset,
        to_dept=Department.objects.create(site=site, name="Network Operations"),
    )
    asset_factory(asset_tag="IT-LS-SPARE")  # no holder

    client.force_login(viewer_user)

    by_person = client.get(URL, {"_fragment": "1", "q": "Thandar"}).json()
    assert "IT-LS-HOLD" in by_person["rows"]
    assert "IT-LS-DEPT" not in by_person["rows"] and "IT-LS-SPARE" not in by_person["rows"]
    assert "1 total" in by_person["count"]

    by_dept = client.get(URL, {"_fragment": "1", "q": "network operations"}).json()
    assert "IT-LS-DEPT" in by_dept["rows"]
    assert "1 total" in by_dept["count"]

    # the holder's own department name finds the member's asset as well
    by_member_dept = client.get(URL, {"_fragment": "1", "q": "shared services"}).json()
    assert "IT-LS-HOLD" in by_member_dept["rows"]
    assert "IT-LS-DEPT" not in by_member_dept["rows"]
    assert "1 total" in by_member_dept["count"]


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


# 2b. match highlighting -------------------------------------------------------


def test_rows_highlight_matched_text(client, viewer_user, asset_factory):
    """Every column q searched on wraps its hit in <mark> — tag match on
    the first row, model match on the second (whose tag cell stays plain,
    proving highlighting follows the actual match, not the whole row)."""
    asset_factory(asset_tag="IT-LS-HL-100", model_name="ThinkPad X1")
    asset_factory(asset_tag="IT-LS-PC-200", model_name="Elite HL-Box")

    client.force_login(viewer_user)
    rows = client.get(URL, {"_fragment": "1", "q": "hl"}).json()["rows"]
    assert "IT-LS-<mark>HL</mark>-100" in rows  # case-insensitive, original casing
    assert "Elite <mark>HL</mark>-Box" in rows
    assert ">IT-LS-PC-200</a>" in rows  # the non-matching column stays unmarked

    # no query → the rows render exactly as before (no stray <mark>)
    plain = client.get(URL, {"_fragment": "1"}).json()["rows"]
    assert "<mark>" not in plain

    # the full page (no-JS path) highlights through the same partial
    body = client.get(URL, {"q": "hl"}).content.decode()
    assert "IT-LS-<mark>HL</mark>-100" in body


def test_rows_highlight_holder_columns(client, viewer_user, asset_factory, person_factory, site):
    """The holder cell's three shapes all highlight: the person's name,
    that person's own department, and the department the asset is checked
    out to — the exact branches the q filter matches on."""
    from apps.assets.models import Assignment
    from apps.people.models import Department

    dept = Department.objects.create(site=site, name="Network Operations")
    member = person_factory(name="Thandar Aung")
    member.department = dept
    member.save(update_fields=["department"])
    held = asset_factory(asset_tag="IT-LS-HLD-1", status=Asset.Status.ASSIGNED)
    Assignment.objects.create(asset=held, to_person=member)

    shared = Department.objects.create(site=site, name="Shared Services")
    dept_asset = asset_factory(asset_tag="IT-LS-HLD-2", status=Asset.Status.ASSIGNED)
    Assignment.objects.create(asset=dept_asset, to_dept=shared)

    client.force_login(viewer_user)
    by_person = client.get(URL, {"_fragment": "1", "q": "thandar"}).json()["rows"]
    assert "<mark>Thandar</mark>" in by_person

    by_member_dept = client.get(URL, {"_fragment": "1", "q": "network operations"}).json()["rows"]
    assert "<mark>Network Operations</mark>" in by_member_dept

    by_to_dept = client.get(URL, {"_fragment": "1", "q": "shared services"}).json()["rows"]
    assert "<mark>Shared Services</mark>" in by_to_dept


def test_rows_highlight_escapes_html(client, viewer_user, asset_factory):
    """Both the value and the query are HTML-escaped around <mark>, so no
    markup in the data (or in what someone types) can ever reach the page
    unescaped — <mark> is the only tag the highlighter emits."""
    asset_factory(asset_tag="IT-LS-XSS-1", model_name="<script>alert(1)</script>")
    client.force_login(viewer_user)
    rows = client.get(URL, {"_fragment": "1", "q": "<script>"}).json()["rows"]
    assert "<script>alert" not in rows
    assert "<mark>&lt;script&gt;</mark>" in rows
    assert "alert(1)&lt;/script&gt;" in rows


# 3. access gate ---------------------------------------------------------------


def test_fragment_requires_login(client):
    resp = client.get(URL, {"_fragment": "1", "q": "x"})
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]
