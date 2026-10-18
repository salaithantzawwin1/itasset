from django.contrib import admin

from .models import Attachment
from .scopes import scope_attachments


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "kind",
        "owner_display",
        "original_name",
        "size",
        "uploaded_by",
        "created_at",
    )
    list_filter = ("kind", "created_at")
    search_fields = ("original_name", "asset__asset_tag", "transfer__tracking_no")
    autocomplete_fields = ("asset", "request", "transfer")
    readonly_fields = ("original_name", "size", "content_type", "uploaded_by", "created_at")

    def get_queryset(self, request):
        return scope_attachments(
            request.user,
            super().get_queryset(request),
            action="admin_attachment_list",
            path=request.path,
        )

    @admin.display(description="owner")
    def owner_display(self, obj):
        return str(obj.owner or "—")
