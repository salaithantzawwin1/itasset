"""Development settings — dev server, permissive defaults (never in prod, §19)."""

from .base import *  # noqa: F401,F403
from .base import env

DEBUG = True
SECRET_KEY = env("SECRET_KEY", default="dev-only-insecure-key")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])
