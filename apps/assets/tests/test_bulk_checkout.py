"""Bulk department check-out (session 36).

`/assets/bulk-checkout/` ticks many AVAILABLE assets and assigns them all
to one department in a single POST — same contract as the bulk attach
queue: technician-gated, scope-narrowed, candidates re-derived server-side
before writing, and every asset goes through `services.check_out` so the
status sync and per-asset ActivityLog trail stay the normal lifecycle path.

1. GET lists AVAILABLE assets only, with site/category/search filters and
   a scope-narrowed department picker.
2. POST assigns every ticked asset (status sync + one check_out event per
   asset); a crafted pk outside the candidate set is dropped.
3. Guards: no dept / nothing ticked / viewer / anonymous.
4. Entry button on the assets list is technician-only.
"""

import pytest

from apps.assets.models import Asset, Assignment

pytestmark = pytest.mark.django_db

URL = "/assets/bulk-checkout/"


@pytest.fixture
def tech_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="technician")
    u = django_user_model.objects.create_user("tech_bulk", "tech_bulk@itasset.dev", "pass12345!")
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


@pytest.fixture
def viewer_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="viewer")
    u = django_user_model.objects.create_user(
        "viewer_bulk", "viewer_bulk@itasset.dev", "pw1234567!"
    )
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


@pytest.fixture
def dept_factory(db, site):
    from apps.people.models import Department

    counter = {"n": 0}

    def _make(name=None, **extra):
        counter["n"] += 1
        return Department.objects.create(
            name=name or f"Dept {counter['n']}",
            site=extra.pop("site", site),
            **extra,
        )

    return _make


# 1. GET ----------------------------------------------------------------------


def test_get_lists_only_available_assets(client, tech_user, asset_factory, person_factory):
    asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-AVL-6001")
    asset_factory(status=Asset.Status.IN_STOCK, asset_tag="IT-STK-6001")
    assigned = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ASG-6001")
    Assignment.objects.create(asset=assigned, to_person=person_factory(name="H"))

    client.force_login(tech_user)
    resp = client.get(URL)
    assert resp.status_code == 200
    tags = [a.asset_tag for a in resp.context["candidates"]]
    assert "IT-AVL-6001" in tags
    assert "IT-STK-6001" not in tags  # in-stock goes through receive first
    assert "IT-ASG-6001" not in tags  # already out — repair queue owns orphans
    # department picker present
    assert "to_dept" in resp.content.decode()


def test_get_filters_by_site_category_and_query(client, tech_user, asset_factory, category, site):
    from apps.people.models import Site

    hit = asset_factory(
        status=Asset.Status.AVAILABLE, asset_tag="IT-FIL-6001", model_name="MatchBox"
    )
    asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-FIL-6002", model_name="Other")
    other_site = Site.objects.create(code="mdy-bulk", name="MDY Bulk")
    asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-FIL-6003", site=other_site)

    client.force_login(tech_user)
    body = client.get(f"{URL}?q=MatchBox").content.decode()
    assert "IT-FIL-6001" in body and "IT-FIL-6002" not in body

    resp = client.get(f"{URL}?site={other_site.pk}")
    tags = [a.asset_tag for a in resp.context["candidates"]]
    assert tags == ["IT-FIL-6003"]

    resp = client.get(f"{URL}?category={category.pk}")
    assert hit.pk in [a.pk for a in resp.context["candidates"]]


# 2. POST ---------------------------------------------------------------------


def test_bulk_post_assigns_all_ticked_to_department(client, tech_user, asset_factory, dept_factory):
    from apps.audit.models import ActivityLog

    a1 = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-BLK-6001")
    a2 = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-BLK-6002")
    dept = dept_factory(name="Datacenter")

    client.force_login(tech_user)
    resp = client.post(URL, {"to_dept": dept.pk, "assets": [str(a1.pk), str(a2.pk)]})
    assert resp.status_code == 302

    for a in (a1, a2):
        row = Assignment.objects.get(asset=a, in_at__isnull=True)
        assert row.to_dept == dept
        assert row.to_person is None
        a.refresh_from_db()
        assert a.status == Asset.Status.ASSIGNED
    # one normal check_out event per asset (lifecycle path, not row surgery)
    events = ActivityLog.objects.filter(action="check_out")
    assert events.count() == 2
    assert all(e.details["to_dept"] == dept.pk for e in events)
    # list drained — both left the candidate set
    after = client.get(URL)
    tags = [a.asset_tag for a in after.context["candidates"]]
    assert "IT-BLK-6001" not in tags and "IT-BLK-6002" not in tags


def test_crafted_pk_outside_candidates_is_dropped(
    client, tech_user, asset_factory, dept_factory, person_factory
):
    from apps.audit.models import ActivityLog

    available = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-OK-6010")
    assigned = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-CRF-6010")
    Assignment.objects.create(asset=assigned, to_person=person_factory(name="Holder"))
    in_stock = asset_factory(status=Asset.Status.IN_STOCK, asset_tag="IT-CRF-6011")
    dept = dept_factory(name="Ops")

    client.force_login(tech_user)
    resp = client.post(
        URL,
        {
            "to_dept": dept.pk,
            "assets": [str(available.pk), str(assigned.pk), str(in_stock.pk)],
        },
    )
    assert resp.status_code == 302
    # only the assignable one went through
    assert Assignment.objects.filter(asset=available, to_dept=dept).exists()
    assert not Assignment.objects.filter(asset=assigned, to_dept=dept).exists()
    assert not Assignment.objects.filter(asset=in_stock).exists()
    assert ActivityLog.objects.filter(action="check_out").count() == 1


def test_post_without_department_is_refused(client, tech_user, asset_factory):
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    client.force_login(tech_user)
    resp = client.post(URL, {"assets": [str(asset.pk)]})
    assert resp.status_code == 302
    assert not Assignment.objects.filter(asset=asset).exists()
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE


def test_post_without_ticks_is_refused(client, tech_user, dept_factory):
    dept = dept_factory()
    client.force_login(tech_user)
    resp = client.post(URL, {"to_dept": dept.pk})
    assert resp.status_code == 302
    assert Assignment.objects.count() == 0


# 3. guards -------------------------------------------------------------------


def test_viewer_is_forbidden(client, viewer_user, asset_factory):
    asset_factory(status=Asset.Status.AVAILABLE)
    client.force_login(viewer_user)
    assert client.get(URL).status_code == 403
    assert client.post(URL, {"to_dept": 1}).status_code == 403


def test_anonymous_redirects(client, asset_factory):
    asset_factory(status=Asset.Status.AVAILABLE)
    resp = client.get(URL)
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


# 4. entry button -------------------------------------------------------------


def test_assets_list_offers_bulk_button_to_technicians_only(
    client, tech_user, viewer_user, asset_factory
):
    asset_factory(status=Asset.Status.AVAILABLE)
    client.force_login(tech_user)
    body = client.get("/assets/").content.decode()
    assert 'href="/assets/bulk-checkout/"' in body
    client.force_login(viewer_user)
    assert 'href="/assets/bulk-checkout/"' not in client.get("/assets/").content.decode()
