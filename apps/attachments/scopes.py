"""Scope authorization for attachments — design §5.2 (Spec A §6.13).

An attachment is visible exactly when its owning record is: assets and
requests follow their site; transfers follow either end (v1 union rule,
confirmed by the business 2026-10-16). Deny by default, fail closed, and the
§4.4 self-view carve-out carries over to attachments of an employee's own
currently-assigned assets.
"""

from __future__ import annotations

import logging

from django.db.models import Q, QuerySet

from apps.core.scopes import (
    OutOfScope,
    effective_scopes,
    enforcement_enabled,
    record_shadow,
    self_view_q,
)

logger = logging.getLogger(__name__)

DENY_ALL = Q(pk__in=[])


def attachment_scope_q(user) -> Q:
    """Q filter matching the attachments the caller may see (never None)."""
    from apps.assets.models import Asset

    try:
        scopes = effective_scopes(user)
    except Exception:
        logger.exception("scope resolution failed; denying attachments")
        return DENY_ALL
    if scopes.global_access:
        return Q()
    if scopes.sites:
        sites = scopes.sites
        return (
            Q(asset__site_id__in=sites)
            | Q(request__site_id__in=sites)
            | Q(transfer__from_site_id__in=sites)
            | Q(transfer__to_site_id__in=sites)
        )
    # §4.4 self-view: attachments of assets currently held by the employee
    own = self_view_q(user, Asset)
    if own is not None:
        return Q(asset__in=Asset.objects.filter(own))
    return DENY_ALL


def scope_attachments(user, qs: QuerySet, *, action: str = "attachment_list", path: str = ""):
    """Flag-aware list filter (design §5.2): enforced → scoped; shadow →
    unchanged list plus one would-hide event for the Stage B review loop."""
    filtered = qs.filter(attachment_scope_q(user))
    if enforcement_enabled():
        return filtered
    try:
        total, kept = qs.count(), filtered.count()
    except Exception:
        logger.exception("shadow attachment count failed; leaving list unchanged")
        return qs
    if kept < total:
        record_shadow(user, action=action, path=path, details={"would_hide": total - kept})
    return qs


def check_attachment_scope(
    user, attachment, *, action: str = "attachment_download", path: str = ""
):
    """Raise OutOfScope unless the caller may see *attachment* (404 at the edge).

    Out-of-scope must look identical to nonexistent — Spec A §10.1.
    """
    from .models import Attachment

    try:
        allowed = Attachment.objects.filter(attachment_scope_q(user), pk=attachment.pk).exists()
    except Exception:
        logger.exception("attachment scope check failed; denying")
        allowed = False
    if allowed:
        return
    if enforcement_enabled():
        raise OutOfScope(f"attachment {attachment.pk} is outside the caller's scope")
    record_shadow(user, action=action, path=path, obj=attachment)
