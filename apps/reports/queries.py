"""Standard report queries (DEVELOPMENT.md §4, M7).

Each returns `(headers, rows)`. Lazy imports keep app load light; queries use
select_related to stay under the §17 no-N+1 rule.
"""

from __future__ import annotations

from datetime import date, timedelta


def _fmt(v):
    if v is None:
        return ""
    return str(v)


# ---- inventory / ownership -------------------------------------------------


def inventory_by_site(request=None, site=None):
    from apps.assets.models import Asset

    qs = Asset.objects.select_related("site", "category")
    if site:
        qs = qs.filter(site=site)
    headers = ["Site", "Category", "Status", "Count"]
    rows = []
    agg = {}
    for a in qs:
        key = (a.site.code, a.category.code, a.status)
        agg[key] = agg.get(key, 0) + 1
    for (s, c, st), n in sorted(agg.items()):
        rows.append([s, c, st, n])
    return headers, rows


def asset_aging(request=None):
    from apps.assets.models import Asset

    today = date.today()
    headers = ["Asset tag", "Model", "Purchase date", "Age (years)"]
    rows = []
    for a in Asset.objects.select_related("category").filter(purchase_date__isnull=False):
        years = round((today - a.purchase_date).days / 365.25, 1)
        rows.append([a.asset_tag, a.model_name, a.purchase_date.isoformat(), years])
    return headers, rows


def depreciation_schedule(request=None, useful_years=4, salvage_pct=0.1):
    """Straight-line depreciation for finance (§4)."""
    from decimal import Decimal

    from apps.assets.models import Asset

    headers = ["Asset tag", "Cost", "Salvage", "Annual dep.", "Accum. dep. (Y1)", "NBV (Y1)"]
    rows = []
    for a in Asset.objects.filter(cost__isnull=False):
        cost = Decimal(a.cost)
        salvage = cost * Decimal(str(salvage_pct))
        annual = (cost - salvage) / Decimal(useful_years)
        rows.append(
            [
                a.asset_tag,
                float(cost),
                float(salvage),
                round(float(annual), 2),
                round(float(annual), 2),
                round(float(cost - annual), 2),
            ]
        )
    return headers, rows


# ---- warranty / license / contract -----------------------------------------


def warranty_expiring(request=None, days=90):
    from apps.assets.models import Asset

    cutoff = date.today() + timedelta(days=days)
    headers = ["Asset tag", "Model", "Site", "Holder", "Warranty ends", "Days left"]
    rows = []
    for a in Asset.objects.select_related("site").filter(
        warranty_end__isnull=False, warranty_end__lte=cutoff
    ):
        active = a.assignments.filter(in_at__isnull=True).select_related("to_person").first()
        holder = active.to_person.name if active and active.to_person else ""
        left = (a.warranty_end - date.today()).days
        rows.append(
            [a.asset_tag, a.model_name, a.site.code, holder, a.warranty_end.isoformat(), left]
        )
    return headers, rows


def license_compliance(request=None):
    from apps.licenses.models import SoftwareLicense

    headers = ["License", "Vendor", "Seats", "Assigned", "Over-assigned"]
    rows = []
    for lic in SoftwareLicense.objects.select_related("vendor"):
        assigned = lic.keys.filter(released_at__isnull=True).count()
        rows.append(
            [
                lic.name,
                lic.vendor.name if lic.vendor else "",
                lic.seats,
                assigned,
                "YES" if assigned > lic.seats else "",
            ]
        )
    return headers, rows


def contract_renewals(request=None, days=90):
    from apps.vendors.models import Contract

    cutoff = date.today() + timedelta(days=days)
    headers = ["Contract", "Vendor", "Type", "Ends", "Days left", "Value", "Auto-renew"]
    rows = []
    for c in Contract.objects.select_related("vendor").filter(end_date__lte=cutoff):
        rows.append(
            [
                c.title,
                c.vendor.name,
                c.type,
                c.end_date.isoformat(),
                (c.end_date - date.today()).days,
                float(c.value) if c.value is not None else "",
                "yes" if c.auto_renew else "no",
            ]
        )
    return headers, rows


