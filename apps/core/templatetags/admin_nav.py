"""Sidebar navigation + dashboard KPIs for the redesigned admin shell.

Django's stock admin only offers a flat, one-page app index; every changelist
and change form is otherwise an island. These tags give every admin page the
same permission-filtered model tree and the dashboard its live counters.

Permission filtering comes from ``admin.site.get_app_list`` — the same
callable the stock index uses — so scoped/superuser gates on individual
ModelAdmins keep working exactly as before.
"""

from datetime import timedelta

from django import template
from django.contrib import admin
from django.utils import timezone

register = template.Library()


@register.simple_tag(takes_context=True)
def admin_nav(context):
    """Return the admin model tree for the sidebar.

    Shape: ``[{"name", "url", "active", "models": [{"name", "url", "active"}]}]``
    Empty for anonymous/non-staff callers so the aside never renders on the
    login page. ``active`` compares the request path against the model's
    changelist URL, which also matches its add/change/delete pages.
    """
    request = context.get("request")
    user = getattr(request, "user", None)
    if request is None or not (user and user.is_staff):
        return []
    path = request.path
    groups = []
    for app in admin.site.get_app_list(request):
        models = []
        for model in app.get("models", []):
            url = model.get("admin_url")
            if not url:
                continue
            models.append(
                {
                    "name": model["name"],
                    "url": url,
                    "active": path == url or path.startswith(url),
                }
            )
        if not models:
            continue
        groups.append(
            {
                "name": app.get("name") or app.get("app_label", ""),
                "url": app.get("app_url", ""),
                "active": path == app.get("app_url") or any(m["active"] for m in models),
                "models": models,
            }
        )
    return groups


@register.simple_tag
def admin_stats():
    """Six live counters for the dashboard hero (one query each)."""
    from apps.assets.models import Asset, AssetRequest, Assignment

    today = timezone.localdate()
    in_30 = today + timedelta(days=30)
    live = Asset.objects.exclude(status__in=(Asset.Status.RETIRED, Asset.Status.DISPOSED))
    return {
        "total": Asset.objects.count(),
        "active": live.count(),
        "assigned": Asset.objects.filter(status=Asset.Status.ASSIGNED).count(),
        "pending": AssetRequest.objects.filter(status=AssetRequest.Status.PENDING).count(),
        "overdue": Assignment.objects.filter(in_at__isnull=True, due_at__lt=timezone.now()).count(),
        "warranty": Asset.objects.filter(
            warranty_end__isnull=False,
            warranty_end__gte=today,
            warranty_end__lte=in_30,
        ).count(),
    }
