from django.urls import path

from . import views

urlpatterns = [
    path("", views.DashboardView.as_view(), name="home"),
    path("set-lang/", views.set_lang, name="set-lang"),
    path("healthz", views.healthz, name="healthz"),
]
