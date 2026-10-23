"""Holder-facing flows (session 30).

1. Person detail splits into "currently held" (open rows, category/site/
   status) + a capped history card — the query is select_related, not N+1.
2. The orphan fix-up queue (/assets/repair/) lists ASSIGNED assets with no
   open row and repairs them through `services.check_out` (trail intact),
   technician-gated like the other writes.
3. Bulk attach (/assets/<pk>/attach/) links same-site unparented components
   to a workstation in one POST; a crafted cross-site/already-parented pk
   is dropped by re-deriving candidates server-side; one ActivityLog event.
4. Asset list filters: by the holder's department (open assignment only)
   and "assigned to me" (linked Person; no link → empty list, not everyone).
5. Filter-bar fine-tune (session 33): active controls tinted + selects
   auto-submit; the width:100% cascade override stays off `.filterbar select`.
"""

import pytest

from apps.assets.models import Asset, Assignment
from apps.audit.models import ActivityLog

pytestmark = pytest.mark.django_db


@pytest.fixture
def tech_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="technician")
    u = django_user_model.objects.create_user("tech_flows", "tech_flows@itasset.dev", "pass12345!")
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
        "viewer_flows", "viewer_flows@itasset.dev", "pw1234567!"
    )
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


# 1. person detail -------------------------------------------------------------


def test_person_detail_splits_held_now_from_history(
    client, tech_user, asset_factory, person_factory
):
    person = person_factory(name="Holder One")
    held = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HELD-0001")
    Assignment.objects.create(asset=held, to_person=person)
    done = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-DONE-0001")
    closed = Assignment.objects.create(asset=done, to_person=person, in_at=done.updated_at)

    client.force_login(tech_user)
    resp = client.get(f"/people/{person.pk}/")
    assert resp.status_code == 200
    held_now = list(resp.context["held_now"])
    history = list(resp.context["history_recent"])
    assert [a.asset_id for a in held_now] == [held.pk]
    assert [a.asset_id for a in history] == [closed.asset_id]
    body = resp.content.decode()
    assert "IT-HELD-0001" in body and "IT-DONE-0001" in body
    # held row shows category + status pill (not just a bare tag)
    assert "Currently held" in body


def test_person_detail_empty_state(client, tech_user, person_factory):
    person = person_factory(name="Nobody Yet")
    client.force_login(tech_user)
    body = client.get(f"/people/{person.pk}/").content.decode()
    assert "No assets currently held." in body


# 2. orphan fix-up queue -------------------------------------------------------


def test_orphan_queue_lists_and_repairs(client, tech_user, asset_factory, person_factory):
    orphan = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-1001")
    healthy = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HEAL-1001")
    Assignment.objects.create(asset=healthy, to_person=person_factory(name="Real Holder"))

    client.force_login(tech_user)
    resp = client.get("/assets/repair/")
    body = resp.content.decode()
    assert "IT-ORPH-1001" in body, (
        resp.status_code,
        "Repair assignments" in body,
        len(list(resp.context.get("orphans", []))) if resp.context else None,
    )
    assert "IT-HEAL-1001" not in body  # has a holder — nothing to repair

    person = person_factory(name="Picked Holder")
    resp = client.post("/assets/repair/", {"asset": orphan.pk, "to_person": person.pk})
    assert resp.status_code == 302
    row = Assignment.objects.filter(asset=orphan, in_at__isnull=True).get()
    assert row.to_person == person
    assert "repaired" in row.remarks
    # queue no longer lists it (the success message still carries the tag,
    # so assert on the queue rows, not the raw page body)
    after = client.get("/assets/repair/")
    assert list(after.context["orphans"]) == []


def test_orphan_queue_requires_technician(client, viewer_user, asset_factory):
    asset_factory(status=Asset.Status.ASSIGNED)  # an orphan to see
    client.force_login(viewer_user)
    resp = client.get("/assets/repair/")
    assert resp.status_code == 403


def test_orphan_queue_anonymous_redirects(client, asset_factory):
    asset_factory(status=Asset.Status.ASSIGNED)
    resp = client.get("/assets/repair/")
    assert resp.status_code == 302


# 3. bulk attach ---------------------------------------------------------------


