"""Scope administration — privileged grant/revoke with reason + audit.

Design §5.3 / Spec A §5.3: *"Require a reason and audit event for privileged
scope changes."* This module is the single write path for `UserAccessScope`
rows — the HTTP endpoint (`POST|DELETE /api/v1/users/{id}/scopes/`) and the
Django admin both call into it, so IDOR rows 17 and 20 are enforced once:

- **row 17** — only the admin role may grant or revoke a scope
  (`ScopeAdminForbidden` → HTTP 403); everyone else hits the same wall.
- **row 20** — a grant without a reason is rejected
  (`ScopeGrantInvalid` → HTTP 400) and writes no row; a successful grant or
  revoke always emits a `scope_grant` / `scope_revoke` ActivityLog event.

Validation runs *before* save (typed-column rule of the DB CHECK
`scope_typed_columns`, date window from `UserAccessScope.clean`) so a bad
payload surfaces as a 400 instead of an IntegrityError 500.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError as DjangoValidationError

from apps.core.models import UserAccessScope
from apps.core.roles import user_has_role


class ScopeAdminError(Exception):
    """Base class — the HTTP layer maps subclasses to status codes."""


class ScopeAdminForbidden(ScopeAdminError):
    """Actor is not an admin → HTTP 403 (design §6 row 17)."""


class ScopeGrantInvalid(ScopeAdminError):
    """Bad payload (missing reason, mismatched typed columns, date window)
    → HTTP 400 (design §6 row 20)."""


def _require_admin(actor) -> None:
    if actor is None or not getattr(actor, "is_authenticated", False):
        raise ScopeAdminForbidden("admin role required to change access scopes")
    if not user_has_role(actor, "admin"):
        raise ScopeAdminForbidden("admin role required to change access scopes")


def _require_reason(reason) -> str:
    text = (reason or "").strip()
    if not text:
        raise ScopeGrantInvalid("reason is required for every scope change")
    return text


def _validate_typed(scope_type, site, department) -> None:
    """Mirror the DB CHECK `scope_typed_columns` before save (400, not 500)."""
    typed = (
        (scope_type == UserAccessScope.ScopeType.GLOBAL and site is None and department is None)
        or (
            scope_type == UserAccessScope.ScopeType.SITE and site is not None and department is None
        )
        or (
            scope_type == UserAccessScope.ScopeType.DEPARTMENT
            and department is not None
            and site is None
        )
    )
    if scope_type not in UserAccessScope.ScopeType.values:
        raise ScopeGrantInvalid(f"unknown scope_type: {scope_type!r}")
    if not typed:
        raise ScopeGrantInvalid(
            f"scope_type {scope_type} needs exactly one of site/department and no other target"
        )


def grant_scope(
    *,
    actor,
    user,
    scope_type: str,
    reason: str,
    site=None,
    department=None,
    valid_from=None,
    valid_to=None,
) -> UserAccessScope:
    """Create one scope row for *user* and audit it (design §5.3)."""
    _require_admin(actor)
    reason = _require_reason(reason)
    _validate_typed(scope_type, site, department)

    scope = UserAccessScope(
        user=user,
        scope_type=scope_type,
        site=site,
        department=department,
        valid_from=valid_from,
        valid_to=valid_to,
        reason=reason,
        created_by=actor,
    )
    # date window + field-level rules; ValidationError → 400 for the caller
    try:
        scope.full_clean()
    except DjangoValidationError as exc:
        if hasattr(exc, "message_dict"):
            detail = "; ".join(
                f"{k}: {'; '.join(map(str, v))}" for k, v in exc.message_dict.items()
            )
        else:
            detail = "; ".join(map(str, exc.messages))
        raise ScopeGrantInvalid(detail or str(exc)) from exc
    scope.save()

    from apps.audit.models import ActivityLog

    ActivityLog.record(
        actor=actor,
        action="scope_grant",
        obj=scope,
        details={
            "target_user": user.username,
            "scope_type": scope.scope_type,
            "site": site.code if site is not None else None,
            "department": department.name if department is not None else None,
            "valid_from": scope.valid_from.isoformat() if scope.valid_from else None,
            "valid_to": scope.valid_to.isoformat() if scope.valid_to else None,
            "reason": reason,
        },
    )
    return scope


def revoke_scope(*, actor, scope: UserAccessScope) -> None:
    """Delete one scope row and audit it (design §5.3)."""
    _require_admin(actor)
    from apps.audit.models import ActivityLog

    details = {
        "target_user": scope.user.username,
        "scope_type": scope.scope_type,
        "site": scope.site.code if scope.site_id else None,
        "department": scope.department.name if scope.department_id else None,
        "reason": scope.reason,
        "scope_id": scope.pk,
    }
    object_repr = str(scope)
    scope.delete()
    # no `obj=` here: the row is gone, so the GFK would dangle
    ActivityLog.record(
        actor=actor,
        action="scope_revoke",
        object_repr=object_repr,
        details=details,
    )
