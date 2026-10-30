from django.contrib import admin

from apps.core.admin import ScopedAdminMixin

from .models import Department, Person, Site, next_employee_no


@admin.register(Site)
class SiteAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_site_field = "pk"  # sites ARE the org rows

    list_display = ("name", "code", "lead_email", "is_active")
    search_fields = ("name", "code")
    list_filter = ("is_active",)


@admin.register(Department)
class DepartmentAdmin(ScopedAdminMixin, admin.ModelAdmin):
    list_display = ("name", "site", "head")
    list_filter = ("site",)
    search_fields = ("name", "head__name", "head__employee_no")


@admin.register(Person)
class PersonAdmin(ScopedAdminMixin, admin.ModelAdmin):
    scope_dept_field = "department"

    list_display = ("name", "employee_no", "department", "site", "is_active")
    list_filter = ("site", "department", "is_active")
    search_fields = ("name", "employee_no", "email", "ldap_uid")

    def get_changeform_initial_data(self, request):
        # visible prefill: the add form opens with the next free EMP-NNNN
        # number — the same series the main-app create modal uses (session 47)
        initial = super().get_changeform_initial_data(request)
        initial["employee_no"] = next_employee_no()
        return initial

    def get_form(self, request, obj=None, change=False, **kwargs):
        form_cls = super().get_form(request, obj, change, **kwargs)
        if change:
            # edit: the stored number is never rewritten
            return form_cls

        class AutoEmployeeNoForm(form_cls):
            """Add form: a blank/missing employee_no arrives filled server-side
            — the same contract as the main-app PersonForm, so a cleared
            field (or a non-browser POST) never dies on 'required'. An
            explicit value always wins over the auto-assign."""

            def __init__(self, *args, **form_kwargs):
                super().__init__(*args, **form_kwargs)
                if self.is_bound and not (self.data.get("employee_no") or "").strip():
                    data = self.data.copy()
                    data["employee_no"] = next_employee_no()
                    self.data = data

        return AutoEmployeeNoForm
