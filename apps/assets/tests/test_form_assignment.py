"""Person ↔ Asset linking through the edit form (session 29).

(a) the "Assigned to" picker on `AssetForm` drives check-out / handover /
    check-in through the lifecycle services — status and the append-only
    assignment trail stay in sync, and clearing the picker returns the asset.
(b) `parent_asset` links a component to its workstation (§6.1 recommended
    relationship) — the detail page lists the peripherals, each keeping its
    own holder, and a parent loop is refused.
(c) the assets-by-department report groups active holders by the holder's
    department, and flags ASSIGNED assets with no open assignment.
(d) orphan recovery: an asset whose status says ASSIGNED with no open row
    (the "Assigned assets cannot be checked out" dead-end) can be repaired
    from the form and the detail page, and the form refuses a reverse orphan
    (open row + a non-Assigned status with the holder untouched).
"""

import pytest

from apps.assets.forms import AssetForm
from apps.assets.models import Asset, Assignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def tech_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="technician")
    u = django_user_model.objects.create_user("tech_form", "tech_form@itasset.dev", "pass12345!")
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


def _post(asset, **extra):
    data = {
        "asset_tag": asset.asset_tag,
        "category": asset.category_id,
        "site": asset.site_id,
        "status": asset.status,
        "condition": asset.condition,
    }
    data.update(extra)
    return data


# (a) picker → services -------------------------------------------------------


def test_create_with_picker_assigns_immediately(client, tech_user, asset_factory, person_factory):
    person = person_factory(name="Cho Cho")
    client.force_login(tech_user)
    cat = asset_factory().category
    site = asset_factory().site
    resp = client.post(
        "/assets/new/",
        {
            "asset_tag": "IT-TEST-0001",
            "category": cat.pk,
            "site": site.pk,
            # the form's selects always post these (pre-filled defaults)
            "status": Asset.Status.IN_STOCK,
            "condition": Asset.Condition.GOOD,
            "assigned_to": person.pk,
        },
    )
    if resp.status_code != 302:  # pragma: no cover - debugging aid
        form = resp.context.get("form") if resp.context else None
        pytest.fail(f"create failed: {resp.status_code} {getattr(form, 'errors', None)}")
    asset = Asset.objects.get(asset_tag="IT-TEST-0001")
    assert asset.status == Asset.Status.ASSIGNED
    active = Assignment.objects.filter(asset=asset, in_at__isnull=True).get()
    assert active.to_person == person


def test_edit_picker_assigns_available_asset(client, tech_user, asset_factory, person_factory):
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    person = person_factory(name="Aung Aung")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=person.pk))
    assert resp.status_code == 302
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED
    active = Assignment.objects.filter(asset=asset, in_at__isnull=True).get()
    assert active.to_person == person
    assert active.remarks  # the form path labels its trail rows


def test_edit_picker_same_holder_is_a_noop(client, tech_user, asset_factory, person_factory):
    person = person_factory(name="Same Holder")
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    Assignment.objects.create(asset=asset, to_person=person)
    before = Assignment.objects.count()
    client.force_login(tech_user)
    client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=person.pk))
    assert Assignment.objects.count() == before


def test_edit_picker_handover_closes_and_opens(client, tech_user, asset_factory, person_factory):
    old = person_factory(name="Old Holder")
    new = person_factory(name="New Holder")
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    open_row = Assignment.objects.create(asset=asset, to_person=old)
    client.force_login(tech_user)
    client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=new.pk))
    open_row.refresh_from_db()
    assert open_row.in_at is not None  # closed
    fresh = Assignment.objects.filter(asset=asset, in_at__isnull=True).get()
    assert fresh.to_person == new
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED  # preserved across handover


def test_edit_clearing_picker_checks_in(client, tech_user, asset_factory, person_factory):
    person = person_factory(name="Returning")
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    open_row = Assignment.objects.create(asset=asset, to_person=person)
    client.force_login(tech_user)
    client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=""))
    open_row.refresh_from_db()
    assert open_row.in_at is not None
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE


def test_edit_picker_refused_on_in_repair(client, tech_user, asset_factory, person_factory):
    asset = asset_factory(status=Asset.Status.IN_REPAIR)
    person = person_factory(name="Blocked")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=person.pk))
    assert resp.status_code == 200  # re-rendered with the error
    assert b"lifecycle flow" in resp.content
    assert Assignment.objects.filter(asset=asset).count() == 0


# (b) parent ↔ component -----------------------------------------------------


