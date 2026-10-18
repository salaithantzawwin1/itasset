"""Dashboard app: healthz, root dashboard with widgets, and language switch."""

from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect
from django.views.generic import TemplateView


def healthz(request):
    """Liveness: DB ping. Monitored by Uptime Kuma (§18)."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except Exception as exc:  # pragma: no cover - failure path
        return JsonResponse({"status": "error", "db": str(exc)}, status=503)
    return JsonResponse({"status": "ok", "db": "ok"})


def set_lang(request):
    """Switch UI language (en/my); returns to the referring page."""
    lang = request.POST.get("lang", "en")
    if lang in ("en", "my"):
        request.session["lang"] = lang
    return redirect(request.META.get("HTTP_REFERER") or "/")


class DashboardView(TemplateView):
    """Root page — asset status summary widgets (M2 reporting, §4)."""

    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        from apps.assets.models import Asset
        from apps.people.models import Person, Site

        ctx = super().get_context_data(**kwargs)

        ctx["total_assets"] = Asset.objects.count()
        ctx["total_people"] = Person.objects.filter(is_active=True).count()
        ctx["total_sites"] = Site.objects.filter(is_active=True).count()

        ctx["by_status"] = (
            Asset.objects.values("status", "status_label")
            if False  # placeholder to keep code short
            else [
                {"status": s, "label": label, "n": n}
                for s, label in Asset.Status.choices
                for n in [Asset.objects.filter(status=s).count()]
                if n
            ]
        )
        ctx["by_condition"] = [
            {"condition": c, "label": label, "n": n}
            for c, label in Asset.Condition.choices
            for n in [Asset.objects.filter(condition=c).count()]
            if n
        ]
        ctx["by_site"] = (
            Site.objects.annotate(n=Count("assets", distinct=True))
            .filter(is_active=True)
            .order_by("-n")
        )
        ctx["recent"] = Asset.objects.select_related("category", "site").order_by("-created_at")[:6]
        return ctx
