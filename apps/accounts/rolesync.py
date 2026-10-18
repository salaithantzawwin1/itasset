"""AD-group → Django-role sync (DEVELOPMENT.md §11, M5).

Pure logic, no `django_auth_ldap` import — `python-ldap` needs OS build tools
and is only installed on the deploy target (Ubuntu, §19). The backend glue
lives in `apps/accounts/ldap.py` and is imported only when `LDAP_ENABLED=1`.
"""

import logging

log = logging.getLogger(__name__)


def role_map(settings) -> dict[str, str]:
    """AD group CN (lowercased) → Django role group name (§11 table)."""
    return {
        settings.LDAP_GROUP_ADMIN.lower(): "admin",
        settings.LDAP_GROUP_TECHNICIAN.lower(): "technician",
        settings.LDAP_GROUP_AUDITOR.lower(): "auditor",
        settings.LDAP_GROUP_VIEWER.lower(): "viewer",
    }


def wanted_roles(ad_groups: set[str], settings) -> set[str]:
    """Map AD group CNs → Django roles; unmapped users get `viewer` (§11)."""
    mapping = role_map(settings)
    return {role for cn, role in mapping.items() if cn.lower() in ad_groups} or {"viewer"}


def sync_role_groups(user, group_names) -> set[str]:
    """Replace the user's role groups to mirror AD membership.

    Returns the roles the user was synced into. Never raises — an LDAP/AD
    hiccup must not block an otherwise successful login (§11 fallback).
    """
    from django.conf import settings
    from django.contrib.auth.models import Group

    try:
        roles = wanted_roles({g.lower() for g in group_names}, settings)
        user.groups.set(Group.objects.filter(name__in=roles))
        log.info("user %s synced to groups: %s", user.username, sorted(roles))
        return roles
    except Exception:  # pragma: no cover - defensive
        log.exception("role sync failed for %s", getattr(user, "username", "?"))
        return set()
