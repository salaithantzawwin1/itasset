from django.urls import path

from . import views

urlpatterns = [
    path("reports/", views.ReportIndex.as_view(), name="report-index"),
    path("reports/<slug:slug>.<slug:fmt>", views.ReportRun.as_view(), name="report-run"),
]
