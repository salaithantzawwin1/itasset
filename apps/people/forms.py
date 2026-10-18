"""ModelForms for Site / Person CRUD (M2)."""

from django import forms

from .models import Person, Site


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = ["name", "code", "address", "is_active"]


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
