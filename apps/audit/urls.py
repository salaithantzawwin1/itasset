from django.urls import path

from . import views

urlpatterns = [
    path("activity/", views.ActivityLogList.as_view(), name="activity-log"),
    path("audits/", views.AuditSessionList.as_view(), name="audit-sessions"),
    path("audits/start/", views.AuditSessionStart.as_view(), name="audit-start"),
    path("audits/<int:pk>/", views.AuditSessionDetail.as_view(), name="audit-session"),
    path("audits/<int:pk>/scan/", views.AuditSessionScan.as_view(), name="audit-scan"),
    path("audits/<int:pk>/close/", views.AuditSessionClose.as_view(), name="audit-close"),
    path("audits/<int:pk>/report/", views.AuditReport.as_view(), name="audit-report"),
]
