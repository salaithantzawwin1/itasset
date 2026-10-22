"""Asset lifecycle service layer (DEVELOPMENT.md §3, §9).

All status transitions go through here — never directly in views or the UI.
Illegal transitions raise an exception, tested under §20.

This file implements the core M2 behaviors:
- check_out / check_in (assignment open/close)
- create_assignment / close_assignment (handover)
- receive_asset (IN_STOCK -> AVAILABLE, with optional initial assignment)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.assets.models import Asset, Assignment, Category
from apps.audit.models import ActivityLog
from apps.core.roles import user_has_role

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from django.contrib.auth.models import User

    from apps.people.models import Person


# ---------------------------------------------------------------------------
# Domain exceptions
# ---------------------------------------------------------------------------


class AssetError(Exception):
    """Base for asset-lifecycle service errors."""


class AssetNotAvailable(AssetError):
    def __init__(self, asset: Asset) -> None:
        self.asset = asset
        super().__init__(f"{asset.asset_tag} is not available (status={asset.status})")


class AssignmentError(AssetError):
    """Base for assignment-related errors."""


class AssetAlreadyAssigned(AssignmentError):
    def __init__(self, asset: Asset) -> None:
        self.asset = asset
        super().__init__(
            f"{asset.asset_tag} already has an active assignment "
            f"(holder={self._holder_display(asset)})"
        )

    @staticmethod
    def _holder_display(asset: Asset) -> str:
        active = asset.assignments.filter(in_at__isnull=True).first()
        if active is None:
            return "nobody"
        person = active.to_person
        return person.name if person else "(no holder)"


class AssetNotAssigned(AssignmentError):
    def __init__(self, asset: Asset) -> None:
        self.asset = asset
        super().__init__(f"{asset.asset_tag} has no active assignment to check in")


class InvalidStatusTransition(AssetError):
    def __init__(self, asset: Asset, from_status: str, to_status: str) -> None:
        self.asset = asset
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(f"{asset.asset_tag}: illegal transition {from_status} -> {to_status}")


# ---------------------------------------------------------------------------
# Assignment helpers
# ---------------------------------------------------------------------------


def next_asset_tag(category: Category) -> str:
    """Next free tag for a category: ``<CODE>-NNNN`` (per-prefix sequence).

    Scans the category's existing tags for the highest numeric suffix and
    increments it — sparse or out-of-order numbers (seed data mixes global
    counters into per-code prefixes) never cause a duplicate. The winner is
    only advisory: ``Asset.asset_tag`` stays unique, so a lost race surfaces
    as a normal form error rather than bad data.
    """
    prefix = f"{category.code}-"
    highest = 0
    tags = Asset.objects.filter(asset_tag__startswith=prefix).values_list("asset_tag", flat=True)
    for tag in tags:
        suffix = tag[len(prefix) :]
        if suffix.isdigit() and int(suffix) > highest:
            highest = int(suffix)
    return f"{prefix}{highest + 1:04d}"


def active_assignment(asset: Asset) -> Assignment | None:
    """Return the currently-active assignment for *asset* (in_at IS NULL)."""
    return asset.assignments.filter(in_at__isnull=True).first()


def can_assign(asset: Asset) -> bool:
    """Predicate: is *asset* in a state that allows a new assignment?"""
    return asset.status == Asset.Status.AVAILABLE


# ---------------------------------------------------------------------------
# Core lifecycle operations (§3 stages ④/⑤, §9)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CheckOutResult:
    assignment: Assignment
    asset: Asset


def check_out(
    asset: Asset,
    person: Person,
    *,
    actor: User,
    due_at: datetime | None = None,
    condition_out: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> CheckOutResult:
    """Assign *asset* to *person* (DEVELOPMENT.md §3 stage ⑤, §9).

    Preconditions enforced here (not in the view layer):
    - asset.status == AVAILABLE
    - no active assignment exists for the asset

    The caller must have already verified permissions; this layer is
    intentionally status-only and does not check roles.
    """
    from django.db import IntegrityError, transaction

    from apps.people.models import Person  # local import to avoid circular dep at import time

    if not isinstance(person, Person):
        raise TypeError("person must be a Person instance")

    if asset.status != Asset.Status.AVAILABLE:
        raise AssetNotAvailable(asset)

    if active_assignment(asset) is not None:
        raise AssetAlreadyAssigned(asset)

    now = timezone.now()
    try:
        # Inner atomic → the failed insert rolls back to a savepoint, so the
        # rest of the request (error handling, audit) can still run queries.
        with transaction.atomic():
            assignment = Assignment.objects.create(
                asset=asset,
                to_person=person,
                assigned_by=person,  # simplified: assigned_by mirrors the person for now
                out_at=now,
                due_at=due_at,
                condition_out=condition_out,
                remarks=remarks,
            )
    except IntegrityError:
        # A concurrent check-out won the race between the guard above and this
        # insert; the partial unique index (uniq_active_assignment_per_asset)
        # is the authority — surface it as the same domain conflict (§14.2 #5).
        raise AssetAlreadyAssigned(asset) from None

    asset.status = Asset.Status.ASSIGNED
    asset.bump_version()
    asset.save(update_fields=["status", "version"])

    ActivityLog.record(
        actor=actor,
        action="check_out",
        obj=asset,
        details={"to_person": person.pk, "assignment": assignment.pk},
    )

    return CheckOutResult(assignment=assignment, asset=asset)


@dataclass(frozen=True)
class CheckInResult:
    assignment: Assignment
    asset: Asset


def check_in(
    asset: Asset,
    *,
    actor: User | None = None,
    condition_in: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> CheckInResult:
    """Close the active assignment for *asset* and return it to Available.

    - Reading (DEVELOPMENT.md §3): check-in is the close side of an assignment;
      the asset returns to AVAILABLE unless it is DAMAGED, in which case it
      stays IN_REPAIR (a RepairTicket is expected to be created separately by
      the caller / damage flow).
    - If *condition_in* is DAMAGED the asset is left as ASSIGNED→IN_REPAIR by
      the caller; here we just record the return and do not change status to
      RETIRED — that belongs in the disposal path (§3 stage ⑦/⑧).
    """
    assignment = active_assignment(asset)
    if assignment is None:
        raise AssetNotAssigned(asset)

    now = timezone.now()
    assignment.in_at = now
    assignment.condition_in = condition_in
    if remarks:
        assignment.remarks = (assignment.remarks + " " if assignment.remarks else "") + remarks
    assignment.save(update_fields=["in_at", "condition_in", "remarks"])

    # Decide status:
    # - DAMAGED returns go to IN_REPAIR (caller should also open a RepairTicket)
    # - otherwise back to AVAILABLE
    target_status: Asset.Status
    if condition_in == Asset.Condition.DAMAGED:
        target_status = Asset.Status.IN_REPAIR
    else:
        target_status = Asset.Status.AVAILABLE

    if asset.status != target_status:
        asset.status = target_status
        asset.bump_version()
        asset.save(update_fields=["status", "version"])

    ActivityLog.record(
        actor=actor,
        action="check_in",
        obj=asset,
        details={"assignment": assignment.pk, "condition_in": str(condition_in)},
    )
    return CheckInResult(assignment=assignment, asset=asset)


def create_assignment(
    asset: Asset,
    person: Person,
    *,
    assigned_by: Person | None = None,
    due_at: datetime | None = None,
    condition_out: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> Assignment:
    """Public alias for check_out when the caller only wants the Assignment.

    Prefer check_out when you also need the CheckOutResult / consistent return.
    """
    result = check_out(
        asset,
        person,
        actor=assigned_by or person,
        due_at=due_at,
        condition_out=condition_out,
        remarks=remarks,
    )
    return result.assignment


def close_assignment(
    asset: Asset,
    *,
    condition_in: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> Assignment:
    """Public alias for check_in when the caller only wants the closed Assignment."""
    return check_in(asset, condition_in=condition_in, remarks=remarks).assignment


def handover(
    asset: Asset,
    from_person: Person,
    to_person: Person,
    *,
    actor: User,
    condition_in: Asset.Condition | str = Asset.Condition.GOOD,
    condition_out: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> tuple[Assignment, Assignment]:
    """Person-to-person handover (DEVELOPMENT.md §3 Transfers).

    Implemented as: close current assignment (in_at set) + open a new one,
    in a single logical operation. Status is preserved across the handover
    (a handover is not a status transition). The receiver is named on the new
    assignment; the return condition is recorded on the closed row.

    Returns (closed_assignment, new_assignment).
    """
    from apps.people.models import Person

    if not isinstance(from_person, Person) or not isinstance(to_person, Person):
        raise TypeError("from_person and to_person must be Person instances")

    # Close current assignment with the return condition from the giver.
    closed = check_in(asset, actor=actor, condition_in=condition_in, remarks=remarks)

    # Open new assignment with the condition out for the receiver.
    result = check_out(
        asset,
        to_person,
        actor=actor,
        condition_out=condition_out,
        remarks=remarks,
    )

    return closed.assignment, result.assignment


# ---------------------------------------------------------------------------
# Receive / tag (DEVELOPMENT.md §3 stage ④)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReceiveResult:
    asset: Asset
    assignment: Assignment | None


def receive_asset(
    asset: Asset,
    *,
    actor: User,
    to_person: Person | None = None,
    condition: Asset.Condition | str = Asset.Condition.GOOD,
    remarks: str = "",
) -> ReceiveResult:
    """Receive an asset into stock and optionally assign it immediately.

    Used at stage ④ (Receive & Tag): status moves IN_STOCK -> AVAILABLE and
    a QR label is expected to be printed by the caller (labels app, §3/§27).

    If *to_person* is provided the asset is assigned in the same call
    (stage ④→⑤ shortcut); otherwise it remains AVAILABLE in stock.
    """
    from apps.people.models import Person

    if asset.status != Asset.Status.IN_STOCK:
        raise InvalidStatusTransition(asset, asset.status, Asset.Status.AVAILABLE)

    asset.status = Asset.Status.AVAILABLE
    asset.condition = condition
    asset.bump_version()
    asset.save(update_fields=["status", "condition", "version"])

    assignment: Assignment | None = None
    if to_person is not None:
        if not isinstance(to_person, Person):
            raise TypeError("to_person must be a Person instance")
        result = check_out(asset, to_person, actor=actor, condition_out=condition, remarks=remarks)
        assignment = result.assignment

    ActivityLog.record(
        actor=actor,
        action="receive",
        obj=asset,
        details={"to_person": to_person.pk if to_person else None},
    )
    return ReceiveResult(asset=asset, assignment=assignment)


# ---------------------------------------------------------------------------
# CSV import (DEVELOPMENT.md §13: mapping → dry-run → commit, max 5,000 rows)
# ---------------------------------------------------------------------------

IMPORT_MAX_ROWS = 5_000

# canonical import column -> (model field, kind)
IMPORT_COLUMNS: dict[str, tuple[str, str]] = {
    "asset_tag": ("asset_tag", "str"),
    "category": ("category", "fk:code"),
    "site": ("site", "fk:code"),
    "status": ("status", "choice"),
    "condition": ("condition", "choice"),
    "manufacturer": ("manufacturer", "str"),
    "model": ("model_name", "str"),
    "model_name": ("model_name", "str"),
    "serial_no": ("serial_no", "serial"),
    "hostname": ("hostname", "str"),
    "purchase_date": ("purchase_date", "date"),
    "cost": ("cost", "decimal"),
    "warranty_end": ("warranty_end", "date"),
    "remarks": ("remarks", "str"),
}


def _norm_header(h: str) -> str:
    return h.strip().lower().replace(" ", "_").replace("-", "_")


@dataclass
class ImportRowError:
    row: int  # 1-based data row (excludes the header)
    message: str


@dataclass
class ImportResult:
    dry_run: bool
    file_hash: str
    total_rows: int
    created: int
    skipped_duplicates: int
    errors: list[ImportRowError]
    ignored_columns: list[str]

    @property
    def ok(self) -> bool:
        return not self.errors


def import_assets_csv(
    rows,
    *,
    actor: User | None = None,
    dry_run: bool = True,
) -> ImportResult:
    """Import assets from CSV rows (iterable of dicts, already decoded).

    §13 pipeline: column mapping → dry-run preview → commit.
    - duplicates (existing asset_tag, or same normalized serial_no + model)
      are skipped and reported, never overwritten
    - normalisation: serial_no trimmed + uppercased
    - a committed import writes one ActivityLog row with the file hash
    """
    import csv
    import hashlib
    import io
    from datetime import datetime

    from django.db import transaction

    from apps.assets.models import Asset, Category
    from apps.audit.models import ActivityLog
    from apps.people.models import Site

    # accept either a list of dicts or a raw CSV text blob
    if isinstance(rows, (str, bytes)):
        text = rows.decode("utf-8-sig") if isinstance(rows, bytes) else rows
        file_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        reader = csv.DictReader(io.StringIO(text))
        data = list(reader)
        fieldnames = reader.fieldnames or []
    else:
        data = list(rows)
        fieldnames = list(data[0].keys()) if data else []
        file_hash = hashlib.sha256(repr(data).encode("utf-8")).hexdigest()

    # ---- column mapping (§13 step 1)
    mapping: dict[str, str] = {}  # csv column -> canonical name
    ignored: list[str] = []
    for col in fieldnames:
        canon = _norm_header(col or "")
        if canon in IMPORT_COLUMNS:
            mapping[col] = canon
        else:
            ignored.append(col)

    errors: list[ImportRowError] = []
    created = skipped = 0

    if len(data) > IMPORT_MAX_ROWS:
        return ImportResult(
            dry_run=dry_run,
            file_hash=file_hash,
            total_rows=len(data),
            created=0,
            skipped_duplicates=0,
            errors=[ImportRowError(0, f"too many rows: {len(data)} > {IMPORT_MAX_ROWS} (§13 cap)")],
            ignored_columns=ignored,
        )

    def _parse(row_no: int, raw: dict) -> Asset | None:
        nonlocal skipped
        values: dict[str, object] = {}
        for col, canon in mapping.items():
            field, kind = IMPORT_COLUMNS[canon]
            val = (raw.get(col) or "").strip()
            if not val:
                continue
            if kind == "fk:code":
                model = Category if field == "category" else Site
                obj = model.objects.filter(code__iexact=val).first()
                if obj is None:
                    errors.append(ImportRowError(row_no, f"unknown {field} code: {val!r}"))
                    return None
                values[field] = obj
            elif kind == "choice":
                allowed = dict(
                    Asset.Status.choices if field == "status" else Asset.Condition.choices
                )
                hit = next(
                    (
                        k
                        for k, v in allowed.items()
                        if v.lower() == val.lower() or k.lower() == val.lower()
                    ),
                    None,
                )
                if hit is None:
                    errors.append(ImportRowError(row_no, f"invalid {field}: {val!r}"))
                    return None
                values[field] = hit
            elif kind == "date":
                try:
                    values[field] = datetime.strptime(val, "%Y-%m-%d").date()
                except ValueError:
                    errors.append(
                        ImportRowError(row_no, f"bad date ({field}): {val!r} — expected YYYY-MM-DD")
                    )
                    return None
            elif kind == "decimal":
                values[field] = val.replace(",", "")
            elif kind == "serial":
                values[field] = val.upper()  # §13 normalisation
            else:
                values[field] = val

        tag = values.get("asset_tag")
        if not tag:
            errors.append(ImportRowError(row_no, "asset_tag is required"))
            return None
        if "category" not in values:
            errors.append(ImportRowError(row_no, "category is required"))
            return None
        if "site" not in values:
            errors.append(ImportRowError(row_no, "site is required"))
            return None

        # ---- duplicate detection (§13)
        if Asset.objects.filter(asset_tag=tag).exists():
            skipped += 1
            errors.append(ImportRowError(row_no, f"duplicate asset_tag skipped: {tag}"))
            return None
        serial = values.get("serial_no")
        if (
            serial
            and Asset.objects.filter(
                serial_no=serial, model_name=values.get("model_name", "")
            ).exists()
        ):
            skipped += 1
            errors.append(
                ImportRowError(row_no, f"duplicate serial_no (same model) skipped: {serial}")
            )
            return None

        values.setdefault("status", Asset.Status.IN_STOCK)  # §3 stage ④ default
        values.setdefault("condition", Asset.Condition.GOOD)
        return Asset(**values)

    if dry_run:
        for i, raw in enumerate(data, start=1):
            obj = _parse(i, raw)
            if obj is not None:
                created += 1
        return ImportResult(
            dry_run=True,
            file_hash=file_hash,
            total_rows=len(data),
            created=created,
            skipped_duplicates=skipped,
            errors=errors,
            ignored_columns=ignored,
        )

    # ---- commit (§13 step 3)
    with transaction.atomic():
        for i, raw in enumerate(data, start=1):
            obj = _parse(i, raw)
            if obj is not None:
                obj.save()
                created += 1
        ActivityLog.record(
            actor=actor,
            action="csv_import",
            object_repr=f"CSV import ({created} assets)",
            details={"file_hash": file_hash, "created": created, "rows": len(data)},
        )

    return ImportResult(
        dry_run=False,
        file_hash=file_hash,
        total_rows=len(data),
        created=created,
        skipped_duplicates=skipped,
        errors=errors,
        ignored_columns=ignored,
    )


# ---------------------------------------------------------------------------
# Lifecycle services (DEVELOPMENT.md §3, M6)
# Eight-stage state machine. All status transitions go through here — never in
# views or the UI (§3: "state transitions happen only in services.py").
# ---------------------------------------------------------------------------


class LifecycleError(AssetError):
    """Base for lifecycle (request/transfer/repair/dispose) errors."""


class NotAuthorized(LifecycleError):
    def __init__(self, action: str, hint: str = "check role, §11"):
        super().__init__(f"not authorized to {action} ({hint})")


class SelfApprovalForbidden(NotAuthorized):
    """§14.2 #3 (IDOR row 22): a requester never decides their own request.

    Callers map this to HTTP 403 like any other NotAuthorized — approval and
    rejection are both covered.
    """

    def __init__(self) -> None:
        super().__init__(
            "decide your own request",
            "self-approval forbidden — segregation of duties, §14.2 #3",
        )


class ApprovalSegregationError(NotAuthorized):
    """Spec A §6.6: one person may not cover two steps of the same chain.

    A subclass of `NotAuthorized`, so the HTTP layer already maps it to 403
    like self-approval does.
    """

    def __init__(self) -> None:
        super().__init__(
            "approve two steps of the same request",
            "segregation of duties — another approver is required for this step",
        )


class RequestStateError(LifecycleError):
    pass


class DisposalGuardError(LifecycleError):
    """§3: no asset may reach DISPOSED without a completed DisposalRecord."""

    def __init__(self, asset: Asset):
        super().__init__(f"{asset.asset_tag} cannot be disposed without a DisposalRecord")


# ---- Stage ① Request → ② Approve → ③ Procure → ④ Receive -------------------


def create_request(*, requester, category, site, quantity=1, justification=""):
    """Stage ① — any logged-in user may request (§11 viewer+)."""
    from apps.assets.models import AssetRequest
    from apps.audit.models import ActivityLog

    req = AssetRequest.objects.create(
        requester=requester,
        category=category,
        site=site,
        quantity=max(1, int(quantity or 1)),
        justification=justification,
    )
    ActivityLog.record(actor=requester, action="request_create", obj=req, object_repr=str(req))
    _best_effort("request_pending", notify_pending_approvers, req)
    return req


def resolve_approval_steps(request) -> list[dict]:
    """The ordered approval chain for *request* (Spec A §6.6).

    Matching active `ApprovalRule` rows ordered by `step`; **no match → the
    legacy single admin step**, i.e. exactly the pre-engine behaviour, so
    shipping the engine changes nothing until rules are configured. Pure
    read: safe for views/serializers to render the chain.
    """
    from apps.assets.models import ApprovalRule

    rules = [
        rule
        for rule in ApprovalRule.objects.filter(active=True).select_related("category", "site")
        if rule.matches(request)
    ]
    rules.sort(key=lambda r: (r.step, r.pk))
    if not rules:
        return [{"step": 1, "rule": None, "required_role": "admin"}]
    return [
        {"step": index + 1, "rule": rule, "required_role": rule.required_role}
        for index, rule in enumerate(rules)
    ]


def notify_pending_approvers(request) -> bool:
    """§14: "Asset request awaiting approval → approvers, within 1 h".

    Sent inline at the moment the request starts awaiting approval (and each
    time a chain advances to a new step), so the 1-hour budget is met by
    construction on this LAN setup — no queue to lag behind. Recipients = the
    current step's `required_role` holders who are in scope for the request's
    site (deny-by-default applies to who gets told too); nobody configured →
    §14 fallback (IT lead), never a silent black hole. Dedupe bucket
    (request, step); no-op unless the request is still PENDING.
    """
    from apps.assets.models import ApprovalDecision, AssetRequest
    from apps.audit.notify import resolve_recipients, role_emails, send_alert

    if request.status != AssetRequest.Status.PENDING:
        return False
    steps = resolve_approval_steps(request)
    decided = request.approval_decisions.filter(action=ApprovalDecision.Action.APPROVE).count()
    current = steps[min(decided, len(steps) - 1)]  # decided == 0 right after create
    recipients = role_emails(current["required_role"], request.site)
    return send_alert(
        "request_pending",
        f"request_pending:{request.pk}:step{current['step']}",
        "request_pending",
        {
            "request": request,
            "category": request.category.name,
            "site_name": request.site.name,
            "quantity": request.quantity,
            "step": current["step"],
            "steps_total": len(steps),
            "required_role": current["required_role"],
            "requester": request.requester.username,
        },
        subject=(
            f"[IT Asset] Approval needed: {request.category.name} ×{request.quantity} "
            f"({request.site.name}) — step {current['step']}/{len(steps)}"
        ),
        recipients=recipients or resolve_recipients("request_pending"),
    )


def _best_effort(label: str, fn, /, *args, **kwargs):
    """Run an in-band §14 alert so it can never fail the business action
    (same pattern as `loginaudit` break-glass): SMTP errors are logged, the
    user's operation still succeeds. Idempotent buckets mean a later retry
    (manual re-run of the task, next event touch) can still deliver.
    """
    try:
        return fn(*args, **kwargs)
    except Exception:
        log.exception("%s alert failed", label)
        return False


def delegation_for_role(actor, required_role):
    """An active delegation letting *actor* exercise *required_role* now.

    Deny by default (gap §3.2): the row must be `active`, its window must
    cover today, and its **delegator must hold the role** — a delegation
    never widens authority beyond what the delegator could do themselves.
    Returns None otherwise; multiple rows → the first that qualifies.
    """
    from apps.assets.models import ApprovalDelegation

    rows = ApprovalDelegation.objects.filter(delegate=actor, active=True).select_related(
        "delegator"
    )
    for row in rows:
        if row.covers_today and user_has_role(row.delegator, required_role):
            return row
    return None


def decide_request(request, *, approve: bool, actor, reason=""):
    """Stage ② — approve/reject through the configured approval chain (§11, §6.6).

    - no matching rule → the legacy single admin step (behaviour unchanged);
    - configured chains approve **step by step**, each step gated by its
      `required_role`; the request turns APPROVED only after the last step
      (intermediate approvals leave it PENDING, which is what the UI shows);
    - rejection is final at any step;
    - the same person may never cover two steps (`ApprovalSegregationError`) —
      **principals**, so a delegate and the delegator they act for count as
      one human (§3.2);
    - a step may be approved with one's own role *or* under an active
      delegation whose delegator holds that role (`delegation_for_role`);
    - every decision writes an immutable `ApprovalDecision` event (with
      `delegated_from` when applicable) plus the ActivityLog entry, so
      decisions are events rather than mutable state.

    Errors map to HTTP as before: `SelfApprovalForbidden`/`NotAuthorized` →
    403, `RequestStateError` → 409.
    """
    from django.utils import timezone

    from apps.assets.models import ApprovalDecision, AssetRequest
    from apps.audit.models import ActivityLog

    if request.requester_id is not None and request.requester_id == getattr(actor, "pk", None):
        raise SelfApprovalForbidden()

    steps = resolve_approval_steps(request)
    approved_so_far = request.approval_decisions.filter(
        action=ApprovalDecision.Action.APPROVE
    ).count()
    current = steps[min(approved_so_far, len(steps) - 1)]

    # Authority for this step: own role, else an active delegation whose
    # delegator holds the role. Never widens; never self-approval by proxy.
    delegated_from = None
    if not user_has_role(actor, current["required_role"]):
        delegation = delegation_for_role(actor, current["required_role"])
        if delegation is None:
            raise NotAuthorized(
                f"approve step {current['step']} of this request",
                hint=f"'{current['required_role']}' role required",
            )
        if delegation.delegator_id == request.requester_id:
            raise SelfApprovalForbidden()  # the requester cannot approve by proxy
        delegated_from = delegation.delegator

    if request.status != AssetRequest.Status.PENDING:
        raise RequestStateError(f"request is {request.status}, not PENDING")
    if approve:
        # segregation counts people: the actor plus whoever they act for
        principals = {actor.pk}
        if delegated_from is not None:
            principals.add(delegated_from.pk)
        covered: set[int] = set()
        for actor_pk, delegate_pk in request.approval_decisions.filter(
            action=ApprovalDecision.Action.APPROVE
        ).values_list("actor_id", "delegated_from_id"):
            covered.update(pk for pk in (actor_pk, delegate_pk) if pk)
        if covered & principals:
            raise ApprovalSegregationError()

    step_no = approved_so_far + 1  # == current["step"] unless rules changed mid-chain
    ApprovalDecision.objects.create(
        request=request,
        step=step_no,
        rule=current["rule"],
        action=ApprovalDecision.Action.APPROVE if approve else ApprovalDecision.Action.REJECT,
        actor=actor,
        delegated_from=delegated_from,
        comment=(reason or "")[:255],
    )
    if approve:
        if step_no >= len(steps):  # last configured step reached
            request.status = AssetRequest.Status.APPROVED
            request.approved_by = actor
            request.approved_at = timezone.now()
        # else: stays PENDING — awaiting the next configured step
    else:
        request.status = AssetRequest.Status.REJECTED
        request.rejection_reason = reason[:255]
    request.save()
    ActivityLog.record(
        actor=actor,
        action="request_approve" if approve else "request_reject",
        obj=request,
        details={
            "reason": reason,
            "step": step_no,
            "steps_total": len(steps),
            "delegated_from": delegated_from.username if delegated_from else None,
        },
    )
    # chain advanced → the next step's approvers get their §14 heads-up
    # (a no-op once the request leaves PENDING)
    _best_effort("request_pending", notify_pending_approvers, request)
    return request


def mark_procured(request, *, actor, po_number="", supplier="", cost=None):
    """Stage ③ — attach PO/supplier/cost (§11 admin)."""
    from apps.assets.models import AssetRequest
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin"):
        raise NotAuthorized("mark a request procured")
    if request.status != AssetRequest.Status.APPROVED:
        raise RequestStateError(f"request is {request.status}, not APPROVED")
    request.status = AssetRequest.Status.PROCURED
    request.po_number = po_number
    request.supplier = supplier
    if cost is not None:
        request.estimated_cost = cost
    request.save()
    ActivityLog.record(actor=actor, action="request_procure", obj=request)
    return request


def fulfill_request(request, *, actor, specs=None):
    """Stage ④ — create the Asset(s) IN_STOCK, link to request (§11 technician+).

    `specs` is a list of dicts (one per requested unit) with at least asset_tag;
    defaults fill manufacturer/model/serial from the category template.
    """
    from apps.assets.models import Asset, AssetRequest
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("receive an asset")
    if request.status not in (AssetRequest.Status.PROCURED, AssetRequest.Status.APPROVED):
        raise RequestStateError(f"request is {request.status}, not ready to receive")

    specs = specs or []
    created = []
    for i in range(request.quantity):
        spec = dict(specs[i]) if i < len(specs) and specs[i] else {}
        tag = spec.get("asset_tag")
        if not tag:
            raise LifecycleError("each received unit needs an asset_tag (§13: system-generated)")
        # category-specific specifications (§5 catalogue) — validated through
        # the same engine as the asset form/API; absent attrs stay empty
        from .specs import validate_specs as _validate_specs

        attrs = spec.get("attrs") or {}
        try:
            attrs = _validate_specs(request.category, attrs)
        except ValidationError as exc:
            raise LifecycleError(f"unit {tag}: {exc.message_dict}") from exc
        asset = Asset.objects.create(
            asset_tag=tag,
            category=request.category,
            site=request.site,
            status=Asset.Status.IN_STOCK,  # §3 stage ④
            condition=spec.get("condition", Asset.Condition.NEW),
            manufacturer=spec.get("manufacturer", ""),
            model_name=spec.get("model_name", ""),
            serial_no=(spec.get("serial_no", "") or "").upper(),
            hostname=spec.get("hostname", ""),
            cost=spec.get("cost", request.estimated_cost),
            warranty_end=spec.get("warranty_end"),
            attrs=attrs,
        )
        request.assets.add(asset)
        created.append(asset)
        ActivityLog.record(
            actor=actor, action="receive", obj=asset, details={"from_request": request.pk}
        )

    request.status = AssetRequest.Status.FULFILLED
    request.save(update_fields=["status"])
    ActivityLog.record(
        actor=actor,
        action="request_fulfill",
        obj=request,
        details={"assets": [a.pk for a in created]},
    )
    return created


# ---- Stage ⑥ Transfer (site-to-site, §3) -----------------------------------


def _validate_transfer_assets(assets, *, from_site):
    """Shared guard: every asset sits at the sending site and is movable."""
    assets = list(assets)
    if not assets:
        raise LifecycleError("transfer has no assets")
    for a in assets:
        if a.site_id != from_site.pk:
            raise LifecycleError(f"{a.asset_tag} is not at {from_site.code}")
        if a.status != Asset.Status.AVAILABLE:
            raise AssetNotAvailable(a)
    return assets


def create_transfer(*, actor, from_site, to_site, assets=(), tracking_no="", notes=""):
    """Create a PENDING transfer (§11 technician+).

    Scope checks belong to the caller (API/UI layer) — this layer owns the
    role and state rules only, like the rest of the service layer.
    """
    from apps.assets.models import Transfer
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("create a transfer")
    if from_site.pk == to_site.pk:
        raise LifecycleError("a transfer needs two different sites")
    assets = _validate_transfer_assets(assets, from_site=from_site)
    transfer = Transfer.objects.create(
        from_site=from_site, to_site=to_site, tracking_no=tracking_no or "", notes=notes or ""
    )
    transfer.assets.set(assets)
    ActivityLog.record(
        actor=actor,
        action="transfer_create",
        obj=transfer,
        details={"assets": [a.pk for a in assets]},
    )
    return transfer


def edit_transfer(transfer, *, actor, **changes):
    """Edit a PENDING transfer (technician+). Once dispatched the record is
    frozen — the §3 handover trail must not be rewritten."""
    from apps.assets.models import Transfer
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("edit a transfer")
    if transfer.status != Transfer.Status.PENDING:
        raise LifecycleError(f"transfer is {transfer.status}, not PENDING")
    from_site = changes.pop("from_site", None) or transfer.from_site
    to_site = changes.pop("to_site", None) or transfer.to_site
    if from_site.pk == to_site.pk:
        raise LifecycleError("a transfer needs two different sites")
    if (assets := changes.pop("assets", None)) is not None:
        transfer.assets.set(_validate_transfer_assets(assets, from_site=from_site))
    transfer.from_site = from_site
    transfer.to_site = to_site
    if "tracking_no" in changes:
        transfer.tracking_no = changes["tracking_no"] or ""
    if "notes" in changes:
        transfer.notes = changes["notes"] or ""
    transfer.save()
    ActivityLog.record(actor=actor, action="transfer_edit", obj=transfer)
    return transfer


def dispatch_transfer(transfer, *, actor):
    """Send assets to another site → IN_TRANSIT (§11 technician+)."""
    from django.utils import timezone

    from apps.assets.models import Transfer
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("dispatch a transfer")
    if transfer.status != Transfer.Status.PENDING:
        raise LifecycleError(f"transfer is {transfer.status}, not PENDING")
    assets = list(transfer.assets.all())
    if not assets:
        raise LifecycleError("transfer has no assets")
    for a in assets:
        a.status = Asset.Status.IN_TRANSIT
        a.bump_version()
        a.save(update_fields=["status", "version"])
        ActivityLog.record(
            actor=actor, action="transfer_dispatch", obj=a, details={"transfer": transfer.pk}
        )
    transfer.status = Transfer.Status.IN_TRANSIT
    transfer.dispatched_by = actor
    transfer.dispatched_at = timezone.now()
    transfer.save()
    return transfer


def receive_transfer(transfer, *, actor, damaged_tags=None):
    """Confirm receipt → assets land at destination, back to AVAILABLE (§3).

    Arrival discrepancy: tags in `damaged_tags` go to IN_REPAIR with a
    RepairTicket (§3 "auto damage entry"); the rest return to AVAILABLE.
    """
    from django.utils import timezone

    from apps.assets.models import RepairTicket, Transfer
    from apps.audit.models import ActivityLog
    from apps.audit.notify import resolve_recipients, role_emails, send_alert

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("receive a transfer")
    if transfer.status != Transfer.Status.IN_TRANSIT:
        raise LifecycleError(f"transfer is {transfer.status}, not IN_TRANSIT")
    damaged = set(damaged_tags or [])
    for a in transfer.assets.all():
        a.site = transfer.to_site  # §3: on receipt site = destination
        if a.asset_tag in damaged:
            a.status = Asset.Status.IN_REPAIR
            RepairTicket.objects.create(
                asset=a, fault_category="other", description="Damaged in transit", reported_by=actor
            )
        else:
            a.status = Asset.Status.AVAILABLE
        a.bump_version()
        a.save(update_fields=["site", "status", "version"])
        ActivityLog.record(
            actor=actor, action="transfer_receive", obj=a, details={"transfer": transfer.pk}
        )
    transfer.status = Transfer.Status.RECEIVED if not damaged else Transfer.Status.EXCEPTION
    transfer.received_by = actor
    transfer.received_at = timezone.now()
    transfer.save()
    if damaged:
        # §14: "transfer exception → technician + site lead, immediate" —
        # ONE alert per transfer (not one per damaged tag), in-band + best-effort
        site = transfer.to_site
        recipients = role_emails("technician", site) + (
            [site.lead_email] if site.lead_email else []
        )
        _best_effort(
            "transfer_exception",
            send_alert,
            kind="transfer_exception",
            dedupe_key=f"transfer_exception:{transfer.pk}",
            template="transfer_exception",
            context={
                "transfer": transfer,
                "tags": ", ".join(sorted(damaged)),
                "site_name": site.name,
                "receiver": getattr(actor, "username", "") or "",
            },
            subject=(
                f"[IT Asset] Transfer #{transfer.pk} exception: "
                f"{transfer.from_site.code}→{transfer.to_site.code}"
            ),
            recipients=recipients or resolve_recipients("transfer_exception"),
        )
    return transfer


# ---- Stage ⑥ Repair (§3 damage entry) --------------------------------------
def report_damage(*, asset, actor, fault_category="other", severity="medium", description=""):
    """Report a fault → RepairTicket + asset → IN_REPAIR (any user, §11)."""
    from apps.assets.models import RepairTicket
    from apps.audit.models import ActivityLog
    from apps.audit.notify import resolve_recipients, role_emails, send_alert

    ticket = RepairTicket.objects.create(
        asset=asset,
        fault_category=fault_category,
        severity=severity,
        description=description,
        reported_by=actor,
    )
    if asset.status != Asset.Status.IN_REPAIR:
        asset.status = Asset.Status.IN_REPAIR
        asset.bump_version()
        asset.save(update_fields=["status", "version"])
    ActivityLog.record(
        actor=actor, action="damage_report", obj=asset, details={"ticket": ticket.pk}
    )
    # §14: "Damage reported → technician + site lead, immediate" (in-band,
    # best-effort; technicians scoped to the asset's site, plus its lead)
    site = asset.site
    recipients = role_emails("technician", site) + ([site.lead_email] if site.lead_email else [])
    _best_effort(
        "damage_reported",
        send_alert,
        kind="damage_reported",
        dedupe_key=f"damage_report:{ticket.pk}",
        template="damage_reported",
        context={
            "asset": asset,
            "ticket": ticket,
            "site_name": site.name,
            "reporter": getattr(actor, "username", "") or "",
        },
        subject=f"[IT Asset] Damage reported: {asset.asset_tag}",
        recipients=recipients or resolve_recipients("damage_reported"),
    )
    return ticket


def resolve_repair(ticket, *, actor, outcome, cost=None, replaces_asset=None):
    """Close a repair (§11 technician+): REPAIRED→AVAILABLE, REPLACED links the
    new asset, WRITTEN_OFF hands off to the write-off flow."""
    from apps.assets.models import RepairTicket
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin", "technician"):
        raise NotAuthorized("resolve a repair")
    if ticket.outcome != RepairTicket.Outcome.OPEN:
        raise LifecycleError(f"ticket already {ticket.outcome}")
    ticket.outcome = outcome
    if cost is not None:
        ticket.cost = cost
    if replaces_asset is not None:
        ticket.replaces_asset = replaces_asset
    ticket.save()
    if outcome == RepairTicket.Outcome.REPAIRED:
        ticket.asset.status = Asset.Status.AVAILABLE
        ticket.asset.bump_version()
        ticket.asset.save(update_fields=["status", "version"])
    ActivityLog.record(
        actor=actor, action="repair_resolve", obj=ticket.asset, details={"outcome": outcome}
    )
    return ticket


# ---- Stage ⑦ Write-off → Retire -------------------------------------------
def decide_write_off(write_off, *, actor, approve: bool):
    """Admin signs off a prepared write-off → RETIRED (§3, §11 admin-only)."""
    from django.utils import timezone

    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin"):
        raise NotAuthorized("decide a write-off")
    if write_off.decided:
        raise LifecycleError("write-off already decided")
    write_off.decided = True
    write_off.decided_by = actor
    write_off.decision_at = timezone.now()
    write_off.save()
    if approve:
        reason = "LOST/STOLEN" if write_off.cause == "theft" else "DAMAGED_BEYOND_REPAIR"
        write_off.asset.status = Asset.Status.RETIRED
        write_off.asset.bump_version()
        write_off.asset.save(update_fields=["status", "version"])
        write_off.asset.remarks = (write_off.asset.remarks + f"\nRETIRED: {reason}").strip()
        write_off.asset.save(update_fields=["remarks"])
        ActivityLog.record(
            actor=actor, action="write_off_approve", obj=write_off.asset, details={"reason": reason}
        )
    else:
        ActivityLog.record(actor=actor, action="write_off_reject", obj=write_off.asset)
    return write_off


# ---- Stage ⑦ Sanitize → ⑧ Dispose (§3, §25) --------------------------------
def dispose_asset(*, asset, actor, method, tool_used="", date=None, certificate_no="", notes=""):
    """Create the DisposalRecord and move the asset to DISPOSED (admin, §11).

    Guard (§3/§25): an asset must be RETIRED before it can be disposed, and a
    DisposalRecord (NIST SP 800-88 method, second-person verification) is
    always written first — never DISPOSED without sanitization evidence.
    """
    from django.utils import timezone

    from apps.assets.models import DisposalRecord
    from apps.audit.models import ActivityLog

    if not user_has_role(actor, "admin"):
        raise NotAuthorized("dispose an asset")
    if asset.status != Asset.Status.RETIRED:
        raise DisposalGuardError(asset)

    cert = certificate_no or f"DISP-{asset.asset_tag}-{timezone.localdate().strftime('%Y%m%d')}"
    record = DisposalRecord.objects.create(
        asset=asset,
        method=method,
        tool_used=tool_used,
        operator=actor,
        date=date or timezone.localdate(),
        certificate_no=cert,
        notes=notes,
    )
    asset.status = Asset.Status.DISPOSED
    asset.bump_version()
    asset.save(update_fields=["status", "version"])
    ActivityLog.record(
        actor=actor, action="dispose", obj=asset, details={"certificate": cert, "method": method}
    )
    return record
