"""Dashboard app: healthz, root dashboard with widgets, and language switch."""

from django.contrib.auth.mixins import LoginRequiredMixin
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
# it cycles, so every category gets its own colour however many there are.
_CHART_COLORS = ["#3b82f6", "#10b981", "#8b5cf6", "#f59e0b", "#ef4444", "#6b7280", "#14b8a6"]


class DashboardView(LoginRequiredMixin, TemplateView):
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
        cells: Counter = Counter()  # (type|None, speed label|None) → assets
        ram_recorded = 0
        for attrs in assets.values_list("attrs", flat=True)[:1000]:
            data = attrs if isinstance(attrs, dict) else {}
            kind = next((data.get(k) for k in ("ram_type", "memory_type") if data.get(k)), None)
            speed = next((data.get(k) for k in ("ram_speed_mhz", "speed_mhz") if data.get(k)), None)
            if not kind and speed is None:
                continue
            ram_recorded += 1
            kind_key = str(kind) if kind else None
            speed_key = _speed_label(speed) if speed is not None else None
            if kind_key:
                type_counts[kind_key] += 1
            if speed_key:
                speed_counts[speed_key] += 1
            cells[(kind_key, speed_key)] += 1

        ctx["ram_recorded"] = ram_recorded
        # ---- RAM matrix: type × speed, totals on both edges --------------
        # Two separate lists answered “how many DDR4?” and “how many
        # 1600 MHz?” but never “how many DDR3 at 1600 MHz?”, and each list
        # counted only the half it showed (10 types vs 10 speeds while 11
        # assets had RAM). One cross-tab puts every asset in exactly one
        # cell, so row/column totals reconcile with `ram_recorded`; an asset
        # with only half the pair recorded lands on the “not recorded” edge
        # of the other axis instead of vanishing.
        type_order = [k for k, _ in sorted(type_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        speed_order = [k for k, _ in sorted(speed_counts.items(), key=lambda kv: -_mhz(kv[0]))]
        row_keys = type_order + ([None] if any(k is None for k, _ in cells) else [])
        col_keys = speed_order + ([None] if any(s is None for _, s in cells) else [])

        # cells are shaded by how many assets they hold, so the busy combos
        # read at a glance: 0 → no tint, the fullest cell → 0.32 alpha
        busiest = max(cells.values(), default=0)

        def _heat(n: int) -> float:
            if n <= 0 or busiest <= 0:
                return 0.0
            if busiest == 1:
                return 0.22
            return round(0.10 + 0.22 * (n - 1) / (busiest - 1), 3)

        def _speed_key(label):
            """The value the asset list filters on: `2400` from “2400 MHz”.

            A non-numeric label (some modules record “LPDDR4X-4266”) is used
            as-is, and `none` reaches the matrix's “Not recorded” edge.
            """
            if label is None:
                return "none"
            head = label.split()[0]
            return head if head.isdigit() else label

        def _row(key):
            counts = [cells.get((key, col), 0) for col in col_keys]
            return {
                "label": key,
                "key": key or "none",
                "unknown": key is None,
                "cells": [
                    {"n": n, "heat": _heat(n), "speed_key": _speed_key(col)}
                    for n, col in zip(counts, col_keys, strict=True)
                ],
                "total": sum(counts),
            }

        rows = [_row(k) for k in row_keys]
        ctx["ram_matrix"] = {
            "columns": [{"label": c, "key": _speed_key(c), "unknown": c is None} for c in col_keys],
            "rows": rows,
            "col_totals": [sum(r["cells"][i]["n"] for r in rows) for i in range(len(col_keys))],
            "total": ram_recorded,
            # phone view: the non-empty cells as “DDR4 · 2133 MHz — 4”, in
            # the same type-major / fastest-first order and shading as the table
            "combos": [
                {
                    "type": r["label"],
                    "type_key": r["key"],
                    "speed": col,
                    "speed_key": r["cells"][i]["speed_key"],
                    "n": r["cells"][i]["n"],
                    "heat": r["cells"][i]["heat"],
                }
                for r in rows
                for i, col in enumerate(col_keys)
                if r["cells"][i]["n"]
            ],
        }

        # ---- CPU card: the same cross-tab, model × cores -----------------
        # There is no CPU-speed field in the §5 catalogue, so the numeric
        # axis is the core count — the one number every CPU row carries.
        # Model names are free text, so rows are ordered by how common they
        # are (the fleet's workhorses first) exactly like RAM types.
        cpu_cells: Counter = Counter()  # (model|None, cores|None) → assets

        def _cores_key(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return str(value).strip() or None

        cpu_recorded = 0
        for attrs in assets.values_list("attrs", flat=True)[:1000]:
            data = attrs if isinstance(attrs, dict) else {}
            model = data.get("cpu_model")
            cores = data.get("cpu_cores")
            if not model and cores is None:
                continue
            cpu_recorded += 1
            model_key = str(model).strip() if model else None
            cores_key = _cores_key(cores) if cores is not None else None
            cpu_cells[(model_key, cores_key)] += 1

        model_counts: Counter = Counter()
        core_counts: Counter = Counter()
        for (model, cores), n in cpu_cells.items():
            if model:
                model_counts[model] += n
            if cores is not None:
                core_counts[cores] += n
        model_order = [m for m, _ in sorted(model_counts.items(), key=lambda kv: (-kv[1], kv[0]))]
        core_order = sorted(
            core_counts, key=lambda c: (0, c, "") if isinstance(c, int) else (1, 0, str(c))
        )
        cpu_rows = model_order + ([None] if any(m is None for m, _ in cpu_cells) else [])
        cpu_cols = core_order + ([None] if any(c is None for _, c in cpu_cells) else [])

        cpu_busiest = max(cpu_cells.values(), default=0)

        def _cpu_heat(n: int) -> float:
            if n <= 0 or cpu_busiest <= 0:
                return 0.0
            if cpu_busiest == 1:
                return 0.22
            return round(0.10 + 0.22 * (n - 1) / (cpu_busiest - 1), 3)

        def _cores_label(value):
            return None if value is None else f"{value} cores"

        ctx["cpu_recorded"] = cpu_recorded
        ctx["cpu_matrix"] = {
            "columns": [
                {
                    "label": _cores_label(c),
                    "key": "none" if c is None else str(c),
                    "unknown": c is None,
                }
                for c in cpu_cols
            ],
            "rows": [
                {
                    "label": m,
                    "key": m or "none",
                    "unknown": m is None,
                    "cells": [
                        {
                            "n": cpu_cells.get((m, c), 0),
                            "heat": _cpu_heat(cpu_cells.get((m, c), 0)),
                            "col_key": "none" if c is None else str(c),
                        }
                        for c in cpu_cols
                    ],
                    "total": sum(cpu_cells.get((m, c), 0) for c in cpu_cols),
                }
                for m in cpu_rows
            ],
            "col_totals": [sum(cpu_cells.get((m, c), 0) for m in cpu_rows) for c in cpu_cols],
            "total": cpu_recorded,
            # phone view: the non-empty combinations as “i5-1335U · 10 cores”
            "combos": [
                {
                    "model": m,
                    "model_key": m or "none",
                    "cores": _cores_label(c),
                    "cores_key": "none" if c is None else str(c),
                    "n": n,
                    "heat": _cpu_heat(n),
                }
                for (m, c), n in sorted(
                    cpu_cells.items(),
                    key=lambda kv: (
                        cpu_rows.index(kv[0][0]),
                        cpu_cols.index(kv[0][1]),
                    ),
                )
            ],
        }

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

        # ---- category chart: one column per category, no “Others” bucket --
        # The old top-5 + Others split hid real categories behind a grey
        # lump (Server and Switch were both invisible). Every category the
        # register actually uses now gets its own column, busiest first, and
        # the palette cycles so even a wide catalogue stays readable.
        rows = [
            (row["category__name"], row["n"])
            for row in assets.values("category__name")
            .annotate(n=Count("pk"))
            .order_by("-n", "category__name")
        ]
        top = max((n for _lbl, n in rows), default=0)
        ctx["by_category"] = [
            {
                "label": lbl,
                "n": n,
                "pct": max(4, round(n * 100 / top)) if top else 0,
                "color": _CHART_COLORS[i % len(_CHART_COLORS)],
            }
            for i, (lbl, n) in enumerate(rows)
        ]
        return ctx
