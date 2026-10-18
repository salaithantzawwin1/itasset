"""Export job records (Spec A §10.8, gap §3.5 — shipped 2026-10-17).

Generation runs in the request cycle today (LAN scale — same as the HTML
report views, §17 defers heavy exports to Celery); the row still exists so
exports are enumerable, downloadable once, owner-scoped and auditable. The
`status` choices include the async states the Celery swap will need; `FAILED`
records unexpected render errors for ops evidence (client errors never create
a row — see the API view).
"""

from django.conf import settings
from django.db import models

from apps.attachments.storage import private_storage


def _upload_to(instance, filename):
    return f"exports/{instance.requested_by_id}/{filename}"


class ExportJob(models.Model):
    class Status(models.TextChoices):
        READY = "READY", "Ready"
        RUNNING = "RUNNING", "Running"  # reserved for the async swap
        FAILED = "FAILED", "Failed"

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="export_jobs"
    )
    report = models.SlugField(max_length=60)  # registry slug
    format = models.CharField(max_length=8)  # csv | xlsx | pdf (report.formats)
    site = models.ForeignKey(
        "people.Site",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="export_jobs",
    )
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.READY)
    row_count = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    file = models.FileField(upload_to=_upload_to, storage=private_storage, blank=True)
    error = models.TextField(blank=True)  # FAILED rows only
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "export job"
        verbose_name_plural = "export jobs"
        indexes = [models.Index(fields=["requested_by", "-created_at"])]

    @property
    def filename(self) -> str:
        return self.file.name.rsplit("/", 1)[-1] if self.file else ""

    def __str__(self) -> str:
        return f"{self.report}.{self.format} ×{self.row_count} ({self.status})"
