"""ModelForms for Site / Person / Department CRUD (M2; session 37 dept edit)."""

from django import forms

from .models import Department, Person, Site, next_employee_no


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
    """Create/edit a person — employee number auto-assigned on create.

    The create modal opens with ``EMP-NNNN`` already filled in (the next free
    number in the series), and a blank submit still gets one server-side, so
    the field works with or without JS — the same contract as the asset tag.
    On edit the stored number is kept as-is. The number stays visible and
    editable: an explicit value always wins over the auto-assign.
    """

    class Meta:
        model = Person
        fields = ["employee_no", "name", "email", "ldap_uid", "site", "department", "is_active"]
        labels = {
            "employee_no": "Employee No",
            "ldap_uid": "LDAP UID",
        }
        help_texts = {
            "employee_no": "Auto-assigned (EMP-0001…) — change only if you need a specific number.",
            "ldap_uid": "Directory account name, if this person logs in through LDAP/AD.",
            "email": "Used to link the account on LDAP login.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # department depends on the chosen site's tree; re-sort by site name.
        self.fields["department"].queryset = self.fields["department"].queryset.select_related(
            "site"
        )
        self.fields["department"].empty_label = "— None —"
        creating = self.instance is None or not self.instance.pk
        if creating:
            # visible prefill (create modal opens with the next number) …
            self.initial.setdefault("employee_no", next_employee_no())
            # … and server-side assign when the field arrives blank/missing
            if self.is_bound and not (self.data.get("employee_no") or "").strip():
                data = self.data.copy()
                data["employee_no"] = next_employee_no()
                self.data = data
            self.fields["name"].widget.attrs["autofocus"] = True
        self.fields["employee_no"].widget.attrs["placeholder"] = "EMP-0001"
        self.fields["name"].widget.attrs["placeholder"] = "Full name"
        self.fields["email"].widget.attrs["placeholder"] = "name@example.com"
