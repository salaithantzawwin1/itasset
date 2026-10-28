"""M2 CRUD view tests: role checks per §11 + happy paths.

Covers: anonymous → login redirect; viewer/auditor → 403 on create;
technician/admin can create assets; site/person manage is admin-only;
asset detail shows assignment history; the list search/quick-filter /
pagination contract (regression: filter inputs once sat outside the form).
"""

import re

import pytest

from apps.assets.models import Asset, AssetRequest, Category
from apps.people.models import Site

pytestmark = pytest.mark.django_db

URLS = {
    "site_list": "/sites/",
    "site_create": "/sites/new/",
    "person_list": "/people/",
    "person_create": "/people/new/",
    "asset_list": "/assets/",
    "asset_create": "/assets/new/",
}


def _login(client, user):
    client.force_login(user)


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {
        name: Group.objects.get_or_create(name=name)[0]
        for name in ("admin", "technician", "auditor", "viewer")
    }


def _user(django_user_model, group_setup, group_name, superuser=False):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(
        f"u_{group_name}", f"{group_name}@itasset.dev", "pass12345!"
    )
    if superuser:
        u.is_superuser = True
        u.save()
    else:
        u.groups.add(group_setup[group_name])
    # Feature tests, not scope tests: GLOBAL scope keeps enforcement
    # transparent (deny-by-default cases live in tests/test_scopes.py).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


# ---------------------------------------------------------------- privilégios
def test_anonymous_redirects_to_login(client):
    r = client.get(URLS["asset_list"])
    assert r.status_code == 302 and "login" in r.url


@pytest.mark.parametrize("page", ["asset_list", "site_list", "person_list"])
def test_authenticated_read_allowed(client, django_user_model, group_setup, page):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    assert client.get(URLS[page]).status_code == 200


def test_person_list_offers_add_button(client, django_user_model, group_setup):
    """The People page carries its create entry point: "+ New person" opens
    /people/new/ in the shared create-modal (session 34 — same pattern as
    the assets list's "+ New asset"; the admin-only role gate lives on the
    view itself, pinned by test_viewer_cannot_create)."""
    _login(client, _user(django_user_model, group_setup, "admin"))
    body = client.get(URLS["person_list"]).content.decode()
    assert '<a class="btn" href="/people/new/" data-modal>' in body
    assert "+ New person" in body


@pytest.mark.parametrize("page", ["asset_create", "site_create", "person_create"])
def test_viewer_cannot_create(client, django_user_model, group_setup, page):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    assert client.get(URLS[page]).status_code == 403


def test_auditor_cannot_create(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "auditor"))
    assert client.get(URLS["asset_create"]).status_code == 403


def test_technician_can_create_asset_but_not_site(client, django_user_model, group_setup):
    from apps.assets.models import Category

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)

    assert client.get(URLS["asset_create"]).status_code == 200
    assert client.get(URLS["site_create"]).status_code == 403

    site = _site()
    cat = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]
    r = client.post(
        URLS["asset_create"],
        {
            "asset_tag": "IT-HW-LAP-0001",
            "category": cat.pk,
            "site": site.pk,
            "status": "IN_STOCK",
            "condition": "GOOD",
        },
    )
    assert r.status_code == 302, r.context["form"].errors


def test_create_refuses_a_tag_from_another_category(client, django_user_model, group_setup):
    """§13 tag format {category-code}-{seq} — the production bug.

    `IT-HW-DSK-0010` was filed under `IT-HW-LAP`, so the register and the
    taxonomy disagreed about what the asset is. `Asset.clean()` refuses it
    on the way in: the form redisplays with the error and no row lands.
    """
    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    site = _site()
    Category.objects.get_or_create(code="IT-HW-DSK", defaults={"name": "Desktop / Workstation"})
    lap = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]

    r = client.post(
        URLS["asset_create"],
        {
            "asset_tag": "IT-HW-DSK-0010",  # a Desktop tag on a Laptop row
            "category": lap.pk,
            "site": site.pk,
            "status": "IN_STOCK",
            "condition": "GOOD",
        },
    )
    assert r.status_code == 200  # form redisplayed, not saved
    errors = r.context["form"].errors
    assert "asset_tag" in errors
    assert "IT-HW-DSK" in errors["asset_tag"][0]
    assert not Asset.objects.filter(asset_tag="IT-HW-DSK-0010").exists()


