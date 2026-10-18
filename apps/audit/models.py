"""ActivityLog — who changed what, when (DEVELOPMENT.md §9 audit trail, §13, §25).

- Generic target (any model) via ContentType; `object_repr` keeps a human label
  even after the target row is gone.
- `details` JSON carries context: CSV import file hash, before/after values,
  transfer ids, etc. (§13: "Every import writes an ActivityLog entry with file hash").
- Retention: 24 months, purged by the monthly `purge_activity_log` task (§15/§25).
"""

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class ActivityLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="activities",
    )
    action = models.CharField(max_length=40, db_index=True)  # e.g. check_out, import, dispose
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField(null=True, blank=True)
    content_object = GenericForeignKey("content_type", "object_id")
    object_repr = models.CharField(max_length=200, blank=True)
    details = models.JSONField(default=dict, blank=True)  # free-form context
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["content_type", "object_id"])]
        verbose_name = "activity log entry"

    def __str__(self) -> str:
        who = self.actor.username if self.actor else "system"
        when = f"{self.created_at:%Y-%m-%d %H:%M}"
        return f"{self.action} by {who} on {self.object_repr or '—'} ({when})"

    @classmethod
    def record(
        cls,
        *,
        actor=None,
        action: str,
        obj=None,
        object_repr: str = "",
        details: dict | None = None,
    ):
        """Write one audit row. Never raises — audit must not break the operation."""
        try:
            ct = oid = None
            repr_ = object_repr
            if obj is not None:
                ct = ContentType.objects.get_for_model(obj, for_concrete_model=False)
                oid = obj.pk
                repr_ = object_repr or str(obj)[:200]
            return cls.objects.create(
                actor=actor if getattr(actor, "is_authenticated", False) else None,
                action=action,
                content_type=ct,
                object_id=oid,
                object_repr=repr_[:200],
                details=details or {},
            )
        except Exception:  # pragma: no cover - audit must never break the caller
            import logging

            logging.getLogger(__name__).exception("ActivityLog.record failed (action=%s)", action)
            return None


class EmailAlert(models.Model):
    """Sent-alert ledger (§14: "a last_sent_at row prevents duplicate emails").

    One row per (kind, dedupe_key); `dedupe_key` identifies the alert bucket,
    e.g. "warranty:{asset_id}:{90|30|7}" or "contract:{id}:{60|14}". The row is
    created before sending (see notify.send_alert) so a crash cannot double-send.
    """

    kind = models.CharField(max_length=40, db_index=True)
    dedupe_key = models.CharField(max_length=200, unique=True)
    recipients = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)  # set once delivery succeeded

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "email alert"

    def __str__(self) -> str:
        return f"{self.kind}: {self.dedupe_key}"


class AuditSession(models.Model):
    """Physical count session (§3 audit mode, §11 auditor, §25 audit readiness).

    A technician/auditor opens a session for a site, scans asset tags, and
    closes it — the report lists found / missing / unexpected. Count results
    feed the §4 "Audit results" export.
    """

    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    site = models.ForeignKey("people.Site", on_delete=models.PROTECT, related_name="audit_sessions")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.OPEN)
    started_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_sessions_started",
    )
    started_at = models.DateTimeField(auto_now_add=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        verbose_name = "audit session"

    def __str__(self) -> str:
        return f"Audit {self.site.code} #{self.pk} ({self.status})"


class AuditItem(models.Model):
    """One scanned tag inside a session. Duplicate scans are idempotent."""

    session = models.ForeignKey(AuditSession, on_delete=models.CASCADE, related_name="items")
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.SET_NULL, related_name="audit_hits"
    )
    asset_tag = models.CharField(max_length=40)  # kept even if the asset row is gone
    scanned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="audit_scans",
    )
    scanned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["scanned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "asset_tag"], name="uniq_audit_tag_per_session"
            )
        ]

    def __str__(self) -> str:
        return f"{self.asset_tag} @ session {self.session_id}"
