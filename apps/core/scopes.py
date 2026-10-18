"""Scope resolution helpers — RBAC Stage A (ITAM_Scope_RBAC_Design_v1.0 §4–5).

Deny by default: no active scope rows → no access. These helpers are pure and
fail closed (exceptions → deny). Enforcement points (views, API, admin,
exports) are enabled in Stage B/C behind settings.SCOPE_ENFORCEMENT_ENABLED;
Stage A uses them for shadow logging, backfill review, and tests only.

Status-code policy for future callers (design §5.2):
    OutOfScope     → HTTP 404 (out-of-scope looks identical to nonexistent)
    ForbiddenScope → HTTP 403 (in scope, but the action is not allowed)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

from django.conf import settings
from django.db.models import Q, QuerySet
from django.http import Http404

from apps.core.models import UserAccessScope

logger = logging.getLogger(__name__)


class OutOfScope(Exception):
    """Object is outside the caller's record scope — map to HTTP 404."""


class ForbiddenScope(Exception):
    """Caller's scope forbids the action — map to HTTP 403."""


@dataclass(frozen=True)
class ScopeSet:
    """Effective access for one user (design §4.3): union of active rows."""

    global_access: bool = False
    sites: frozenset[int] = frozenset()
    departments: frozenset[int] = frozenset()

    @property
    def is_empty(self) -> bool:
        return not self.global_access and not self.sites and not self.departments

    def allows_site(self, site_id: int | None) -> bool:
        return self.global_access or (site_id is not None and site_id in self.sites)

    def allows_department(self, department_id: int | None) -> bool:
        return self.global_access or (
            department_id is not None and department_id in self.departments
        )


def enforcement_enabled() -> bool:
    """Stage gate (design §5.4): False in Stage A/B, True from Stage C."""
    return bool(getattr(settings, "SCOPE_ENFORCEMENT_ENABLED", False))


def effective_scopes(user) -> ScopeSet:
    """Resolve a user's active scopes (design §4.3). Deny by default.

    - unauthenticated → empty (deny)
    - superuser → GLOBAL (break-glass; audited separately)
    - otherwise the union of rows whose validity window covers today
    """
    if user is None or not user.is_authenticated:
        return ScopeSet()
    if user.is_superuser:
        return ScopeSet(global_access=True)

    today = date.today()
    rows = (
        user.access_scopes.filter(Q(valid_from__isnull=True) | Q(valid_from__lte=today))
        .filter(Q(valid_to__isnull=True) | Q(valid_to__gte=today))
        .values_list("scope_type", "site_id", "department_id")
    )

    sites: set[int] = set()
    departments: set[int] = set()
    for scope_type, site_id, department_id in rows:
        if scope_type == UserAccessScope.ScopeType.GLOBAL:
            return ScopeSet(global_access=True)
        if scope_type == UserAccessScope.ScopeType.SITE and site_id:
            sites.add(site_id)
        elif scope_type == UserAccessScope.ScopeType.DEPARTMENT and department_id:
            departments.add(department_id)
    return ScopeSet(sites=frozenset(sites), departments=frozenset(departments))


def scope_queryset(
    user,
    qs: QuerySet,
    *,
    site_field: str | None = "site",
    dept_field: str | None = None,
) -> QuerySet:
    """Filter a queryset to the caller's scope. GLOBAL passes through; a user
    with no usable scope conditions gets an empty queryset (fail closed)."""
    try:
        scopes = effective_scopes(user)
    except Exception:
        logger.exception("scope resolution failed; denying queryset access")
        return qs.none()

    if scopes.global_access:
        return qs

    conditions = Q()
    narrowed = False
    if site_field and scopes.sites:
        conditions |= Q(**{f"{site_field}__in": scopes.sites})
        narrowed = True
    if dept_field and scopes.departments:
        conditions |= Q(**{f"{dept_field}__in": scopes.departments})
        narrowed = True
    if not narrowed:
        # §4.4 self-view: empty scope + linked Person → own rows only
        if scopes.is_empty:
            own = self_view_q(user, qs.model)
            if own is not None:
                return qs.filter(own)
        return qs.none()
    return qs.filter(conditions)


def user_in_site(user, site) -> bool:
    """True when the user's scope covers the site (Site object or pk)."""
    site_id = getattr(site, "id", site)
    try:
        return effective_scopes(user).allows_site(site_id)
    except Exception:
        logger.exception("scope resolution failed; denying site access")
        return False


def user_in_department(user, department) -> bool:
    """True when the user's scope covers the department (object or pk)."""
    department_id = getattr(department, "id", department)
    try:
        return effective_scopes(user).allows_department(department_id)
    except Exception:
        logger.exception("scope resolution failed; denying department access")
        return False


# ---------------------------------------------------------------------------
# Employee self-view carve-out (design §4.4) — the one exception to
# deny-by-default: a user with ZERO scope rows but a linked Person sees
# exactly their own Assignment history, their own AssetRequest rows, and
# read-only detail of assets currently assigned to them. A zero-scope user
# with no linked Person still gets nothing (row 14 stays green).
# ---------------------------------------------------------------------------