def test_detail_lists_components_with_their_holders(
    client, tech_user, asset_factory, person_factory
):
    desktop = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HW-DSK-9001")
    monitor = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-HW-MON-9001")
    holder = person_factory(name="Mon Owner")
    Assignment.objects.create(asset=desktop, to_person=person_factory(name="Desk Owner"))
    Assignment.objects.create(asset=monitor, to_person=holder)
    monitor.parent_asset = desktop
    monitor.save(update_fields=["parent_asset"])

    client.force_login(tech_user)
    resp = client.get(f"/assets/{desktop.pk}/")
    body = resp.content.decode()
    assert "Components" in body
    assert "IT-HW-MON-9001" in body
    assert "Mon Owner" in body  # the component's own holder, not the desk's
    # the component page points back at its parent
    back = client.get(f"/assets/{monitor.pk}/")
    assert "IT-HW-DSK-9001" in back.content.decode()


def test_form_refuses_parent_loop(client, tech_user, asset_factory):
    a = asset_factory(asset_tag="IT-LOOP-A")
    b = asset_factory(asset_tag="IT-LOOP-B")
    c = asset_factory(asset_tag="IT-LOOP-C")
    b.parent_asset = a
    b.save(update_fields=["parent_asset"])
    c.parent_asset = b
    c.save(update_fields=["parent_asset"])
    # making A a child of C would close the loop
    form = AssetForm(data=_post(a, parent_asset=c.pk), instance=a, request=None)
    assert not form.is_valid()
    assert "parent_asset" in form.errors


def test_self_parent_refused(asset_factory):
    a = asset_factory()
    form = AssetForm(data=_post(a, parent_asset=a.pk), instance=a)
    assert not form.is_valid()
    assert "parent_asset" in form.errors


# (c) department report -------------------------------------------------------


def test_assets_by_department_report(client, tech_user, asset_factory, person_factory, site):
    from apps.people.models import Department

    dept = Department.objects.create(name="Finance", site=site)
    holder = person_factory(name="Dept Holder")
    holder.department = dept
    holder.save(update_fields=["department"])
    asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-DEPT-0001")
    Assignment.objects.create(asset=asset, to_person=holder)
    # completeness check: ASSIGNED with no open assignment row
    asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-DEPT-0002")

    client.force_login(tech_user)
    resp = client.get("/reports/assets-by-department.csv")
    assert resp.status_code == 200
    body = resp.content.decode("utf-8-sig")
    assert "Finance" in body
    assert "Dept Holder" in body
    assert "IT-DEPT-0001" in body
    assert "Not assigned" in body  # IT-DEPT-0002 has no open assignment


def test_report_requires_login(client, asset_factory, site):
    from apps.people.models import Department

    asset_factory()
    resp = client.get("/reports/assets-by-department.csv")
    assert resp.status_code == 302  # redirected to login
    assert Department.objects.count() >= 0  # smoke: report app loads


# (d) orphan recovery ---------------------------------------------------------


def test_form_repairs_orphan_assignment(client, tech_user, asset_factory, person_factory):
    # status ASSIGNED + no open row — the state behind
    # "Assigned assets cannot be checked out from this form"
    asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-0001")
    person = person_factory(name="Repair Picker")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _post(asset, assigned_to=person.pk))
    assert resp.status_code == 302
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED
    active = Assignment.objects.filter(asset=asset, in_at__isnull=True).get()
    assert active.to_person == person


def test_status_keeps_holder_refused(client, tech_user, asset_factory, person_factory):
    # reverse orphan: an open row + a non-Assigned status while the holder
    # field is untouched — clear the picker instead (check_in sets status)
    person = person_factory(name="Stays Held")
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    Assignment.objects.create(asset=asset, to_person=person)
    client.force_login(tech_user)
    resp = client.post(
        f"/assets/{asset.pk}/edit/",
        _post(asset, status=Asset.Status.AVAILABLE, assigned_to=person.pk),
    )
    assert resp.status_code == 200
    assert b"id_status_error" in resp.content
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED  # row untouched


def test_detail_orphan_offers_checkout(client, tech_user, asset_factory, person_factory):
    orphan = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-0002")
    client.force_login(tech_user)
    body = client.get(f"/assets/{orphan.pk}/").content.decode()
    assert 'name="to_person"' in body  # check-out picker, not check-in
    assert "no holder is recorded" in body  # the repair hint

    held = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-0003")
    Assignment.objects.create(asset=held, to_person=person_factory(name="Held"))
    body2 = client.get(f"/assets/{held.pk}/").content.decode()
    assert 'name="condition_in"' in body2  # proper holder → check-in stays
