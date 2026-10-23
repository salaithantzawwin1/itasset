"""DRF views for /api/v1/ (M3; DEVELOPMENT.md §10, §16 scanner).

Mutations go through the same service layer as the UI (shared rules).
"""

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db.models import Q
from django.db.models.deletion import ProtectedError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view
from rest_framework.decorators import permission_classes as api_permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.assets import services
from apps.assets.models import Asset, AssetRequest, Transfer
from apps.core import scopeadmin
from apps.core.models import UserAccessScope
from apps.core.roles import user_has_role
from apps.core.scopes import (
    OutOfScope,
    check_scope,
    effective_scopes,
    enforcement_enabled,
    record_shadow,
    scope_list,
)
from apps.people.models import Department, Person
from apps.reports.models import ExportJob
from apps.vendors.models import Contract

from .permissions import IsAdmin, IsTechnicianOrAdmin
from .serializers import (
    ApprovalDecisionSerializer,
    AssetSerializer,
    CheckInSerializer,
    CheckOutSerializer,
    ContractSerializer,
    ExportJobCreateSerializer,
    ExportJobSerializer,
    ReceiveSerializer,
    RequestDecideSerializer,
    RequestSerializer,
    ScopeGrantSerializer,
    TransferSerializer,
    TransferWriteSerializer,
)


def _error(message: str, code: int, request=None) -> Response:
    """Consistent error envelope for the hand-written API actions (§10.9,
    gap §3.5): `detail` (unchanged), `status`, plus `code` and
    `correlationId` so a reported id joins up with the server log — the DRF
    handler in apps/api/exceptions.py does the same for raised exceptions."""
    body = {
        "detail": message,
        "status": code,
        "code": _ERROR_CODES.get(code, "error"),
        "correlationId": getattr(request, "correlation_id", "") or "",
    }
    return Response(body, status=code)


_ERROR_CODES = {
    status.HTTP_400_BAD_REQUEST: "bad_request",
    status.HTTP_403_FORBIDDEN: "forbidden",
    status.HTTP_404_NOT_FOUND: "not_found",
    status.HTTP_409_CONFLICT: "conflict",
}


