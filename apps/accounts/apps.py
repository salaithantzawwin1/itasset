from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"
    verbose_name = "Accounts & roles"

    def ready(self):  # pragma: no cover - wiring
        from . import (
            loginaudit,  # noqa: F401  (login audit + break-glass alert, §11.2)
            personlink,  # noqa: F401  (connects user_logged_in, §4.4)
        )
