"""M2 service-layer tests (DEVELOPMENT.md §3 lifecycle, §9 service layer).

Covers: check_out, check_in, handover, receive_asset, error paths,
illegal status transitions. Run with: pytest apps/assets/tests/test_services.py
"""

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.assets.models import Asset, Assignment
from apps.assets.services import (
    AssetNotAssigned,
    AssetNotAvailable,
    CheckInResult,
    CheckOutResult,
    InvalidStatusTransition,
    active_assignment,
    can_assign,
    check_in,
    check_out,
    close_assignment,
    create_assignment,
    handover,
    receive_asset,
)

User = get_user_model()


# NOTE: do NOT cache model instances across tests. pytest-django truncates
# the DB after every test, so a cached Site/Person instance would carry a
# stale id whose row no longer exists → deferred-FK violations at teardown.
def _site(code="yangon", name="Yangon HQ"):
    from apps.people.models import Site

    s, _ = Site.objects.get_or_create(code=code, defaults={"name": name})
    return s


def _category(code="IT-HW-LAP", name="Laptop"):
    from apps.assets.models import Category

    c, _ = Category.objects.get_or_create(code=code, defaults={"name": name})
    return c


def _person(employee_no="E001", name="Test Person", site=None, **extra):
    if site is None:
        site = _site()
    from apps.people.models import Person

    p, _ = Person.objects.get_or_create(
        employee_no=employee_no,
        defaults={"name": name, "site": site, **extra},
    )
    return p


def site_id(site):
    return getattr(site, "id", site)


@pytest.fixture
def user(db):
    return User.objects.create_user("tech", "tech@itasset.dev", "pass12345!")


@pytest.fixture
def person_factory(db):
    def _make(*, employee_no="E001", name="Test Person", site=None, **extra):
        return _person(employee_no=employee_no, name=name, site=site, **extra)

    return _make


@pytest.fixture
def category_factory(db):
    def _make(code="IT-HW-LAP", name="Laptop"):
        return _category(code=code, name=name)

    return _make


@pytest.fixture
def asset_factory(db, category_factory):
    def _make(*, status=Asset.Status.AVAILABLE, serial="SN001", **extra):
        from apps.assets.models import Asset

        site = _site()
        cat = _category()
        asset_tag = f"{cat.code}-{serial}"
        asset, _ = Asset.objects.get_or_create(
            asset_tag=asset_tag,
            defaults={
                "category": cat,
                "site": site,
                "status": status,
                "condition": Asset.Condition.GOOD,
                "serial_no": serial,
                **extra,
            },
        )
        return asset

    return _make


def _make_ready(asset_factory, person_factory):
    person = person_factory(employee_no="E001", name="Holder")
    asset = asset_factory(serial="SN001")
    return asset, person


class TestCanAssign:
    def test_true_for_available(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.AVAILABLE)
        assert can_assign(a) is True

    def test_false_for_assigned(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.ASSIGNED)
        assert can_assign(a) is False

    def test_false_for_in_repair(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.IN_REPAIR)
        assert can_assign(a) is False

    def test_false_for_in_stock(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.IN_STOCK)
        assert can_assign(a) is False


