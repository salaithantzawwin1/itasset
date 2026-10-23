"""DRF serializers for /api/v1/ (M3; DEVELOPMENT.md §10)."""

from rest_framework import serializers

from apps.assets.models import ApprovalDecision, Asset, AssetRequest, Assignment, Category, Transfer
from apps.core.models import UserAccessScope
from apps.people.models import Person, Site
from apps.reports.models import ExportJob
from apps.vendors.models import Contract


class ContractSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.name", read_only=True)
    days_to_end = serializers.IntegerField(read_only=True)

    class Meta:
        model = Contract
        fields = [
            "id",
            "title",
            "contract_no",
            "type",
            "vendor",
            "vendor_name",
            "start_date",
            "end_date",
            "days_to_end",
            "value",
            "currency",
            "renewal_notice_days",
            "auto_renew",
        ]


class SiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = Site
        fields = ["id", "name", "code", "is_active"]


class PersonSerializer(serializers.ModelSerializer):
    site = SiteSerializer(read_only=True)

    class Meta:
        model = Person
        fields = ["id", "employee_no", "name", "email", "site", "is_active"]


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        from apps.assets.models import Category

        model = Category
        fields = ["id", "code", "name"]


class AssetSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    site = SiteSerializer(read_only=True)
    # writable FKs for POST — the nested category/site above are read-only, so
    # without these create() could never populate the NOT NULL columns (was a
    # live 500 until 2026-10-17; API create is now tested).
    category_id = serializers.PrimaryKeyRelatedField(
        source="category", queryset=Category.objects.all(), write_only=True
    )
    site_id = serializers.PrimaryKeyRelatedField(
        source="site", queryset=Site.objects.all(), write_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    condition_display = serializers.CharField(source="get_condition_display", read_only=True)
    holder = serializers.SerializerMethodField()
    # category-specific specifications (§5 catalogue → Asset.attrs), validated
    # below through the same engine as the asset form
    attrs = serializers.DictField(required=False)

    class Meta:
        model = Asset
        fields = [
            "id",
            "asset_tag",
            "category",
            "category_id",
            "site",
            "site_id",
            "status",
            "status_display",
            "condition",
            "condition_display",
            "manufacturer",
            "model_name",
            "serial_no",
            "hostname",
            "purchase_date",
            "cost",
            "warranty_end",
            "remarks",
            "attrs",
            "version",
            "holder",
            "created_at",
            "updated_at",
        ]
        # `version` is the optimistic lock (Spec A §10.1): written by the view
        # after its stale-check, never taken from the payload itself.
        read_only_fields = ["id", "version", "created_at", "updated_at"]

    def validate_attrs(self, value):
        """§5 catalogue engine: types, option sets, min/max, unknown keys.

        Values recorded under a previous category (keys outside the current
        schema) are preserved — spec data is never silently deleted (§8.2).
        """
        from django.core.exceptions import ValidationError as DjangoValidationError

        from apps.assets.models import Category as _Category
        from apps.assets.specs import merge_preserved, validate_specs

        category = getattr(self.instance, "category", None)
        raw_cat = (self.initial_data or {}).get("category_id") or (self.initial_data or {}).get(
            "category"
        )
        if isinstance(raw_cat, _Category):
            category = raw_cat
        elif raw_cat not in (None, ""):
            category = _Category.objects.filter(pk=raw_cat).first() or category
        if category is None:
            raise serializers.ValidationError("category is required to validate specifications.")
        try:
            cleaned = validate_specs(category, value or {})
        except DjangoValidationError as exc:
            raise serializers.ValidationError(
                getattr(exc, "message_dict", None) or exc.messages
            ) from exc
        old = (self.instance.attrs if self.instance else None) or {}
        return merge_preserved(old, cleaned, category)

    def get_holder(self, obj) -> dict | None:
        from apps.assets.services import active_assignment

        a = active_assignment(obj)
        if a is None:
            return None
        if a.to_dept is not None:
            return {"employee_no": "", "name": a.to_dept.name, "kind": "department"}
        if a.to_person is None:
            return None
        return {"employee_no": a.to_person.employee_no, "name": a.to_person.name}


class AssignmentSerializer(serializers.ModelSerializer):
    to_person = PersonSerializer(read_only=True)
    to_dept = serializers.SlugRelatedField(slug_field="name", read_only=True)
    condition_in_display = serializers.CharField(source="get_condition_in_display", read_only=True)
    condition_out_display = serializers.CharField(
        source="get_condition_out_display", read_only=True
    )

    class Meta:
        model = Assignment
        fields = [
            "id",
            "asset",
            "to_person",
            "to_dept",
            "out_at",
            "due_at",
            "in_at",
            "condition_out",
            "condition_out_display",
            "condition_in",
            "condition_in_display",
            "remarks",
        ]


class CheckOutSerializer(serializers.Serializer):
    """Scanner/web payload: person by employee_no (badge) or pk; a department
    holder (server/network kit) by `to_dept` pk — exactly one target."""

    to_person = serializers.IntegerField(required=False)
    to_dept = serializers.IntegerField(required=False)
    employee_no = serializers.CharField(required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)
    condition_out = serializers.ChoiceField(
        choices=Asset.Condition.choices, default=Asset.Condition.GOOD
    )
    remarks = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        targets = sum(bool(attrs.get(k)) for k in ("to_person", "to_dept", "employee_no"))
        if targets != 1:
            raise serializers.ValidationError(
                "exactly one holder is required: to_person (pk), to_dept (pk) or employee_no"
            )
        return attrs

    def resolve_person(self):
        from apps.people.models import Person

        if self.validated_data.get("to_person"):
            return Person.objects.get(pk=self.validated_data["to_person"])
        return Person.objects.get(employee_no=self.validated_data["employee_no"].strip())

    def resolve_target(self) -> dict:
        """{person: ...} or {department: ...} for services.check_out()."""
        from apps.people.models import Department

        if self.validated_data.get("to_dept"):
            return {"department": Department.objects.get(pk=self.validated_data["to_dept"])}
        return {"person": self.resolve_person()}


class CheckInSerializer(serializers.Serializer):
    condition_in = serializers.ChoiceField(
        choices=Asset.Condition.choices, default=Asset.Condition.GOOD
    )
    remarks = serializers.CharField(required=False, allow_blank=True, default="")


class ReceiveSerializer(serializers.Serializer):
    """Stage ④ receive & tag: IN_STOCK → AVAILABLE (optionally assign)."""

    to_person = serializers.IntegerField(required=False, allow_null=True)
    employee_no = serializers.CharField(required=False, allow_blank=True)
    condition = serializers.ChoiceField(
        choices=Asset.Condition.choices, default=Asset.Condition.GOOD
    )
    remarks = serializers.CharField(required=False, allow_blank=True, default="")

    def resolve_person(self):
        from apps.people.models import Person

        pk = self.validated_data.get("to_person")
        emp = (self.validated_data.get("employee_no") or "").strip()
        if pk:
            return Person.objects.get(pk=pk)
        if emp:
            return Person.objects.get(employee_no=emp)
        return None


class TransferWriteSerializer(serializers.ModelSerializer):
    """Writable payload for POST/PATCH /transfers/ — cargo addressed by tag."""

    asset_tags = serializers.SlugRelatedField(
        source="assets",
        slug_field="asset_tag",
        many=True,
        queryset=Asset.objects.all(),
        required=False,
    )

    class Meta:
        model = Transfer
        fields = ["id", "from_site", "to_site", "tracking_no", "notes", "asset_tags"]

    def validate(self, attrs):
        if self.instance is None:  # create names both ends; edit may move one
            missing = [f for f in ("from_site", "to_site") if not attrs.get(f)]
            if missing:
                raise serializers.ValidationError({f: "required" for f in missing})
        from_site = attrs.get("from_site", getattr(self.instance, "from_site", None))
        to_site = attrs.get("to_site", getattr(self.instance, "to_site", None))
        if from_site is not None and to_site is not None and from_site.pk == to_site.pk:
            raise serializers.ValidationError("a transfer needs two different sites")
        return attrs


class RequestSerializer(serializers.ModelSerializer):
    """Read payload for /api/v1/requests/ (scoped list + detail)."""

    requester = serializers.CharField(source="requester.username", read_only=True)
    category_code = serializers.CharField(source="category.code", read_only=True)

    class Meta:
        model = AssetRequest
        fields = [
            "id",
            "requester",
            "category",
            "category_code",
            "site",
            "quantity",
            "justification",
            "status",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "po_number",
            "supplier",
            "estimated_cost",
            "created_at",
        ]
        read_only_fields = [
            "status",
            "approved_by",
            "approved_at",
            "rejection_reason",
            "po_number",
            "supplier",
            "estimated_cost",
            "created_at",
        ]


class RequestDecideSerializer(serializers.Serializer):
    """Body for POST /requests/{id}/approve|reject/ — rejection needs a reason."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


class ApprovalDecisionSerializer(serializers.ModelSerializer):
    """One immutable approval event (GET /requests/{id}/approvals/)."""

    actor = serializers.SerializerMethodField()
    rule = serializers.SerializerMethodField()
    delegated_from = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalDecision
        fields = [
            "id",
            "step",
            "action",
            "actor",
            "delegated_from",
            "rule",
            "comment",
            "created_at",
        ]

    def get_actor(self, obj) -> str | None:
        return obj.actor.username if obj.actor_id else None

    def get_delegated_from(self, obj) -> str | None:
        """Whose authority the actor exercised (§3.2 delegation), if anyone."""
        return obj.delegated_from.username if obj.delegated_from_id else None

    def get_rule(self, obj) -> str | None:
        return obj.rule.name if obj.rule_id else None


class ScopeGrantSerializer(serializers.ModelSerializer):
    """Payload for POST /api/v1/users/{id}/scopes/ (design §5.3, row 20).

    `reason` is mandatory and never blank — the service re-checks it, and the
    typed site/department pairing is validated there too (400 before the DB
    CHECK `scope_typed_columns` could turn it into a 500). `user` and
    `created_by` come from the URL and the acting admin, never the body.
    """

    reason = serializers.CharField(required=True, allow_blank=False, trim_whitespace=True)

    class Meta:
        model = UserAccessScope
        fields = ["id", "scope_type", "site", "department", "valid_from", "valid_to", "reason"]
        read_only_fields = ["id"]


class TransferSerializer(serializers.ModelSerializer):
    """Dispatch/receive API payload (§10.6); tags included for the UI."""

    from_site_code = serializers.CharField(source="from_site.code", read_only=True)
    to_site_code = serializers.CharField(source="to_site.code", read_only=True)
    asset_tags = serializers.SlugRelatedField(
        source="assets", slug_field="asset_tag", many=True, read_only=True
    )

    class Meta:
        model = Transfer
        fields = [
            "id",
            "from_site",
            "from_site_code",
            "to_site",
            "to_site_code",
            "status",
            "tracking_no",
            "asset_tags",
            "dispatched_at",
            "received_at",
            "created_at",
        ]


class ExportJobCreateSerializer(serializers.Serializer):
    """POST /api/v1/exports/ — run a registered report as an export job (§10.8).

    Format support and the scope gate are enforced by the shared
    `reports.service.run_report` (one layer with the HTML views), and the
    report-slug existence check lives in the view so an unknown report gets
    the same `{detail, status, code, correlationId}` envelope as every other
    §10.9 error (this serializer owns payload shape only).
    """

    report = serializers.SlugField()
    format = serializers.ChoiceField(choices=["csv", "xlsx", "pdf"])
    site = serializers.IntegerField(required=False, allow_null=True, default=None)


class ExportJobSerializer(serializers.ModelSerializer):
    """Job payload — includes the private download path (owner-scoped)."""

    download = serializers.SerializerMethodField()

    class Meta:
        model = ExportJob
        fields = [
            "id",
            "report",
            "format",
            "status",
            "row_count",
            "site",
            "created_at",
            "download",
        ]
        read_only_fields = fields

    def get_download(self, obj) -> str | None:
        if obj.status != ExportJob.Status.READY or not obj.file:
            return None
        return f"/api/v1/exports/{obj.pk}/download/"
