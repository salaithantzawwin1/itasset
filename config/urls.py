from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path, reverse_lazy
from django.utils.functional import lazy
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.core.context_processors import current_brand_name
from apps.core.views import logo as branding_logo

# Admin branding: header bar, browser tab title, index page heading. Lazy, so
# changing the Branding row renames the admin without a restart.
admin.site.site_header = lazy(lambda: f"{current_brand_name()} administration", str)()
admin.site.site_title = lazy(lambda: f"{current_brand_name()} admin", str)()
admin.site.index_title = "Control panel"
admin.site.site_url = "/"  # "View site" link → main dashboard

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.dashboard.urls")),
    path("accounts/login/", auth_views.LoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    # every signed-in user may rotate their own password (topbar username link)
    path(
        "accounts/password/change/",
        auth_views.PasswordChangeView.as_view(
            template_name="registration/password_change_form.html",
            success_url=reverse_lazy("password_change_done"),
        ),
        name="password_change",
    ),
    path(
        "accounts/password/change/done/",
        auth_views.PasswordChangeDoneView.as_view(
            template_name="registration/password_change_done.html"
        ),
        name="password_change_done",
    ),
    # public company logo for the sign-in page (no /media/ tree exposed)
    path("branding/logo/", branding_logo, name="branding-logo"),
    path("", include("apps.people.urls")),
    path("", include("apps.assets.urls")),
    path("", include("apps.labels.urls")),
    path("", include("apps.audit.urls")),
    path("", include("apps.reports.urls")),
    path("api/v1/", include("apps.api.urls")),
    path("api/v1/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/v1/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
]
