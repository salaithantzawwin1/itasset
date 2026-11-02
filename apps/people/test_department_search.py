"""Search on the Departments list (same live-search contract as People).

Departments are found by the three things a reader actually knows about
them — the department's own name, its site (code or name) and its head —
so "who runs field ops in Mandalay" is one query. The list also answers
`_fragment=1` with just the count and rows, which is what the type-ahead
script swaps in without a page hop.
"""

import json

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.models import Department, Site


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser(
        "dept-searcher", "dept-search@example.com", "x"
    )
    client.force_login(user)
    return client


@pytest.fixture
def departments(db, site):
    from apps.people.models import Person

    mandalay = Site.objects.create(name="Mandalay Office", code="mandalay")
    Person.objects.create(employee_no="E-1", name="Su Myat Noe", site=site)
    head = Person.objects.create(employee_no="E-2", name="Kyaw Zin", site=mandalay)
    it = Department.objects.create(name="IT Support", site=site)
    ops = Department.objects.create(name="Field Operations", site=mandalay, head=head)
    hr = Department.objects.create(name="People Ops", site=site)
    return {"it": it, "ops": ops, "hr": hr, "head": head, "mandalay": mandalay}


def _names(client, params=None):
    resp = client.get(reverse("department-list"), params or {})
    assert resp.status_code == 200
    return sorted(d.name for d in resp.context["object_list"])


def test_search_box_sits_inside_the_filter_form(admin_client, departments):
    """Regression guard shared with People/Assets: an input outside the form
    submits an empty GET and silently clears the search."""
    html = admin_client.get(reverse("department-list")).content.decode()

    form = html.split('id="deptfilterform"', 1)[1].split("</form>", 1)[0]
    assert 'name="q"' in form
    assert "Search by name, site or head" in form


def test_search_matches_name_site_and_head(admin_client, departments):
    assert _names(admin_client) == ["Field Operations", "IT Support", "People Ops"]

    assert _names(admin_client, {"q": "field"}) == ["Field Operations"]  # name
    assert _names(admin_client, {"q": "FIELD"}) == ["Field Operations"]  # case-insensitive
    assert _names(admin_client, {"q": "mandalay"}) == ["Field Operations"]  # site code
    assert _names(admin_client, {"q": "Mandalay Office"}) == ["Field Operations"]  # site name
    assert _names(admin_client, {"q": "Kyaw Zin"}) == ["Field Operations"]  # head
    assert _names(admin_client, {"q": "no such dept"}) == []


def test_count_follows_the_search_and_the_clear_link_appears(admin_client, departments):
    html = admin_client.get(reverse("department-list"), {"q": "ops"}).content.decode()

    assert "1 departments" in html
    assert reverse("department-list") in html  # the Clear link back to all rows
    assert "People Ops" in html
    assert "IT Support" not in html and "Field Operations" not in html


def test_fragment_returns_only_count_and_rows(admin_client, departments):
    resp = admin_client.get(reverse("department-list"), {"q": "IT", "_fragment": "1"})

    assert resp.status_code == 200
    payload = json.loads(resp.content)
    assert set(payload) == {"count", "rows"}
    assert "1 departments" in payload["count"]
    assert "IT Support" in payload["rows"]
    assert "<html" not in payload["rows"].lower()  # a fragment, not a page

    empty = json.loads(
        admin_client.get(reverse("department-list"), {"q": "zzz", "_fragment": "1"}).content
    )
    assert "0 departments" in empty["count"]
    assert "empty-row" in empty["rows"]  # the same empty state the page shows
