"""Login audit + break-glass alerting (Spec A §11.2 #5–6, §9.1; gap §3.6).

Every login success and failure writes an `ActivityLog` event. When LDAP is
the normal path, a login that falls back to the **local** backend is a
break-glass event and additionally emails the IT lead — §11.2 requires
break-glass access to be auditable and alerted. Passwords are never logged,
only the username that was presented.

Wired from `AccountsConfig.ready()` (same pattern as `personlink`).
"""

import logging
import time

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY
from django.contrib.auth.signals import user_logged_in, user_login_failed
from django.utils import timezone

log = logging.getLogger(__name__)

LOCAL_BACKEND = "django.contrib.auth.backends.ModelBackend"


def _ip(request) -> str:
    from apps.core.middleware import client_ip

    try:
        return client_ip(request) if request is not None else "unknown"
    except Exception:  # pragma: no cover - never block a login
        return "unknown"


def on_login(sender, request, user, **kwargs):
    """Audit the login; alert when it was a break-glass (local) sign-in."""
    from apps.audit.models import ActivityLog

    backend = ""
    try:
        backend = request.session.get(BACKEND_SESSION_KEY, "") if request else ""
    except Exception:  # pragma: no cover - defensive
        backend = ""

    ActivityLog.record(
        actor=user,
        action="login",
        object_repr=f"{user.username} signed in",
        details={"backend": backend, "ip": _ip(request), "path": getattr(request, "path", "")},
    )

    is_local = backend.endswith("ModelBackend")
    if is_local and getattr(settings, "LDAP_ENABLED", False):
        # LDAP is the normal path → the local backend is break-glass (§11.2)
        _alert_breakglass(user, request)


def _alert_breakglass(user, request) -> None:
    from apps.audit.notify import send_alert

    try:
        send_alert(
            kind="breakglass",
            # time-stamped: every break-glass login must alert, not just the first
            dedupe_key=f"breakglass_login:{user.pk}:{int(time.time())}",
            template="breakglass_login",
            context={
                "username": user.username,
                "ip": _ip(request),
                "when": timezone.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            subject="Break-glass login — local backend used",
        )
    except Exception:  # pragma: no cover - alerting must never block login
        log.exception("break-glass login alert failed for %s", user.username)


def on_login_failed(sender, credentials, request=None, **kwargs):
    """Audit rejected credentials — username only, never the password."""
    from apps.audit.models import ActivityLog

    username = str((credentials or {}).get("username", ""))[:150]
    ActivityLog.record(
        actor=None,
        action="login_failed",
        object_repr=f"login failed: {username or '(blank)'}",
        details={"username": username, "ip": _ip(request)},
    )


# dispatch_uids keep double-connects impossible (ready() may run twice in tests)
user_logged_in.connect(on_login, dispatch_uid="accounts.login_audit")
user_login_failed.connect(on_login_failed, dispatch_uid="accounts.login_failed_audit")
