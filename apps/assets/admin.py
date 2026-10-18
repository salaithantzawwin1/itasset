from django.contrib import admin

from apps.core.admin import ScopedAdminMixin, _is_scope_admin

from .models import (
    ApprovalDecision,
    ApprovalDelegation,
    ApprovalRule,
    Asset,
    AssetRequest,
    Assignment,
    Category,
    DisposalRecord,
    RepairTicket,
    Transfer,
    WriteOff,
)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("code", "name")
    search_fields = ("code", "name")
    ordering = ("code",)


@admin.register(Asset)
class AssetAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ("asset_tag", "category", "site", "status", "condition", "warranty_end")
    list_filter = ("status", "condition", "site", "category")
    search_fields = ("asset_tag", "serial_no", "hostname", "model_name")
    date_hierarchy = "purchase_date"
    readonly_fields = ("created_at", "updated_at")
    list_select_related = ("category", "site")
    list_per_page = 50
    save_on_top = True  # long form — don't scroll back up to save


class ActiveAssignmentFilter(admin.SimpleListFilter):
    """Quick toggle: currently checked-out vs returned (§3 in_at IS NULL)."""

    title = "state"
    parameter_name = "active"

    def lookups(self, request, model_admin):
        return [("yes", "Checked out"), ("no", "Returned")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(in_at__isnull=True)
        if self.value() == "no":
            return queryset.filter(in_at__isnull=False)
        return queryset


@admin.register(Assignment)
class AssignmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "asset__site"  # assignments hang off the asset

    """Read-only: assignment rows are written by the check-out/in service, which
    also keeps `asset.status` in sync — hand-editing here would desync them."""

    list_display = ("asset", "to_person", "out_at", "due_at", "in_at", "condition_out")
    list_filter = (ActiveAssignmentFilter, "condition_out", "condition_in", "asset__site")
    search_fields = ("asset__asset_tag", "asset__serial_no", "to_person__name", "remarks")
    date_hierarchy = "out_at"
    list_select_related = ("asset", "to_person", "assigned_by")
    autocomplete_fields = ("asset", "to_person", "assigned_by")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(AssetRequest)
class AssetRequestAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ("pk", "requester", "category", "site", "quantity", "status", "created_at")
    list_filter = ("status", "site", "category")
    search_fields = (
        "requester__username",
        "justification",
        "po_number",
        "supplier",
        "category__code",
        "category__name",
    )
    date_hierarchy = "created_at"
    list_select_related = ("requester", "category", "site")
    # assets M2M can hold thousands of rows → autocomplete, not filter_horizontal
    autocomplete_fields = ("requester", "category", "site", "approved_by", "assets")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Transfer)
class TransferAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "from_site"  # v1: source side defines visibility

    list_display = (
        "pk",
        "from_site",
        "to_site",
        "status",
        "tracking_no",
        "dispatched_at",
        "received_at",
    )
    list_filter = ("status", "from_site", "to_site")
    search_fields = ("tracking_no", "notes")
    date_hierarchy = "created_at"
    list_select_related = ("from_site", "to_site", "dispatched_by", "received_by")
    autocomplete_fields = ("from_site", "to_site", "dispatched_by", "received_by", "assets")
    readonly_fields = ("created_at",)


@admin.register(RepairTicket)
class RepairTicketAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "asset__site"

    list_display = (
        "asset",
        "fault_category",
        "severity",
        "outcome",
        "vendor",
        "cost",
        "reported_at",
    )
    list_filter = ("outcome", "fault_category", "severity", "vendor")
    search_fields = ("asset__asset_tag", "rma_no", "description")
    date_hierarchy = "reported_at"
    list_select_related = ("asset", "vendor", "reported_by")
    autocomplete_fields = ("asset", "vendor", "reported_by", "replaces_asset")
    readonly_fields = ("reported_at",)


@admin.register(WriteOff)
class WriteOffAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "asset__site"

    list_display = ("asset", "damage_date", "cause", "decided", "decision_at", "prepared_by")
    list_filter = ("decided", "cause")
    search_fields = ("asset__asset_tag", "description", "police_report_no")
    date_hierarchy = "damage_date"
    list_select_related = ("asset", "prepared_by", "decided_by")
    autocomplete_fields = ("asset", "prepared_by", "decided_by")
    readonly_fields = ("created_at",)


@admin.register(DisposalRecord)
class DisposalRecordAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "asset__site"

    list_display = ("asset", "method", "date", "certificate_no", "operator", "verified_by")
    list_filter = ("method", "date")
    search_fields = ("asset__asset_tag", "certificate_no", "tool_used", "notes")
    date_hierarchy = "date"
    list_select_related = ("asset", "operator", "verified_by")
    autocomplete_fields = ("asset", "operator", "verified_by")
    readonly_fields = ("created_at",)


# ---- approval engine (gap §3.2, Spec A §6.6) -------------------------------


@admin.register(ApprovalRule)
class ApprovalRuleAdmin(admin.ModelAdmin):
    """Approval templates — admin-role only, like scope grants: these rows
    decide *who may approve what*, so they are gated the same way (§5.3)."""

    list_display = (
        "step",
        "name",
        "category",
        "site",
        "min_quantity",
        "min_amount",
        "required_role",
        "active",
    )
    list_filter = ("active", "required_role", "site", "category")
    search_fields = ("name", "category__code", "category__name", "site__name")
    autocomplete_fields = ("category", "site")
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        from apps.audit.models import ActivityLog

        ActivityLog.record(
            actor=request.user,
            action="approval_rule_change" if change else "approval_rule_create",
            obj=obj,
            details={
                "name": obj.name,
                "step": obj.step,
                "required_role": obj.required_role,
                "active": obj.active,
            },
        )

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


@admin.register(ApprovalDelegation)
class ApprovalDelegationAdmin(admin.ModelAdmin):
    """Delegated approval authority — admin-role only and audited like
    ApprovalRule: these rows decide *who may approve what* (§5.3)."""

    list_display = ("delegator", "delegate", "valid_from", "valid_to", "active", "reason")
    list_filter = ("active",)
    search_fields = ("delegator__username", "delegate__username", "reason")
    autocomplete_fields = ("delegator", "delegate")
    readonly_fields = ("created_by", "created_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)
        from apps.audit.models import ActivityLog

        ActivityLog.record(
            actor=request.user,
            action="delegation_change" if change else "delegation_grant",
            obj=obj,
            details={
                "delegator": obj.delegator.username,
                "delegate": obj.delegate.username,
                "reason": obj.reason,
                "active": obj.active,
            },
        )

    def delete_model(self, request, obj):
        from apps.audit.models import ActivityLog

        details = {
            "delegator": obj.delegator.username,
            "delegate": obj.delegate.username,
            "reason": obj.reason,
        }
        object_repr = str(obj)
        super().delete_model(request, obj)
        ActivityLog.record(
            actor=request.user, action="delegation_revoke", object_repr=object_repr, details=details
        )

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


@admin.register(ApprovalDecision)
class ApprovalDecisionAdmin(ScopedAdminMixin, admin.ModelAdmin):
    """Read-only evidence: approval decisions are immutable events (§6.6)."""

    scope_site_field = "request__site"

    list_display = ("request", "step", "action", "actor", "comment", "created_at")
    list_filter = ("action", "created_at")
    search_fields = ("actor__username", "comment", "request__justification")
    date_hierarchy = "created_at"
    list_select_related = ("request", "actor", "rule")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
