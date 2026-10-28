"""Core asset register (DEVELOPMENT.md §2 taxonomy, §3 status flow, §9 model)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Category(models.Model):
    """Taxonomy node, e.g. IT-HW-LAP. Extra fields are declared on the schema (§2)."""

    code = models.SlugField(max_length=20, unique=True)  # e.g. IT-HW-LAP
    name = models.CharField(max_length=120)
    schema = models.JSONField(default=dict, blank=True)  # custom field defs (§2)

    class Meta:
        ordering = ["code"]
        verbose_name = "category"
        verbose_name_plural = "categories"  # Django's naive plural was "categorys"

    def __str__(self) -> str:
        return f"{self.code} — {self.name}"

    def clean(self):
        """Structural check of the declarative spec schema (ADR-0004 layer 2).

        Runs in ModelForms/admin (Django calls full_clean there); raw ORM
        writes (services, migrations) stay schema-engine-free by design.
        """
        from .specs import validate_schema_dict

        validate_schema_dict(self.schema)


class Asset(models.Model):
    class Status(models.TextChoices):
        IN_STOCK = "IN_STOCK", "In stock"
        AVAILABLE = "AVAILABLE", "Available"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_REPAIR = "IN_REPAIR", "In repair"
        IN_TRANSIT = "IN_TRANSIT", "In transit"  # site transfer (§3)
        RETIRED = "RETIRED", "Retired"
        DISPOSED = "DISPOSED", "Disposed"

    class Condition(models.TextChoices):
        NEW = "NEW", "New"
        GOOD = "GOOD", "Good"
        FAIR = "FAIR", "Fair"
        POOR = "POOR", "Poor"
        DAMAGED = "DAMAGED", "Damaged"

    asset_tag = models.CharField(max_length=40, unique=True)  # QR content (§13)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="assets")
    site = models.ForeignKey("people.Site", on_delete=models.PROTECT, related_name="assets")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.IN_STOCK)
    condition = models.CharField(max_length=12, choices=Condition.choices, default=Condition.GOOD)

    manufacturer = models.CharField(max_length=80, blank=True)
    model_name = models.CharField(max_length=120, blank=True)
    serial_no = models.CharField(max_length=120, blank=True, db_index=True)
    hostname = models.CharField(max_length=120, blank=True)

    purchase_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    warranty_end = models.DateField(null=True, blank=True, db_index=True)

    attrs = models.JSONField(default=dict, blank=True)  # per-category fields (§2)
    remarks = models.TextField(blank=True)

    # Component ↔ parent link (§6.1 "Recommended relationship"): a Monitor /
    # UPS / Keyboard / Mouse records which workstation it sits on, while each
    # keeps its own tag, serial, warranty and independent assignment (§6:
    # "a component should become a separate record"). Optional — a standalone
    # asset simply leaves it blank. SET_NULL: deleting the parent never
    # cascades to its separately-tracked components (§6).
    parent_asset = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="components",
    )

    # Optimistic lock (Spec A §10.1, gap §3.5): every state mutation bumps it;
    # an API update carrying a stale version answers 409 instead of silently
    # overwriting a concurrent change.
    version = models.PositiveIntegerField(default=1)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["asset_tag"]
        indexes = [models.Index(fields=["site", "status"])]

    def __str__(self) -> str:
        return f"{self.asset_tag} ({self.get_status_display()})"

    def clean(self) -> None:
        """The tag must belong to the category it is filed under (§13: tag
        format `{category-code}-{seq}`).

        This is the bug behind production's `IT-HW-DSK-0010` sitting in
        category `IT-HW-LAP`: a Desktop tag on a Laptop row, so the register
        and the category disagree about what the asset is. Runs in
        ModelForms/admin (Django calls full_clean there) — the create/edit
        form and the admin both stop on it; raw ORM writes (services,
        migrations, seed) stay validation-free by the same design as
        `Category.clean`. The API path repeats the check in its serializer,
        which never calls `full_clean`.

        Tags that carry no category code at all (`W-1`, `SPEC-0001`, a
        legacy hand-me-down) are left alone: the rule catches a tag that
        actively claims a *different* category, which is the confusion that
        matters.
        """
        if not self.category_id or not self.asset_tag:
            return
        from apps.assets.services import tag_category_error

        message = tag_category_error(self.asset_tag, self.category)
        if message:
            raise ValidationError({"asset_tag": message})

    def bump_version(self) -> None:
        """Advance the optimistic-lock counter (pair with update_fields)."""
        self.version += 1


class Assignment(models.Model):
    """Current + historical assignment (check-out / check-in records).

    One active assignment per asset = row with in_at IS NULL. History is append-only
    (§3: "Person-to-person handover closes the current Assignment and opens a new one").
    """

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="assignments")
    to_person = models.ForeignKey(
        "people.Person", on_delete=models.PROTECT, related_name="assignments", null=True, blank=True
    )
    # Department-as-holder (Server/NAS/Switch/laptop pools): infrastructure
    # and shared kit is assigned to a Department instead of a person — the
    # spec's holder column is "employee, department, or team". Exactly one of
    # (to_person, to_dept) may be set; both NULL stays legal for the
    # historical no-holder rows the orphan queue repairs.
    to_dept = models.ForeignKey(
        "people.Department",
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )
    assigned_by = models.ForeignKey(
        "people.Person",
        on_delete=models.PROTECT,
        related_name="assignments_made",
        null=True,
        blank=True,
    )
    out_at = models.DateTimeField(auto_now_add=True)
    due_at = models.DateTimeField(null=True, blank=True)
    in_at = models.DateTimeField(null=True, blank=True)
    condition_in = models.CharField(
        max_length=12, choices=Asset.Condition.choices, default=Asset.Condition.GOOD
    )
    condition_out = models.CharField(
        max_length=12, choices=Asset.Condition.choices, default=Asset.Condition.GOOD
    )
    remarks = models.TextField(blank=True)

    class Meta:
        ordering = ["-out_at"]
        indexes = [models.Index(fields=["asset", "in_at"])]
        constraints = [
            # DB-level backstop for "one active assignment per asset"
            # (RBAC design §14.2 #5) — guards alone leave a race window.
            models.UniqueConstraint(
                fields=["asset"],
                condition=models.Q(in_at__isnull=True),
                name="uniq_active_assignment_per_asset",
            ),
            # a holder is either a person or a department, never both
            models.CheckConstraint(
                condition=~(models.Q(to_person__isnull=False, to_dept__isnull=False)),
                name="assignment_single_holder_kind",
            ),
        ]

    @property
    def holder_label(self) -> str:
        """Display name of whoever holds the asset (person or department)."""
        if self.to_person_id:
            return self.to_person.name
        if self.to_dept_id:
            return f"{self.to_dept.name} (dept)"
        return "(no holder)"

    def __str__(self) -> str:
        return f"{self.asset.asset_tag} → {self.holder_label} ({self.out_at.date()})"


# ---------------------------------------------------------------------------
# Lifecycle records (DEVELOPMENT.md §3, M6)
# Eight-stage flow: Request → Approve → Procure → Receive&Tag → Deploy →
# Maintain/Repair/Transfer → Retire&Sanitize → Dispose. The state machine
# lives in services.py — these are just the row shapes each stage creates.
# ---------------------------------------------------------------------------


class AssetRequest(models.Model):
    """Stage ① Request → ② Approve → ③ Procure → ④ Receive (creates the Asset)."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending approval"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        PROCURED = "PROCURED", "Procured"
        FULFILLED = "FULFILLED", "Fulfilled (asset created)"
        CANCELLED = "CANCELLED", "Cancelled"

    requester = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="asset_requests"
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT)
    site = models.ForeignKey("people.Site", on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField(default=1)
    justification = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="requests_approved",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=255, blank=True)
    po_number = models.CharField(max_length=60, blank=True)
    supplier = models.CharField(max_length=120, blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    assets = models.ManyToManyField(Asset, blank=True, related_name="source_requests")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]  # §9
        verbose_name = "asset request"

    def __str__(self) -> str:
        return f"REQ#{self.pk} {self.quantity}× {self.category.code} ({self.get_status_display()})"


