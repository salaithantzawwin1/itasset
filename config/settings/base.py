"""Base settings — all values come from the environment (DEVELOPMENT.md §5)."""

from pathlib import Path

import dj_database_url
import environ

BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / ".env"
if env_file.exists():
    environ.Env.read_env(env_file)

SECRET_KEY = env("SECRET_KEY", default="")
DEBUG = env.bool("DEBUG", default=False)
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=[])

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "drf_spectacular",
    "apps.core",
    "apps.people",
    "apps.accounts",
    "apps.audit",
    "apps.labels",
    "apps.vendors",
    "apps.licenses",
    "apps.api",
    "apps.assets",
    "apps.attachments",
    "apps.reports",
    "apps.dashboard",
]

MIDDLEWARE = [
    # correlation id first (outermost): every response — including 429/5xx —
    # carries X-Correlation-ID, and error envelopes can join to server logs
    "apps.core.middleware.CorrelationMiddleware",
    # security hardening first (Spec A §11.3): CSP on HTML, credential throttle
    "apps.core.middleware.SecurityHeadersMiddleware",
    "apps.core.middleware.LoginThrottleMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    # Django's own translations (admin chrome, form errors) follow the same
    # ENG/MM session switch as the app's {% t %} strings — one language per page.
    "apps.core.middleware.SessionLocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # deactivated accounts lose their session on the next request (§3.6)
    "apps.core.middleware.ActiveUserMiddleware",
    # idempotent /api/v1 writes (Spec A §10.1) — needs request.user from auth
    "apps.core.middleware.IdempotencyMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# --- Security hardening (Spec A §11.3, gap §3.5/§3.6) ----------------------
# CSP + brute-force throttling are enforced by apps/core/middleware.py; these
# tune them (env-overridable). The rest are Django's own switches.
LOGIN_THROTTLE_ATTEMPTS = env.int("LOGIN_THROTTLE_ATTEMPTS", default=10)
LOGIN_THROTTLE_WINDOW = env.int("LOGIN_THROTTLE_WINDOW", default=300)
SECURE_CONTENT_TYPE_NOSNIFF = True  # X-Content-Type-Options: nosniff
SECURE_REFERRER_POLICY = "same-origin"

# OpenAPI (drf-spectacular): the schema enumerates every endpoint, so it is
# admin-only — the stock `AllowAny` served it anonymously (found 2026-10-16).
SPECTACULAR_SETTINGS = {
    "TITLE": "IT Asset Manager API",
    "DESCRIPTION": "Scope-checked IT asset API (Spec A §10).",
    "VERSION": "1.0.0",
    "SERVE_PUBLIC": False,
    "SERVE_PERMISSIONS": ["apps.api.permissions.IsAdmin"],
}

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"

DATABASES = {
    "default": dj_database_url.config(
        default="postgresql://itasset:itasset@127.0.0.1:5432/itasset",
        conn_max_age=600,
    )
}

CELERY_BROKER_URL = env("REDIS_URL", default="redis://127.0.0.1:6379/0")
CELERY_TIMEZONE = "Asia/Yangon"  # beat schedules in Yangon time (§15: daily 07:00)

# Cache — dev/tests run on local memory (no services needed for the suite).
# The login throttle (§11.3) needs counters shared by every gunicorn worker,
# so prod.py re-points CACHE_URL at Redis; the middleware fails open if the
# backend is unreachable (a cache outage must not lock people out of login).
CACHES = {"default": env.cache_url("CACHE_URL", default="locmemcache://")}

# Email (§14 notification matrix) — SMTP via env; console backend in dev.
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="itasset@localhost")
# §14 recipients (roles beyond "holder" which comes from the assignment)
IT_LEAD_EMAIL = env("IT_LEAD_EMAIL", default="")
PROCUREMENT_EMAIL = env("PROCUREMENT_EMAIL", default="")
ADMIN_EMAIL = env("ADMIN_EMAIL", default="")  # §14 daily digest recipients (falls back to IT lead)

# §15 Celery beat schedule (Asia/Yangon)
from celery.schedules import crontab  # noqa: E402

CELERY_BEAT_SCHEDULE = {
    "scan-warranties": {"task": "scan_warranties", "schedule": crontab(hour=7, minute=0)},
    "scan-license-seats": {"task": "scan_license_seats", "schedule": crontab(hour=7, minute=5)},
    "scan-contracts": {"task": "scan_contracts", "schedule": crontab(hour=7, minute=10)},
    # §14: loans due + 3 days → holder + issuing technician
    "scan-loans": {"task": "scan_loans", "schedule": crontab(hour=7, minute=15)},
    "purge-activity-log": {
        "task": "purge_activity_log",
        "schedule": crontab(hour=2, minute=0, day_of_month=1),
    },
    # §14: data-quality issues → IT lead, monthly on the 1st
    "data-quality-report": {
        "task": "data_quality_report",
        "schedule": crontab(hour=7, minute=0, day_of_month=1),
    },
    # §14: daily activity digest → admins at 08:00
    "send-daily-digest": {"task": "send_daily_digest", "schedule": crontab(hour=8, minute=0)},
    # §4 scheduled reports: weekly Mon 07:30 + monthly 1st 08:00
    "send-scheduled-reports-weekly": {
        "task": "send_scheduled_reports",
        "schedule": crontab(hour=7, minute=30, day_of_week="mon"),
        "kwargs": {"cadence": "weekly"},
    },
    "send-scheduled-reports-monthly": {
        "task": "send_scheduled_reports",
        "schedule": crontab(hour=8, minute=0, day_of_month=1),
        "kwargs": {"cadence": "monthly"},
    },
}

