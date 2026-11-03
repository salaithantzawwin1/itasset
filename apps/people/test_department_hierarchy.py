"""Nested departments (Finance → Chan Yin / Mining / TPT).

Departments gained a self-FK ``parent``. Finance sits at the Yangon site and
its branches hang below it, each keeping its own site FK. The Departments list
renders parents before children with an indent, the detail page lists the
sub-departments and links up, the form refuses loops, and a parent with
sub-departments cannot be deleted out from under them.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.forms import DepartmentForm
from apps.people.models import Department


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("dept-boss", "dept-boss@example.com", "x")
    client.force_login(user)
    return client


@pytest.fixture
def finance(db, site):
    return Department.objects.create(name="Finance", site=site)


def _payload(**over):
    data = {"name": "Mining", "site": "", "parent": "", "head": ""}
    data.update(over)
    return data


# ---------------------------------------------------------------------------
# model + form
# ---------------------------------------------------------------------------


def test_department_defaults_to_top_level(finance):
    assert finance.parent is None
    assert finance.ancestors == []
    assert finance.full_path == "Finance"


def test_full_path_walks_the_chain(finance, site):
    chan = Department.objects.create(name="Chan Yin", site=site, parent=finance)

    assert [d.name for d in chan.ancestors] == ["Finance"]
    assert chan.full_path == "Finance / Chan Yin"


def test_a_department_cannot_be_its_own_parent(finance, site):
    form = DepartmentForm(
        instance=finance,
        data={"name": "Finance", "site": site.pk, "parent": finance.pk},
    )

    assert not form.is_valid()
    assert "parent" in form.errors


def test_a_descendant_cannot_become_the_parent(finance, site):
    mining = Department.objects.create(name="Mining", site=site, parent=finance)

    form = DepartmentForm(
        instance=finance,
        data={"name": "Finance", "site": site.pk, "parent": mining.pk},
    )

    assert not form.is_valid()
    assert "parent" in form.errors


def test_the_picker_never_offers_the_department_or_its_branches(finance, site):
    mining = Department.objects.create(name="Mining", site=site, parent=finance)
    other = Department.objects.create(name="Operations", site=site)

    choices = set(DepartmentForm(instance=finance).fields["parent"].queryset)

    assert choices == {other}
    assert mining not in choices


def test_create_nests_under_the_chosen_parent(admin_client, finance, site):
    resp = admin_client.post(
        reverse("department-create"), _payload(site=site.pk, parent=finance.pk)
    )

    assert resp.status_code == 302
    assert Department.objects.get(name="Mining").parent == finance


def test_a_branch_keeps_its_own_site(admin_client, finance, site):
    """Finance is at Yangon; its Chan Yin branch sits at the Chan Yin site."""
    from apps.people.models import Site

    chan_site = Site.objects.create(name="Chan Yin", code="chan-yin", parent=site)
    admin_client.post(
        reverse("department-create"),
        _payload(name="Chan Yin", site=chan_site.pk, parent=finance.pk),
    )

    branch = Department.objects.get(name="Chan Yin")
    assert branch.parent == finance
    assert branch.site == chan_site  # not inherited from the parent department


# ---------------------------------------------------------------------------
# list + detail
# ---------------------------------------------------------------------------


def test_list_renders_parents_before_their_children(admin_client, finance, site):
    Department.objects.create(name="Chan Yin", site=site, parent=finance)
    Department.objects.create(name="Mining", site=site, parent=finance)
    Department.objects.create(name="Operations", site=site)

    rows = admin_client.get(reverse("department-list")).context["object_list"]

    assert [d.name for d in rows] == ["Finance", "Chan Yin", "Mining", "Operations"]
    assert [d.tree_depth for d in rows] == [0, 1, 1, 0]


def test_search_still_keeps_the_parent_context(admin_client, finance, site):
    """A matching branch shows on its own (its parent is filtered out)."""

    Department.objects.create(name="Mining", site=site, parent=finance)
    Department.objects.create(name="Operations", site=site)

    rows = admin_client.get(reverse("department-list"), {"q": "Mini"}).context["object_list"]

    assert [d.name for d in rows] == ["Mining"]
    assert rows[0].tree_depth == 0


def test_detail_lists_the_sub_departments(admin_client, finance, site):
    Department.objects.create(name="Chan Yin", site=site, parent=finance)

    resp = admin_client.get(reverse("department-detail", args=[finance.pk]))

    assert [d.name for d in resp.context["children"]] == ["Chan Yin"]
    body = resp.content.decode()
    assert "Sub-departments" in body


def test_child_detail_links_back_up_to_its_parent(admin_client, finance, site):
    mining = Department.objects.create(name="Mining", site=site, parent=finance)

    body = admin_client.get(reverse("department-detail", args=[mining.pk])).content.decode()

    assert reverse("department-detail", args=[finance.pk]) in body


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_a_parent_with_sub_departments_is_not_deleted(admin_client, finance, site):
    Department.objects.create(name="Chan Yin", site=site, parent=finance)

    resp = admin_client.post(reverse("department-delete", args=[finance.pk]))

    assert resp.status_code == 302
    assert resp["Location"] == reverse("department-detail", args=[finance.pk])
    assert Department.objects.filter(pk=finance.pk).exists()


def test_a_leaf_department_still_deletes(admin_client, finance, site):
    mining = Department.objects.create(name="Mining", site=site, parent=finance)

    resp = admin_client.post(reverse("department-delete", args=[mining.pk]))

    assert resp.status_code == 302
    assert not Department.objects.filter(pk=mining.pk).exists()
