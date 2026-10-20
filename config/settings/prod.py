"""Production settings — strict, no defaults for secrets (DEVELOPMENT.md §22).

Interim LAN deployment (§24 phase 1): HTTP only inside the office LAN, behind
nginx on 127.0.0.1:8001. TLS terminates later (M8); SSL flags are env-driven so
they can be flipped without a code change.
"""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")  # no default: missing key must fail loudly
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS")

# --- TLS hardening (flipped on when certs exist; §22) -------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=False)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=0)  # 0 until TLS
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
# SAMEORIGIN (not DENY): the create-in-modal dialog frames our own add forms
# in a same-origin <iframe> (templates/partials/modal.html). CSP
# frame-ancestors 'self' already matches; cross-site framing stays blocked.
X_FRAME_OPTIONS = "SAMEORIGIN"

# Shared cache (gap §3.6): gunicorn runs 2×CPU+1 workers — LocMem would
# multiply the login-throttle budget by the worker count. Redis is already
# this host's broker (Celery); LoginThrottleMiddleware fails open if it is
# down, so a Redis outage degrades the cap instead of breaking login.
CACHES = {"default": env.cache_url("CACHE_URL", default="redis://127.0.0.1:6379/1")}
