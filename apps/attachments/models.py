"""Attachments/documents (Spec A §6.13, Spec B §2.2; gap report §3.4).

Invoices, warranty files, photos, handover forms — the first file-storage
models in the project. Exactly one owning record per row, expressed as typed
FKs plus a DB CHECK (design principle #4: no polymorphic scope_type+id).
Every download goes through the scope check of the owning record.
"""

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from .storage import private_storage

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB
ALLOWED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".webp",
        ".txt",
        ".csv",
        ".doc",
        ".docx",
        ".xls",
        ".xlsx",
        ".ppt",
        ".pptx",
        ".zip",
    }
)


def _upload_to(instance, filename):
    """Opaque, collision-free path — the client's name never touches disk."""
    ext = os.path.splitext(filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:  # validated again in clean(); belt + braces
        ext = ""
    return f"attachments/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    """One uploaded file bound to exactly one owning record."""

    class Kind(models.TextChoices):
        INVOICE = "INVOICE", "Invoice"
        WARRANTY = "WARRANTY", "Warranty document"
        PHOTO = "PHOTO", "Photo"
        HANDOVER = "HANDOVER", "Handover form"
        OTHER = "OTHER", "Other"

    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.CASCADE, related_name="attachments"
    )
    request = models.ForeignKey(
        "assets.AssetRequest",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    transfer = models.ForeignKey(
        "assets.Transfer",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    kind = models.CharField(max_length=12, choices=Kind.choices, default=Kind.OTHER)
    file = models.FileField(upload_to=_upload_to, storage=private_storage)
    original_name = models.CharField(max_length=255, blank=True)
    size = models.PositiveIntegerField(default=0)
    content_type = models.CharField(max_length=100, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="attachments_uploaded",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "attachment"
        constraints = [
            models.CheckConstraint(
                name="attachment_exactly_one_owner",
                condition=(
                    (Q(asset__isnull=False) & Q(request__isnull=True) & Q(transfer__isnull=True))
                    | (Q(asset__isnull=True) & Q(request__isnull=False) & Q(transfer__isnull=True))
                    | (Q(asset__isnull=True) & Q(request__isnull=True) & Q(transfer__isnull=False))
                ),
            )
        ]

    @property
    def owner(self):
        """The single owning record (Asset | AssetRequest | Transfer)."""
        return self.asset or self.request or self.transfer

    def clean(self):
        super().clean()
        owners = [self.asset_id, self.request_id, self.transfer_id]
        if sum(1 for o in owners if o is not None) != 1:
            raise ValidationError(
                "an attachment needs exactly one owner (asset, request, transfer)"
            )
        if self.file:
            ext = os.path.splitext(self.file.name or "")[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                raise ValidationError(f"file type '{ext or 'unknown'}' is not allowed")
            size = getattr(self.file, "size", 0) or 0
            if size > MAX_UPLOAD_BYTES:
                raise ValidationError(f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")

    def save(self, *args, **kwargs):
        # A fresh upload is uncommitted; metadata is copied off the incoming
        # file object (FieldFile does not proxy attributes like content_type).
        if self.file and not self.file._committed:
            incoming = self.file.file
            if not self.original_name:
                self.original_name = os.path.basename(self.file.name or incoming.name or "")[:255]
            if not self.size:
                self.size = getattr(incoming, "size", 0) or 0
            if not self.content_type:
                self.content_type = getattr(incoming, "content_type", "") or ""
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.get_kind_display()} → {self.owner} ({self.original_name or 'file'})"
