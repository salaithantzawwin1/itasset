from django.contrib import admin
from django.http import Http404

from apps.core.models import IdempotencyRecord, UserAccessScope
from apps.core.roles import user_has_role
from apps.core.scopes import enforcement_enabled, scope_list


def _is_scope_admin(user) -> bool:
    """Scope administration is admin-role only (design §3); superuser passes."""
    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or user_has_role(user, "admin"))


@admin.register(UserAccessScope)
class UserAccessScopeAdmin(admin.ModelAdmin):
    """Scope grants (design §4). `reason` is required by the model; `created_by`
    is taken from the acting admin, never chosen from the form."""

    list_display = (
        "user",
        "scope_type",
        "target",
        "valid_from",
        "valid_to",
        "reason",
        "created_by",
    )
    list_filter = ("scope_type", "site")
    search_fields = ("user__username", "user__email", "reason", "site__name", "department__name")
    autocomplete_fields = ("user", "site", "department")
    readonly_fields = ("created_by", "created_at")

    @admin.display(description="target")
    def target(self, obj) -> str:
        if obj.scope_type == UserAccessScope.ScopeType.SITE:
            return str(obj.site) if obj.site_id else "(none)"
        if obj.scope_type == UserAccessScope.ScopeType.DEPARTMENT:
            return str(obj.department) if obj.department_id else "(none)"
        return "—"

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        # design §5.3: every privileged scope change is audited with a reason
        from apps.audit.models import ActivityLog

        ActivityLog.record(
            actor=request.user,
            action="scope_change" if change else "scope_grant",
            obj=obj,
            details={"target_user": obj.user.username, "reason": obj.reason, "via": "admin"},
        )

    def delete_model(self, request, obj):
        from apps.audit.models import ActivityLog

        details = {
            "target_user": obj.user.username,
            "scope_type": obj.scope_type,
            "reason": obj.reason,
            "scope_id": obj.pk,
            "via": "admin",
        }
        object_repr = str(obj)
        super().delete_model(request, obj)
        ActivityLog.record(
            actor=request.user, action="scope_revoke", object_repr=object_repr, details=details
        )

    def delete_queryset(self, request, queryset):
        from apps.audit.models import ActivityLog

        rows = [
            {
                "target_user": s.user.username,
                "scope_type": s.scope_type,
                "reason": s.reason,
                "scope_id": s.pk,
                "via": "admin",
            }
            for s in queryset
        ]
        super().delete_queryset(request, queryset)
        for details in rows:
            ActivityLog.record(
                actor=request.user,
                action="scope_revoke",
                object_repr=f"{details['target_user']} → {details['scope_type']}",
                details=details,
            )

    # --- admin-role-only gate (design §3: restrict role/scope administration) ---
    def has_module_permission(self, request):
        return _is_scope_admin(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_scope_admin(request.user)

    def has_add_permission(self, request):
        return _is_scope_admin(request.user)

    def has_change_permission(self, request, obj=None):
        return _is_scope_admin(request.user)

    def has_delete_permission(self, request, obj=None):
        return _is_scope_admin(request.user)


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(admin.ModelAdmin):
    """Evidence for §10.1 replays — read-only by design (never edited)."""

    list_display = ("user", "method", "path", "key", "status_code", "created_at")
    list_filter = ("method", "status_code")
    search_fields = ("user__username", "key", "path")
    readonly_fields = (
        "user",
        "key",
        "method",
        "path",
        "request_hash",
        "status_code",
        "response_body",
        "content_type",
        "created_at",
    )
    date_hierarchy = "created_at"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # records are immutable evidence


class ScopedAdminMixin:
    """Stage D (design §5.4): scope Django admin querysets to the caller's
    access scopes. Shadow mode (flag off) logs would-deny and shows everything;
    enforced (flag on) filters rows — an out-of-scope pk in a change/delete URL
    then 404s, because get_object() resolves through get_queryset().

    Set `scope_site_field` to the dotted lookup of the site column ('pk' when
    the model IS the org row) and `scope_dept_field` for department scoping.
    """

    scope_site_field: str | None = "site"
    scope_dept_field: str | None = None

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return scope_list(
            request.user,
            qs,
            site_field=self.scope_site_field,
            dept_field=self.scope_dept_field,
            action=f"admin_{self.model._meta.model_name}_list",
            path=request.path,
        )

    def _get_obj_does_not_exist_redirect(self, request, opts, obj_id):
        """Design §6 row 13: an out-of-scope pk must look exactly like a
        missing one. Stock Django redirects viewers to the changelist; under
        enforcement we 404 instead so admin URLs follow the same policy as
        the web views (shadow mode keeps the Django default)."""
        if enforcement_enabled():
            raise Http404(f"{obj_id} does not exist")
        return super()._get_obj_does_not_exist_redirect(request, opts, obj_id)