def test_retagging_onto_a_mismatched_category_is_blocked(
    client, django_user_model, group_setup, asset_factory
):
    """The other half of the bug: an asset whose category is changed while
    the tag keeps the old code. The row must not silently become a
    Desktop-tagged Laptop again — the edit stops until the tag follows."""
    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    desk = Category.objects.get_or_create(
        code="IT-HW-DSK", defaults={"name": "Desktop / Workstation"}
    )[0]
    lap = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]
    asset = asset_factory(asset_tag="IT-HW-DSK-0010", category=desk)

    r = client.post(
        f"/assets/{asset.pk}/edit/",
        {
            "asset_tag": asset.asset_tag,  # unchanged DSK tag
            "category": lap.pk,  # …filed under Laptop
            "site": asset.site_id,
            "status": asset.status,
            "condition": asset.condition,
        },
    )
    assert r.status_code == 200
    assert "asset_tag" in r.context["form"].errors
    asset.refresh_from_db()
    assert asset.category_id == desk.pk  # nothing changed on either axis

    # …and the fixed pair saves cleanly
    r2 = client.post(
        f"/assets/{asset.pk}/edit/",
        {
            "asset_tag": "IT-HW-LAP-0010",
            "category": lap.pk,
            "site": asset.site_id,
            "status": asset.status,
            "condition": asset.condition,
        },
    )
    assert r2.status_code == 302, r2.context["form"].errors
    asset.refresh_from_db()
    assert asset.asset_tag == "IT-HW-LAP-0010" and asset.category_id == lap.pk


def test_admin_can_manage_site(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "admin"))
    r = client.post(URLS["site_create"], {"name": "Mandalay HQ", "code": "mandalay"})
    assert r.status_code == 302
    from apps.people.models import Site

    assert Site.objects.filter(code="mandalay").exists()


def _site():
    from apps.people.models import Site

    return Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0]


def test_check_out_via_view(client, django_user_model, group_setup, asset_factory, person_factory):
    from apps.assets.services import active_assignment

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    person = person_factory(employee_no="E008", name="Someone")
    asset = asset_factory(status="AVAILABLE", serial="SN-CRUD1")
    r = client.post(f"/assets/{asset.pk}/check-out/", {"to_person": person.pk})
    assert r.status_code == 302
    assert active_assignment(asset).to_person_id == person.pk
    asset.refresh_from_db(fields=["status"])  # service updated the DB row
    assert asset.status == "ASSIGNED"


def test_check_in_via_view(client, django_user_model, group_setup, asset_factory, person_factory):
    from apps.assets.services import active_assignment

    tech = _user(django_user_model, group_setup, "technician")
    _login(client, tech)
    asset = asset_factory(status="AVAILABLE", serial="SN-CRUD2")
    client.post(f"/assets/{asset.pk}/check-out/", {"to_person": person_factory().pk})
    r = client.post(f"/assets/{asset.pk}/check-in/", {"condition_in": "GOOD"})
    assert r.status_code == 302
    assert active_assignment(asset) is None
    asset.refresh_from_db(fields=["status"])
    assert asset.status == "AVAILABLE"


# --------------------------------------------- search / quick filters / paging
def test_filter_form_contains_its_inputs(client, django_user_model, group_setup):
    """Regression: q/status/etc. once lived OUTSIDE #filterform, so Search
    submitted an empty GET and silently cleared the filters."""
    _login(client, _user(django_user_model, group_setup, "viewer"))
    html = client.get(URLS["asset_list"]).content.decode()
    match = re.search(r'<form id="filterform"[^>]*>(.*?)</form>', html, re.S)
    assert match, "#filterform missing from the asset list"
    inner = match.group(1)
    for field in ('name="q"', 'name="status"', 'name="warranty_days"', 'name="missing_serial"'):
        assert field in inner, f"{field} is not inside #filterform"


def test_search_filters_rows(client, django_user_model, group_setup, asset_factory):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    asset_factory(asset_tag="ZZZ-1", serial="SN-UNIQUE-1")
    asset_factory(asset_tag="ZZZ-2", serial="SN-OTHER-2")
    r = client.get(URLS["asset_list"], {"q": "SN-UNIQUE-1"})
    assert [a.asset_tag for a in r.context["object_list"]] == ["ZZZ-1"]


