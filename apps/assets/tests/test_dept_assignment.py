"""Department-as-holder (session 31).

Servers/NAS/Switches and shared laptop pools are assigned to a Department
instead of an individual. Coverage:

1. services.check_out(department=…) opens an Assignment with to_dept set,
   refuses person+dept / neither, and keeps status in sync.
2. Edit form: assigned_dept picker checks out, returns, and switches holder
   kind (person ↔ department); filling both pickers is refused.
3. Detail-page check-out picker and orphan repair accept a department target;
   a crafted POST with both targets is ignored (exactly one required).
4. Asset list department filter matches department-held assets.
5. Department report: department-held rows + summary (dept, count, value);
   orphan report flags reverse orphans (open row, status not ASSIGNED).
"""

import pytest

from apps.assets.models import Asset, Assignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def tech_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="technician")
    u = django_user_model.objects.create_user("tech_dept", "tech_dept@itasset.dev", "pass12345!")
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


# 1. services -----------------------------------------------------------------


def test_check_out_to_department(db, asset_factory, dept_factory, tech_user):
    from apps.assets import services

    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory(name="Infrastructure")
    result = services.check_out(asset, actor=tech_user, department=dept)
    assert result.assignment.to_dept == dept
    assert result.assignment.to_person is None
    assert asset.status == Asset.Status.ASSIGNED
    # ActivityLog records the dept target too
    from apps.audit.models import ActivityLog

    ev = ActivityLog.objects.filter(action="check_out").latest("created_at")
    assert ev.details["to_dept"] == dept.pk
    assert ev.details["to_person"] is None


def test_check_out_requires_exactly_one_holder(
    db, asset_factory, dept_factory, person_factory, tech_user
):
    from apps.assets import services

    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory()
    person = person_factory(name="Extra")
    with pytest.raises(TypeError):
        services.check_out(asset, actor=tech_user)  # neither
    with pytest.raises(TypeError):
        services.check_out(asset, person, actor=tech_user, department=dept)  # both


def test_holder_label_and_str(db, asset_factory, dept_factory, tech_user):
    from apps.assets import services

    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory(name="Network Ops")
    result = services.check_out(asset, actor=tech_user, department=dept)
    assert result.assignment.holder_label == "Network Ops (dept)"
    assert "Network Ops (dept)" in str(result.assignment)


def test_check_in_returns_department_held_asset(db, asset_factory, dept_factory, tech_user):
    from apps.assets import services

    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory()
    services.check_out(asset, actor=tech_user, department=dept)
    services.check_in(asset, actor=tech_user)
    assert asset.status == Asset.Status.AVAILABLE
    assert services.active_assignment(asset) is None


# 2. edit form ----------------------------------------------------------------


def _form_post(asset, **extra):
    """Minimal valid payload for the tabbed asset form."""
    payload = {
        "asset_tag": asset.asset_tag,
        "category": asset.category_id,
        "site": asset.site_id,
        "status": asset.status,
        "condition": asset.condition,
        "manufacturer": "",
        "model_name": "",
        "serial_no": asset.serial_no,
        "hostname": "",
        "purchase_date": "",
        "cost": "",
        "warranty_end": "",
        "parent_asset": "",
        "remarks": "",
        "assigned_to": "",
        "assigned_dept": "",
    }
    payload.update(extra)
    return payload


def test_form_assigns_to_department(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory(name="Datacenter")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _form_post(asset, assigned_dept=dept.pk))
    assert resp.status_code == 302, (
        resp.context["form"].errors if resp.context and resp.context.get("form") else None
    )
    active = Assignment.objects.get(asset=asset, in_at__isnull=True)
    assert active.to_dept == dept
    assert active.to_person is None
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED


def test_form_clearing_department_returns_asset(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    dept = dept_factory()
    Assignment.objects.create(asset=asset, to_dept=dept)
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _form_post(asset))
    assert resp.status_code == 302
    assert not Assignment.objects.filter(asset=asset, in_at__isnull=True).exists()
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE


