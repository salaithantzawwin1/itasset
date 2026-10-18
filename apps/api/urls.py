"""API URLs (M3; DEVELOPMENT.md §10): /api/v1/."""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import tokens, views

router = DefaultRouter()
router.register(r"assets", views.AssetViewSet, basename="api-asset")
router.register(r"transfers", views.TransferViewSet, basename="api-transfer")
router.register(r"requests", views.AssetRequestViewSet, basename="api-request")
# export jobs (§10.8, gap §3.5): create + list + private download
router.register(r"exports", views.ExportJobViewSet, basename="api-export")

urlpatterns = [
    path("auth/token/", tokens.obtain_scanner_token, name="api-token"),
    # identity endpoint (§10.2, gap §3.5): who am I + effective scopes
    path("me/", views.me, name="api-me"),
    # org reference tree (§10.2, gap §3.5): sites + departments for form choices
    path("org/sites/", views.org_tree, name="api-org-sites"),
    path("scan/<str:asset_tag>/", views.scan_payload, name="api-scan"),
    path(
        "warranties/expiring/",
        views.WarrantyExpiringView.as_view({"get": "list"}),
        name="api-warranties-expiring",
    ),
    path(
        "contracts/expiring/",
        views.ContractExpiringView.as_view({"get": "list"}),
        name="api-contracts-expiring",
    ),
    # scope administration (design §5.3, rows 17/20): admin-only grant/revoke
    path("users/<int:user_id>/scopes/", views.user_scopes, name="api-user-scopes"),
    path(
        "users/<int:user_id>/scopes/<int:scope_id>/",
        views.user_scope_detail,
        name="api-user-scope-detail",
    ),
    path("", include(router.urls)),
    # attachments module (Spec A §6.13): scoped list/upload + authorized download
    path("", include("apps.attachments.urls")),
]
