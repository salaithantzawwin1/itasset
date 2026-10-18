"""URLs for Asset CRUD + lifecycle actions (M2)."""

from django.urls import path

from . import views

urlpatterns = [
    path("assets/", views.AssetList.as_view(), name="asset-list"),
    path("assets/new/", views.AssetCreate.as_view(), name="asset-create"),
    path("assets/<int:pk>/", views.AssetDetail.as_view(), name="asset-detail"),
    path("assets/<int:pk>/edit/", views.AssetUpdate.as_view(), name="asset-update"),
    path("assets/<int:pk>/delete/", views.AssetDelete.as_view(), name="asset-delete"),
    path("assets/<int:pk>/check-out/", views.check_out_view, name="asset-check-out"),
    path("assets/<int:pk>/check-in/", views.check_in_view, name="asset-check-in"),
    # Employee self-view (design §4.4): own assignments + own requests only.
    path("me/", views.SelfView.as_view(), name="self-view"),
    # employee self-service request (§6.5 stage ① — was admin-only)
    path("requests/new/", views.RequestCreate.as_view(), name="request-create"),
]
