from django.contrib import admin

from .models import LicenseKey, SoftwareLicense


class LicenseKeyInline(admin.TabularInline):
    model = LicenseKey
    extra = 0
    readonly_fields = ("assigned_at",)


@admin.register(SoftwareLicense)
class SoftwareLicenseAdmin(admin.ModelAdmin):
    list_display = ("name", "vendor", "seats", "seats_assigned_display", "updated_at")
    search_fields = ("name", "license_key", "vendor__name")
    inlines = (LicenseKeyInline,)

    @admin.display(description="assigned")
    def seats_assigned_display(self, obj) -> int:
        return obj.seats_assigned


@admin.register(LicenseKey)
class LicenseKeyAdmin(admin.ModelAdmin):
    list_display = ("license", "asset", "assigned_to", "assigned_at", "released_at")
    list_filter = ("license",)
    search_fields = ("key", "asset__asset_tag", "assigned_to__name")
    date_hierarchy = "assigned_at"
