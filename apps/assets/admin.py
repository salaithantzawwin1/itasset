import json
from urllib.parse import unquote

from django import forms
from django.contrib import admin, messages
from django.contrib.admin.helpers import flatten_fieldsets
from django.http import HttpResponseRedirect
from django.urls import reverse

from apps.core.admin import ScopedAdminMixin, _is_scope_admin

from .forms import AssetForm
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
    SpecChoice,
    Transfer,
    WriteOff,
)
from .specs import SPEC_FIELD_PREFIX, build_spec_form_fields, schema_as_json, spec_fields


class PrettyJSONField(forms.JSONField):
    """Indented, re-submittable JSON text in the schema textarea.

    BoundField.value() calls field.prepare_value — the stock forms.JSONField
    would json.dumps a str initial again (double-encoding, which then decodes
    back to a string and fails structure validation). Strings pass through;
    dicts are dumped with indentation.
    """

    def prepare_value(self, value):
        if isinstance(value, str):
            return value
        return json.dumps(value or {}, indent=2, ensure_ascii=False)


class CategoryAdminForm(forms.ModelForm):
    """Schema edited as pretty JSON in a textarea.

    Malformed definitions are rejected by Category.clean →
    specs.validate_schema_dict during ModelForm._post_clean.
    """

    schema = PrettyJSONField(
        required=False,
        help_text='Choice fields whose key has rows under "Spec choice options" '
        "(ram_type, storage_1_type …) take their option list from there — the "
        '"choices" written here only apply to keys without rows.',
        widget=forms.Textarea(
            attrs={"rows": 22, "cols": 96, "style": "font-family:monospace;font-size:12.5px;"}
        ),
    )

    class Meta:
        model = Category
        fields = ("code", "name", "schema")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance is not None and self.instance.pk and self.instance.schema:
            self.initial["schema"] = schema_as_json(self.instance.schema)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Category master + its declarative spec schema (ADR-0004 layer 2)."""

    form = CategoryAdminForm
    list_display = ("code", "name", "field_count")
    search_fields = ("code", "name")
    ordering = ("code",)
    fields = ("code", "name", "schema")

    @admin.display(description="spec fields")
    def field_count(self, obj) -> int:
        fields = (obj.schema or {}).get("fields") if isinstance(obj.schema, dict) else None
        return len(fields) if isinstance(fields, list) else 0


def _spec_choice_key_choices(current: str | None = None) -> list[tuple[str, str]]:
    """(value, label) options for every choice field in the live category schemas.

    The ``key`` of a SpecChoice must match a real spec field — a typo'd key
    would silently collect rows that no form ever shows. Labels use the first
    schema that declares the key (deterministic: categories order by code).
    """
    labels: dict[str, str] = {}
    for category in Category.objects.all().only("schema"):
        for fdef in spec_fields(category):
            if fdef.get("type") in ("choice", "multi-choice"):
                labels.setdefault(fdef["key"], fdef.get("label") or fdef["key"])
    if current and current not in labels:
        labels[current] = f"{current} (no longer in any schema)"
    return sorted(
        ((key, f"{label} ({key})") for key, label in labels.items()), key=lambda pair: pair[0]
    )


class SpecChoiceAdminForm(forms.ModelForm):
    """``key`` as a dropdown of the live schemas' choice fields (see helper)."""

    class Meta:
        model = SpecChoice
        fields = ("key", "value", "order")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        current = self.instance.key if self.instance is not None and self.instance.pk else None
        original = self.fields["key"]
        self.fields["key"] = forms.ChoiceField(
            choices=[("", "---------")] + _spec_choice_key_choices(current),
            label=original.label,
            help_text=original.help_text,
            required=original.required,
        )


@admin.register(SpecChoice)
class SpecChoiceAdmin(admin.ModelAdmin):
    """CRUD for the option lists behind choice spec fields (RAM Type,
    Primary Storage Type …) — one shared list per key, every category that
    declares the field offers it (engine: ``specs.managed_choice_options``).

    Data-safety guards:
    - rename/case-duplicate → refused in ``SpecChoice.clean()`` while assets
      still record the value;
    - single delete → a friendly refusal before the confirmation page;
    - bulk delete → in-use options are reported as *protected*, which makes
      Django skip the deletion (and the audit log entry) entirely.
    """

    form = SpecChoiceAdminForm
    list_display = ("key", "value", "order", "assets_using")
    list_filter = ("key",)
    search_fields = ("key", "value")
    ordering = ("key", "order", "value")

    @admin.display(description="assets")
    def assets_using(self, obj) -> int:
        return obj.assets_in_use()

    def delete_view(self, request, object_id, extra_context=None):
        """Refuse an in-use option *before* the confirmation page, with a
        message that says which value is stuck and why (permission handling
        stays with the base view — no guard for users who may not delete)."""
        obj = self.get_object(request, unquote(object_id))
        if obj is not None and self.has_delete_permission(request, obj):
            used = obj.assets_in_use()
            if used:
                plural = "assets" if used != 1 else "asset"
                self.message_user(
                    request,
                    f"Cannot delete “{obj.value}” — {used} {plural} still record it under "
                    f"{obj.key}. Edit those assets first, or keep the option.",
                    level=messages.ERROR,
                )
                return HttpResponseRedirect(reverse("admin:assets_specchoice_changelist"))
        return super().delete_view(request, object_id, extra_context)

    def get_deleted_objects(self, objs, request):
        """Bulk delete: in-use options are protected — the action then shows
        them on the confirmation page and deletes nothing (no misleading
        "successfully deleted" log either)."""
        objs = list(objs)
        deleted, model_count, perms_needed, protected = super().get_deleted_objects(objs, request)
        for obj in objs:
            used = obj.assets_in_use()
            if used:
                plural = "assets" if used != 1 else "asset"
                protected.append(
                    f"{obj.key}: {obj.value} — still recorded by {used} {plural}; "
                    "edit those assets first."
                )
        return deleted, model_count, perms_needed, protected