def test_search_matches_holder_name_and_department(
    client, django_user_model, group_setup, asset_factory, person_factory
):
    """The search box answers "who has it" as well as "what is it": an open
    assignment's person name, that person's own department, or the department
    the asset is checked out to matches (case-insensitive, like every other
    field), while a *closed* row is history, not a holder.
    """
    from apps.assets.models import Assignment
    from apps.people.models import Department

    _login(client, _user(django_user_model, group_setup, "viewer"))
    person_asset = asset_factory(asset_tag="IT-HLD-1", status=Asset.Status.ASSIGNED)
    holder = person_factory(name="Su Myat Noe")
    holder_dept = Department.objects.create(site=_site(), name="Shared Services")
    holder.department = holder_dept
    holder.save(update_fields=["department"])
    Assignment.objects.create(asset=person_asset, to_person=holder)
    # a closed history row on the same asset: must not match, and must not
    # duplicate the open hit either (EXISTS, not a join → one row, one count)
    Assignment.objects.create(asset=person_asset, to_person=holder, in_at=person_asset.updated_at)

    dept_asset = asset_factory(asset_tag="IT-HLD-2", status=Asset.Status.ASSIGNED)
    dept = Department.objects.create(site=_site(), name="Field Operations")
    Assignment.objects.create(asset=dept_asset, to_dept=dept)

    asset_factory(asset_tag="IT-HLD-3")  # in stock: no holder at all

    r = client.get(URLS["asset_list"], {"q": "Su Myat"})
    assert [a.asset_tag for a in r.context["object_list"]] == ["IT-HLD-1"]
    assert r.context["paginator"].count == 1  # history row did not fan it out

    # typing the holder's *department* finds the member's asset too — the
    # same thing the HOLDER column shows ("Su Myat Noe (Shared Services)")
    r = client.get(URLS["asset_list"], {"q": "shared services"})
    assert [a.asset_tag for a in r.context["object_list"]] == ["IT-HLD-1"]
    assert r.context["paginator"].count == 1

    r = client.get(URLS["asset_list"], {"q": "field operations"})  # case-insensitive
    assert [a.asset_tag for a in r.context["object_list"]] == ["IT-HLD-2"]

    # the department *filter* still works alongside the new q match
    r = client.get(URLS["asset_list"], {"department": dept.pk})
    assert [a.asset_tag for a in r.context["object_list"]] == ["IT-HLD-2"]


def test_quick_filters_warranty_and_missing_serial(
    client, django_user_model, group_setup, asset_factory
):
    from datetime import timedelta

    from django.utils import timezone

    _login(client, _user(django_user_model, group_setup, "viewer"))
    today = timezone.localdate()
    soon = asset_factory(asset_tag="W-1", serial="S1", warranty_end=today + timedelta(days=10))
    asset_factory(asset_tag="W-2", serial="S2", warranty_end=today + timedelta(days=200))
    noserial = asset_factory(asset_tag="W-3", serial="SN-PLACEHOLDER")
    noserial.serial_no = ""  # factory treats "" as unset and substitutes a serial
    noserial.save(update_fields=["serial_no"])

    r = client.get(URLS["asset_list"], {"warranty_days": "30"})
    assert [a.pk for a in r.context["object_list"]] == [soon.pk]
    r = client.get(URLS["asset_list"], {"warranty_days": "7"})
    assert list(r.context["object_list"]) == []  # 10 days > 7-day window
    r = client.get(URLS["asset_list"], {"missing_serial": "1"})
    assert [a.pk for a in r.context["object_list"]] == [noserial.pk]


def test_pagination_link_keeps_filters(client, django_user_model, group_setup, asset_factory):
    """Regression: ?page=N used to drop q/status (audit list did it right)."""
    _login(client, _user(django_user_model, group_setup, "viewer"))
    for i in range(51):
        asset_factory(asset_tag=f"PG-{i:03d}", serial=f"SN-PG-{i:03d}")

    r = client.get(URLS["asset_list"], {"q": "PG"})
    assert r.context["is_paginated"] is True
    html = r.content.decode()
    # literal & in the template stays & (autoescape covers variable output only)
    assert 'href="?page=2&q=PG' in html, "page-2 link lost the q filter"

    r2 = client.get(URLS["asset_list"], {"q": "PG", "page": 2})
    assert len(r2.context["object_list"]) == 1  # 51st row lands on page 2


# ------------------------------------------ employee request UI (§6.5 stage ①)
def test_request_create_requires_login(client):
    r = client.get("/requests/new/")
    assert r.status_code == 302 and "login" in r.url


def test_request_form_renders(client, django_user_model, group_setup):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    r = client.get("/requests/new/")
    assert r.status_code == 200
    fields = r.context["form"].fields
    assert set(fields) == {"category", "site", "quantity", "justification"}
    assert "requester" not in fields  # set server-side, never client-supplied


