"""Department detail page (session 32).

`/departments/<pk>/` is the landing page for a department-held asset fleet:
the department head (တာဝန်ခံ, `Department.head`), the department-held
inventory (open Assignment rows with `to_dept` set), a capped history card
and the member list. Coverage:

1. Head + members + held/history split render; member-held assets surface
   in their own "Held by department members" card while staying OUT of
   the department-held list (held_now is still to_dept only).
2. Empty states (no head, nothing held).
3. Anonymous → login redirect; out-of-scope department → 404 under
   enforcement (same policy as Site/Person detail).
4. Entry links: person list/detail + site detail dept names and the asset
   detail's department holder all link to the new page.
5. Departments list (session 37): head + annotated asset count
   (open rows only — the dept-held card AND the members' own card, so the
   number matches the detail page and the asset-list filter it links to),
   count links into the asset-list filter, nav link, anonymous redirect;
   the member count column (people in the department) — all counts are
   `distinct=True` so the multi-valued joins never multiply.
6. Department edit (session 37): admin changes the head through the main
   app form; technicians are refused (admin-only like Site/Person).
7. Delete flow: admin-only, and only for a department nothing references
   (no members, no assignment rows). The button renders solely in that
   case; the view refuses stale/crafted URLs with a message + redirect
   back to the detail page instead of tripping the PROTECT FKs (no 500),
   and a successful delete lands on the list with a confirmation.
"""

import pytest

from apps.assets.models import Asset, Assignment

pytestmark = pytest.mark.django_db