# ---- lifecycle activity ----------------------------------------------------


def orphan_assets(request=None):
    """Assigned assets whose holder left, or assigned with no holder (§4)."""
    from apps.assets.models import Asset

    headers = ["Asset tag", "Status", "Holder", "Holder active", "Last out"]
    rows = []
    for a in Asset.objects.filter(status=Asset.Status.ASSIGNED).select_related("site"):
        active = a.assignments.filter(in_at__isnull=True).select_related("to_person").first()
        if active is None:
            rows.append([a.asset_tag, a.status, "", "", ""])
        elif active.to_person is None or not active.to_person.is_active:
            rows.append(
                [
                    a.asset_tag,
                    a.status,
                    active.to_person.name if active.to_person else "",
                    "no",
                    active.out_at.date().isoformat(),
                ]
            )
    return headers, rows


def assets_by_department(request=None):
    """Who holds what, grouped by the holder's department (Person.department).

    One row per active assignment (in_at IS NULL) — the department/employee
    come from the Person record, so a department move needs no asset edit.
    Assets whose status says ASSIGNED but have no open assignment land in a
    "Not assigned" bucket: a cheap completeness check (§13 data quality)
    instead of a silently misleading blank.
    """
    from apps.assets.models import Asset, Assignment

    headers = ["Department", "Employee", "Asset tag", "Category", "Site", "Status", "Out"]
    rows = []
    assigned_ids: set[int] = set()
    open_asgs = (
        Assignment.objects.filter(in_at__isnull=True)
        .select_related(
            "to_person",
            "to_person__department",
            "asset",
            "asset__category",
            "asset__site",
        )
        .order_by("to_person__department__name", "to_person__name", "asset__asset_tag")
    )
    for asg in open_asgs:
        person = asg.to_person
        dept = person.department.name if person and person.department_id else "(no department)"
        who = person.name if person else "(no holder)"
        assigned_ids.add(asg.asset_id)
        rows.append(
            [
                dept,
                who,
                asg.asset.asset_tag,
                asg.asset.category.code,
                asg.asset.site.code,
                asg.asset.status,
                asg.out_at.date().isoformat(),
            ]
        )
    # completeness: ASSIGNED assets without an open assignment row
    for a in (
        Asset.objects.filter(status=Asset.Status.ASSIGNED)
        .exclude(pk__in=assigned_ids)
        .select_related("category", "site")
        .order_by("asset_tag")
    ):
        rows.append(["Not assigned", "", a.asset_tag, a.category.code, a.site.code, a.status, ""])
    return headers, rows


def check_activity(request=None, days=30):
    from apps.assets.models import Assignment
    from apps.audit.models import ActivityLog

    since = date.today() - timedelta(days=days)
    headers = ["Asset", "Holder", "Out", "In", "By (out)"]
    rows = []
    asgs = list(
        Assignment.objects.select_related("asset", "to_person")
        .filter(out_at__date__gte=since)
        .order_by("-out_at")
    )
    # "By (out)" = the operator who checked the asset out, from the
    # check_out ActivityLog event (Assignment.assigned_by is a Person, not
    # the operator). One batched lookup for the window — no N+1 (§17), and
    # no `.username` on a Person (that raised AttributeError for every real
    # checkout; only the never-assigned seed rows avoided it).
    operators = {}
    if asgs:
        event_since = min(a.out_at for a in asgs)
        for event in ActivityLog.objects.filter(
            action="check_out", created_at__gte=event_since
        ).select_related("actor"):
            aid = (event.details or {}).get("assignment")
            if aid and aid not in operators:
                operators[aid] = event.actor
    for asg in asgs:
        actor = operators.get(asg.pk)
        by = actor.username if actor is not None and actor.username else None
        if by is None and asg.assigned_by is not None:
            by = asg.assigned_by.name  # fall back to the person record's name
        rows.append(
            [
                asg.asset.asset_tag,
                asg.to_person.name if asg.to_person else "",
                asg.out_at.date().isoformat(),
                asg.in_at.date().isoformat() if asg.in_at else "",
                by or "",
            ]
        )
    return headers, rows


