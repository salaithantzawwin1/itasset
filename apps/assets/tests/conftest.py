"""Shared fixtures for asset test suite (usable by test_services + test_crud_views)."""

import pytest


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
