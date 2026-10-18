"""Role-mapping LDAP backend (DEVELOPMENT.md §11, M5).

Only imported when `LDAP_ENABLED=1` (base.py inserts it into
AUTHENTICATION_BACKENDS). The local ModelBackend always stays second so the
break-glass superuser works even if the AD is down (§11 fallback).

The mapping logic itself is in `rolesync.py` (importable without python-ldap).
"""

import logging

from django_auth_ldap.backend import LDAPBackend

from .rolesync import sync_role_groups

log = logging.getLogger(__name__)


class RoleMappingLDAPBackend(LDAPBackend):
    """LDAPBackend + AD-group → Django-role sync (§11)."""

    def authenticate(self, username=None, password=None, **kwargs):
        user = super().authenticate(username=username, password=password, **kwargs)
        if user is not None:
            try:
                sync_role_groups(user, user.ldap_user.group_names)
            except Exception:  # pragma: no cover - group lookup hiccup
                log.exception("LDAP group lookup failed for %s", username)
        return user
