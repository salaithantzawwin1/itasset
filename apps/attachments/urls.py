"""Attachments API URLs — mounted under /api/v1/ via apps.api.urls."""

from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"attachments", views.AttachmentViewSet, basename="api-attachment")

urlpatterns = router.urls