class TestActiveAssignment:
    def test_none_when_no_assignments(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.AVAILABLE)
        assert active_assignment(a) is None

    def test_returns_open_assignment(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        result = check_out(a, p, actor=user)
        assert active_assignment(a).id == result.assignment.id

    def test_returns_none_after_check_in(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user)
        check_in(a)
        assert active_assignment(a) is None


class TestCheckOut:
    def test_creates_assignment_and_sets_assigned(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        result = check_out(a, p, actor=user)
        assert isinstance(result, CheckOutResult)
        assert result.asset.status == Asset.Status.ASSIGNED
        assert result.assignment.asset_id == a.id
        assert result.assignment.to_person_id == p.id
        assert result.assignment.in_at is None
        assert result.assignment.condition_out == Asset.Condition.GOOD

    def test_requires_available_status(self, db, asset_factory, person_factory, user):
        a = asset_factory(status=Asset.Status.IN_STOCK)
        p = person_factory()
        with pytest.raises(AssetNotAvailable):
            check_out(a, p, actor=user)

    def test_requires_no_active_assignment(self, db, asset_factory, person_factory, user):
        # check_out then check_in returns asset to AVAILABLE; a second check_out is fine.
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user)
        check_in(a)
        q = person_factory(employee_no="E002", name="Other")
        result = check_out(a, q, actor=user)  # should succeed
        assert a.status == Asset.Status.ASSIGNED
        assert result.assignment.to_person_id == q.id
        assert result.assignment.in_at is None

    def test_accepts_due_at(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        due = timezone.now() + timezone.timedelta(days=7)
        result = check_out(a, p, actor=user, due_at=due)
        assert result.assignment.due_at == due

    def test_accepts_condition_out(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        result = check_out(a, p, actor=user, condition_out=Asset.Condition.FAIR)
        assert result.assignment.condition_out == Asset.Condition.FAIR


class TestCheckIn:
    def test_closes_assignment_and_returns_available(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user)
        result = check_in(a)
        assert isinstance(result, CheckInResult)
        assert result.assignment.in_at is not None
        assert result.asset.status == Asset.Status.AVAILABLE

    def test_requires_active_assignment(self, db, asset_factory):
        a = asset_factory(status=Asset.Status.AVAILABLE)
        with pytest.raises(AssetNotAssigned):
            check_in(a)

    def test_damage_returns_to_in_repair(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user)
        result = check_in(a, condition_in=Asset.Condition.DAMAGED)
        assert result.asset.status == Asset.Status.IN_REPAIR

    def test_preserves_condition_on_closed_row(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user, condition_out=Asset.Condition.GOOD)
        check_in(a, condition_in=Asset.Condition.FAIR)
        closed = Assignment.objects.filter(asset=a, in_at__isnull=False).first()
        assert closed.condition_in == Asset.Condition.FAIR


class TestWrappers:
    def test_create_assignment_is_check_out(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        assignment = create_assignment(a, p)
        assert assignment.in_at is None
        assert a.status == Asset.Status.ASSIGNED

    def test_close_assignment_is_check_in(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        check_out(a, p, actor=user)
        closed = close_assignment(a)
        assert closed.in_at is not None
        assert a.status == Asset.Status.AVAILABLE


class TestHandover:
    def test_closes_current_and_opens_new(self, db, asset_factory, person_factory, user):
        a, holder = _make_ready(asset_factory, person_factory)
        alice = person_factory(employee_no="E002", name="Alice")
        bob = person_factory(employee_no="E003", name="Bob")
        check_out(a, alice, actor=user)
        closed, opened = handover(a, alice, bob, actor=user)
        assert closed.in_at is not None
        # the NEW assignment is the active one: out_at stamped, in_at still NULL
        assert opened.out_at is not None
        assert opened.in_at is None
        assert opened.to_person_id == bob.id
        assert a.status == Asset.Status.ASSIGNED

    def test_requires_active_assignment_on_asset(self, db, asset_factory, person_factory, user):
        alice = person_factory(name="Alice")
        bob = person_factory(name="Bob")
        a = asset_factory(status=Asset.Status.AVAILABLE, serial="SN9999")
        with pytest.raises(AssetNotAssigned):
            handover(a, alice, bob, actor=user)

    def test_from_and_to_must_be_person_instances(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        with pytest.raises(TypeError):
            handover(a, p.id, p, actor=user)  # int is not a Person instance


class TestReceiveAsset:
    def test_moves_in_stock_to_available(self, db, category_factory, user):
        from apps.assets.models import Asset

        site = _site()
        cat = _category(code="IT-HW-DSK", name="Desktop")
        a = Asset.objects.create(
            asset_tag="IT-HW-DSK-0001",
            category=cat,
            site=site,
            status=Asset.Status.IN_STOCK,
            condition=Asset.Condition.GOOD,
        )
        result = receive_asset(a, actor=user)
        assert result.asset.status == Asset.Status.AVAILABLE
        assert result.assignment is None

    def test_optionally_assigns_on_receive(self, db, category_factory, person_factory, user):
        from apps.assets.models import Asset

        site = _site()
        cat = _category(code="IT-HW-LAP", name="Laptop")
        a = Asset.objects.create(
            asset_tag="IT-HW-LAP-0001",
            category=cat,
            site=site,
            status=Asset.Status.IN_STOCK,
            condition=Asset.Condition.GOOD,
        )
        p = person_factory(employee_no="E007", name="First holder")
        result = receive_asset(a, actor=user, to_person=p)
        assert result.asset.status == Asset.Status.ASSIGNED
        assert result.assignment.to_person_id == p.id

    def test_rejects_if_not_in_stock(self, db, asset_factory, person_factory, user):
        a, p = _make_ready(asset_factory, person_factory)
        with pytest.raises(InvalidStatusTransition):
            receive_asset(a, actor=user)

    def test_sets_condition_on_receive(self, db, category_factory, user):
        from apps.assets.models import Asset

        site = _site()
        cat = _category(code="IT-HW-PER", name="Peripheral")
        a = Asset.objects.create(
            asset_tag="IT-HW-PER-0001",
            category=cat,
            site=site,
            status=Asset.Status.IN_STOCK,
            condition=Asset.Condition.NEW,
        )
        result = receive_asset(a, actor=user, condition=Asset.Condition.GOOD)
        assert result.asset.condition == Asset.Condition.GOOD