def test_request_submission_creates_pending_row(
    client, django_user_model, group_setup, site, category
):
    user = _user(django_user_model, group_setup, "viewer")
    _login(client, user)
    r = client.post(
        "/requests/new/",
        {
            "category": category.pk,
            "site": site.pk,
            "quantity": 2,
            "justification": "Need a laptop for onboarding.",
        },
    )
    assert r.status_code == 302 and r.url == "/me/"
    req = AssetRequest.objects.get()
    assert req.requester_id == user.pk
    assert req.status == AssetRequest.Status.PENDING
    assert req.quantity == 2


def test_quantity_must_be_positive(client, django_user_model, group_setup, site, category):
    _login(client, _user(django_user_model, group_setup, "viewer"))
    r = client.post(
        "/requests/new/",
        {"category": category.pk, "site": site.pk, "quantity": 0, "justification": "x"},
    )
    assert r.status_code == 200  # re-rendered with the error
    assert "quantity" in r.context["form"].errors
    assert not AssetRequest.objects.exists()


def test_request_carve_out_own_site_only(client, django_user_model, db, settings):
    """No org-scope rows + linked Person → may request for their own site only
    (§4.4 self carve-out); another site is a crafted POST → 403, no row."""
    from apps.people.models import Person

    settings.SCOPE_ENFORCEMENT_ENABLED = True  # shadow mode would allow all
    own = Site.objects.create(name="Own", code="own")
    other = Site.objects.create(name="Other", code="other")
    cat = Category.objects.get_or_create(code="IT-HW-PER", defaults={"name": "Peripheral"})[0]
    emp = django_user_model.objects.create_user("emp1", "e@x.dev", "pass12345!")
    Person.objects.create(employee_no="E777", name="Emp", site=own, user=emp)
    _login(client, emp)

    r = client.get("/requests/new/")
    choices = list(r.context["form"].fields["site"].queryset)
    assert [s.pk for s in choices] == [own.pk]  # own site only

    r = client.post(
        "/requests/new/",
        {"category": cat.pk, "site": other.pk, "quantity": 1, "justification": "x"},
    )
    # the restricted site queryset rejects the crafted choice at form level
    # (the view keeps a second pk check behind it as defense in depth)
    assert r.status_code == 200
    assert "site" in r.context["form"].errors
    assert not AssetRequest.objects.exists()


# ------------------------------------------------- overdue loans page (§14)
def test_overdue_loans_requires_login(client):
    r = client.get("/loans/overdue/")
    assert r.status_code == 302 and "login" in r.url


def test_overdue_loans_lists_only_past_due(
    client, django_user_model, group_setup, asset_factory, person_factory, settings
):
    from datetime import timedelta

    from django.utils import timezone

    from apps.assets.models import Assignment

    settings.SCOPE_ENFORCEMENT_ENABLED = True
    _login(client, _user(django_user_model, group_setup, "viewer"))  # GLOBAL scope
    person = person_factory()
    late = Assignment.objects.create(
        asset=asset_factory(),
        to_person=person,
        due_at=timezone.now() - timedelta(days=3),
    )
    Assignment.objects.create(
        asset=asset_factory(),
        to_person=person,
        due_at=timezone.now() + timedelta(days=5),  # not due yet → hidden
    )
    r = client.get("/loans/overdue/")
    assert r.status_code == 200
    loans = list(r.context["loans"])
    assert [loan.pk for loan in loans] == [late.pk]
    assert loans[0].days_late == 3
    assert "3d late" in r.content.decode()


def test_overdue_loans_empty_without_scope(client, django_user_model, asset_factory, settings):
    from datetime import timedelta

    from django.utils import timezone

    from apps.assets.models import Assignment

    settings.SCOPE_ENFORCEMENT_ENABLED = True
    emp = django_user_model.objects.create_user("noloan", "nl@x.dev", "pass12345!")
    _login(client, emp)  # no scope rows → deny by default
    Assignment.objects.create(asset=asset_factory(), due_at=timezone.now() - timedelta(days=1))
    r = client.get("/loans/overdue/")
    assert r.status_code == 200
    assert list(r.context["loans"]) == []


