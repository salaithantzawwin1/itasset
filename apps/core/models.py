"""Scope-based RBAC records (ITAM_Scope_RBAC_Design_v1.0 §4).

Role = what actions (Django groups, apps.core.roles); scope = which records
(this model). Stage A records scopes only — enforcement lands in Stage B/C.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class UserAccessScope(models.Model):
    """Which records a user may act on (Spec A §5.2, §9.1).

    Deny by default: a user with no active rows has no access beyond the
    employee self-view (design §4.4). Exactly one typed column is populated
    and must match scope_type — enforced by a DB CHECK, not just the app.
    """

    class ScopeType(models.TextChoices):
        GLOBAL = "GLOBAL", "All records"  # full visibility (policy-approved)
        SITE = "SITE", "Site"  # people.Site
        DEPARTMENT = "DEPARTMENT", "Department"  # people.Department

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_scopes"
    )
    scope_type = models.CharField(max_length=12, choices=ScopeType.choices)
    site = models.ForeignKey(
        "people.Site", null=True, blank=True, on_delete=models.CASCADE, related_name="user_scopes"
    )
    department = models.ForeignKey(
        "people.Department",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="user_scopes",
    )
    valid_from = models.DateField(null=True, blank=True)  # NULL = open start
    valid_to = models.DateField(null=True, blank=True)  # NULL = open end
    reason = models.CharField(max_length=255)  # required: why granted (§5.3)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="scopes_granted",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["user__username", "scope_type"]
        verbose_name = "user access scope"
        verbose_name_plural = "user access scopes"
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(scope_type="SITE", site__isnull=False, department__isnull=True)
                    | Q(scope_type="DEPARTMENT", department__isnull=False, site__isnull=True)
                    | Q(scope_type="GLOBAL", site__isnull=True, department__isnull=True)
                ),
                name="scope_typed_columns",
            ),
        ]
        indexes = [models.Index(fields=["user", "scope_type"])]

    def clean(self):
        super().clean()
        if self.valid_from and self.valid_to and self.valid_to < self.valid_from:
            raise ValidationError({"valid_to": "valid_to must be on or after valid_from."})

    @property
    def is_active(self) -> bool:
        """True when 'today' falls inside the validity window."""
        from datetime import date

        today = date.today()
        if self.valid_from and today < self.valid_from:
            return False
        if self.valid_to and today > self.valid_to:
            return False
        return True

    def __str__(self) -> str:
        if self.scope_type == self.ScopeType.SITE:
            target = str(self.site) if self.site_id else "(no site)"
        elif self.scope_type == self.ScopeType.DEPARTMENT:
            target = str(self.department) if self.department_id else "(no department)"
        else:
            target = "all records"
        return f"{self.user} → {target}"


class IdempotencyRecord(models.Model):
    """Stored response for a replayed write (Spec A §10.1; gap §3.5).

    A client that retries a mutation may send an `Idempotency-Key` header.
    The first request with a given (user, key) runs and its response (status
    < 500) is stored here; a replay returns that stored response with
    `Idempotency-Replayed: true` and never reaches the view again. The same
    key with a different payload/path, or a duplicate that arrives while the
    original is still running, answers 409. Rows are pruned after 7 days by
    the middleware (opportunistic delete — no extra cron task).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="idempotency_records"
    )
    key = models.CharField(max_length=255)
    method = models.CharField(max_length=10)
    path = models.CharField(max_length=500)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveIntegerField(null=True, blank=True)  # NULL = still running
    response_body = models.TextField(blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "idempotency record"
        verbose_name_plural = "idempotency records"
        constraints = [
            models.UniqueConstraint(fields=["user", "key"], name="idempotency_user_key_unique"),
        ]
        indexes = [models.Index(fields=["created_at"])]

    def __str__(self) -> str:
        state = str(self.status_code) if self.status_code is not None else "in progress"
        return f"{self.method} {self.path} [{self.key}] → {state}"
