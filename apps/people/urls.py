"""URLs for Site and Person CRUD (M2)."""

from django.urls import path

from . import views

urlpatterns = [
    # Site
    path("sites/", views.SiteList.as_view(), name="site-list"),
    path("sites/new/", views.SiteCreate.as_view(), name="site-create"),
    path("sites/<int:pk>/", views.SiteDetail.as_view(), name="site-detail"),
    path("sites/<int:pk>/edit/", views.SiteUpdate.as_view(), name="site-update"),
    path("sites/<int:pk>/delete/", views.SiteDelete.as_view(), name="site-delete"),
    # Person
    path("people/", views.PersonList.as_view(), name="person-list"),
    path("people/new/", views.PersonCreate.as_view(), name="person-create"),
    path("people/<int:pk>/", views.PersonDetail.as_view(), name="person-detail"),
    path("people/<int:pk>/edit/", views.PersonUpdate.as_view(), name="person-update"),
    path("people/<int:pk>/delete/", views.PersonDelete.as_view(), name="person-delete"),
    # Department: list with counts (session 37) + detail (32) + edit (37)
    path("departments/", views.DepartmentList.as_view(), name="department-list"),
    path("departments/<int:pk>/", views.DepartmentDetail.as_view(), name="department-detail"),
    path(
        "departments/<int:pk>/edit/",
        views.DepartmentUpdate.as_view(),
        name="department-update",
    ),
]
