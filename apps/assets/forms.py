"""ModelForms for Asset CRUD (M2) + the employee request form (§6.5 stage ①).

AssetForm is spec-aware (ADR-0004): dynamic ``spec__<key>`` fields are built
from the selected category's schema and validated through
``apps.assets.specs.validate_specs`` — the same engine the API and imports use.
"""

from django import forms
from django.core.exceptions import ValidationError

from .models import Asset, AssetRequest, Category
from .specs import (
    SPEC_FIELD_PREFIX,
    build_spec_form_fields,
    merge_preserved,
    spec_form_initial,
    validate_specs,
)


class AssetForm(forms.ModelForm):
    class Meta:
        model = Asset
        fields = [
            "asset_tag",
            "category",
            "site",
            "status",
            "condition",
            "manufacturer",
            "model_name",
            "serial_no",
            "hostname",
            "purchase_date",
            "cost",
            "warranty_end",
            "remarks",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cost"].localize = True
        # ---- category first + focused: the tag and the spec fields both
        # depend on it (auto-assign + live swap pick it up from self.data).
        creating = self.instance is None or not self.instance.pk
        if creating:
            self.fields["category"].widget.attrs.setdefault("autofocus", True)
            if self.is_bound and not (self.data.get("asset_tag") or "").strip():
                cat = self._resolve_category()
                if cat is not None:
                    from . import services

                    data = self.data.copy()  # QueryDict → mutable
                    data["asset_tag"] = services.next_asset_tag(cat)
                    self.data = data
        # ---- category-specific specification fields (§5 catalogue) --------
        self._spec_category = self._resolve_category()
        if self._spec_category is not None:
            self.fields.update(build_spec_form_fields(self._spec_category))
            if self.instance and self.instance.pk:
                for name, value in spec_form_initial(
                    self._spec_category, self.instance.attrs
                ).items():
                    if name in self.fields and name not in self.initial:
                        self.initial[name] = value

    def _resolve_category(self, cleaned=None):
        """Category governing the spec fields: posted value wins over instance.

        A category change on the form must swap the visible field set
        immediately (§8.2), so the POST value is preferred when present.
        """
        data = (self.data or {}) if not cleaned else cleaned
        cat_id = data.get("category")
        if isinstance(cat_id, Category):  # cleaned_data holds the instance
            return cat_id
        if cat_id not in (None, ""):
            try:
                return Category.objects.get(pk=cat_id)
            except (Category.DoesNotExist, TypeError, ValueError):
                pass
        if self.instance is not None and self.instance.category_id:
            return self.instance.category
        return None

    def clean(self):
        cleaned = super().clean()
        category = self._resolve_category(cleaned)
        if category is None:
            return cleaned
        raw = {
            name[len(SPEC_FIELD_PREFIX) :]: cleaned.get(name)
            for name in self.fields
            if name.startswith(SPEC_FIELD_PREFIX)
        }
        try:
            cleaned["specs"] = validate_specs(category, raw)
        except ValidationError as exc:
            # attach each message to its dynamic field so the form shows it inline
            for field, messages in exc.message_dict.items():
                target = f"{SPEC_FIELD_PREFIX}{field}" if field != "_unknown" else None
                for message in messages:
                    if target and target in self.fields:
                        self.add_error(target, message)
                    else:
                        self.add_error(None, message)
            cleaned["specs"] = None
        return cleaned

    def save(self, commit=True):
        obj = super().save(commit=False)
        specs = self.cleaned_data.get("specs")
        if specs is not None:
            # values recorded under a previous category (or removed from the
            # schema) are preserved — never silently deleted (§8.2/§4.3)
            obj.attrs = merge_preserved(obj.attrs, specs, obj.category)
        if commit:
            obj.save()
            self.save_m2m()
        return obj


class AssetRequestForm(forms.ModelForm):
    """Employee self-service request (gap: app UI was admin-only).

    Only the fields a requester actually fills; `requester` is set by the
    view and the row always starts PENDING for the approval chain.
    The site queryset is scope-narrowed by the view.
    """

    class Meta:
        model = AssetRequest
        fields = ["category", "site", "quantity", "justification"]
        widgets = {"justification": forms.Textarea(attrs={"rows": 3})}

    def clean_quantity(self):
        qty = self.cleaned_data.get("quantity") or 0
        if qty < 1:
            raise forms.ValidationError("Quantity must be at least 1.")
        return qty
