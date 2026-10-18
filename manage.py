#!/usr/bin/env python3
"""Django management entrypoint. Settings module picked by DJANGO_ENV (dev default)."""

import os
from pathlib import Path

from django.core.management import execute_from_command_line


def _settings_module() -> str:
    if os.environ.get("DJANGO_SETTINGS_MODULE"):
        return os.environ["DJANGO_SETTINGS_MODULE"]
    env = os.environ.get("DJANGO_ENV", "dev")
    env_file = Path(__file__).resolve().parent / ".env"
    if env_file.exists():  # allow DJANGO_ENV from .env
        for line in env_file.read_text().splitlines():
            if line.startswith("DJANGO_ENV="):
                env = line.split("=", 1)[1].strip() or env
    return f"config.settings.{env}"


if __name__ == "__main__":
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", _settings_module())
    execute_from_command_line(os.sys.argv)
