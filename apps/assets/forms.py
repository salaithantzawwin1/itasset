"""ModelForms for Asset CRUD (M2) + the employee request form (§6.5 stage ①).

AssetForm is spec-aware (ADR-0004): dynamic ``spec__<key>`` fields are built
from the selected category's schema and validated through
``apps.assets.specs.validate_specs`` — the same engine the API and imports use.
"""

from django import forms
from django.core.exceptions import ValidationError

from apps.people.models import Person

from .models import Asset, AssetRequest, Assignment, Category
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
            "parent_asset",
            "remarks",
        ]

    # Not a model column: drives the check-out / check-in / handover through
    # the same services the detail page uses (single write path — the status
    # and the assignment trail stay in sync). Blank on a create leaves the
    # asset in stock; picking someone on an edit hands it over.
    assigned_to = forms.ModelChoiceField(
        queryset=Person.objects.none(),
        required=False,
        label="Assigned to",
        help_text=(
            "Employee holding this asset — saving checks it out (or returns it when cleared)."
        ),
    )

    def __init__(self, *args, **kwargs):
        # optional scope narrowing of the picker (main-app views pass request)
        self.request = kwargs.pop("request", None)
        super().__init__(*args, **kwargs)
        # guards: a subclass or an admin fieldset that drops either field
        # must not break the form (the admin builds its own field list)
        if "parent_asset" in self.fields:
            self.fields["parent_asset"].queryset = Asset.objects.select_related(
                "category"
            ).order_by("asset_tag")
        if "assigned_to" in self.fields:
            self.fields["assigned_to"].queryset = Person.objects.filter(
                is_active=True
            ).select_related("site", "department")
            self.fields["assigned_to"].widget.attrs.update(
                {"data-assigned": "1"}  # marker for the tab script / future JS
            )
        # seed the picker from the currently-active assignment
        self._initial_holder_id = None
        if self.instance is not None and self.instance.pk:
            active = (
                Assignment.objects.filter(asset=self.instance, in_at__isnull=True)
                .select_related("to_person")
                .first()
            )
            if active is not None and active.to_person_id:
                self._initial_holder_id = active.to_person_id
                self.initial.setdefault("assigned_to", active.to_person_id)
            self.fields["parent_asset"].queryset = self.fields["parent_asset"].queryset.exclude(
                pk=self.instance.pk
            )
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

    def clean_parent_asset(self):
        parent = self.cleaned_data.get("parent_asset")
        if parent is None:
            return None
        if self.instance is not None and parent.pk == self.instance.pk:
            raise ValidationError("An asset cannot be its own parent.")
        # walk up the parent chain — a cycle would orphan a whole subtree
        seen, cursor = {parent.pk}, parent
        for _ in range(20):
            next_id = cursor.parent_asset_id
            if next_id is None:
                break
            if self.instance is not None and next_id == self.instance.pk:
                raise ValidationError("That would create a parent loop (§6.1).")
            if next_id in seen:
                break  # pre-existing cycle further up — stop, don't loop forever
            seen.add(next_id)
            cursor = cursor.parent_asset
        return parent

    def clean_assigned_to(self):
        person = self.cleaned_data.get("assigned_to")
        if person is None or self.instance is None or not self.instance.pk:
            return person
        # transition feasibility — mirror the service preconditions so a bad
        # pick fails here, in the form, instead of after the row is saved
        from . import services

        active = services.active_assignment(self.instance)
        status = self.instance.status
        if active is None and status not in (
            Asset.Status.AVAILABLE,
            Asset.Status.IN_STOCK,
        ):
            raise ValidationError(
                f"{self.instance.get_status_display()} assets cannot be checked "
                f"out from this form — use the lifecycle flow."
            )
        if active is not None and status in (
            Asset.Status.RETIRED,
            Asset.Status.DISPOSED,
            Asset.Status.IN_TRANSIT,
        ):
            raise ValidationError(
                f"{self.instance.get_status_display()} assets cannot change holder "
                f"from this form — use the lifecycle flow."
            )
        return person

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
            self._apply_assignment(obj)
        return obj

    def _apply_assignment(self, obj):
        """Run the check-out / handover / check-in the picker asked for.

        The picker is UI sugar over the same lifecycle services the detail
        page's buttons use — status changes and the append-only assignment
        trail happen there, never here. Best-effort: if a concurrent edit
        races the transition the asset is still saved (with a warning the
        view turns into a message), because the row itself is valid.
        """
        from . import services

        if not self.instance.pk:
            return
        wanted = self.cleaned_data.get("assigned_to")
        wanted_id = wanted.pk if wanted is not None else None
        if wanted_id == self._initial_holder_id:
            return
        try:
            active = services.active_assignment(obj)
            if wanted is None:
                if active is not None:
                    services.check_in(obj, actor=self._actor(), remarks="Returned via edit form")
            elif active is not None and active.to_person_id != wanted.pk:
                services.handover(
                    obj,
                    active.to_person,
                    wanted,
                    actor=self._actor(),
                    remarks="Handover via edit form",
                )
            else:
                if obj.status == Asset.Status.IN_STOCK:
                    services.receive_asset(obj, actor=self._actor(), to_person=wanted)
                else:
                    services.check_out(
                        obj, wanted, actor=self._actor(), remarks="Assigned via edit form"
                    )
        except services.AssetError as exc:
            self.assignment_warning = str(exc)

    def _actor(self):
        """The editing user when the view supplied one; None means the
        services record the event without an actor (admin/shell edits)."""
        request = getattr(self, "request", None)
        user = getattr(request, "user", None)
        return user if getattr(user, "is_authenticated", False) else None


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
