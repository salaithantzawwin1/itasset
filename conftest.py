"""Shared fixtures for the whole suite (site/category/person/asset factories).

Kept at the project root so apps/labels and apps/api tests see the same
fixtures as apps/assets tests (pytest only exposes conftest.py to the
directory tree below it).
"""

import pytest


@pytest.fixture(autouse=True)
def _private_attachments_dir(settings, tmp_path):
    """Uploaded files go to a per-test tmp dir, never the real private store."""
    settings.PRIVATE_MEDIA_ROOT = str(tmp_path / "private_attachments")


@pytest.fixture
def site(db):
    from apps.people.models import Site

    s, _ = Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})
    return s


@pytest.fixture
def category(db):
    from apps.assets.models import Category

    c, _ = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})
    return c


@pytest.fixture
def person_factory(db, site):
    from apps.people.models import Person

    counter = {"n": 0}

    def _make(employee_no=None, name="Test Person", **extra):
        counter["n"] += 1
        n = employee_no or f"E{9000 + counter['n']}"
        return Person.objects.create(
            employee_no=n, name=name, site=extra.pop("site", site), **extra
        )

    return _make


@pytest.fixture
def asset_factory(db, category, site):
    from apps.assets.models import Asset

    counter = {"n": 0}

    def _make(status=None, serial=None, **extra):
        counter["n"] += 1
        tag = extra.pop("asset_tag", f"IT-HW-LAP-{9000 + counter['n']:04d}")
        return Asset.objects.create(
            asset_tag=tag,
            category=extra.pop("category", category),
            site=extra.pop("site", site),
            status=status or Asset.Status.AVAILABLE,
            condition=Asset.Condition.GOOD,
            serial_no=serial or f"SN-{9000 + counter['n']}",
            **extra,
        )

    return _make
