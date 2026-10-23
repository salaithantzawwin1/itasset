"""ModelForms for Site / Person / Department CRUD (M2; session 37 dept edit)."""

from django import forms

from .models import Department, Person, Site


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "code", "address", "is_active"]


class DepartmentForm(forms.ModelForm):
    """Main-app department edit (name/site + the head from session 32).

    The head picker lists every person with their site preloaded for the
    label; it is optional (a department without a head renders
    "No head assigned" on the detail page).
    """

    class Meta:
        model = Department
        fields = ["name", "site", "head"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["head"].queryset = Person.objects.select_related("site", "department")


class PersonForm(forms.ModelForm):
    class Meta:
        model = Person
        fields = ["employee_no", "name", "email", "ldap_uid", "site", "department", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # department depends on the chosen site's tree; re-sort by site name.
        self.fields["department"].queryset = self.fields["department"].queryset.select_related(
            "site"
        )
