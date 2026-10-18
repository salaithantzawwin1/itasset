"""Attachment API payloads: multipart upload + read (Spec A §6.13)."""

import os

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from apps.assets.models import AssetRequest, Transfer
from apps.core.roles import user_has_role
from apps.core.scopes import OutOfScope, check_scope

from .models import ALLOWED_EXTENSIONS, MAX_UPLOAD_BYTES, Attachment


class AttachmentSerializer(serializers.ModelSerializer):
    """Upload needs exactly one owner (`asset` | `request` | `transfer`).

    The file itself is write-only: downloads only ever go through the
    authorizing endpoint, never by URL.
    """

    owner = serializers.SerializerMethodField()
    uploaded_by = serializers.SerializerMethodField()
    file = serializers.FileField(write_only=True)

    class Meta:
        model = Attachment
        fields = [
            "id",
            "kind",
            "asset",
            "request",
            "transfer",
            "owner",
            "file",
            "original_name",
            "size",
            "content_type",
            "uploaded_by",
            "created_at",
        ]
        read_only_fields = ["original_name", "size", "content_type", "created_at"]

    def get_owner(self, obj):
        target = obj.owner
        if target is None:
            return None
        label = "asset" if obj.asset_id else ("request" if obj.request_id else "transfer")
        return {"type": label, "id": target.pk}

    def get_uploaded_by(self, obj):
        return obj.uploaded_by.username if obj.uploaded_by else None

    def validate_file(self, f):
        ext = os.path.splitext(f.name or "")[1].lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise serializers.ValidationError(f"file type '{ext or 'unknown'}' is not allowed")
        if (f.size or 0) > MAX_UPLOAD_BYTES:
            raise serializers.ValidationError(
                f"file exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB"
            )
        return f

    def validate(self, attrs):
        owners = [attrs.get(k) for k in ("asset", "request", "transfer")]
        if sum(1 for o in owners if o is not None) != 1:
            raise serializers.ValidationError(
                "exactly one of asset, request or transfer is required"
            )
        self._authorize(self.context["request"].user, next(o for o in owners if o is not None))
        return attrs

    @staticmethod
    def _scope_target(owner):
        """The org record an upload is scoped against.

        Assets and requests carry a site FK; a transfer upload is a
        sender-side action, so it is scoped by `from_site`.
        """
        return owner.from_site if isinstance(owner, Transfer) else owner

    def _authorize(self, user, owner):
        """Role gate + scope gate (forged owner → 403, design §5.2)."""
        if isinstance(owner, AssetRequest):
            allowed = user_has_role(user, "admin", "technician") or owner.requester_id == user.pk
        else:
            allowed = user_has_role(user, "admin", "technician")
        if not allowed:
            raise PermissionDenied("technician/admin role required to attach files here")
        try:
            check_scope(user, self._scope_target(owner), action="attachment_upload")
        except OutOfScope as exc:
            raise PermissionDenied("that record is outside your scope") from exc

    def create(self, validated_data):
        from apps.audit.models import ActivityLog

        user = self.context["request"].user
        attachment = Attachment.objects.create(uploaded_by=user, **validated_data)
        ActivityLog.record(
            actor=user,
            action="attachment_upload",
            obj=attachment,
            details={"kind": attachment.kind, "owner": self.get_owner(attachment)},
        )
        return attachment