def test_bulk_attach_links_same_site_candidates(client, tech_user, asset_factory, site, category):
    from apps.people.models import Site

    desk = asset_factory(asset_tag="IT-DESK-2001")
    c1 = asset_factory(asset_tag="IT-COMP-2001")  # same fixture site
    c2 = asset_factory(asset_tag="IT-COMP-2002")
    other_site = Site.objects.create(code="mdy-test", name="MDY Test")
    foreign = asset_factory(asset_tag="IT-COMP-2099", site=other_site)
    already = asset_factory(asset_tag="IT-COMP-2003")
    already.parent_asset = desk
    already.save(update_fields=["parent_asset"])

    client.force_login(tech_user)
    body = client.get(f"/assets/{desk.pk}/attach/").content.decode()
    assert "IT-COMP-2001" in body and "IT-COMP-2002" in body
    assert "IT-COMP-2099" not in body  # other site never listed
    # the workstation itself is never a candidate (no self-tick)
    assert f'value="{desk.pk}"' not in body

    resp = client.post(
        f"/assets/{desk.pk}/attach/",
        # crafted POST sneaks the foreign + already-parented pks in
        {"assets": [str(c1.pk), str(c2.pk), str(foreign.pk), str(already.pk)]},
    )
    assert resp.status_code == 302
    c1.refresh_from_db()
    c2.refresh_from_db()
    foreign.refresh_from_db()
    already.refresh_from_db()
    assert c1.parent_asset_id == desk.pk
    assert c2.parent_asset_id == desk.pk
    assert foreign.parent_asset_id is None  # cross-site refused
    assert already.parent_asset_id == desk.pk  # unchanged (same value)

    event = ActivityLog.objects.filter(action="component_attach").first()
    assert event is not None
    assert event.details["components"] == sorted([c1.pk, c2.pk]) or set(
        event.details["components"]
    ) == {c1.pk, c2.pk}


def test_bulk_attach_requires_technician(client, viewer_user, asset_factory):
    desk = asset_factory()
    client.force_login(viewer_user)
    assert client.get(f"/assets/{desk.pk}/attach/").status_code == 403


def test_detail_page_offers_attach_to_technicians(client, tech_user, viewer_user, asset_factory):
    desk = asset_factory()
    client.force_login(tech_user)
    assert "Attach components" in client.get(f"/assets/{desk.pk}/").content.decode()
    client.force_login(viewer_user)
    # viewers see the card only when components exist; no button either way
    assert "Attach components" not in client.get(f"/assets/{desk.pk}/").content.decode()


# 4. list filters --------------------------------------------------------------


def test_department_filter_keeps_only_held_assets_of_that_department(
    client, tech_user, asset_factory, person_factory, site
):
    from apps.people.models import Department

    finance = Department.objects.create(name="Finance", site=site)
    ops = Department.objects.create(name="Ops", site=site)
    holder_f = person_factory(name="Fin Holder")
    holder_f.department = finance
    holder_f.save(update_fields=["department"])
    holder_o = person_factory(name="Ops Holder")
    holder_o.department = ops
    holder_o.save(update_fields=["department"])

    a_fin = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-FIN-3001")
    Assignment.objects.create(asset=a_fin, to_person=holder_f)
    a_ops = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-OPS-3001")
    Assignment.objects.create(asset=a_ops, to_person=holder_o)

    client.force_login(tech_user)
    body = client.get(f"/assets/?department={finance.pk}").content.decode()
    assert "IT-FIN-3001" in body
    assert "IT-OPS-3001" not in body


def test_mine_filter_uses_linked_person(
    client, tech_user, asset_factory, person_factory, django_user_model
):
    mine = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-MINE-4001")
    mine_holder = person_factory(name="Me Myself")
    mine_holder.user = tech_user
    mine_holder.save(update_fields=["user"])
    Assignment.objects.create(asset=mine, to_person=mine_holder)
    theirs = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-THEIR-4001")
    Assignment.objects.create(asset=theirs, to_person=person_factory(name="Other"))

    client.force_login(tech_user)
    body = client.get("/assets/?mine=1").content.decode()
    assert "IT-MINE-4001" in body
    assert "IT-THEIR-4001" not in body


def test_mine_filter_empty_without_person_link(client, tech_user, asset_factory, person_factory):
    # no linked Person → mine must answer nothing, never "everyone"
    linked = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-LINK-4009")
    Assignment.objects.create(asset=linked, to_person=person_factory(name="Somebody"))

    client.force_login(tech_user)
    resp = client.get("/assets/?mine=1")
    assert list(resp.context["object_list"]) == []


def test_filter_bar_active_state_and_cascade(client, tech_user, site):
    """Session 33's fine-tune: active controls are tinted + auto-apply, and
    the width:100% override that stacked every filterbar select onto its
    own row stays out of the shared form rule (the cascade bug: same
    specificity, later in the sheet than `.filterbar select`'s width:auto)."""
    from apps.people.models import Department

    dept = Department.objects.create(name="FinTune", site=site)
    client.force_login(tech_user)
    body = client.get(f"/assets/?status=ASSIGNED&department={dept.pk}&mine=1").content.decode()
    # active select is tinted and applies immediately
    assert 'name="status" class="on" onchange="this.form.submit()"' in body
    assert 'name="department" class="on" onchange="this.form.submit()"' in body
    # inactive select carries neither tint nor class
    assert 'name="warranty_days" class="on"' not in body
    assert 'name="warranty_days"' in body
    # checkbox container tints when ticked
    assert 'class="chk on"' in body
    # the cascade pin: width:100% is scoped to frm/inline controls only
    assert (
        "form.frm input, form.frm select, form.frm textarea, form.inline-form "
        "select { width: 100%; }" in body
    )
    assert ".filterbar input, .filterbar select { width: 100%;" not in body
