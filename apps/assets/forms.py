"""ModelForms for Asset CRUD (M2)."""

from django import forms

from .models import Asset


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
