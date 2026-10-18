from django.contrib import admin

from apps.core.admin import ScopedAdminMixin

from .models import Department, Person, Site


@admin.register(Site)
class SiteAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "pk"  # sites ARE the org rows

    list_display = ("name", "code", "lead_email", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


@admin.register(Department)
class DepartmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "site")
    list_filter = ("site",)
    search_fields = ("name",)


@admin.register(Person)
class PersonAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_dept_field = "department"

    list_display = ("name", "employee_no", "department", "site", "is_active")
    list_filter = ("site", "department", "is_active")
    search_fields = ("name", "employee_no", "email", "ldap_uid")