LOGIN_REDIRECT_URL = "/"  # after sign-in, go to the dashboard home
LOGOUT_REDIRECT_URL = "/"

# --- LDAP / AD login (§11, M5) ---------------------------------------------
# Off by default (dev); enable with LDAP_ENABLED=1. When on, the role-mapping
# LDAP backend is primary and ModelBackend stays as break-glass fallback.
LDAP_ENABLED = env.bool("LDAP_ENABLED", default=False)
LDAP_SERVER_URI = env("LDAP_SERVER_URI", default="ldap://ad.example.com")
LDAP_BIND_DN = env("LDAP_BIND_DN", default="")
LDAP_BIND_PASSWORD = env("LDAP_BIND_PASSWORD", default="")
LDAP_USER_SEARCH_BASE = env("LDAP_USER_SEARCH_BASE", default="ou=staff,dc=example,dc=com")
LDAP_USER_FILTER = env("LDAP_USER_FILTER", default="(sAMAccountName=%(user)s)")
LDAP_GROUP_SEARCH_BASE = env("LDAP_GROUP_SEARCH_BASE", default="ou=groups,dc=example,dc=com")
LDAP_START_TLS = env.bool("LDAP_START_TLS", default=True)
LDAP_NESTED_GROUPS = env.bool("LDAP_NESTED_GROUPS", default=True)
# AD group CNs → Django roles (§11 table)
LDAP_GROUP_ADMIN = env("LDAP_GROUP_ADMIN", default="IT-Admins")
LDAP_GROUP_TECHNICIAN = env("LDAP_GROUP_TECHNICIAN", default="IT-Technicians")
LDAP_GROUP_AUDITOR = env("LDAP_GROUP_AUDITOR", default="IT-Auditors")
LDAP_GROUP_VIEWER = env("LDAP_GROUP_VIEWER", default="IT-Users")

# --- Scope-based RBAC (ITAM_Scope_RBAC_Design_v1.0 §5.4) --------------------
# Stage A records scopes but does not enforce them. Stage B (shadow logging)
# and Stage C (enforcement) flip this to True; tests force True so regressions
# fail CI. Deny-by-default helpers live in apps.core.scopes.
SCOPE_ENFORCEMENT_ENABLED = env.bool("SCOPE_ENFORCEMENT_ENABLED", default=False)

AUTHENTICATION_BACKENDS = ["django.contrib.auth.backends.ModelBackend"]
if LDAP_ENABLED:
    # imported lazily so dev (LDAP off) never needs django_auth_ldap configured
    AUTHENTICATION_BACKENDS.insert(0, "apps.accounts.ldap.RoleMappingLDAPBackend")
    from django_auth_ldap import config as _ldap_config  # noqa: E402

    AUTH_LDAP_SERVER_URI = LDAP_SERVER_URI
    AUTH_LDAP_BIND_DN = LDAP_BIND_DN
    AUTH_LDAP_BIND_PASSWORD = LDAP_BIND_PASSWORD
    AUTH_LDAP_USER_SEARCH = _ldap_config.LDAPSearch(
        LDAP_USER_SEARCH_BASE, _ldap_config.SEARCH_SCOPE_SUBTREE, LDAP_USER_FILTER
    )
    AUTH_LDAP_GROUP_SEARCH = _ldap_config.LDAPSearch(
        LDAP_GROUP_SEARCH_BASE, _ldap_config.SEARCH_SCOPE_SUBTREE, "(objectClass=group)"
    )
    AUTH_LDAP_GROUP_TYPE = (
        _ldap_config.NestedActiveDirectoryGroupType()
        if LDAP_NESTED_GROUPS
        else _ldap_config.ActiveDirectoryGroupType()
    )
    AUTH_LDAP_MIRROR_GROUPS = True
    AUTH_LDAP_ALWAYS_UPDATE_USER = True
    AUTH_LDAP_START_TLS = LDAP_START_TLS

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "my"  # Burmese default (§8 i18n)
TIME_ZONE = "Asia/Yangon"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"
# Private uploads (attachments, Spec A §6.13): NOT under MEDIA_ROOT, so no web
# server can expose them — downloads only go through the authorizing view.
PRIVATE_MEDIA_ROOT = env("PRIVATE_MEDIA_ROOT", default=str(BASE_DIR / "private_attachments"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_AUTHENTICATION_CLASSES": [
        # token first so unauthenticated requests get 401 + WWW-Authenticate (§10/§16)
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.PageNumberPagination",
    "PAGE_SIZE": 100,
    # error envelope (Spec A §10.9, gap §3.5): adds `code` + `correlationId`
    # to detail-style errors; `detail` stays exactly where clients expect it
    "EXCEPTION_HANDLER": "apps.api.exceptions.api_exception_handler",
}