class AssetViewSet(viewsets.ModelViewSet):
    """Assets CRUD + lifecycle actions.

    List supports ?site=, ?status=, ?q= (§10); detail is looked up by
    asset_tag (the QR content) so scanners can hit /assets/{tag}/ directly.
    """

    serializer_class = AssetSerializer
    permission_classes = [IsTechnicianOrAdmin]
    lookup_field = "asset_tag"
    lookup_value_regex = "[^/]+"
    pagination_page_size = 100

    # Sort allowlist (Spec A §10.1, gap §3.5): policy-driven — anything else
    # is a 400 listing the allowed fields, never silently ignored (which
    # hides client bugs) and never passed through to order_by (which would
    # be an ORM injection surface).
    ORDERING_FIELDS = {
        "asset_tag",
        "status",
        "condition",
        "model_name",
        "site",
        "category",
        "purchase_date",
        "warranty_end",
        "created_at",
        "updated_at",
    }

    def get_permissions(self):
        # §11: delete is admin-only (same rule as the web UI's AssetDelete)
        if self.action == "destroy":
            return [IsAdmin()]
        return super().get_permissions()

    def destroy(self, request, *args, **kwargs):
        """DELETE /assets/{tag}/ — assets with history are protected (§3 trail)."""
        try:
            return super().destroy(request, *args, **kwargs)
        except ProtectedError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)

    def get_queryset(self):
        qs = Asset.objects.select_related("category", "site")
        params = self.request.query_params
        if site := params.get("site"):
            if site.isdigit():
                qs = qs.filter(Q(site__code=site) | Q(site_id=int(site)))
            else:
                qs = qs.filter(site__code=site)
        if status_ := params.get("status"):
            qs = qs.filter(status=status_)
        if q := params.get("q", "").strip():
            qs = qs.filter(
                Q(asset_tag__icontains=q)
                | Q(serial_no__icontains=q)
                | Q(hostname__icontains=q)
                | Q(model_name__icontains=q)
            )
        qs = scope_list(self.request.user, qs, action="api_asset_list", path=self.request.path)
        if ordering := (params.get("ordering") or "").strip():
            fields = [f.lstrip("-") for f in ordering.split(",") if f]
            invalid = [f for f in fields if f not in self.ORDERING_FIELDS]
            if invalid or not fields:
                raise ValidationError(
                    {
                        "detail": (
                            f"invalid ordering field(s): {', '.join(invalid) or ordering} — "
                            f"allowed: {', '.join(sorted(self.ORDERING_FIELDS))} "
                            "(prefix '-' for descending)"
                        )
                    }
                )
            qs = qs.order_by(*ordering.split(","))
        return qs

    def create(self, request, *args, **kwargs):
        """New assets land as IN_STOCK (§3 stage ④ receive & tag).

        `category_id` / `site_id` are the writable FKs (the nested read
        serializers stay read-only) — without them create() could not fill
        the NOT NULL columns and answered 500 (defect found 2026-10-17).
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        asset = serializer.save(status=Asset.Status.IN_STOCK)
        return Response(self.get_serializer(asset).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        """PUT/PATCH /assets/{tag}/ — optimistic lock via `version` (§10.1).

        A payload that carries `version` is compared with the stored row: a
        stale value → **409** and the row is untouched, so two editors can't
        silently overwrite each other. Payloads without `version` keep
        last-write-wins for simple clients (scanner scripts). On success the
        version increments; lifecycle services bump it too, so any
        check-out/transfer between read and write is also detected.
        """
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        raw = request.data.get("version") if hasattr(request.data, "get") else None
        if raw is not None:
            try:
                incoming = int(raw)
            except (TypeError, ValueError):
                return _error(
                    "version must be an integer", status.HTTP_400_BAD_REQUEST, request=request
                )
            if incoming != instance.version:
                return _error(
                    f"version conflict: this asset is at version {instance.version}; "
                    "re-read it and retry with the current version",
                    status.HTTP_409_CONFLICT,
                    request=request,
                )
        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        asset = serializer.save(version=instance.version + 1)
        return Response(self.get_serializer(asset).data)

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, asset_tag=None):
        """POST /assets/{tag}/check-out/ — assign to a person (technician+)."""
        asset = self.get_object()
        ser = CheckOutSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            target = ser.resolve_target()
        except (Person.DoesNotExist, Department.DoesNotExist):
            return _error("holder not found", status.HTTP_404_NOT_FOUND, request=request)
        try:
            result = services.check_out(
                asset,
                actor=request.user,
                due_at=ser.validated_data.get("due_at"),
                condition_out=ser.validated_data.get("condition_out", Asset.Condition.GOOD),
                remarks=ser.validated_data.get("remarks", ""),
                **target,
            )
        except services.AssetError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(self.get_serializer(result.asset).data)

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, asset_tag=None):
        """POST /assets/{tag}/check-in/ — return the asset (technician+)."""
        asset = self.get_object()
        ser = CheckInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            result = services.check_in(
                asset,
                actor=request.user,
                condition_in=ser.validated_data.get("condition_in", Asset.Condition.GOOD),
                remarks=ser.validated_data.get("remarks", ""),
            )
        except services.AssetError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(self.get_serializer(result.asset).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, asset_tag=None):
        """POST /assets/{tag}/receive/ — IN_STOCK → AVAILABLE (stage ④)."""
        asset = self.get_object()
        ser = ReceiveSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            person = ser.resolve_person()
        except Person.DoesNotExist:
            return _error("person not found", status.HTTP_404_NOT_FOUND, request=request)
        try:
            services.receive_asset(
                asset,
                actor=request.user,
                to_person=person,
                condition=ser.validated_data.get("condition", Asset.Condition.GOOD),
                remarks=ser.validated_data.get("remarks", ""),
            )
        except services.AssetError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(self.get_serializer(asset).data)


class TransferViewSet(
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """GET /transfers/ (+ detail), POST create, PATCH edit, dispatch + receive (§10.6).

    Visibility: a transfer shows when either end is in the caller's scope
    (v1 union rule — confirmed by the business 2026-10-16). Mutations are
    sender-side: `from_site` and every asset must be in scope (forged fields
    → 403), out-of-scope object → 404 — no existence leak (design §5.2, IDOR
    rows 11). Dispatch/receive stay service-guarded; wrong state → 409.
    """

    serializer_class = TransferSerializer
    permission_classes = [IsAuthenticated]
    http_method_names = ["get", "post", "patch", "head", "options"]  # no PUT/DELETE
    queryset = Transfer.objects.select_related("from_site", "to_site")

    def get_serializer_class(self):
        if self.action in {"create", "partial_update"}:
            return TransferWriteSerializer
        return TransferSerializer

    def get_permissions(self):
        if self.action in {"create", "partial_update"}:
            return [IsTechnicianOrAdmin()]
        return [IsAuthenticated()]

    def get_queryset(self):
        user = self.request.user
        qs = Transfer.objects.select_related("from_site", "to_site")
        scopes = effective_scopes(user)
        if scopes.global_access:
            return qs
        if scopes.sites:
            filtered = qs.filter(Q(from_site__in=scopes.sites) | Q(to_site__in=scopes.sites))
        else:
            filtered = qs.none()
        if enforcement_enabled():
            return filtered
        # shadow mode: keep the list unchanged, log the would-hide delta
        if filtered.count() != qs.count():
            record_shadow(
                user,
                action="api_transfer_list",
                path=self.request.path,
                details={"would_hide": qs.count() - filtered.count()},
            )
        return qs

    def create(self, request, *args, **kwargs):
        """POST /transfers/ — new PENDING transfer (technician+).

        Forged org fields are rejected, never re-mapped (design §5.2):
        out-of-scope site or cargo → 403, wrong state → 409.
        """
        ser = TransferWriteSerializer(data=request.data, context=self.get_serializer_context())
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            check_scope(
                request.user, data["from_site"], action="transfer_create", path=request.path
            )
            for a in data.get("assets", []):
                check_scope(request.user, a, action="transfer_create", path=request.path)
        except OutOfScope:
            return _error(
                "site or asset outside your scope", status.HTTP_403_FORBIDDEN, request=request
            )
        try:
            transfer = services.create_transfer(
                actor=request.user,
                from_site=data["from_site"],
                to_site=data["to_site"],
                assets=data.get("assets", []),
                tracking_no=data.get("tracking_no", ""),
                notes=data.get("notes", ""),
            )
        except services.NotAuthorized:
            return _error(
                "technician or admin role required", status.HTTP_403_FORBIDDEN, request=request
            )
        except (services.LifecycleError, services.AssetError) as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(
            TransferSerializer(transfer, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    def partial_update(self, request, *args, **kwargs):
        """PATCH /transfers/{id}/ — sender-side edits while still PENDING."""
        transfer = self.get_object()  # scoped → 404 out of scope (enforcement)
        ser = TransferWriteSerializer(
            transfer,
            data=request.data,
            partial=True,
            context=self.get_serializer_context(),
        )
        ser.is_valid(raise_exception=True)
        data = ser.validated_data
        try:
            check_scope(
                request.user,
                data.get("from_site", transfer.from_site),
                action="transfer_edit",
                path=request.path,
            )
            for a in data.get("assets", []):
                check_scope(request.user, a, action="transfer_edit", path=request.path)
        except OutOfScope:
            return _error(
                "site or asset outside your scope", status.HTTP_403_FORBIDDEN, request=request
            )
        changes = {
            k: v
            for k, v in data.items()
            if k in ("from_site", "to_site", "assets", "tracking_no", "notes")
        }
        try:
            transfer = services.edit_transfer(transfer, actor=request.user, **changes)
        except services.NotAuthorized:
            return _error(
                "technician or admin role required", status.HTTP_403_FORBIDDEN, request=request
            )
        except (services.LifecycleError, services.AssetError) as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(TransferSerializer(transfer, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"], url_path="dispatch")
    def dispatch_transfer(self, request, pk=None):
        """POST /transfers/{id}/dispatch/ — sending side (technician+).

        (Method named dispatch_transfer: a bare `dispatch` would shadow
        ViewSet.dispatch and break the whole router.)
        """
        transfer = self.get_object()
        try:
            check_scope(
                request.user,
                transfer.from_site,
                action="transfer_dispatch",
                path=request.path,
            )
            for a in transfer.assets.all():
                check_scope(request.user, a, action="transfer_dispatch", path=request.path)
        except OutOfScope:
            return _error("transfer not found", status.HTTP_404_NOT_FOUND, request=request)
        try:
            services.dispatch_transfer(transfer, actor=request.user)
        except services.NotAuthorized:
            return _error(
                "technician or admin role required", status.HTTP_403_FORBIDDEN, request=request
            )
        except services.AssetError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(self.get_serializer(transfer).data)

    @action(detail=True, methods=["post"])
    def receive(self, request, pk=None):
        """POST /transfers/{id}/receive/ — destination side (technician+).

        Body: {"damaged_tags": ["TAG-1", ...]} for arrival discrepancies."""
        transfer = self.get_object()
        try:
            check_scope(
                request.user,
                transfer.to_site,
                action="transfer_receive",
                path=request.path,
            )
        except OutOfScope:
            return _error("transfer not found", status.HTTP_404_NOT_FOUND, request=request)
        damaged = request.data.get("damaged_tags") or []
        try:
            services.receive_transfer(transfer, actor=request.user, damaged_tags=damaged)
        except services.NotAuthorized:
            return _error(
                "technician or admin role required", status.HTTP_403_FORBIDDEN, request=request
            )
        except services.AssetError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(self.get_serializer(transfer).data)


@api_view(["GET"])
@api_permission_classes([IsAuthenticated])
def me(request):
    """GET /api/v1/me/ — caller identity, roles and effective scopes (§10.2).

    Gap §3.5 ("still missing /api/v1/me"): clients use this to render "who am
    I, what can I see" instead of guessing from group names; `scopes` mirrors
    the deny-by-default set (design §4.3) that filters every list, so a user
    with no visible records can see *why*.
    """
    from apps.people.models import Department, Site

    user = request.user
    scopes = effective_scopes(user)
    sites = list(Site.objects.filter(pk__in=scopes.sites).values("id", "code", "name"))
    departments = list(Department.objects.filter(pk__in=scopes.departments).values("id", "name"))
    return Response(
        {
            "username": user.username,
            "email": user.email,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "roles": sorted(g.name for g in user.groups.all()),
            "scopes": {
                "global_access": scopes.global_access,
                "sites": sites,
                "departments": departments,
            },
        }
    )


@api_view(["GET"])
@api_permission_classes([IsAuthenticated])
def org_tree(request):
    """GET /api/v1/org/sites/ — org reference tree (§10.2, gap §3.5).

    Sites + their departments, for form choices (site pickers, transfer
    destinations). Reference data, not records: the deny-by-default scope
    filters *records*, while these names already surface through nested
    serializers — the scoped org model waits on the hierarchy decision
    (gap §6, workstream 3).
    """
    from apps.people.models import Department, Site

    departments: dict[int, list] = {}
    for d in Department.objects.order_by("name").values("id", "name", "site_id"):
        departments.setdefault(d["site_id"], []).append({"id": d["id"], "name": d["name"]})
    return Response(
        [
            {
                "id": s.id,
                "code": s.code,
                "name": s.name,
                "is_active": s.is_active,
                "departments": departments.get(s.id, []),
            }
            for s in Site.objects.order_by("code")
        ]
    )


@api_view(["GET"])
@api_permission_classes([IsAuthenticated])
def scan_payload(request, asset_tag):
    """GET /api/v1/scan/{tag}/ — fast scanner lookup (§16 Mode 1/2 payload)."""
    try:
        asset = Asset.objects.select_related("category", "site").get(asset_tag=asset_tag)
    except Asset.DoesNotExist:
        return Response(
            {"detail": f"unknown asset_tag: {asset_tag}", "status": status.HTTP_404_NOT_FOUND},
            status=status.HTTP_404_NOT_FOUND,
        )
    try:
        check_scope(request.user, asset, action="api_scan", path=request.path)
    except OutOfScope:
        # out-of-scope tag must look exactly like an unknown one (design §5.2)
        return Response(
            {"detail": f"unknown asset_tag: {asset_tag}", "status": status.HTTP_404_NOT_FOUND},
            status=status.HTTP_404_NOT_FOUND,
        )
    active = services.active_assignment(asset)
    return Response(
        {
            "asset_tag": asset.asset_tag,
            "status": asset.status,
            "condition": asset.condition,
            "site": asset.site.code,
            "category": asset.category.code,
            "model": asset.model_name,
            "serial_no": asset.serial_no,
            "holder": (
                {
                    "employee_no": active.to_person.employee_no,
                    "name": active.to_person.name,
                }
                if active and active.to_person
                else (
                    {"employee_no": "", "name": active.to_dept.name, "kind": "department"}
                    if active and active.to_dept
                    else None
                )
            ),
            "can_check_out": services.can_assign(asset),
            "can_check_in": active is not None,
        }
    )


class WarrantyExpiringView(viewsets.ViewSet):
    """GET /api/v1/warranties/expiring/?days=90 (§10, §4 standard report)."""

    def list(self, request):
        from datetime import timedelta

        from django.utils import timezone

        try:
            days = int(request.query_params.get("days", 90))
        except ValueError:
            days = 90
        today = timezone.localdate()
        qs = (
            Asset.objects.filter(
                warranty_end__isnull=False,
                warranty_end__gte=today,
                warranty_end__lte=today + timedelta(days=days),
            )
            .select_related("site", "category")
            .order_by("warranty_end")
        )
        data = [
            {
                "asset_tag": a.asset_tag,
                "model": a.model_name,
                "site": a.site.code,
                "status": a.status,
                "warranty_end": a.warranty_end,
                "days_left": (a.warranty_end - today).days,
            }
            for a in scope_list(request.user, qs, action="api_warranty_expiring", path=request.path)
        ]
        return Response({"days": days, "count": len(data), "results": data})


class ContractExpiringView(viewsets.ViewSet):
    """GET /api/v1/contracts/expiring/?days=90 (§10, §12 renewal alerts)."""

    def list(self, request):
        from datetime import timedelta

        from django.utils import timezone

        # Contracts have no org reference → GLOBAL-scope records only (§5.2).
        scopes = effective_scopes(request.user)
        if not scopes.global_access:
            if enforcement_enabled():
                return Response(
                    {
                        "detail": "contracts are global-scope records",
                        "status": status.HTTP_403_FORBIDDEN,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            record_shadow(request.user, action="api_contract_expiring", path=request.path)

        try:
            days = int(request.query_params.get("days", 90))
        except ValueError:
            days = 90
        today = timezone.localdate()
        qs = (
            Contract.objects.filter(end_date__gte=today, end_date__lte=today + timedelta(days=days))
            .select_related("vendor")
            .order_by("end_date")
        )
        return Response(
            {"days": days, "count": qs.count(), "results": ContractSerializer(qs, many=True).data}
        )


# ---------------------------------------------------------------------------
# Scope administration (design §5.3, §6 rows 17 + 20; gap §3.1 last bullet:
# "audit + reason for privileged scope changes").
#
# GET  /api/v1/users/{id}/scopes/               → the target's scope rows
# POST /api/v1/users/{id}/scopes/               → grant  (admin, reason → 201)
# DELETE /api/v1/users/{id}/scopes/{scope_id}/  → revoke (admin → 204)
#
# IsAdmin answers row 17 (non-admin → 403, before the payload is even read);
# the serializer + service answer row 20 (no reason → 400, no row written,
# and every grant/revoke writes a scope_grant/scope_revoke ActivityLog event).
# ---------------------------------------------------------------------------

User = get_user_model()


@api_view(["GET", "POST"])
@api_permission_classes([IsAdmin])
def user_scopes(request, user_id):
    """Scope list/grant for one user — admin role only (design §6 row 17)."""
    target = get_object_or_404(User, pk=user_id)
    if request.method == "GET":
        return Response(ScopeGrantSerializer(target.access_scopes.all(), many=True).data)

    serializer = ScopeGrantSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)  # missing reason → 400 (row 20)
    try:
        scope = scopeadmin.grant_scope(actor=request.user, user=target, **serializer.validated_data)
    except scopeadmin.ScopeAdminForbidden as exc:
        return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
    except scopeadmin.ScopeGrantInvalid as exc:
        return _error(str(exc), status.HTTP_400_BAD_REQUEST, request=request)
    return Response(ScopeGrantSerializer(scope).data, status=status.HTTP_201_CREATED)


@api_view(["DELETE"])
@api_permission_classes([IsAdmin])
def user_scope_detail(request, user_id, scope_id):
    """Revoke one scope row — admin role only, audited (design §5.3)."""
    scope = get_object_or_404(UserAccessScope, pk=scope_id, user_id=user_id)
    try:
        scopeadmin.revoke_scope(actor=request.user, scope=scope)
    except scopeadmin.ScopeAdminForbidden as exc:
        return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
    return Response(status=status.HTTP_204_NO_CONTENT)


class AssetRequestViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet
):
    """GET /requests/ (+ detail, scoped), POST .../approve|reject/.

    Step authorization lives in the **service** (per-step `required_role` +
    §3.2 delegation): a blanket IsAdmin gate made configured technician
    steps unreachable over the wire and would have hidden delegations.
    Wrong role → 403 from the service, self-approval (incl. by proxy) → 403,
    out-of-scope → 404, already decided → 409 (design §6, §14.2 #3).
    """

    serializer_class = RequestSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = AssetRequest.objects.select_related("requester", "category", "site", "approved_by")
        return scope_list(self.request.user, qs, action="api_request_list", path=self.request.path)

    def _decide(self, request, *, approve: bool):
        target = self.get_object()  # scoped → 404 out of scope (enforcement)
        ser = RequestDecideSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        try:
            services.decide_request(
                target,
                approve=approve,
                actor=request.user,
                reason=ser.validated_data.get("reason", ""),
            )
        except services.SelfApprovalForbidden as exc:
            return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
        except services.ApprovalSegregationError as exc:
            # §6.6: the same person may not cover two steps of one chain
            return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
        except services.NotAuthorized as exc:
            # carries the step's required role ("'technician' role required")
            return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
        except services.RequestStateError as exc:
            return _error(str(exc), status.HTTP_409_CONFLICT, request=request)
        return Response(RequestSerializer(target, context=self.get_serializer_context()).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, approve=True)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(request, approve=False)

    @action(detail=True, methods=["get"])
    def approvals(self, request, pk=None):
        """GET /api/v1/requests/{id}/approvals/ — configured chain + immutable
        decision trail (gap §3.2, Spec A §6.6). Scoped: out of scope → 404."""
        target = self.get_object()
        steps = services.resolve_approval_steps(target)
        decided = target.approval_decisions.count()
        return Response(
            {
                "status": target.status,
                "steps_total": len(steps),
                "current_step": min(decided + 1, len(steps)),
                "chain": [
                    {
                        "step": step["step"],
                        "required_role": step["required_role"],
                        "rule": step["rule"].name if step["rule"] else None,
                    }
                    for step in steps
                ],
                "decisions": ApprovalDecisionSerializer(
                    target.approval_decisions.all(), many=True
                ).data,
            }
        )


class ExportJobViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """GET/POST /exports/ + GET /exports/{id}/download/ — report export jobs
    (§10.8, gap §3.5).

    Same scope gate as the HTML reports (shared `reports.service.run_report`,
    §5.2 — forbidden answers 403 *before* the query runs). Files live in
    private storage with no URL: only this download action serves them, and
    the queryset is owner-scoped (admins see all), so a foreign job id
    answers 404 and never a file. The newest 20 jobs per user are kept.
    """

    permission_classes = [IsAuthenticated]
    queryset = ExportJob.objects.select_related("requested_by", "site")  # for schema/lookup

    def get_serializer_class(self):
        if self.action == "create":
            return ExportJobCreateSerializer
        return ExportJobSerializer

    def get_queryset(self):
        # built fresh per request (same as TransferViewSet), so nothing can
        # ever be cached on the class-level `queryset` between users/requests
        qs = ExportJob.objects.select_related("requested_by", "site")
        if user_has_role(self.request.user, "admin"):
            return qs
        return qs.filter(requested_by=self.request.user)

    def create(self, request, *args, **kwargs):
        ser = ExportJobCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        data = ser.validated_data

        from apps.reports import queries
        from apps.reports.exporters import REGISTRY
        from apps.reports.service import ReportForbidden, UnsupportedFormat, run_report

        # Registry lookup first: an unknown report is a 400, not a 404
        # (a bad *site* pk below stays a 404) — both before any query runs.
        if not REGISTRY:
            queries._register_all()  # idempotent (same guard as the views)
        if data["report"] not in REGISTRY:
            return _error(
                f"unknown report: {data['report']}",
                status.HTTP_400_BAD_REQUEST,
                request=request,
            )

        try:
            content, ctype, filename, row_count = run_report(
                request,
                data["report"],
                data["format"],
                site_id=data.get("site"),
                action="export_create",
            )
        except UnsupportedFormat as exc:
            return _error(str(exc), status.HTTP_400_BAD_REQUEST, request=request)
        except ReportForbidden as exc:
            return _error(str(exc), status.HTTP_403_FORBIDDEN, request=request)
        except Http404:
            raise  # bad site pk etc. — a 404, not a render failure
        except Exception as exc:
            # unexpected render failure → keep an ops row (§10.8 evidence),
            # then re-raise so the correlation-id error envelope is returned
            ExportJob.objects.create(
                requested_by=request.user,
                report=data["report"],
                format=data["format"],
                site_id=data.get("site"),
                status=ExportJob.Status.FAILED,
                error=str(exc)[:500],
            )
            raise

        job = ExportJob(
            requested_by=request.user,
            report=data["report"],
            format=data["format"],
            site_id=data.get("site"),
            row_count=row_count,
            content_type=ctype,
            status=ExportJob.Status.READY,
        )
        job.file.save(filename, ContentFile(content), save=False)
        job.save()

        from apps.audit.models import ActivityLog

        ActivityLog.record(
            actor=request.user,
            action="export_create",
            object_repr=f"Export #{job.pk}: {job.report}.{job.format}",
            details={
                "job": job.pk,
                "report": job.report,
                "format": job.format,
                "rows": row_count,
                "site": job.site_id,
            },
        )
        self._prune_old(request.user)
        return Response(ExportJobSerializer(job).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _prune_old(user):
        """Keep the newest 20 jobs (and their files) per user — §10.8."""
        for old in ExportJob.objects.filter(requested_by=user).order_by("-created_at")[20:]:
            old.file.delete(save=False)
            old.delete()

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        """GET /api/v1/exports/{id}/download/ — the stored file, private (§6.13)."""
        job = self.get_object()  # owner-scoped queryset → foreign id 404s
        if not job.file:
            return _error(
                "export file is no longer available", status.HTTP_404_NOT_FOUND, request=request
            )
        resp = FileResponse(
            job.file.open("rb"),
            content_type=job.content_type or "application/octet-stream",
        )
        resp["Content-Disposition"] = f'attachment; filename="{job.filename}"'
        return resp
