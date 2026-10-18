"""ModelForms for Asset CRUD (M2) + the employee request form (§6.5 stage ①)."""

from django import forms

from .models import Asset, AssetRequest


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
