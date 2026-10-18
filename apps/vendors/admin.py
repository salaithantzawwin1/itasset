from django.contrib import admin

from .models import Contract, Vendor, VendorNote


@admin.register(Vendor)
class VendorAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "email", "support_level")
    list_filter = ("category",)
    search_fields = ("name", "email", "contact_name")


@admin.register(VendorNote)
class VendorNoteAdmin(admin.ModelAdmin):
    list_display = ("vendor", "created_at", "author")
    list_filter = ("vendor",)
    date_hierarchy = "created_at"


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = ("title", "vendor", "type", "start_date", "end_date", "auto_renew")
    list_filter = ("type", "auto_renew", "vendor")
    search_fields = ("title", "contract_no", "vendor__name")
    date_hierarchy = "end_date"
    filter_horizontal = ("assets", "licenses")