class Transfer(models.Model):
    """Site-to-site move (§3 Transfers): bulk, IN_TRANSIT, tracked."""

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending dispatch"
        IN_TRANSIT = "IN_TRANSIT", "In transit"
        RECEIVED = "RECEIVED", "Received"
        EXCEPTION = "EXCEPTION", "Exception"

    from_site = models.ForeignKey(
        "people.Site", on_delete=models.PROTECT, related_name="transfers_out"
    )
    to_site = models.ForeignKey(
        "people.Site", on_delete=models.PROTECT, related_name="transfers_in"
    )
    assets = models.ManyToManyField(Asset, related_name="transfers")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    tracking_no = models.CharField(max_length=80, blank=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_dispatched",
    )
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="transfers_received",
    )
    received_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "transfer"

    def __str__(self) -> str:
        return f"{self.from_site.code}→{self.to_site.code} #{self.pk} ({self.status})"


class RepairTicket(models.Model):
    """Stage ⑥ Maintain/Repair (§3 damage entry, RMA tracking)."""

    class FaultCategory(models.TextChoices):
        SCREEN = "screen", "Screen"
        BATTERY = "battery", "Battery"
        POWER = "power", "Power"
        STORAGE = "storage", "Storage"
        BOARD = "board", "Board"
        LIQUID = "liquid", "Liquid"
        ACCIDENT = "accident", "Accident"
        OTHER = "other", "Other"

    class Outcome(models.TextChoices):
        OPEN = "OPEN", "Open"
        REPAIRED = "REPAIRED", "Repaired"
        REPLACED = "REPLACED", "Replaced"
        WRITTEN_OFF = "WRITTEN_OFF", "Written off"

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="repair_tickets")
    fault_category = models.CharField(
        max_length=12, choices=FaultCategory.choices, default=FaultCategory.OTHER
    )
    severity = models.CharField(max_length=12, default="medium")
    description = models.TextField(blank=True)
    reported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="repairs_reported",
    )
    reported_at = models.DateTimeField(auto_now_add=True)

    vendor = models.ForeignKey("vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL)
    rma_no = models.CharField(max_length=80, blank=True)
    sent_date = models.DateField(null=True, blank=True)
    returned_date = models.DateField(null=True, blank=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    outcome = models.CharField(max_length=12, choices=Outcome.choices, default=Outcome.OPEN)
    replaces_asset = models.ForeignKey(
        Asset, null=True, blank=True, on_delete=models.SET_NULL, related_name="replaced_by_ticket"
    )

    class Meta:
        ordering = ["-reported_at"]
        verbose_name = "repair ticket"

    def __str__(self) -> str:
        return f"Repair {self.asset.asset_tag} — {self.get_fault_category_display()}"


class WriteOff(models.Model):
    """Stage ⑦ write-off / dead list (§3): technician prepares, admin decides."""

    class Cause(models.TextChoices):
        WEAR = "wear", "Wear"
        ACCIDENT = "accident", "Accident"
        FLOOD = "flood", "Flood"
        FIRE = "fire", "Fire"
        THEFT = "theft", "Theft"
        UNKNOWN = "unknown", "Unknown"

    asset = models.ForeignKey(Asset, on_delete=models.PROTECT, related_name="write_offs")
    damage_date = models.DateField()
    cause = models.CharField(max_length=12, choices=Cause.choices, default=Cause.WEAR)
    description = models.TextField(blank=True)
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    actual_cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    police_report_no = models.CharField(max_length=80, blank=True)  # theft

    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="write_offs_prepared",
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="write_offs_decided",
    )
    decision_at = models.DateTimeField(null=True, blank=True)
    decided = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "write-off"

    def __str__(self) -> str:
        return f"WriteOff {self.asset.asset_tag} ({self.get_cause_display()})"


class DisposalRecord(models.Model):
    """Stage ⑦ Sanitize → ⑧ Dispose (§3, NIST SP 800-88, §25 7-year retention)."""

    class Method(models.TextChoices):
        CRYPTO_ERASE = "crypto_erase", "Crypto erase"
        FACTORY_RESET = "factory_reset", "Factory reset"
        PHYSICAL_DESTRUCTION = "physical_destruction", "Physical destruction"
        NOT_APPLICABLE = "not_applicable", "Not applicable (stolen)"

    asset = models.OneToOneField(Asset, on_delete=models.PROTECT, related_name="disposal")
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.FACTORY_RESET)
    tool_used = models.CharField(max_length=120, blank=True)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disposals_operated",
    )
    verified_by = models.ForeignKey(  # second person (§25)
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="disposals_verified",
    )
    date = models.DateField()
    certificate_no = models.CharField(max_length=60, unique=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date"]
        verbose_name = "disposal record"

    def __str__(self) -> str:
        return f"Disposal {self.asset.asset_tag} — {self.certificate_no}"


# ---------------------------------------------------------------------------
# Approval engine (gap §3.2 / Spec A §6.6) — templates + immutable decisions
# ---------------------------------------------------------------------------


class ApprovalRule(models.Model):
    """One configured approval step (Spec A §6.6: by category/site/threshold).

    A request's approval chain is the set of *matching* active rules ordered
    by `step`. No matching rule → the legacy single admin step, so this table
    changes nothing until somebody configures it (safe to ship, reversible).

    Matching: NULL category/site = any; `min_quantity`/`min_amount` are lower
    bounds on the request. An amount rule only matches when the request
    actually carries an `estimated_cost` — unknown money never silently
    widens nor narrows the chain.
    """

    name = models.CharField(max_length=120)
    step = models.PositiveIntegerField(default=1)
    category = models.ForeignKey(
        Category, null=True, blank=True, on_delete=models.CASCADE, related_name="approval_rules"
    )
    site = models.ForeignKey(
        "people.Site",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="approval_rules",
    )
    min_quantity = models.PositiveIntegerField(default=0)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    required_role = models.CharField(
        max_length=20,
        default="admin",
        choices=[(r, r) for r in ("admin", "technician", "auditor", "viewer")],
    )
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_rules_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["step", "pk"]
        verbose_name = "approval rule"
        verbose_name_plural = "approval rules"
        indexes = [models.Index(fields=["active", "step"])]

    def matches(self, request) -> bool:
        """True when this rule is part of *request*'s approval chain."""
        if not self.active:
            return False
        if self.category_id is not None and self.category_id != request.category_id:
            return False
        if self.site_id is not None and self.site_id != request.site_id:
            return False
        if request.quantity < self.min_quantity:
            return False
        if self.min_amount is not None:
            cost = request.estimated_cost
            if cost is None or cost < self.min_amount:
                return False
        return True

    def __str__(self) -> str:
        return f"step {self.step}: {self.name} ({self.required_role})"


class ApprovalDecision(models.Model):
    """Immutable approval event (Spec A §6.6: decisions are events, not state).

    Append-only — `save()` refuses to touch an existing row, so the chain's
    history stays evidence (§9.1). One decision per request+step (DB unique
    constraint), covering both the default single admin step and configured
    multi-step chains.
    """

    class Action(models.TextChoices):
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"

    request = models.ForeignKey(
        AssetRequest, on_delete=models.CASCADE, related_name="approval_decisions"
    )
    step = models.PositiveIntegerField(default=1)
    rule = models.ForeignKey(
        ApprovalRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="decisions"
    )
    action = models.CharField(max_length=10, choices=Action.choices)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_decisions",
    )
    # §3.2 delegation: set when the actor exercised someone else's authority
    delegated_from = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_decisions_via_delegation",
    )
    comment = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["created_at", "pk"]
        verbose_name = "approval decision"
        constraints = [
            models.UniqueConstraint(fields=["request", "step"], name="uniq_decision_per_step"),
        ]

    def save(self, *args, **kwargs):
        if self.pk is not None and not kwargs.get("force_insert"):
            from django.core.exceptions import ValidationError

            raise ValidationError("approval decisions are immutable — append a new event instead")
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        who = self.actor.username if self.actor_id else "system"
        return f"{self.get_action_display()} by {who} (step {self.step}) on {self.request_id}"