def damage_writeoff_log(request=None):
    from apps.assets.models import RepairTicket, WriteOff

    headers = ["Type", "Asset", "Detail", "Cost", "Date"]
    rows = []
    for t in RepairTicket.objects.select_related("asset").order_by("-reported_at"):
        rows.append(
            [
                "repair",
                t.asset.asset_tag,
                t.get_fault_category_display(),
                float(t.cost) if t.cost else "",
                t.reported_at.date().isoformat(),
            ]
        )
    for w in WriteOff.objects.select_related("asset").order_by("-damage_date"):
        rows.append(
            [
                "write-off",
                w.asset.asset_tag,
                w.get_cause_display(),
                float(w.actual_cost) if w.actual_cost else "",
                w.damage_date.isoformat(),
            ]
        )
    return headers, rows


def disposal_log(request=None):
    from apps.assets.models import DisposalRecord

    headers = ["Asset", "Method", "Certificate", "Date", "Operator", "Verified by"]
    rows = []
    for d in DisposalRecord.objects.select_related("asset", "operator", "verified_by"):
        rows.append(
            [
                d.asset.asset_tag,
                d.get_method_display(),
                d.certificate_no,
                d.date.isoformat(),
                d.operator.username if d.operator else "",
                d.verified_by.username if d.verified_by else "",
            ]
        )
    return headers, rows


def audit_results(request=None):
    from apps.assets.models import Asset
    from apps.audit.models import AuditSession

    headers = ["Session", "Site", "Status", "Started", "Closed", "Scanned", "Missing (est.)"]
    rows = []
    for s in AuditSession.objects.select_related("site"):
        expected = Asset.objects.filter(site=s.site).exclude(status="DISPOSED").count()
        rows.append(
            [
                s.pk,
                s.site.code,
                s.status,
                s.started_at.date().isoformat(),
                s.closed_at.date().isoformat() if s.closed_at else "",
                s.items.count(),
                max(0, expected - s.items.count()),
            ]
        )
    return headers, rows


def os_inventory(request=None):
    """Best-effort OS/hostname inventory from the hostname field (§4)."""
    from apps.assets.models import Asset

    headers = ["Asset tag", "Hostname", "Model", "Site", "Status"]
    rows = [
        [a.asset_tag, a.hostname, a.model_name, a.site.code, a.status]
        for a in Asset.objects.select_related("site")
    ]
    return headers, rows


# ---- registration ----------------------------------------------------------


def _register_all():
    from .exporters import Report, register

    register(
        Report(
            "inventory-by-site",
            "Inventory by site/category/status",
            inventory_by_site,
            ("csv", "xlsx", "pdf"),
        )
    )
    register(Report("asset-aging", "Asset aging", asset_aging, ("xlsx",)))
    register(Report("depreciation", "Depreciation schedule", depreciation_schedule, ("xlsx",)))
    register(
        Report(
            "warranty-expiring", "Warranty expiring (30/60/90d)", warranty_expiring, ("csv", "pdf")
        )
    )
    register(Report("license-compliance", "License compliance", license_compliance, ("xlsx",)))
    register(Report("contract-renewals", "Contract renewals (90d)", contract_renewals, ("csv",)))
    register(Report("orphan-assets", "Orphan assets", orphan_assets, ("csv",)))
    register(
        Report(
            "assets-by-department",
            "Assets by department (holder)",
            assets_by_department,
            ("csv", "xlsx"),
        )
    )
    register(Report("check-activity", "Check-out/in activity", check_activity, ("csv", "xlsx")))
    register(Report("damage-writeoff", "Damage & write-off log", damage_writeoff_log, ("pdf",)))
    register(Report("disposal-log", "Disposal & sanitization log", disposal_log, ("pdf",)))
    register(Report("audit-results", "Audit results", audit_results, ("xlsx",)))
    register(Report("os-inventory", "OS inventory & versions", os_inventory, ("xlsx",)))
