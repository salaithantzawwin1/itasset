"""Department detail page (session 32).

`/departments/<pk>/` is the landing page for a department-held asset fleet:
the department head (တာဝန်ခံ, `Department.head`), the department-held
inventory (open Assignment rows with `to_dept` set), a capped history card
and the member list. Coverage:

1. Head + members + held/history split render; member-held assets stay on
   the person pages (they are NOT department-held).
2. Empty states (no head, nothing held).
3. Anonymous → login redirect; out-of-scope department → 404 under
   enforcement (same policy as Site/Person detail).
4. Entry links: person list/detail + site detail dept names and the asset
   detail's department holder all link to the new page.
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
    assert "IT-PERS-5001" not in body  # member-held, not dept-held


def test_dept_detail_empty_state(client, tech_user, dept_factory):
    dept = dept_factory(name="Empty Dept")
    client.force_login(tech_user)
    body = client.get(f"/departments/{dept.pk}/").content.decode()
    assert "No head assigned." in body
    assert "No assets held by this department." in body


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
