"""Label views (M3; DEVELOPMENT.md §13/§16): print QR label sheets.

technician/admin can print; any authenticated user may preview a single label.
"""

from django.http import HttpResponse
from django.shortcuts import get_object_or_404

from apps.assets.models import Asset
from apps.core.roles import user_has_role

from . import services


def print_labels(request):
    """GET /labels/print/?ids=1,2,3 → one A4 PDF sheet (technician+)."""
    if not request.user.is_authenticated:
        return HttpResponse(status=302, headers={"Location": "/accounts/login/"})
    if not user_has_role(request.user, "admin", "technician"):
        return HttpResponse("Technician or admin role required.", status=403)

    ids = [i for i in request.GET.get("ids", "").replace(" ", "").split(",") if i.isdigit()]
    assets = (
        Asset.objects.filter(pk__in=ids).select_related("category", "site").order_by("asset_tag")
        if ids
        else Asset.objects.none()
    )
    pdf = services.label_pdf(assets)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="asset-labels.pdf"'
    return resp


def label_preview(request, pk):
    """GET /labels/<pk>/ → PNG of one asset's QR (any authenticated user)."""
    if not request.user.is_authenticated:
        return HttpResponse(status=302, headers={"Location": "/accounts/login/"})
    asset = get_object_or_404(Asset, pk=pk)
    return HttpResponse(services.qr_png(asset), content_type="image/png")