@admin.register(Asset)
class AssetAdmin(ScopedAdminMixin, admin.ModelAdmin):
    # AssetForm carries the category's dynamic spec fields (§5 catalogue);
    # they render after the common columns and save into Asset.attrs.
    form = AssetForm
    # Tabbed change form (templates/admin/assets/asset/change_form.html turns
    # each fieldset into a tab — same sectioning as the main app's edit page).
    # Category leads Basics: the tag auto-assign and the spec fields both
    # depend on it. "Specifications" starts empty (filled from the category's
    # schema by get_fieldsets; the live swap fills it client-side on add) and
    # the readonly timestamps ride in the last tab to keep their old position
    # at the bottom of the form.
    fieldsets = (
        (
            "Basics",
            {
                "fields": (
                    "category",
                    "asset_tag",
                    "status",
                    "condition",
                    "site",
                    "assigned_to",
                    "assigned_dept",
                    "parent_asset",
                )
            },
        ),
        ("Specifications", {"fields": ()}),
        ("Device", {"fields": ("manufacturer", "model_name", "serial_no", "hostname")}),
        (
            "Procurement",
            {
                "fields": (
                    "purchase_date",
                    "cost",
                    "warranty_end",
                    "remarks",
                    "created_at",
                    "updated_at",
                )
            },
        ),
    )
    list_display = ("asset_tag", "category", "site", "status", "condition", "warranty_end")
    list_filter = ("status", "condition", "site", "category")

    def get_fieldsets(self, request, obj=None):
        """Merge the category's spec fields into the "Specifications" fieldset.

        Admin only renders fields it knows via base_fields ∪ fieldsets, while
        the dynamic spec fields live on the form *instance* (AssetForm.__init__
        builds them from the category) — so they must be listed here. On a
        POST re-render the posted category is used, so values entered before
        a validation error elsewhere survive.

        The class-level fieldset dicts are copied before extending them —
        mutating them would leak the first request's spec fields into every
        later render.
        """
        fieldsets = [(title, dict(opts)) for title, opts in super().get_fieldsets(request, obj)]
        cat = None
        if obj is not None:
            cat = obj.category
        elif request.method == "POST" and request.POST.get("category"):
            cat = Category.objects.filter(pk=request.POST.get("category")).first()
        if cat is not None:
            names = list(build_spec_form_fields(cat))
            if names:
                for index, (title, opts) in enumerate(fieldsets):
                    if title == "Specifications":
                        opts["fields"] = tuple(opts.get("fields") or ()) + tuple(names)
                        fieldsets[index] = (title, opts)
                        break
                else:
                    # the fieldset was renamed/removed — keep specs visible
                    fieldsets.append(("Specifications", {"fields": names}))
        return fieldsets

    def get_form(self, request, obj=None, change=False, **kwargs):
        # spec__* names are not model columns — strip them before the admin
        # validates the field list against Asset. Django's changeform view
        # passes fields=flatten_fieldsets(fieldsets) explicitly, so the strip
        # must be unconditional. AssetForm.__init__ re-adds the dynamic
        # fields at instance level from the category schema.
        if "fields" in kwargs and kwargs["fields"] is None:
            # _get_form_for_get_fields() wants the bare base form — passing
            # it through avoids get_form ↔ get_fieldsets recursion.
            return super().get_form(request, obj, change, **kwargs)
        fields = kwargs.get("fields")
        if not isinstance(fields, (list, tuple)):
            fields = flatten_fieldsets(self.get_fieldsets(request, obj))
        kwargs["fields"] = [n for n in fields if not n.startswith(SPEC_FIELD_PREFIX)]
        return super().get_form(request, obj, change, **kwargs)

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

    list_display = ("asset", "to_person", "to_dept", "out_at", "due_at", "in_at", "condition_out")
    list_filter = (ActiveAssignmentFilter, "condition_out", "condition_in", "asset__site")
    search_fields = (
        "asset__asset_tag",
        "asset__serial_no",
        "to_person__name",
        "to_dept__name",
        "remarks",
    )
    date_hierarchy = "out_at"
    list_select_related = ("asset", "to_person", "to_dept", "assigned_by")
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
