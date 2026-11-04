"""Label views (M3; DEVELOPMENT.md §13/§16): print QR label sheets.

technician/admin can print; any authenticated user may preview a single label.
"""

from django.http import Http404, HttpResponse
from django.shortcuts import redirect

from apps.assets.models import Asset
from apps.core.roles import user_has_role
from apps.core.scopes import OutOfScope, check_scope, scope_list

from . import services


def print_labels(request):
    """GET /labels/print/?ids=1,2,3 → one A4 PDF sheet (technician+)."""
    if not request.user.is_authenticated:
        return redirect("login")
    if not user_has_role(request.user, "admin", "technician"):
        return HttpResponse("Technician or admin role required.", status=403)

    ids = [i for i in request.GET.get("ids", "").replace(" ", "").split(",") if i.isdigit()]
    assets = (
        Asset.objects.filter(pk__in=ids).select_related("category", "site").order_by("asset_tag")
        if ids
        else Asset.objects.none()
    )
    # printing is a read of the assets themselves: a pk outside the caller's
    # scope must not leak a label (same rule as the detail/API views)
    assets = scope_list(request.user, assets, action="label_print", path=request.path)
    pdf = services.label_pdf(assets)
    resp = HttpResponse(pdf, content_type="application/pdf")
    resp["Content-Disposition"] = 'attachment; filename="asset-labels.pdf"'
    return resp


def label_preview(request, pk):
    """GET /labels/<pk>/ → PNG of one asset's QR (any authenticated user)."""
    if not request.user.is_authenticated:
        return redirect("login")
    asset = Asset.objects.filter(pk=pk).select_related("category", "site").first()
    if asset is None:
        raise Http404("Asset not found")
    try:
        check_scope(request.user, asset, action="label_preview", path=request.path)
    except OutOfScope:
        raise Http404("Asset not found") from None
    return HttpResponse(services.qr_png(asset), content_type="image/png")
