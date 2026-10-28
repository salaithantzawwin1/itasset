"""Dashboard app: healthz, root dashboard with widgets, and language switch."""

from django.db import connection
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.generic import TemplateView

from apps.core.roles import user_has_role
from apps.core.scopes import effective_scopes, enforcement_enabled, scope_list


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

        from django.db.models import Q
        from django.utils import timezone

        from apps.assets.models import (
            Asset,
            AssetRequest,
            Assignment,
            Transfer,
        )
        from apps.people.models import Person, Site

        ctx = super().get_context_data(**kwargs)
        user = self.request.user

        # ---- scope-aware: every number below is the caller's own scope ----
        # `scope_list` is flag-aware: shadow mode (flag off) keeps today's
        # global behaviour; enforcement on → deny-by-default, so a
        # site-scoped user counts only their site and a zero-scope or
        # anonymous caller sees zeros instead of the whole register.
        act = dict(action="dashboard", path=self.request.path)
        assets = scope_list(user, Asset.objects.all(), **act)
        sites = scope_list(user, Site.objects.filter(is_active=True), site_field="id", **act)
        people = scope_list(user, Person.objects.filter(is_active=True), **act)

        ctx["total_assets"] = assets.count()
        ctx["total_people"] = people.count()
        ctx["total_sites"] = sites.count()

        ctx["by_status"] = [
            {"status": s, "label": label, "n": n}
            for s, label in Asset.Status.choices
            for n in [assets.filter(status=s).count()]
            if n
        ]
        ctx["by_condition"] = [
            {"condition": c, "label": label, "n": n}
            for c, label in Asset.Condition.choices
            for n in [assets.filter(condition=c).count()]
            if n
        ]
        ctx["by_site"] = sites.annotate(n=Count("assets", distinct=True)).order_by("-n")
        ctx["recent"] = assets.select_related("category", "site").order_by("-created_at")[:6]

        # ---- RAM card: what memory is actually in the fleet --------------
        # attrs is a JSON column, so there is no SQL group-by to lean on —
        # read the page's own (already scope-filtered) assets, capped, and
        # count in Python. Two spellings exist and both answer the same
        # question: installed devices record `ram_type`/`ram_speed_mhz`
        # (§5 catalogue), the RAM-module category records `memory_type`/
        # `speed_mhz`; a RAM with neither is simply not counted (the coverage
        # line below says how much of the register has RAM recorded).
        from collections import Counter

        def _speed_label(value) -> str:
            try:
                return f"{int(value)} MHz"
            except (TypeError, ValueError):
                return str(value)

        def _mhz(label: str) -> int:
            head = label.split()[0]
            return int(head) if head.isdigit() else -1

        type_counts: Counter = Counter()
        speed_counts: Counter = Counter()
        ram_recorded = 0
        for attrs in assets.values_list("attrs", flat=True)[:1000]:
            data = attrs if isinstance(attrs, dict) else {}
            kind = next((data.get(k) for k in ("ram_type", "memory_type") if data.get(k)), None)
            speed = next((data.get(k) for k in ("ram_speed_mhz", "speed_mhz") if data.get(k)), None)
            if kind or speed is not None:
                ram_recorded += 1
            if kind:
                type_counts[str(kind)] += 1
            if speed is not None:
                speed_counts[_speed_label(speed)] += 1

        ctx["ram_recorded"] = ram_recorded
        # types lead with the most common stick; speeds read as a spec sheet
        # (fastest first) — neither needs a second pass over the register
        ctx["ram_types"] = [
            {"label": label, "n": n}
            for label, n in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))
        ]
        ctx["ram_speeds"] = [
            {"label": label, "n": n}
            for label, n in sorted(speed_counts.items(), key=lambda kv: -_mhz(kv[0]))
        ]

        # ---- mockup KPIs + alerts (live queries, caller-scoped) ----------
        today = timezone.localdate()
        in_30 = today + timedelta(days=30)
        in_7 = today + timedelta(days=7)
        month_start = today.replace(day=1)

        excluded = (Asset.Status.RETIRED, Asset.Status.DISPOSED)
        warranty_30 = assets.filter(
            warranty_end__isnull=False,
            warranty_end__gte=today,
            warranty_end__lte=in_30,
        ).count()
        warranty_7 = assets.filter(
            warranty_end__isnull=False,
            warranty_end__gte=today,
            warranty_end__lte=in_7,
        ).count()
        active = assets.exclude(status__in=excluded).count()
        assigned = assets.filter(status=Asset.Status.ASSIGNED).count()
        new_this_month = assets.filter(created_at__date__gte=month_start).count()
        overdue = (
            scope_list(user, Assignment.objects.all(), site_field="asset__site", **act)
            .filter(in_at__isnull=True, due_at__lt=timezone.now())
            .count()
        )
        pending = (
            scope_list(user, AssetRequest.objects.all(), **act)
            .filter(status=AssetRequest.Status.PENDING)
            .count()
        )
        missing_serial = assets.filter(serial_no="").count()

        # transfer exceptions: a site cares if it is the source *or* the
        # destination — one `site_field` can't express that union, so filter
        # by hand with the same flag-aware semantics as `scope_list`.
        exceptions_qs = Transfer.objects.filter(status=Transfer.Status.EXCEPTION)
        if enforcement_enabled():
            scopes = effective_scopes(user)
            if scopes.global_access:
                pass
            elif scopes.is_empty:
                exceptions_qs = exceptions_qs.none()
            else:
                exceptions_qs = exceptions_qs.filter(
                    Q(from_site_id__in=scopes.sites) | Q(to_site_id__in=scopes.sites)
                )
        exceptions = exceptions_qs.count()

        # severity order: critical first; zero counts never render.
        # Approvers (admin/technician) act first → pending approvals up front.
        staff = bool(getattr(self.request.user, "is_staff", False))
        asset_list = reverse("asset-list")
        links = {
            "alert.overdue_loans": reverse("loan-overdue"),
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
            {"name": row["category__name"], "n": row["n"]}
            for row in assets.values("category__name")
            .annotate(n=Count("pk"))
            .order_by("-n", "category__name")[:5]
        ]
        others_n = ctx["total_assets"] - sum(c["n"] for c in top5)
        rows = [(c["name"], c["n"], False) for c in top5]
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
