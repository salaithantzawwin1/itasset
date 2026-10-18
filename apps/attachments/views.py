"""Attachments API: scoped list/upload + authorized download (Spec A §6.13)."""

from django.http import FileResponse, Http404
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.scopes import OutOfScope

from .models import Attachment
from .scopes import check_attachment_scope, scope_attachments
from .serializers import AttachmentSerializer


class AttachmentViewSet(mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """GET /attachments/ (?asset=tag &request= &transfer=), POST /attachments/,
    GET /attachments/{id}/download/.

    Every response is scope-checked (design §5.2): an out-of-scope attachment
    is 404, identical to nonexistent (IDOR row 23). Deletion is admin-only via
    Django admin in v1.
    """

    serializer_class = AttachmentSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = Attachment.objects.select_related("asset", "request", "transfer", "uploaded_by")
        params = self.request.query_params
        if tag := params.get("asset"):
            qs = qs.filter(asset__asset_tag=tag)
        if req := params.get("request"):
            qs = qs.filter(request_id=req)
        if tr := params.get("transfer"):
            qs = qs.filter(transfer_id=tr)
        return scope_attachments(
            self.request.user, qs, action="attachment_list", path=self.request.path
        )

    @action(detail=True, methods=["get"], url_path="download")
    def download(self, request, pk=None):
        """Serve the private file — 404 when the owner's scope says no."""
        attachment = self.get_object()  # already scoped under enforcement …
        try:
            # … and shadow mode records a would-deny event before serving
            check_attachment_scope(
                request.user, attachment, action="attachment_download", path=request.path
            )
        except OutOfScope as exc:
            raise Http404(str(exc)) from exc
        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.original_name or attachment.file.name,
        )
