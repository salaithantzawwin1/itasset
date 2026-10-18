"""Stage A tests: scope admin gating (design §3) + backfill report (design §5.4)."""

from io import StringIO

import pytest
from django.contrib import admin as django_admin
from django.contrib.auth.models import AnonymousUser, Group
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory

from apps.core.admin import UserAccessScopeAdmin
from apps.core.models import UserAccessScope

pytestmark = pytest.mark.django_db


def _staff_user(django_user_model, username, *groups):
    u = django_user_model.objects.create_user(username, f"{username}@itasset.dev", "pass12345!")
    u.is_staff = True
    u.save()
    for name in groups:
        g, _ = Group.objects.get_or_create(name=name)
        u.groups.add(g)
    return u


def _request_for(user):
    request = RequestFactory().get("/admin/core/useraccessscope/")
    request.user = user
    return request


def test_scope_admin_gated_to_admin_role(django_user_model):
    admin_user = _staff_user(django_user_model, "scopeadmin", "admin")
    tech = _staff_user(django_user_model, "scopetech", "technician")
    model_admin = UserAccessScopeAdmin(UserAccessScope, django_admin.site)

    request = _request_for(admin_user)
    assert model_admin.has_module_permission(request) is True
    assert model_admin.has_add_permission(request) is True
    assert model_admin.has_change_permission(request) is True
    assert model_admin.has_view_permission(request) is True
    assert model_admin.has_delete_permission(request) is True

    tech_request = _request_for(tech)
    assert model_admin.has_module_permission(tech_request) is False
    assert model_admin.has_add_permission(tech_request) is False
    assert model_admin.has_change_permission(tech_request) is False

    anon_request = _request_for(AnonymousUser())
    assert model_admin.has_module_permission(anon_request) is False
    assert model_admin.has_add_permission(anon_request) is False


def test_scope_admin_save_and_delete_are_audited(django_user_model):
    """Design §5.3: the Django-admin scope path writes the same
    `scope_grant` / `scope_revoke` events as the API endpoint (row 20)."""
    from apps.audit.models import ActivityLog
    from apps.people.models import Site

    root = django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    target = django_user_model.objects.create_user("grantee", "grantee@itasset.dev", "pass12345!")
    site = Site.objects.create(name="Audited", code="audit-site")
    request = _request_for(root)
    model_admin = UserAccessScopeAdmin(UserAccessScope, django_admin.site)

    scope = UserAccessScope(
        user=target,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=site,
        reason="why it was granted",
        created_by=root,
    )
    model_admin.save_model(request, scope, form=None, change=False)
    grant = ActivityLog.objects.get(action="scope_grant")
    assert grant.actor == root and grant.details["reason"] == "why it was granted"
    assert grant.details["target_user"] == "grantee"

    model_admin.save_model(request, scope, form=None, change=True)  # an edit is still audited
    assert ActivityLog.objects.filter(action="scope_change").exists()

    model_admin.delete_model(request, scope)
    assert not UserAccessScope.objects.filter(pk=scope.pk).exists()
    revoke = ActivityLog.objects.get(action="scope_revoke")
    assert revoke.actor == root and revoke.details["target_user"] == "grantee"


def test_backfill_report_is_read_only(django_user_model):
    _staff_user(django_user_model, "boss", "admin")
    _staff_user(django_user_model, "tech1", "technician")

    out = StringIO()
    call_command("scope_backfill_report", stdout=out)
    text = out.getvalue()

    assert "boss" in text and "BACKFILL" in text
    assert "tech1" in text and "REVIEW" in text
    assert UserAccessScope.objects.count() == 0  # report writes nothing


def test_backfill_apply_creates_global_for_admin_role_only(django_user_model):
    root = django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    _staff_user(django_user_model, "boss", "admin")
    _staff_user(django_user_model, "tech1", "technician")

    call_command("scope_backfill_report", "--apply", stdout=StringIO())

    scopes = UserAccessScope.objects.filter(scope_type=UserAccessScope.ScopeType.GLOBAL)
    assert {s.user.username for s in scopes} == {"root", "boss"}  # tech1 excluded
    assert all(s.created_by_id == root.id for s in scopes)
    assert all(s.reason for s in scopes)  # reason required by design §5.3


def test_backfill_apply_is_idempotent(django_user_model):
    django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    _staff_user(django_user_model, "boss", "admin")

    call_command("scope_backfill_report", "--apply", stdout=StringIO())
    assert UserAccessScope.objects.count() == 2

    out = StringIO()
    call_command("scope_backfill_report", "--apply", stdout=out)
    assert UserAccessScope.objects.count() == 2  # no duplicates on re-run
    assert "nothing to apply" in out.getvalue()


def test_backfill_apply_preserves_existing_scopes(django_user_model):
    root = django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    boss = _staff_user(django_user_model, "boss", "admin")
    from apps.people.models import Site

    site = Site.objects.create(name="Existing", code="exist")
    UserAccessScope.objects.create(
        user=boss,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=site,
        reason="already scoped manually",
        created_by=root,
    )

    call_command("scope_backfill_report", "--apply", stdout=StringIO())
    # boss had a scope already → not touched, no GLOBAL row added
    assert list(UserAccessScope.objects.filter(user=boss).values_list("scope_type", flat=True)) == [
        "SITE"
    ]


def test_backfill_apply_with_unknown_actor_raises(django_user_model):
    django_user_model.objects.create_superuser("root", "root@itasset.dev", "pass12345!")
    with pytest.raises(CommandError):
        call_command("scope_backfill_report", "--apply", "--actor", "ghost", stdout=StringIO())
