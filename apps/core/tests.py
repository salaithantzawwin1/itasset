"""Unit tests for the §11 role helpers + RBAC Stage A scopes (design §4–5)."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import AnonymousUser, Group
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core.models import UserAccessScope
from apps.core.roles import is_admin, is_technician_or_admin, user_has_role
from apps.core.scopes import (
    OutOfScope,
    effective_scopes,
    enforcement_enabled,
    require_scope,
    scope_queryset,
    user_in_department,
    user_in_site,
)
from apps.people.models import Department, Person, Site

pytestmark = pytest.mark.django_db


def _user_with_groups(django_user_model, *group_names):
    u = django_user_model.objects.create_user("rtest", "r@itasset.dev", "pass12345!")
    for name in group_names:
        g, _ = Group.objects.get_or_create(name=name)
        u.groups.add(g)
    return u


def test_anonymous_has_no_roles():
    assert user_has_role(AnonymousUser(), "admin") is False
    assert is_admin(AnonymousUser()) is False


def test_technician_license(django_user_model):
    u = _user_with_groups(django_user_model, "technician")
    assert is_technician_or_admin(u) is True
    assert is_admin(u) is False


def test_admin_license(django_user_model):
    u = _user_with_groups(django_user_model, "admin")
    assert is_admin(u) is True


def test_viewer_cannot_edit(django_user_model):
    u = _user_with_groups(django_user_model, "viewer")
    assert is_technician_or_admin(u) is False


def test_superuser_passes_all(django_user_model):
    u = django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    assert is_admin(u) is True
    assert is_technician_or_admin(u) is True


# ---------------------------------------------------------------------------
# RBAC Stage A — UserAccessScope + scope helpers (ITAM_Scope_RBAC_Design_v1.0)
# ---------------------------------------------------------------------------


def _site(name, code):
    return Site.objects.create(name=name, code=code)


def _grant(
    user,
    scope_type,
    *,
    site=None,
    department=None,
    valid_from=None,
    valid_to=None,
    created_by=None,
    reason="test grant",
):
    return UserAccessScope.objects.create(
        user=user,
        scope_type=scope_type,
        site=site,
        department=department,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=reason,
        created_by=created_by or user,
    )


def test_anonymous_scope_is_denied():
    scopes = effective_scopes(AnonymousUser())
    assert scopes.is_empty
    assert scopes.global_access is False


def test_superuser_is_global(django_user_model):
    u = django_user_model.objects.create_superuser("root2", "root2@itasset.dev", "pass12345!")
    assert effective_scopes(u).global_access is True


def test_user_without_scopes_denied_everywhere(django_user_model):
    u = django_user_model.objects.create_user("noscope", "n@itasset.dev", "pass12345!")
    site = _site("NoScope Site", "ns-1")
    person = Person.objects.create(employee_no="E-NS", name="No Scope", site=site)

    scopes = effective_scopes(u)
    assert scopes.is_empty  # deny by default (design §4.3)
    assert list(scope_queryset(u, Person.objects.all())) == []
    with pytest.raises(OutOfScope):
        require_scope(u, person)


def test_site_scope_covers_only_own_site(django_user_model):
    u = django_user_model.objects.create_user("tech1", "t1@itasset.dev", "pass12345!")
    site_a = _site("Site A", "site-a")
    site_b = _site("Site B", "site-b")
    _grant(u, UserAccessScope.ScopeType.SITE, site=site_a)

    person_a = Person.objects.create(employee_no="E-1", name="Alice", site=site_a)
    person_b = Person.objects.create(employee_no="E-2", name="Bob", site=site_b)

    assert user_in_site(u, site_a) is True
    assert user_in_site(u, site_b) is False
    assert list(scope_queryset(u, Person.objects.all())) == [person_a]
    require_scope(u, person_a)  # no raise
    with pytest.raises(OutOfScope):
        require_scope(u, person_b)


def test_global_row_overrides_site_rows(django_user_model):
    u = django_user_model.objects.create_user("lead", "lead@itasset.dev", "pass12345!")
    site_a = _site("Site A", "site-a")
    site_b = _site("Site B", "site-b")
    _grant(u, UserAccessScope.ScopeType.SITE, site=site_a)
    _grant(u, UserAccessScope.ScopeType.GLOBAL, reason="IT lead")

    assert effective_scopes(u).global_access is True
    assert user_in_site(u, site_b) is True
    person_b = Person.objects.create(employee_no="E-9", name="Bob", site=site_b)
    assert list(scope_queryset(u, Person.objects.all())) == [person_b]


def test_union_of_site_and_department_scopes(django_user_model):
    u = django_user_model.objects.create_user("mixed", "m@itasset.dev", "pass12345!")
    site_a = _site("Site A", "site-a")
    site_b = _site("Site B", "site-b")
    dept_b = Department.objects.create(name="Finance", site=site_b)
    _grant(u, UserAccessScope.ScopeType.SITE, site=site_a)
    _grant(u, UserAccessScope.ScopeType.DEPARTMENT, department=dept_b)

    scopes = effective_scopes(u)
    assert scopes.sites == frozenset({site_a.id})
    assert scopes.departments == frozenset({dept_b.id})
    assert user_in_department(u, dept_b) is True
    assert user_in_site(u, site_a) is True and user_in_site(u, site_b) is False


def test_validity_window_gates_scopes(django_user_model):
    today = date.today()
    expired = django_user_model.objects.create_user("expired", "x@itasset.dev", "pass12345!")
    future = django_user_model.objects.create_user("future", "f@itasset.dev", "pass12345!")
    active = django_user_model.objects.create_user("active", "a@itasset.dev", "pass12345!")
    site = _site("Site W", "site-w")

    _grant(expired, UserAccessScope.ScopeType.SITE, site=site, valid_to=today - timedelta(days=1))
    _grant(future, UserAccessScope.ScopeType.SITE, site=site, valid_from=today + timedelta(days=1))
    _grant(
        active,
        UserAccessScope.ScopeType.SITE,
        site=site,
        valid_from=today - timedelta(days=1),
        valid_to=today + timedelta(days=30),
    )

    assert effective_scopes(expired).is_empty
    assert effective_scopes(future).is_empty
    assert effective_scopes(active).sites == frozenset({site.id})


def test_scope_queryset_without_usable_conditions_is_empty(django_user_model):
    """A department-only scope on a site-scoped queryset fails closed."""
    u = django_user_model.objects.create_user("deptonly", "d@itasset.dev", "pass12345!")
    site = _site("Site D", "site-d")
    dept = Department.objects.create(name="HR", site=site)
    _grant(u, UserAccessScope.ScopeType.DEPARTMENT, department=dept)

    people = Person.objects.all()  # has `site`, no dept_field passed
    assert list(scope_queryset(u, people)) == []


def test_typed_columns_constraint_and_reason(db, django_user_model):
    u = django_user_model.objects.create_user("admin1", "adm@itasset.dev", "pass12345!")
    site = _site("Site C", "site-c")

    # SITE without its site column → rejected by full_clean (app level)
    with pytest.raises(ValidationError):
        UserAccessScope(
            user=u, scope_type=UserAccessScope.ScopeType.SITE, reason="r", created_by=u
        ).full_clean()

    # GLOBAL carrying a site → rejected
    with pytest.raises(ValidationError):
        UserAccessScope(
            user=u, scope_type=UserAccessScope.ScopeType.GLOBAL, site=site, reason="r", created_by=u
        ).full_clean()

    # reason is required (admin cannot save a scope without it)
    with pytest.raises(ValidationError):
        UserAccessScope(
            user=u, scope_type=UserAccessScope.ScopeType.GLOBAL, reason="", created_by=u
        ).full_clean()

    # inverted validity window rejected
    tomorrow = date.today() + timedelta(days=1)
    yesterday = date.today() - timedelta(days=1)
    with pytest.raises(ValidationError):
        UserAccessScope(
            user=u,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="r",
            created_by=u,
            valid_from=tomorrow,
            valid_to=yesterday,
        ).full_clean()

    # valid row passes full_clean
    UserAccessScope(
        user=u, scope_type=UserAccessScope.ScopeType.SITE, site=site, reason="ok", created_by=u
    ).full_clean()


def test_check_constraint_rejects_mismatched_insert(db, django_user_model):
    u = django_user_model.objects.create_user("admin3", "adm3@itasset.dev", "pass12345!")
    site = _site("Site F", "site-f")
    with pytest.raises(IntegrityError), transaction.atomic():
        UserAccessScope.objects.create(
            user=u,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            site=site,  # GLOBAL must not carry a site
            reason="mismatch",
            created_by=u,
        )


def test_enforcement_flag_follows_setting(settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = False
    assert enforcement_enabled() is False
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    assert enforcement_enabled() is True
