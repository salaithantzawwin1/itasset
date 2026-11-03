"""Nested sites (Yangon → HQ → Chan Yin / Fortune Office).

Sites gained a self-FK ``parent``. The tree is an org-chart detail: the Sites
list renders parents before children with an indent, a site detail page lists
its branches, the form refuses loops, and a parent with sub-sites cannot be
deleted out from under them.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from apps.people.forms import SiteForm
from apps.people.models import Site
from apps.people.views import _site_tree


@pytest.fixture
def admin_client(client, db):
    user = get_user_model().objects.create_superuser("org-boss", "org-boss@example.com", "x")
    client.force_login(user)
    return client


@pytest.fixture
def yangon(db):
    return Site.objects.create(name="Yangon", code="yangon")


@pytest.fixture
def hq(yangon):
    return Site.objects.create(name="HQ", code="hq", parent=yangon)


def _payload(**over):
    data = {"name": "Chan Yin", "code": "chan-yin", "parent": "", "address": "", "is_active": "on"}
    data.update(over)
    return data


# ---------------------------------------------------------------------------
# model + form
# ---------------------------------------------------------------------------


def test_parent_defaults_to_top_level(db, site):
    assert site.parent is None
    assert site.ancestors == []
    assert site.full_path == site.name


def test_full_path_walks_the_chain(yangon, hq):
    chan = Site.objects.create(name="Chan Yin", code="chan-yin", parent=hq)

    assert [s.name for s in chan.ancestors] == ["Yangon", "HQ"]
    assert chan.full_path == "Yangon / HQ / Chan Yin"


def test_a_site_cannot_be_its_own_parent(yangon):
    form = SiteForm(
        instance=yangon,
        data={"name": "Yangon", "code": "yangon", "parent": yangon.pk, "is_active": "on"},
    )

    assert not form.is_valid()
    assert "parent" in form.errors


def test_a_descendant_cannot_become_the_parent(yangon, hq):
    chan = Site.objects.create(name="Chan Yin", code="chan-yin", parent=hq)

    form = SiteForm(
        instance=yangon,
        data={"name": "Yangon", "code": "yangon", "parent": chan.pk, "is_active": "on"},
    )

    assert not form.is_valid()
    assert "parent" in form.errors


def test_the_picker_never_offers_the_site_or_its_branches(yangon, hq):
    chan = Site.objects.create(name="Chan Yin", code="chan-yin", parent=hq)
    other = Site.objects.create(name="Mandalay", code="mandalay")

    choices = set(SiteForm(instance=yangon).fields["parent"].queryset)

    assert choices == {other}
    assert chan not in choices


def test_create_nests_under_the_chosen_parent(admin_client, db, yangon):
    resp = admin_client.post(reverse("site-create"), _payload(parent=yangon.pk))

    assert resp.status_code == 302
    assert Site.objects.get(code="chan-yin").parent == yangon


# ---------------------------------------------------------------------------
# list + detail
# ---------------------------------------------------------------------------


def test_list_renders_parents_before_their_children(admin_client, db, yangon, hq):
    Site.objects.create(name="Chan Yin", code="chan-yin", parent=hq)
    Site.objects.create(name="Fortune Office", code="fortune", parent=hq)

    rows = admin_client.get(reverse("site-list")).context["object_list"]

    assert [s.name for s in rows] == ["Yangon", "HQ", "Chan Yin", "Fortune Office"]
    assert [s.tree_depth for s in rows] == [0, 1, 2, 2]


def test_a_child_shows_at_the_top_when_its_parent_is_out_of_scope(hq):
    """Scope may hide the parent; the child must still show, at the top."""

    rows = _site_tree([hq])

    assert [s.name for s in rows] == ["HQ"]
    assert rows[0].tree_depth == 0


def test_detail_lists_the_sub_sites(admin_client, db, yangon, hq):
    Site.objects.create(name="Chan Yin", code="chan-yin", parent=hq)

    resp = admin_client.get(reverse("site-detail", args=[yangon.pk]))

    assert [s.name for s in resp.context["children"]] == ["HQ"]
    body = resp.content.decode()
    assert "Sub-sites" in body
    assert reverse("site-detail", args=[hq.pk]) in body


def test_child_detail_links_back_up_to_its_parent(admin_client, db, yangon, hq):
    body = admin_client.get(reverse("site-detail", args=[hq.pk])).content.decode()

    assert reverse("site-detail", args=[yangon.pk]) in body


# ---------------------------------------------------------------------------
# delete
# ---------------------------------------------------------------------------


def test_a_parent_with_sub_sites_is_not_deleted(admin_client, db, yangon, hq):
    resp = admin_client.post(reverse("site-delete", args=[yangon.pk]))

    assert resp.status_code == 302
    assert resp["Location"] == reverse("site-detail", args=[yangon.pk])
    assert Site.objects.filter(pk=yangon.pk).exists()


def test_a_leaf_site_still_deletes(admin_client, db, yangon, hq):
    resp = admin_client.post(reverse("site-delete", args=[hq.pk]))

    assert resp.status_code == 302
    assert not Site.objects.filter(pk=hq.pk).exists()
