"""Per-category badge colours on the assets list (session 45).

The CATEGORY column renders a coloured pill per category, so the column can
be scanned by colour. Covers the auto-assigned ``Category.color`` (distinct
for a whole palette's worth of rows), the admin override + validation, the
badge fallback, the rendered pill on /assets/, and the 0015 backfill that
paints the categories production already has.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from apps.assets.models import Category, default_category_color

HEX = r"#[0-9a-f]{6}"


def _is_hex(value: str) -> bool:
    return bool(re.fullmatch(HEX, value))


# --------------------------------------------------------------- auto-assign


def test_new_category_gets_a_badge_colour(db):
    cat = Category.objects.create(code="IT-HW-AUTO", name="Auto")

    assert _is_hex(cat.color)


def test_successive_categories_get_distinct_colours(db):
    Category.objects.all().delete()  # migrations seed a catalogue — start empty
    # a full palette's worth (24 hue candidates) must never repeat
    colours = [
        Category.objects.create(code=f"IT-HW-T{i}", name=f"Tool {i}").color for i in range(24)
    ]

    assert len(set(colours)) == 24


def test_explicit_colour_is_kept_as_is(db):
    cat = Category.objects.create(code="IT-HW-BRAND", name="Brand", color="#123456")

    assert cat.color == "#123456"
    cat.save()  # re-saving never re-picks
    assert cat.color == "#123456"


def test_new_category_differs_from_every_seeded_one(db):
    # the real production shape: 0015 already painted the seeded catalogue,
    # and a later category must still land on a free hue
    before = set(Category.objects.values_list("color", flat=True))
    assert len(before) >= 21  # the backfill ran during migrations

    cat = Category.objects.create(code="IT-HW-NEW", name="Newcomer")

    assert cat.color not in before


def test_default_colour_walk_avoids_every_taken_hue(db):
    anchor = default_category_color([])
    second = default_category_color([anchor])

    assert _is_hex(anchor)
    assert second != anchor

    # grow the taken list to saturation: every step finds a fresh colour …
    taken = [anchor]
    while len(taken) < 24:
        nxt = default_category_color(taken)
        assert nxt not in taken
        taken.append(nxt)
    # … and once all 24 candidates are used it falls back to the anchor
    assert default_category_color(taken) == anchor


# ------------------------------------------------------------------- badges


def test_badge_colour_returns_the_stored_value(db):
    cat = Category.objects.create(code="IT-HW-B1", name="B", color="#abcdef")

    assert cat.badge_color == "#abcdef"


def test_badge_colour_falls_back_to_neutral_on_garbage(db):
    blank = Category.objects.create(code="IT-HW-B2", name="B2")
    blank.color = ""
    assert blank.badge_color == "#64748b"

    broken = Category.objects.create(code="IT-HW-B3", name="B3", color="red")
    assert broken.badge_color == "#64748b"


def test_colour_format_is_validated(db):
    with pytest.raises(ValidationError) as exc:
        Category(code="IT-HW-B4", name="B4", color="red").full_clean()
    assert "color" in exc.value.error_dict

    Category(code="IT-HW-B4", name="B4", color="#2563eb").full_clean()  # ok


# ------------------------------------------------------------------ rendering


def test_assets_list_renders_the_coloured_category_badge(client, db, asset_factory):
    user = get_user_model().objects.create_superuser("catclr", "catclr@example.com", "x")
    client.force_login(user)
    asset = asset_factory()

    html = client.get(reverse("asset-list")).content.decode()

    assert f'class="pill cat-pill" style="--c: {asset.category.badge_color}"' in html
    assert asset.category.code in html


def test_admin_category_form_offers_a_colour_picker(db):
    user = get_user_model().objects.create_superuser("catclr2", "catclr2@example.com", "x")
    client = Client()
    client.force_login(user)
    cat = Category.objects.create(code="IT-HW-P1", name="Pick")

    resp = client.get(reverse("admin:assets_category_change", args=[cat.pk]))

    assert resp.status_code == 200
    assert 'type="color"' in resp.content.decode()


# ------------------------------------------------------------------ 0015 backfill


def test_0015_paints_the_categories_that_already_exist(db):
    import importlib
    from types import SimpleNamespace

    from django.apps import apps as migration_apps
    from django.db import connection

    Category.objects.create(code="IT-HW-PRE1", name="Old 1")
    Category.objects.create(code="IT-HW-PRE2", name="Old 2")
    Category.objects.create(code="IT-HW-PRE3", name="Old 3")
    # the pre-0015 state: no colour column yet, one operator-set colour kept
    Category.objects.update(color="")
    Category.objects.filter(code="IT-HW-PRE3").update(color="#123456")

    mig = importlib.import_module("apps.assets.migrations.0015_category_color")
    mig.paint_existing_categories(migration_apps, SimpleNamespace(connection=connection))

    painted = dict(Category.objects.values_list("code", "color"))
    assert painted["IT-HW-PRE3"] == "#123456"  # an operator's colour survives
    fresh = [painted["IT-HW-PRE1"], painted["IT-HW-PRE2"]]
    assert all(_is_hex(c) for c in fresh)
    assert fresh[0] != fresh[1]
    assert "#123456" not in fresh