def test_form_switches_holder_kind_person_to_dept(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    person = person_factory(name="Old Holder")
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    Assignment.objects.create(asset=asset, to_person=person)
    dept = dept_factory(name="Facilities")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/edit/", _form_post(asset, assigned_dept=dept.pk))
    assert resp.status_code == 302
    open_rows = Assignment.objects.filter(asset=asset, in_at__isnull=True)
    assert open_rows.count() == 1
    assert open_rows.get().to_dept == dept


def test_form_refuses_both_holders(client, tech_user, asset_factory, person_factory, dept_factory):
    person = person_factory()
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory()
    client.force_login(tech_user)
    resp = client.post(
        f"/assets/{asset.pk}/edit/",
        _form_post(asset, assigned_to=person.pk, assigned_dept=dept.pk),
    )
    assert resp.status_code == 200  # re-rendered with errors
    form = resp.context["form"]
    assert "assigned_to" in form.errors
    assert not Assignment.objects.filter(asset=asset, in_at__isnull=True).exists()


def test_form_seeds_department_picker_on_edit(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    dept = dept_factory(name="Storage Team")
    Assignment.objects.create(asset=asset, to_dept=dept)
    client.force_login(tech_user)
    body = client.get(f"/assets/{asset.pk}/edit/").content.decode()
    assert "Storage Team" in body  # picker pre-seeded with the dept holder


# 3. detail page + orphan repair ---------------------------------------------


def test_detail_check_out_to_department(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory(name="Server Ops")
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/check-out/", {"to_dept": dept.pk})
    assert resp.status_code == 302
    active = Assignment.objects.get(asset=asset, in_at__isnull=True)
    assert active.to_dept == dept
    # detail page shows the department holder
    body = client.get(f"/assets/{asset.pk}/").content.decode()
    assert "Server Ops" in body


def test_detail_check_out_with_both_targets_is_ignored(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    person = person_factory()
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory()
    client.force_login(tech_user)
    client.post(
        f"/assets/{asset.pk}/check-out/",
        {"to_person": person.pk, "to_dept": dept.pk},
    )
    assert not Assignment.objects.filter(asset=asset).exists()
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE


def test_detail_check_in_for_department_holder(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    dept = dept_factory()
    Assignment.objects.create(asset=asset, to_dept=dept)
    client.force_login(tech_user)
    resp = client.post(f"/assets/{asset.pk}/check-in/", {"condition_in": "GOOD"})
    assert resp.status_code == 302
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE
    body = client.get(f"/assets/{asset.pk}/").content.decode()
    # orphan hint not shown — it's properly returned now
    assert 'name="to_dept"' in body  # checkout picker (with dept option) present


def test_orphan_repair_to_department(client, tech_user, asset_factory, dept_factory):
    asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-D001")
    dept = dept_factory(name="Core Network")
    client.force_login(tech_user)
    resp = client.post("/assets/repair/", {"asset": asset.pk, "to_dept": dept.pk})
    assert resp.status_code == 302
    row = Assignment.objects.get(asset=asset, in_at__isnull=True)
    assert row.to_dept == dept
    assert "repaired" in row.remarks
    # queue drained for that asset (the flash message still carries the tag,
    # so assert on the queue context, not the body — lesson from session 30)
    resp = client.get("/assets/repair/")
    assert asset.pk not in [a.pk for a in resp.context["orphans"]]


def test_orphan_repair_with_both_targets_refused(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    asset = asset_factory(status=Asset.Status.ASSIGNED)
    person = person_factory()
    dept = dept_factory()
    client.force_login(tech_user)
    resp = client.post(
        "/assets/repair/",
        {"asset": asset.pk, "to_person": person.pk, "to_dept": dept.pk},
    )
    assert resp.status_code == 302
    assert not Assignment.objects.filter(asset=asset).exists()


# 4. list filter --------------------------------------------------------------


def test_department_filter_matches_department_held_asset(
    client, tech_user, asset_factory, dept_factory, person_factory
):
    finance = dept_factory(name="Finance")
    ops = dept_factory(name="Operations")

    dept_asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-SRV-0001")
    Assignment.objects.create(asset=dept_asset, to_dept=finance)
    person_asset = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-LAP-0001")
    holder = person_factory(name="Ops Holder")
    holder.department = ops
    holder.save(update_fields=["department"])
    Assignment.objects.create(asset=person_asset, to_person=holder)

    client.force_login(tech_user)
    resp = client.get(f"/assets/?department={finance.pk}")
    tags = [a.asset_tag for a in resp.context["object_list"]]
    assert "IT-SRV-0001" in tags
    assert "IT-LAP-0001" not in tags
    # and the dept holder renders in the row
    assert "Finance" in resp.content.decode()


# 5. reports ------------------------------------------------------------------


def test_dept_report_includes_dept_rows_and_summary(
    db, asset_factory, dept_factory, person_factory
):
    from apps.reports.queries import assets_by_department

    infra = dept_factory(name="Infrastructure")
    srv = asset_factory(status=Asset.Status.ASSIGNED, cost="1200.00", asset_tag="IT-SRV-1")
    Assignment.objects.create(asset=srv, to_dept=infra)
    held = asset_factory(status=Asset.Status.ASSIGNED, cost="800.00", asset_tag="IT-LAP-1")
    Assignment.objects.create(asset=held, to_person=person_factory(name="Someone"))
    asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-ORPH-9")

    headers, rows = assets_by_department()
    assert headers[:3] == ["Department", "Employee", "Asset tag"]
    dept_rows = [r for r in rows if r and r[0] == "Infrastructure"]
    assert dept_rows and dept_rows[0][1] == "(department)"
    # summary section: blank row, header, then (dept, count, value)
    idx = next(i for i, r in enumerate(rows) if r and r[0] == "SUMMARY")
    summary = {r[0]: (r[1], r[2]) for r in rows[idx + 1 :] if r}
    assert summary["Infrastructure"] == (1, 1200.0)
    assert summary["(no department)"] == (1, 800.0)
    # completeness bucket still present
    assert any(r and r[0] == "Not assigned" and r[2] == "IT-ORPH-9" for r in rows)


def test_orphan_report_flags_reverse_orphans(db, asset_factory, person_factory):
    from apps.reports.queries import orphan_assets

    # forward orphan: ASSIGNED, no open row
    asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-FWD-1")
    # reverse orphan: AVAILABLE but an open row exists
    rev = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-REV-1")
    Assignment.objects.create(asset=rev, to_person=person_factory(name="Still Holding"))

    headers, rows = orphan_assets()
    by_tag = {r[0]: r for r in rows}
    assert "IT-FWD-1" in by_tag and "no open assignment" in by_tag["IT-FWD-1"][2]
    assert "IT-REV-1" in by_tag
    assert by_tag["IT-REV-1"][2].startswith("REVERSE")
    assert by_tag["IT-REV-1"][1] == "AVAILABLE"