# --------------------------------- my requests: approval progress (self-view)
def test_my_requests_show_progress_stages(client, django_user_model, group_setup, site, category):
    from apps.assets import services

    user = _user(django_user_model, group_setup, "viewer")
    _login(client, user)
    services.create_request(requester=user, category=category, site=site)

    def progress():
        return client.get("/me/").context["request_rows"][0]["progress"]

    p = progress()
    assert p["label_key"] == "prog.approval_wait"
    assert [s["state"] for s in p["stages"]] == ["done", "current", "todo", "todo"]
    assert (p["cur"], p["total"]) == (1, 1)
    assert "Awaiting approval" in client.get("/me/").content.decode()

    req = AssetRequest.objects.get()
    req.status = AssetRequest.Status.APPROVED
    req.save(update_fields=["status"])
    p = progress()
    assert p["label_key"] == "prog.await_procure"
    assert [s["state"] for s in p["stages"]] == ["done", "done", "current", "todo"]

    req.status = AssetRequest.Status.REJECTED
    req.save(update_fields=["status"])
    p = progress()
    assert p["label_key"] == "prog.rejected"
    assert [s["state"] for s in p["stages"]] == ["done", "failed", "todo", "todo"]
    assert "Rejected at approval" in client.get("/me/").content.decode()


# ------------------------------------------- tabbed create/edit form (sections)
def test_form_split_into_tabs_renders_every_field(
    client, django_user_model, group_setup, asset_factory
):
    """The edit/create page is sectioned into tabs — and a bucketing bug must
    never silently drop a field (unrendered fields also vanish from POST)."""
    from apps.assets.forms import AssetForm

    _login(client, _user(django_user_model, group_setup, "admin"))
    asset = asset_factory()

    # edit carries the instance's category → spec fields; create has no
    # category chosen yet → only the base fields (specs attach on POST).
    cases = (
        (f"/assets/{asset.pk}/edit/", AssetForm(instance=asset)),
        ("/assets/new/", AssetForm()),
    )
    for url, form in cases:
        html = client.get(url).content.decode()
        assert 'role="tablist"' in html, url
        for key in ("basics", "specs", "device", "procurement"):
            assert f'data-tab-panel="{key}"' in html, f"{key} panel missing from {url}"
        for name in form.fields:
            assert f'name="{name}"' in html, f"field {name} missing from {url}"


# ------------------------------- category-driven tag auto-assign + live swap
def test_next_asset_tag_sequences_per_category(asset_factory):
    """<CODE>-NNNN: highest numeric suffix wins; garbage suffixes ignored."""
    from apps.assets import services
    from apps.assets.models import Category

    lap = Category.objects.get(code="IT-HW-LAP")
    asset_factory(asset_tag="IT-HW-LAP-0003", category=lap)
    asset_factory(asset_tag="IT-HW-LAP-GHOST", category=lap)
    assert services.next_asset_tag(lap) == "IT-HW-LAP-0004"


def test_create_with_empty_tag_gets_next_category_tag(client, django_user_model, group_setup):
    """Server-side auto-assign: a tagless create POST picks up the category's
    next sequence (works without JS, and backs the client-side fill)."""
    from apps.assets.models import Asset, Category

    _login(client, _user(django_user_model, group_setup, "technician"))
    cat = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]
    r = client.post(
        URLS["asset_create"],
        {
            "asset_tag": "",
            "category": cat.pk,
            "site": _site().pk,
            "status": "IN_STOCK",
            "condition": "GOOD",
        },
    )
    assert r.status_code == 302, r.context["form"].errors
    assert Asset.objects.latest("pk").asset_tag == "IT-HW-LAP-0001"


def test_field_suggest_gates_and_returns_category_fields(client, django_user_model, group_setup):
    """The live-swap endpoint: gated like the forms (401/403), and the spec
    fragment really differs between categories (Laptop vs Monitor)."""
    from apps.assets.models import Category

    url = "/assets/field-suggest/?category={}"
    assert client.get(url.format(1)).status_code == 401

    _login(client, _user(django_user_model, group_setup, "viewer"))
    assert client.get(url.format(1)).status_code == 403

    _login(client, _user(django_user_model, group_setup, "technician"))
    lap = Category.objects.get(code="IT-HW-LAP")
    mon = Category.objects.get(code="IT-HW-MON")

    j_lap = client.get(url.format(lap.pk)).json()
    j_mon = client.get(url.format(mon.pk)).json()
    assert j_lap["next_tag"] == "IT-HW-LAP-0001"
    assert j_mon["next_tag"] == "IT-HW-MON-0001"
    assert 'name="spec__' in j_lap["html"] and 'name="spec__' in j_mon["html"]
    assert j_lap["html"] != j_mon["html"], "different categories → different fields"

    # main-app fragment = <p> rows; admin fragment = fieldset .form-row rows
    assert j_lap["html"].lstrip().startswith("<p")
    admin = client.get(url.format(lap.pk) + "&surface=admin").json()
    assert 'class="form-row' in admin["html"]

    # unknown category → 400, empty fragment
    bad = client.get(url.format(999999))
    assert bad.status_code == 400
    assert bad.json()["html"] == ""