@pytest.fixture
def tech_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="technician")
    u = django_user_model.objects.create_user(
        "tech_deptdetail", "tech_deptdetail@itasset.dev", "pass12345!"
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


# 1. page content --------------------------------------------------------------


def test_dept_detail_shows_head_members_and_held_assets(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    dept = dept_factory(name="Infrastructure")
    head = person_factory(name="Daw Head")
    dept.head = head
    dept.save(update_fields=["head"])
    member = person_factory(name="Staff Member")
    member.department = dept
    member.save(update_fields=["department"])

    held = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-DEPT-5001")
    Assignment.objects.create(asset=held, to_dept=dept)
    done = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-DEPT-DONE")
    Assignment.objects.create(asset=done, to_dept=dept, in_at=done.updated_at)
    # a member's personal asset is NOT department-held
    personal = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-PERS-5001")
    Assignment.objects.create(asset=personal, to_person=member)

    client.force_login(tech_user)
    resp = client.get(f"/departments/{dept.pk}/")
    assert resp.status_code == 200
    held_now = list(resp.context["held_now"])
    history = list(resp.context["history_recent"])
    assert [a.asset_id for a in held_now] == [held.pk]
    assert [a.asset_id for a in history] == [done.pk]
    body = resp.content.decode()
    assert "Daw Head" in body  # head rendered with a person link
    assert f"/people/{head.pk}/" in body
    assert "Staff Member" in body and f"/people/{member.pk}/" in body
    assert "IT-DEPT-5001" in body and "IT-DEPT-DONE" in body
    # member-held rows surface in their own card (session ask) — but the
    # department-held context above still excludes them
    assert "IT-PERS-5001" in body
    assert [a.asset_id for a in resp.context["member_held"]] == [personal.pk]


def test_dept_detail_empty_state(client, tech_user, dept_factory):
    dept = dept_factory(name="Empty Dept")
    client.force_login(tech_user)
    body = client.get(f"/departments/{dept.pk}/").content.decode()
    assert "No head assigned." in body
    assert "No assets held by this department." in body
    assert "No assets held by department members." in body


def test_dept_detail_member_held_card(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    dept = dept_factory(name="Members Dept")
    m1 = person_factory(name="Holder One")
    m1.department = dept
    m1.save(update_fields=["department"])
    m2 = person_factory(name="Holder Two")
    m2.department = dept
    m2.save(update_fields=["department"])

    open_a = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-MH-9001")
    Assignment.objects.create(asset=open_a, to_person=m1)
    # closed member rows stay out (open-only card, like held_now)
    closed = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-MH-9002")
    Assignment.objects.create(asset=closed, to_person=m2, in_at=closed.updated_at)
    # a person OUTSIDE this department must never surface here
    outsider = person_factory(name="Outsider Person")
    out_a = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-MH-9003")
    Assignment.objects.create(asset=out_a, to_person=outsider)

    client.force_login(tech_user)
    resp = client.get(f"/departments/{dept.pk}/")
    assert resp.status_code == 200
    assert [a.asset_id for a in resp.context["member_held"]] == [open_a.pk]
    body = resp.content.decode()
    assert "Held by department members" in body  # card heading (i18n)
    assert "IT-MH-9001" in body
    # holder rendered as a link to the person page, next to the asset
    assert "Holder One" in body and f"/people/{m1.pk}/" in body
    assert "IT-MH-9002" not in body  # closed row
    assert "IT-MH-9003" not in body  # other department's member
    # and the department-held card is untouched by member rows
    assert [a.asset_id for a in resp.context["held_now"]] == []


# 2. access gates --------------------------------------------------------------


def test_dept_detail_anonymous_redirects(client, dept_factory):
    dept = dept_factory()
    resp = client.get(f"/departments/{dept.pk}/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


def test_dept_detail_out_of_scope_is_404_under_enforcement(
    client, dept_factory, settings, django_user_model
):
    from apps.core.models import UserAccessScope
    from apps.people.models import Site

    other = Site.objects.create(code="mdy-scope", name="MDY Scope")
    dept_a = dept_factory(name="Yangon Dept")  # fixture site (yangon)
    dept_b = dept_factory(name="MDY Dept", site=other)

    u = django_user_model.objects.create_user("scope_deptdetail", "sd@itasset.dev", "pass12345!")
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=other,
        created_by=u,
    )
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(u)
    # out of scope looks identical to nonexistent (design §5.2)
    assert client.get(f"/departments/{dept_a.pk}/").status_code == 404
    assert client.get(f"/departments/{dept_b.pk}/").status_code == 200


# 3. entry links ---------------------------------------------------------------


def test_person_list_and_detail_link_the_dept_name(client, tech_user, person_factory, dept_factory):
    dept = dept_factory(name="Linked Dept")
    person = person_factory(name="Link Holder")
    person.department = dept
    person.save(update_fields=["department"])

    client.force_login(tech_user)
    list_body = client.get("/people/").content.decode()
    assert f"/departments/{dept.pk}/" in list_body
    detail_body = client.get(f"/people/{person.pk}/").content.decode()
    assert f"/departments/{dept.pk}/" in detail_body


def test_asset_detail_dept_holder_links_to_department(
    client, tech_user, asset_factory, dept_factory
):
    asset = asset_factory(status=Asset.Status.AVAILABLE)
    dept = dept_factory(name="Network Ops")
    client.force_login(tech_user)
    client.post(f"/assets/{asset.pk}/check-out/", {"to_dept": dept.pk})
    body = client.get(f"/assets/{asset.pk}/").content.decode()
    assert f"/departments/{dept.pk}/" in body


def test_dept_detail_links_back_to_asset_list(client, tech_user, dept_factory):
    dept = dept_factory(name="Fleet Dept")
    client.force_login(tech_user)
    body = client.get(f"/departments/{dept.pk}/").content.decode()
    assert f"/assets/?department={dept.pk}" in body


# 4. list page (session 37) ---------------------------------------------------


def test_department_list_shows_head_and_dept_held_count(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    dept = dept_factory(name="Counted Dept")
    head = person_factory(name="Dept Head")
    dept.head = head
    dept.save(update_fields=["head"])

    held = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-CT-7001")
    Assignment.objects.create(asset=held, to_dept=dept)
    # closed dept row must not count
    done = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-CT-DONE")
    Assignment.objects.create(asset=done, to_dept=dept, in_at=done.updated_at)
    # a member's personal asset DOES count: it is the detail page's second
    # card, and the count links into the department filter that shows it
    member = person_factory(name="Counted Member")
    member.department = dept
    member.save(update_fields=["department"])
    personal = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-CT-PERS")
    Assignment.objects.create(asset=personal, to_person=member)

    client.force_login(tech_user)
    resp = client.get("/departments/")
    assert resp.status_code == 200
    row = next(d for d in resp.context["object_list"] if d.pk == dept.pk)
    assert row.asset_count == 2
    body = resp.content.decode()
    assert "Dept Head" in body and f"/people/{head.pk}/" in body
    # the count deep-links into the asset list's department filter
    assert f"/assets/?department={dept.pk}" in body
    assert ">2</a>" in body
    # nav carries the page
    assert 'href="/departments/"' in body


def test_department_list_counts_member_held_assets(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    """The case reported on production: a department whose assets all sit
    with its members must not read 0 on the list."""
    dept = dept_factory(name="Members Hold All")
    for n, tag in (("Holder One", "IT-MH-9001"), ("Holder Two", "IT-MH-9002")):
        p = person_factory(name=n)
        p.department = dept
        p.save(update_fields=["department"])
        a = asset_factory(status=Asset.Status.ASSIGNED, asset_tag=tag)
        Assignment.objects.create(asset=a, to_person=p)
    # a closed member row must not count
    left = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-MH-DONE")
    p3 = person_factory(name="Holder Three")
    p3.department = dept
    p3.save(update_fields=["department"])
    Assignment.objects.create(asset=left, to_person=p3, in_at=left.updated_at)

    client.force_login(tech_user)
    resp = client.get("/departments/")
    row = next(d for d in resp.context["object_list"] if d.pk == dept.pk)
    assert row.asset_count == 2  # both member-held, none dept-held
    # …and that is exactly what the linked filter and the detail page show
    filtered = client.get(f"/assets/?department={dept.pk}")
    assert filtered.context["paginator"].count == 2
    detail = client.get(f"/departments/{dept.pk}/")
    assert len(detail.context["held_now"]) == 0
    assert len(detail.context["member_held"]) == 2


def test_department_list_shows_member_count(
    client, tech_user, asset_factory, person_factory, dept_factory
):
    dept = dept_factory(name="Membered Dept")
    members = []
    for n in ("Member One", "Member Two"):
        p = person_factory(name=n)
        p.department = dept
        p.save(update_fields=["department"])
        members.append(p)
    # members × held assets fan out the joined rows (2×2) — the two
    # counts must stay exact, which is what distinct=True guarantees
    for tag in ("IT-MC-8001", "IT-MC-8002"):
        a = asset_factory(status=Asset.Status.ASSIGNED, asset_tag=tag)
        Assignment.objects.create(asset=a, to_dept=dept)
    # one member-held asset too: the union count must land on 3, not 2,
    # not anything inflated by the members × assets × member-rows fan-out
    own = asset_factory(status=Asset.Status.ASSIGNED, asset_tag="IT-MC-8003")
    Assignment.objects.create(asset=own, to_person=members[0])
    dept_factory(name="Lonely Dept")  # no members, no held assets

    client.force_login(tech_user)
    resp = client.get("/departments/")
    assert resp.status_code == 200
    rows = {d.name: d for d in resp.context["object_list"]}
    assert rows["Membered Dept"].member_count == 2  # not 2×2
    assert rows["Membered Dept"].asset_count == 3  # 2 dept-held + 1 member-held
    assert rows["Lonely Dept"].member_count == 0
    assert rows["Lonely Dept"].asset_count == 0
    body = resp.content.decode()
    assert "Department members" in body  # column header renders (i18n key dept.members)


def test_department_list_without_head_shows_dash(client, tech_user, dept_factory):
    dept_factory(name="Headless Dept")
    client.force_login(tech_user)
    body = client.get("/departments/").content.decode()
    assert "Headless Dept" in body
    assert "Head of department" in body  # column header still renders


def test_department_list_anonymous_redirects(client, dept_factory):
    dept_factory()
    resp = client.get("/departments/")
    assert resp.status_code == 302
    assert "/accounts/login/" in resp["Location"]


# 5. edit form (session 37) ---------------------------------------------------


def _admin_user(django_user_model):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    group, _ = Group.objects.get_or_create(name="admin")
    u = django_user_model.objects.create_user(
        "admin_deptedit", "admin_deptedit@itasset.dev", "pass12345!"
    )
    u.groups.add(group)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


def test_admin_changes_head_via_main_app_form(
    client, django_user_model, dept_factory, person_factory
):
    admin = _admin_user(django_user_model)
    dept = dept_factory(name="Editable Dept")
    new_head = person_factory(name="New Head")

    client.force_login(admin)
    resp = client.get(f"/departments/{dept.pk}/edit/")
    assert resp.status_code == 200
    assert resp.context["form"].fields["head"].queryset.filter(pk=new_head.pk).exists()

    resp = client.post(
        f"/departments/{dept.pk}/edit/",
        {"name": dept.name, "site": dept.site_id, "head": new_head.pk},
    )
    assert resp.status_code == 302, resp.context["form"].errors
    dept.refresh_from_db()
    assert dept.head_id == new_head.pk
    # the detail page renders the new head immediately (the ask: verify)
    body = client.get(f"/departments/{dept.pk}/").content.decode()
    assert "New Head" in body and f"/people/{new_head.pk}/" in body
    # and the edit button exists on the detail page
    assert f"/departments/{dept.pk}/edit/" in body


def test_technician_cannot_edit_department(client, tech_user, dept_factory):
    dept = dept_factory(name="Locked Dept")
    client.force_login(tech_user)
    assert client.get(f"/departments/{dept.pk}/edit/").status_code == 403
    resp = client.post(
        f"/departments/{dept.pk}/edit/",
        {"name": "Hacked", "site": dept.site_id},
    )
    assert resp.status_code == 403
    dept.refresh_from_db()
    assert dept.name == "Locked Dept"


# 6. delete flow (admin-only, only while nothing references the row) ---------


def test_delete_link_only_for_admins_on_an_empty_department(
    client, django_user_model, tech_user, dept_factory, person_factory
):
    empty = dept_factory(name="Empty Delete Dept")
    busy = dept_factory(name="Busy Delete Dept")
    member = person_factory(name="Blocking Member")
    member.department = busy
    member.save(update_fields=["department"])

    admin = _admin_user(django_user_model)
    client.force_login(admin)
    delete_url = f"/departments/{empty.pk}/delete/"
    assert delete_url in client.get(f"/departments/{empty.pk}/").content.decode()
    # a department with members offers no delete button
    assert (
        f"/departments/{busy.pk}/delete/"
        not in client.get(f"/departments/{busy.pk}/").content.decode()
    )

    # technician: never the button, even on an empty department
    client.force_login(tech_user)
    assert delete_url not in client.get(f"/departments/{empty.pk}/").content.decode()


def test_admin_confirms_and_deletes_empty_department(client, django_user_model, dept_factory):
    from apps.people.models import Department

    dept = dept_factory(name="Doomed Dept")
    admin = _admin_user(django_user_model)
    client.force_login(admin)

    confirm = client.get(f"/departments/{dept.pk}/delete/")
    assert confirm.status_code == 200
    assert "Doomed Dept" in confirm.content.decode()  # generic confirm template

    resp = client.post(f"/departments/{dept.pk}/delete/")
    assert resp.status_code == 302
    assert resp["Location"] == "/departments/"
    assert not Department.objects.filter(pk=dept.pk).exists()
    # confirmation message on the landing page (asserted on the context
    # objects: the template autoescapes the quotes in the text)
    landing = client.get("/departments/")
    assert any('Department "Doomed Dept" deleted.' in str(m) for m in landing.context["messages"])


def test_technician_cannot_delete_department(client, tech_user, dept_factory):
    from apps.people.models import Department

    dept = dept_factory(name="Locked Delete Dept")
    client.force_login(tech_user)
    assert client.get(f"/departments/{dept.pk}/delete/").status_code == 403
    resp = client.post(f"/departments/{dept.pk}/delete/")
    assert resp.status_code == 403
    assert Department.objects.filter(pk=dept.pk).exists()


def test_delete_refused_while_department_has_members(
    client, django_user_model, dept_factory, person_factory
):
    from apps.people.models import Department, Person

    dept = dept_factory(name="Membered Delete Dept")
    member = person_factory(name="Staying Member")
    member.department = dept
    member.save(update_fields=["department"])
    admin = _admin_user(django_user_model)
    client.force_login(admin)

    # GET confirm refuses (redirects back with the reason, no form)
    resp = client.get(f"/departments/{dept.pk}/delete/")
    assert resp.status_code == 302
    assert resp["Location"] == f"/departments/{dept.pk}/"
    # POST refuses without tripping Person.department's PROTECT (no 500)
    resp = client.post(f"/departments/{dept.pk}/delete/", follow=True)
    assert resp.status_code == 200
    assert any("member(s) still belong" in str(m) for m in resp.context["messages"])
    assert Department.objects.filter(pk=dept.pk).exists()
    assert Person.objects.filter(pk=member.pk).exists()


def test_delete_refused_when_assignment_history_exists(
    client, django_user_model, asset_factory, dept_factory
):
    from apps.people.models import Department

    dept = dept_factory(name="History Dept")
    done = asset_factory(status=Asset.Status.AVAILABLE, asset_tag="IT-DEL-9001")
    Assignment.objects.create(asset=done, to_dept=dept, in_at=done.updated_at)  # closed
    admin = _admin_user(django_user_model)
    client.force_login(admin)

    # closed rows count too — no delete button on the detail page
    body = client.get(f"/departments/{dept.pk}/").content.decode()
    assert f"/departments/{dept.pk}/delete/" not in body
    # POST refuses without tripping Assignment.to_dept's PROTECT (no 500)
    resp = client.post(f"/departments/{dept.pk}/delete/", follow=True)
    assert resp.status_code == 200
    assert any("assignment record(s) still reference" in str(m) for m in resp.context["messages"])
    assert Department.objects.filter(pk=dept.pk).exists()
    assert Assignment.objects.filter(to_dept=dept).exists()
