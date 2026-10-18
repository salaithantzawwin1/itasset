from django.urls import path

from . import views

urlpatterns = [
    path("labels/print/", views.print_labels, name="label-print"),
    path("labels/<int:pk>/", views.label_preview, name="label-preview"),
]