class ApprovalDelegation(models.Model):
    """Delegated approval authority (gap §3.2, Spec A §6.6 extension).

    The *delegator* holds a required role; while the window covers today and
    `active` is on, the *delegate* may exercise that role for approvals.
    Decisions made under delegation record `ApprovalDecision.delegated_from`,
    and segregation-of-duties counts **principals**: one human may never
    cover two steps of a chain, whether directly or through a delegate.

    A delegation never widens authority — the delegator must hold the role
    at decision time. Managed in the Django admin (admin-role only, audited
    like ApprovalRule: "who may approve what" stays gated the same way).
    """

    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_delegations_granted",
    )
    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="approval_delegations_received",
    )
    valid_from = models.DateField(null=True, blank=True)  # NULL = open start
    valid_to = models.DateField(null=True, blank=True)  # NULL = open end
    reason = models.CharField(max_length=255)  # why the authority moved
    active = models.BooleanField(default=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="approval_delegations_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["delegator__username", "delegate__username"]
        verbose_name = "approval delegation"
        verbose_name_plural = "approval delegations"
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(delegator=models.F("delegate")),
                name="delegation_distinct_users",
            ),
        ]

    @property
    def covers_today(self) -> bool:
        from datetime import date

        today = date.today()
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        return True

    def __str__(self) -> str:
        return f"{self.delegator.username} → {self.delegate.username}"
