"""ModelForms for Site / Person / Department CRUD (M2; session 37 dept edit)."""

from django import forms

from .models import Department, Person, Site, next_employee_no


class SiteForm(forms.ModelForm):
    """Create/edit a site, optionally under a parent (Yangon → HQ → office).

    The parent picker leaves out the site itself and everything below it, so
    the one choice that would create a loop is never offered; ``Site.clean``
    re-checks server-side for a crafted POST. Top-level stays the default.
    """

    class Meta:
        model = Site
        fields = ["name", "code", "parent", "address", "is_active"]
        labels = {"parent": "Parent site"}
        help_texts = {
            "parent": "Leave blank for a top-level site (e.g. Yangon); pick the "
            "head office to nest a branch under it."
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        qs = Site.objects.select_related("parent").order_by("name")
        if self.instance.pk:
            excluded, pending = {self.instance.pk}, [self.instance.pk]
            while pending:
                children = Site.objects.filter(parent_id=pending.pop()).values_list("pk", flat=True)
                for child in children:
                    if child not in excluded:
                        excluded.add(child)
                        pending.append(child)
            qs = qs.exclude(pk__in=excluded)
        self.fields["parent"].queryset = qs
        self.fields["parent"].empty_label = "— None (top level) —"


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