def linked_person(user):
    """The Person row linked to *user* (design §4.4), or None. Never raises."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    from apps.people.models import Person

    try:
        return Person.objects.filter(user=user).first()
    except Exception:
        logger.exception("person link resolution failed; denying self-view")
        return None


def self_view_q(user, model) -> Q | None:
    """Q filter restricting *model* rows to the caller's own records (§4.4).

    Returns None when the carve-out does not apply (no linked Person, or a
    model with no self-view meaning) — callers then deny as before.
    """
    from apps.assets.models import Asset, AssetRequest, Assignment

    person = linked_person(user)
    if person is None:
        return None
    if model is Asset:
        # read-only detail of assets CURRENTLY assigned to the employee
        return Q(
            pk__in=Assignment.objects.filter(to_person=person, in_at__isnull=True).values(
                "asset_id"
            )
        )
    if model is Assignment:
        return Q(to_person=person)
    if model is AssetRequest:
        return Q(requester=user)
    return None


def _self_view_allows(user, obj) -> bool:
    """True when *obj* is one of the caller's own rows (§4.4 object-level)."""
    query = self_view_q(user, type(obj))
    if query is None:
        return False
    try:
        return type(obj)._default_manager.filter(query, pk=obj.pk).exists()
    except Exception:
        logger.exception("self-view check failed; denying")
        return False


def _org_ids_of(obj) -> tuple[int | None, int | None]:
    """Best-effort (site_id, department_id) of any record; None when absent."""
    from apps.people.models import Department, Site

    if isinstance(obj, Site):
        return obj.pk, None
    if isinstance(obj, Department):
        return obj.site_id, obj.pk
    site_id = getattr(obj, "site_id", None)
    if site_id is None:
        site_id = getattr(getattr(obj, "site", None), "id", None)
    department_id = getattr(obj, "department_id", None)
    if department_id is None:
        department_id = getattr(getattr(obj, "department", None), "id", None)
    return site_id, department_id


def require_scope(user, obj) -> None:
    """Raise OutOfScope unless the caller's scope covers the object.

    Fail closed: scope-resolution errors also raise OutOfScope (design §5.1).
    Objects with no org reference are visible to GLOBAL scope only.
    """
    try:
        scopes = effective_scopes(user)
    except Exception:
        logger.exception("scope resolution failed; denying object access")
        raise OutOfScope(f"scope resolution failed for {obj!r}") from None

    if scopes.global_access:
        return

    site_id, department_id = _org_ids_of(obj)
    if site_id is not None and scopes.allows_site(site_id):
        return
    if department_id is not None and scopes.allows_department(department_id):
        return
    raise OutOfScope(f"{obj!r} is outside the caller's scope")


# ---------------------------------------------------------------------------
# Stage B/C gate — shadow "would-deny" logging (design §5.4 Stage B) and
# flag-aware enforcement (Stage C). Call sites go through these helpers only.
# ---------------------------------------------------------------------------

SHADOW_ACTION = "scope_shadow_deny"


def record_shadow(
    user, *, action: str, path: str = "", obj=None, details: dict | None = None
) -> None:
    """Write one 'would deny' audit event (Stage B). Never raises."""
    from apps.audit.models import ActivityLog

    payload: dict = {"scope_action": action, "path": path, "enforced": False}
    if details:
        payload.update(details)
    ActivityLog.record(actor=user, action=SHADOW_ACTION, obj=obj, details=payload)


def _scopes_or_deny(user) -> ScopeSet:
    try:
        return effective_scopes(user)
    except Exception:
        logger.exception("scope resolution failed; denying")
        return ScopeSet()


def check_scope(user, obj, *, action: str = "read", path: str = "") -> bool:
    """Flag-aware object-level scope check (design §5.2 choke point).

    Allowed → True. Deny path: enforcement on (Stage C) → raise OutOfScope
    (callers map to 404/403 per §5.2); shadow mode (Stage B) → log one
    would-deny event and allow, so the UI keeps behaving exactly as before.
    """
    scopes = _scopes_or_deny(user)
    if scopes.global_access:
        return True
    if scopes.is_empty and _self_view_allows(user, obj):
        return True  # §4.4: own rows are readable regardless of org scope
    site_id, department_id = _org_ids_of(obj)
    if site_id is not None and scopes.allows_site(site_id):
        return True
    if department_id is not None and scopes.allows_department(department_id):
        return True
    if enforcement_enabled():
        raise OutOfScope(f"{obj!r} is outside the caller's scope")
    record_shadow(user, action=action, path=path, obj=obj)
    return True


def scope_list(
    user,
    qs: QuerySet,
    *,
    site_field: str | None = "site",
    dept_field: str | None = None,
    action: str = "list",
    path: str = "",
) -> QuerySet:
    """Flag-aware list scoping (design §5.2). Enforcement on → filtered;
    shadow mode → the original queryset (UI unchanged) plus a single
    would-deny event when rows would have been hidden."""
    filtered = scope_queryset(user, qs, site_field=site_field, dept_field=dept_field)
    if enforcement_enabled():
        return filtered
    try:
        total, kept = qs.count(), filtered.count()
    except Exception:
        logger.exception("shadow scope count failed; leaving list unchanged")
        return qs
    if kept < total:
        record_shadow(user, action=action, path=path, details={"would_hide": total - kept})
    return qs


class ScopeGuardMixin:
    """CBV object-level gate (design §5.2): enforced → 404; shadow → log +
    allow. Out-of-scope must look identical to nonexistent (Http404, not 403)."""

    scope_action = "read"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        try:
            check_scope(self.request.user, obj, action=self.scope_action, path=self.request.path)
        except OutOfScope as exc:
            raise Http404(str(exc)) from exc
        return obj
