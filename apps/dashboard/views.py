"""Dashboard app: healthz, root dashboard with widgets, and language switch."""

from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.roles import user_has_role


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


# Fixed palette for the category chart (mockup `docs/itasset-docs/index.html`);
# the 6th slot is the aggregated "Others" bucket.
_CHART_COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444"]
_OTHERS_COLOR = "#6b7280"


class DashboardView(TemplateView):
    """Root page — KPI row, category chart, alerts and status widgets.

    Layout follows the accepted mockup (`docs/itasset-docs/index.html`), but
    every number is computed live: KPIs from the register, alerts from the
    same queries the email scan tasks use (overdue loans, expiring warranty,
    pending approvals, transfer exceptions, missing serials).
    """

    template_name = "dashboard/home.html"

    def get_context_data(self, **kwargs):
        from datetime import timedelta

        from django.utils import timezone

        from apps.assets.models import (
            Asset,
            AssetRequest,
            Assignment,
            Category,
            Transfer,
        )
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

        # ---- mockup KPIs + alerts (all live queries) ---------------------
        today = timezone.localdate()
        in_30 = today + timedelta(days=30)
        in_7 = today + timedelta(days=7)
        month_start = today.replace(day=1)

        excluded = (Asset.Status.RETIRED, Asset.Status.DISPOSED)
        warranty_30 = Asset.objects.filter(
            warranty_end__isnull=False,
            warranty_end__gte=today,
            warranty_end__lte=in_30,
        ).count()
        warranty_7 = Asset.objects.filter(
            warranty_end__isnull=False,
            warranty_end__gte=today,
            warranty_end__lte=in_7,
        ).count()
        active = Asset.objects.exclude(status__in=excluded).count()
        assigned = Asset.objects.filter(status=Asset.Status.ASSIGNED).count()
        new_this_month = Asset.objects.filter(created_at__date__gte=month_start).count()
        overdue = Assignment.objects.filter(in_at__isnull=True, due_at__lt=timezone.now()).count()
        pending = AssetRequest.objects.filter(status=AssetRequest.Status.PENDING).count()
        exceptions = Transfer.objects.filter(status=Transfer.Status.EXCEPTION).count()
        missing_serial = Asset.objects.filter(serial_no="").count()

        # severity order: critical first; zero counts never render.
        # Approvers (admin/technician) act first → pending approvals up front.
        staff = bool(getattr(self.request.user, "is_staff", False))
        asset_list = reverse("asset-list")
        links = {
            "alert.overdue_loans": f"{asset_list}?overdue=1",
            "alert.warranty_soon": f"{asset_list}?warranty_days=7",
            "alert.missing_serial": f"{asset_list}?missing_serial=1",
            "alert.pending_approvals": (
                reverse("admin:assets_assetrequest_changelist") + "?status__exact=PENDING"
                if staff
                else None
            ),
            "alert.transfer_exceptions": (
                reverse("admin:assets_transfer_changelist") + "?status__exact=EXCEPTION"
                if staff
                else None
            ),
        }
        rows = [
            ("critical", "alert.overdue_loans", overdue),
            ("critical", "alert.transfer_exceptions", exceptions),
            ("warn", "alert.warranty_soon", warranty_7),
            ("warn", "alert.missing_serial", missing_serial),
            ("info", "alert.pending_approvals", pending),
        ]
        if user_has_role(self.request.user, "admin", "technician"):
            rows.sort(key=lambda r: r[1] != "alert.pending_approvals")  # stable → pending first
        alerts = [
            {"tone": tone, "key": key, "n": n, "href": links.get(key)} for tone, key, n in rows if n
        ]
        ctx["alerts"] = alerts

        # -1 = no count to interpolate; the `t` tag ignores unused params
        kpis = [
            {
                "tone": "critical",
                "label_key": "dash.kpi.alerts",
                "value": len(alerts),
                "meta_key": "dash.kpi.attention",
                "meta_n": -1,
            },
            {
                "tone": "warning",
                "label_key": "dash.kpi.warranty",
                "value": warranty_30,
                "meta_key": "dash.kpi.within30",
                "meta_n": -1,
            },
            {
                "tone": "success",
                "label_key": "dash.kpi.active",
                "value": active,
                "meta_key": "dash.kpi.assigned",
                "meta_n": assigned,
            },
            {
                "tone": "",
                "label_key": "dash.total_assets",
                "value": ctx["total_assets"],
                "meta_key": "dash.kpi.this_month",
                "meta_n": new_this_month,
            },
        ]
        # role-aware action board: approvers get their two action tiles first
        if user_has_role(self.request.user, "admin", "technician"):
            kpis[0:0] = [
                {
                    "tone": "critical" if pending else "success",
                    "label_key": "dash.kpi.pending",
                    "value": pending,
                    "meta_key": "dash.kpi.pending_meta",
                    "meta_n": -1,
                },
                {
                    "tone": "critical" if overdue else "success",
                    "label_key": "dash.kpi.overdue",
                    "value": overdue,
                    "meta_key": "dash.kpi.overdue_meta",
                    "meta_n": -1,
                },
            ]
        ctx["kpis"] = kpis

        # ---- category chart (top 5 + Others, like the mockup) ------------
        top5 = [
            c for c in Category.objects.annotate(n=Count("assets")).order_by("-n", "code") if c.n
        ][:5]
        others_n = ctx["total_assets"] - sum(c.n for c in top5)
        rows = [(c.name, c.n, False) for c in top5]
        if others_n > 0:
            rows.append(("Others", others_n, True))  # label localized in the template
        top = max((n for _lbl, n, _o in rows), default=0)
        ctx["by_category"] = [
            {
                "label": lbl,
                "n": n,
                "others": others,
                "pct": max(4, round(n * 100 / top)) if top else 0,
                "color": _CHART_COLORS[i] if i < len(_CHART_COLORS) else _OTHERS_COLOR,
            }
            for i, (lbl, n, others) in enumerate(rows)
        ]
        return ctx
