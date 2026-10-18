"""Admin for export jobs (ops evidence, §10.8 / gap §3.5).

Read-mostly: jobs are created by the API/HTML services and pruned
automatically (newest 20 per user). Admin may inspect FAILED rows and
delete stale ones — no manual creation, nothing to tamper with.
"""

from django.contrib import admin

from .models import ExportJob


@admin.register(ExportJob)
class ExportJobAdmin(admin.ModelAdmin):
    list_display = ("id", "report", "format", "status", "row_count", "requested_by", "created_at")
    list_filter = ("status", "format", "report")
    search_fields = ("report", "requested_by__username", "error")
    date_hierarchy = "created_at"
    readonly_fields = (
        "requested_by",
        "report",
        "format",
        "site",
        "status",
        "row_count",
        "content_type",
        "file",
        "error",
        "created_at",
    )

    def has_add_permission(self, request):
        return False  # jobs only come from run_report
