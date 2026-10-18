from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

# Admin branding: header bar, browser tab title, index page heading.
admin.site.site_header = "IT Asset Manager administration"
admin.site.site_title = "IT Asset Manager admin"
admin.site.index_title = "Control panel"
admin.site.site_url = "/"  # "View site" link → main dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("apps.people.urls")),
    path("", include("apps.assets.urls")),
    path("", include("apps.labels.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.reports.urls")),
    path("api/v1/", include("apps.api.urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
