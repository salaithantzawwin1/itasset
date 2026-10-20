"""Security headers + credential throttling (Spec A §11.3; gap §3.5, §3.6).

Both concerns must apply to *every* view — HTML, API and Django admin — so
they live in middleware instead of being repeated per view.
"""

import hashlib
import json
import logging
import re
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import IntegrityError
from django.http import HttpResponse
from django.utils import timezone, translation

log = logging.getLogger(__name__)


class SessionLocaleMiddleware:
    """Django's own translations follow the app's ENG/MM switch.

    The UI strings come from ``{% t %}`` (session key ``lang``, English when
    unset), but Django's admin chrome used to follow ``LANGUAGE_CODE``
    (Burmese) — so a page mixed Burmese headings with English content. This
    activates gettext from the same session key, defaulting to English like
    the rest of the app. Django's stock LocaleMiddleware resolves from cookie/
    Accept-Language instead, and its translation hook is module-level (not an
    overridable method), so this is a deliberately small standalone middleware.

    Must sit directly after ``SessionMiddleware``.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        lang = (getattr(request, "session", None) or {}).get("lang")
        if lang not in ("en", "my"):
            lang = "en"
        translation.activate(lang)
        request.LANGUAGE_CODE = lang
        response = self.get_response(request)
        response.headers.setdefault("Content-Language", lang)
        return response


class CorrelationMiddleware:
    """Echo or mint a correlation id on every response (Spec A §10.1, §3.5).

    Clients may send `X-Correlation-ID`; each response carries one (minted
    uuid4 hex when absent). The client value is untrusted input that becomes
    a response header, so it is stripped to [A-Za-z0-9_.-] and capped at 64
    chars. API error bodies pick the same id up from `request.correlation_id`
    (apps.api.exceptions), so a user-reported id locates the server log.
    """

    SAFE = re.compile(r"[^A-Za-z0-9_.-]")

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = (request.headers.get("X-Correlation-ID") or "").strip()
        correlation_id = self.SAFE.sub("", incoming)[:64] or uuid.uuid4().hex
        request.correlation_id = correlation_id  # plain attr: works on every Django version
        response = self.get_response(request)
        response["X-Correlation-ID"] = correlation_id
        return response


class ActiveUserMiddleware:
    """Orphaned-session cleanup for deactivated accounts (§11.1, gap §3.6).

    The *authorization* half of revocation needs no code here: Django's
    ModelBackend already refuses inactive users at authentication time, so
    the very next request is anonymous (API → 401, HTML → login redirect) —
    the revocation window is effectively zero, and DRF's token auth refuses
    inactive users the same way. What stays is hygiene: the session row the
    account left behind would linger until expiry. When the session claims an
    identity that the backend refused (account deactivated *or* deleted),
    flush it so the cookie dies too. Zero cost on the happy path — the
    session check is a dict lookup and `request.user` is already loaded.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.contrib.auth import SESSION_KEY

        session = getattr(request, "session", None)
        user = getattr(request, "user", None)
        if (
            session is not None
            and SESSION_KEY in session
            and user is not None
            and not user.is_authenticated
        ):
            session.flush()  # delete the server-side row; the cookie dies too
        return self.get_response(request)


# Pragmatic CSP baseline: no external origins at all (admin, swagger, static
# and the QR labels are all same-origin), no cross-site framing, no plugins.
# `unsafe-inline` for scripts/styles is still required by the Django admin
# and this project's templates — dropping it would break the admin, so this
# is the hardening floor, not a full nonce-based policy.
CSP = (
    "default-src 'self'; base-uri 'self'; object-src 'none'; "
    "frame-ancestors 'self'; form-action 'self'; img-src 'self' data:; "
    "font-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; connect-src 'self'"
)

# Paths that accept credentials (Spec A §11.3 brute-force controls).
LOGIN_PATHS = ("/accounts/login/", "/admin/login/")
TOKEN_PATH = "/api/v1/auth/token/"


def client_ip(request) -> str:
    """First hop of X-Forwarded-For (set by our nginx) or the socket peer.

    gunicorn binds 127.0.0.1 only, so a spoofed XFF can only come from a
    local process — good enough for a throttle key.
    """
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return request.META.get("REMOTE_ADDR", "unknown")


class SecurityHeadersMiddleware:
    """Content-Security-Policy on HTML responses (Spec A §11.3).

    `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and
    `Cross-Origin-Opener-Policy` come from Django's own settings/middleware
    (SECURE_CONTENT_TYPE_NOSNIFF, XFrameOptionsMiddleware) — only the CSP
    header has no Django built-in, hence this wrapper.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if str(response.get("Content-Type", "")).startswith("text/html"):
            response.headers.setdefault("Content-Security-Policy", CSP)
        return response


class LoginThrottleMiddleware:
    """Per-IP cap on *failed* credential POSTs (Spec A §11.3).

    Covers `/accounts/login/`, `/admin/login/` and `/api/v1/auth/token/`
    uniformly. Only failures count (form re-render → 200, token → 401), so a
    successful login clears the counter; over the limit → **429** with
    `Retry-After`. Tunable via `LOGIN_THROTTLE_ATTEMPTS` / `LOGIN_THROTTLE_WINDOW`.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _is_credential_post(request) -> bool:
        if request.method != "POST":
            return False
        path = request.path
        return path in LOGIN_PATHS or path == TOKEN_PATH

    @staticmethod
    def _failed(request, response) -> bool:
        if request.path == TOKEN_PATH:
            return response.status_code in (400, 401)
        # Django re-renders the form (200) when credentials are rejected;
        # success is a 302 redirect, CSRF failure a 400 (not counted, so a
        # token-less flood cannot exhaust someone else's budget).
        return response.status_code == 200

    def __call__(self, request):
        if not self._is_credential_post(request):
            return self.get_response(request)

        limit = int(getattr(settings, "LOGIN_THROTTLE_ATTEMPTS", 10))
        window = int(getattr(settings, "LOGIN_THROTTLE_WINDOW", 300))
        key = f"login-throttle:{client_ip(request)}:{request.path}"

        # The throttle is best-effort: if the cache backend is unreachable
        # (Redis outage in prod), fail *open* — login stays available and only
        # the cap degrades. Never let a cache error 500 a credential POST.
        try:
            blocked = cache.get(key, 0) >= limit
        except Exception:  # pragma: no cover - depends on backend outage
            log.warning("login throttle: cache unavailable, failing open", exc_info=True)
            blocked = False

        if blocked:
            return HttpResponse(
                "Too many login attempts. Please wait and try again.",
                status=429,
                content_type="text/plain",
                headers={"Retry-After": str(window)},
            )

        response = self.get_response(request)
        try:
            if self._failed(request, response):
                cache.add(key, 0, timeout=window)  # first failure starts the window
                try:
                    cache.incr(key)
                except ValueError:  # pragma: no cover - key evicted mid-request
                    cache.set(key, 1, timeout=window)
            else:
                cache.delete(key)  # success clears the slate
        except Exception:  # pragma: no cover - depends on backend outage
            log.warning("login throttle: could not update counter", exc_info=True)
        return response


