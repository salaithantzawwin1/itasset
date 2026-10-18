from django.contrib import admin

from apps.core.admin import ScopedAdminMixin

from .models import ActivityLog, AuditItem, AuditSession, EmailAlert


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "actor", "object_repr")
    list_filter = ("action",)
    search_fields = ("object_repr", "actor__username")
    date_hierarchy = "created_at"
    list_select_related = ("actor",)
    readonly_fields = [f.name for f in ActivityLog._meta.fields]

    def has_add_permission(self, request):
        return False  # entries are written by the service layer only

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(EmailAlert)
class EmailAlertAdmin(admin.ModelAdmin):
    """Sent-alert ledger (§14) — rows are created by notify.send_alert to
    deduplicate; read-only here so `last_sent_at` semantics stay intact."""

    list_display = ("created_at", "kind", "dedupe_key", "sent_at")
    list_filter = ("kind",)
    search_fields = ("dedupe_key", "kind")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in EmailAlert._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


class AuditItemInline(admin.TabularInline):
    model = AuditItem
    extra = 0
    autocomplete_fields = ("asset", "scanned_by")
    readonly_fields = ("scanned_at",)


@admin.register(AuditSession)
class AuditSessionAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ("pk", "site", "status", "started_by", "started_at", "closed_at")
    list_filter = ("status", "site")
    search_fields = ("site__name", "site__code", "notes")
    date_hierarchy = "started_at"
    list_select_related = ("site", "started_by")
    autocomplete_fields = ("site", "started_by")
    readonly_fields = ("started_at",)
    inlines = (AuditItemInline,)


@admin.register(AuditItem)
class AuditItemAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "asset__site"  # tag rows inherit the scanned asset's site

    """Standalone view for searching a tag across all sessions; day-to-day
    scanning happens in the session inline above / the app's audit UI."""

    list_display = ("asset_tag", "session", "asset", "scanned_by", "scanned_at")
    search_fields = ("asset_tag", "asset__asset_tag")
    list_filter = ("session",)
    date_hierarchy = "scanned_at"
    list_select_related = ("session", "asset", "scanned_by")
    autocomplete_fields = ("session", "asset", "scanned_by")
    readonly_fields = ("scanned_at",)