# ---------------------------------------------------------------------------
# Idempotency (Spec A §10.1, gap §3.5): replay-safe writes.

IDEMPOTENCY_HEADER = "Idempotency-Key"
IDEMPOTENCY_RETENTION_DAYS = 7
IDEMPOTENCY_MAX_BODY = 1_000_000  # hash/store cap — big uploads skip the feature


class IdempotencyMiddleware:
    """Replay-safe writes for clients that send `Idempotency-Key` (§10.1).

    Opt-in per request — no header means untouched behaviour. Scope is
    (user, key): the first request with a key runs and its response (status
    < 500) is stored; a replay returns that stored response with
    `Idempotency-Replayed: true` and executes nothing a second time. Replays
    carry no side effects, so returning before the view (and CSRF check) is
    safe: an attacker-triggered replay can only echo the caller's own stored
    response. Misuse answers **409**: the same key with a different payload,
    path or method, or a duplicate arriving while the original still runs.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    @staticmethod
    def _request_user(request):
        """Identity at middleware time.

        Session users arrive via AuthenticationMiddleware; DRF Token clients
        (the scanner, curl scripts) authenticate lazily *inside* the view, so
        a present `Authorization: Token …` header is resolved here too —
        otherwise idempotency would silently skip the API's main clients.
        """
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            return user
        if request.META.get("HTTP_AUTHORIZATION", "").startswith("Token "):
            from rest_framework.authentication import TokenAuthentication

            try:
                authenticated = TokenAuthentication().authenticate(request)
            except Exception:  # bad/expired token → the view answers 401
                return None
            if authenticated:
                request.user = authenticated[0]  # same identity for the view
                return request.user
        return None

    @staticmethod
    def _eligible(request) -> bool:
        if request.method not in ("POST", "PATCH", "PUT", "DELETE"):
            return False
        return request.path.startswith("/api/v1/")

    @staticmethod
    def _conflict(message: str) -> HttpResponse:
        return HttpResponse(
            json.dumps({"detail": message, "status": 409}),
            status=409,
            content_type="application/json",
        )

    def __call__(self, request):
        from apps.core.models import IdempotencyRecord

        if not self._eligible(request):
            return self.get_response(request)

        key = (request.headers.get(IDEMPOTENCY_HEADER) or "").strip()
        if not key or len(key) > 255:
            return self.get_response(request)

        user = self._request_user(request)
        if user is None:
            return self.get_response(request)  # anonymous → let the view 401

        # attachment uploads etc. — bodies over the cap bypass the feature
        if int(request.META.get("CONTENT_LENGTH") or 0) > IDEMPOTENCY_MAX_BODY:
            return self.get_response(request)

        body = request.body or b""  # Django caches it, so the view re-reads fine
        digest = hashlib.sha256(f"{request.method}:{request.path}:".encode() + body).hexdigest()

        try:
            record, created = IdempotencyRecord.objects.get_or_create(
                user=user,
                key=key,
                defaults={
                    "method": request.method,
                    "path": request.path,
                    "request_hash": digest,
                },
            )
        except IntegrityError:
            # lost the creation race → the twin request is still running
            return self._conflict("an identical request is already in progress")

        if not created:
            if (
                record.request_hash != digest
                or record.method != request.method
                or record.path != request.path
            ):
                return self._conflict("Idempotency-Key was reused with a different request")
            if record.status_code is None:
                return self._conflict("an identical request is still in progress")
            return HttpResponse(
                record.response_body,
                status=record.status_code,
                content_type=record.content_type or "application/json",
                headers={"Idempotency-Replayed": "true"},
            )

        response = self.get_response(request)

        if response.status_code >= 500 or getattr(response, "streaming", False):
            # server fault / streaming body: let the client retry safely
            record.delete()
            return response

        if len(response.content) > IDEMPOTENCY_MAX_BODY:  # too big to replay
            record.delete()
            return response

        record.status_code = response.status_code
        record.response_body = response.content.decode("utf-8", "replace")
        record.content_type = response.get("Content-Type", "")
        record.save(update_fields=["status_code", "response_body", "content_type"])

        # opportunistic prune — keeps the table small without another cron task
        IdempotencyRecord.objects.filter(
            created_at__lt=timezone.now() - timedelta(days=IDEMPOTENCY_RETENTION_DAYS)
        ).delete()
        return response
