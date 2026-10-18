"""Celery tasks — §15 scheduled scans + reports, §14 notification matrix (M4).

All tasks are idempotent: alerts go through `apps.audit.notify.send_alert`,
which dedupes on an `EmailAlert` row per (kind, object, bucket). Schedules
live in config/settings/base.py (CELERY_BEAT_SCHEDULE).
"""

import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

log = logging.getLogger(__name__)

# §14 warranty timing: 90 / 30 / 7 days (ascending — nearest bucket first)
WARRANTY_BUCKETS = (7, 30, 90)
# §14 contract timing: 60 / 14 days (ascending — nearest bucket first)
CONTRACT_BUCKETS = (14, 60)

DURATIONS = {"warranty": "Warranty expiring", "contract": "Contract renewal"}


@shared_task(name="scan_warranties")
def scan_warranties(today=None):
    """Daily 07:00 — email holder + IT lead at 90/30/7 days to warranty end (§14)."""
    from apps.assets.models import Asset
    from apps.assets.services import active_assignment
    from apps.audit.notify import send_alert

    today = today or timezone.localdate()
    sent = 0
    qs = Asset.objects.filter(
        warranty_end__isnull=False,
        warranty_end__gte=today - timedelta(days=1),  # still current or ending today
        warranty_end__lte=today + timedelta(days=max(WARRANTY_BUCKETS)),
    ).select_related("site", "category")

    for asset in qs:
        days_left = (asset.warranty_end - today).days
        # pick the bucket this asset falls into (nearest milestone crossed)
        bucket = next((b for b in WARRANTY_BUCKETS if days_left <= b), None)
        if bucket is None:
            continue
        assignment = active_assignment(asset)
        holder = assignment.to_person if assignment else None
        holder_email = getattr(holder, "email", "") or None
        if send_alert(
            "warranty",
            f"warranty:{asset.pk}:{bucket}",
            "warranty_expiring",
            {"asset": asset, "days_left": days_left, "holder_name": getattr(holder, "name", "")},
            subject=f"[IT Asset] {DURATIONS['warranty']}: {asset.asset_tag} ({days_left}d)",
            holder_email=holder_email,
        ):
            sent += 1

    log.info("scan_warranties: %d alert(s) sent", sent)
    return {"alerts": sent}


@shared_task(name="scan_contracts")
def scan_contracts(today=None):
    """Daily 07:10 — contract renewal alerts at 60/14 days before end (§12/§14)."""
    from apps.audit.notify import send_alert
    from apps.vendors.models import Contract

    today = today or timezone.localdate()
    sent = 0
    qs = Contract.objects.filter(
        end_date__gte=today, end_date__lte=today + timedelta(days=max(CONTRACT_BUCKETS))
    ).select_related("vendor")

    for contract in qs:
        days_left = (contract.end_date - today).days
        # respect the contract's own notice period, but never miss the 14d nudge
        horizon = max(contract.renewal_notice_days or 60, 14)
        if days_left > horizon:
            continue
        bucket = next((b for b in CONTRACT_BUCKETS if days_left <= b), None)
        if bucket is None:
            continue
        if send_alert(
            "contract_renewal",
            f"contract:{contract.pk}:{bucket}",
            "contract_renewal",
            {"contract": contract, "days_left": days_left},
            subject=f"[IT Asset] {DURATIONS['contract']}: {contract.title} ({days_left}d)",
        ):
            sent += 1

    log.info("scan_contracts: %d alert(s) sent", sent)
    return {"alerts": sent}


@shared_task(name="scan_license_seats")
def scan_license_seats():
    """Daily 07:05 — flag over-assigned licenses; §14 sends weekly per license.

    Bucket = ISO week so a license alerts once per week even though the task
    runs daily (§14: "License over-assigned → weekly").
    """
    from apps.audit.notify import send_alert
    from apps.licenses.models import SoftwareLicense

    today = timezone.localdate()
    iso = today.isocalendar()
    week_key = f"{iso.year}-W{iso.week:02d}"
    sent = 0

    for license_ in SoftwareLicense.objects.select_related("vendor").all():
        assigned = license_.keys.filter(released_at__isnull=True).count()
        if assigned <= license_.seats:
            continue
        if send_alert(
            "license_over",
            f"license:{license_.pk}:{week_key}",
            "license_over_assigned",
            {"license": license_},
            subject=f"[IT Asset] Seats over-assigned: {license_.name}",
        ):
            sent += 1

    log.info("scan_license_seats: %d alert(s) sent", sent)
    return {"alerts": sent}


@shared_task(name="purge_activity_log")
def purge_activity_log(months: int = 24):
    """Monthly — retention purge (§25: ActivityLog kept 24 months, §15 table)."""
    from apps.audit.models import ActivityLog, EmailAlert

    cutoff = timezone.now() - timedelta(days=31 * months)
    purged, _ = ActivityLog.objects.filter(created_at__lt=cutoff).delete()
    alerts_purged, _ = EmailAlert.objects.filter(created_at__lt=cutoff).delete()
    log.info("purge_activity_log: %d activity rows, %d alert rows removed", purged, alerts_purged)
    return {"activity": purged, "alerts": alerts_purged}


# §15 missing tasks: data_quality_report, send_daily_digest, send_scheduled_reports


@shared_task(name="scan_loans")
def scan_loans(today=None):
    """Daily 07:15 — loan overdue: check-outs 3+ days past `due_at` → holder +
    the issuing technician (§14, "due + 3 days").

    One bucket per assignment (`loan_overdue:{id}:d3`), so the alert fires
    exactly once no matter how many daily runs catch up; a checkout without a
    due date never alerts (nothing was promised to return). Recipients fall
    back to the §14 default (IT lead) when neither party has an address.
    """
    from apps.assets.models import Assignment
    from apps.audit.models import ActivityLog
    from apps.audit.notify import resolve_recipients, send_alert

    today = today or timezone.localdate()
    cutoff = today - timedelta(days=3)
    sent = 0
    overdue = list(
        Assignment.objects.filter(
            in_at__isnull=True, due_at__isnull=False, due_at__date__lte=cutoff
        )
        .select_related("asset__site", "to_person")
        .order_by("due_at")
    )
    # The issuing technician is the actor of the check_out ActivityLog event
    # (Assignment.assigned_by is a Person — a placeholder, not the operator).
    # One batched lookup, never a per-row query (§17 no-N+1).
    operators: dict[int, object] = {}
    if overdue:
        since = min(a.out_at for a in overdue)
        for event in ActivityLog.objects.filter(
            action="check_out", created_at__gte=since
        ).select_related("actor"):
            aid = (event.details or {}).get("assignment")
            if aid and aid not in operators:
                operators[aid] = event.actor
    for asg in overdue:
        tech = operators.get(asg.pk)
        tech_email = tech.email if tech is not None and tech.email else None
        holder_email = getattr(asg.to_person, "email", "") or None
        recipients = [e for e in (holder_email, tech_email) if e]
        days_overdue = (today - asg.due_at.date()).days
        if send_alert(
            "loan_overdue",
            f"loan_overdue:{asg.pk}:d3",
            "loan_overdue",
            {
                "assignment": asg,
                "asset_tag": asg.asset.asset_tag,
                "holder_name": getattr(asg.to_person, "name", ""),
                "site_name": getattr(asg.asset.site, "name", ""),
                "due": asg.due_at.date().isoformat(),
                "days_overdue": days_overdue,
                "by": getattr(tech, "username", "") or "—",
            },
            subject=f"[IT Asset] Loan overdue ({days_overdue}d): {asg.asset.asset_tag}",
            recipients=recipients or resolve_recipients("loan_overdue"),
        ):
            sent += 1

    log.info("scan_loans: %d overdue alert(s)", sent)
    return {"alerts": sent}


@shared_task(name="data_quality_report")
def data_quality_report(today=None):
    """Monthly, 1st 07:00 — data-quality issues list → IT lead (§13, §14).

    Checks (§13): assets missing warranty, missing location, assets assigned
    with no (active) holder, duplicate serial numbers. "Assigned with no
    holder" reuses the registered `orphan-assets` report so the two can never
    disagree; "location" maps to the `Site` row an asset points at — its FK is
    mandatory (§9), so what can go missing in this schema is the site's own
    address data.
    """
    from django.db.models import Count

    from apps.assets.models import Asset
    from apps.audit.notify import send_alert
    from apps.reports.queries import orphan_assets

    today = today or timezone.localdate()
    period = f"{today.year}-{today.month:02d}"

    live = Asset.objects.exclude(status__in=[Asset.Status.RETIRED, Asset.Status.DISPOSED])
    missing_warranty = live.filter(warranty_end__isnull=True).count()
    missing_location = live.filter(site__address="").count()

    # §13 "assigned asset with no holder" = the orphan-assets report (§4)
    _headers, orphan_rows = orphan_assets()
    assigned_no_holder = len(orphan_rows)
    holder_examples = [r[0] for r in orphan_rows[:10]]

    dup_qs = Asset.objects.exclude(serial_no="").values("serial_no").annotate(n=Count("pk"))
    duplicate_serials = dup_qs.filter(n__gt=1).count()
    serial_examples = list(
        dup_qs.filter(n__gt=1).order_by("serial_no").values_list("serial_no", flat=True)[:10]
    )

    stats = {
        "period": period,
        "missing_warranty": missing_warranty,
        "missing_location": missing_location,
        "assigned_no_holder": assigned_no_holder,
        "duplicate_serials": duplicate_serials,
        "serial_examples": serial_examples,
        "holder_examples": holder_examples,
    }

    sent = send_alert(
        "data_quality",
        f"data_quality:{period}",
        "data_quality",
        stats,
        subject=f"[IT Asset] Data-quality report {period}",
    )
    log.info("data_quality_report %s: %s sent=%s", period, stats, sent)
    return {
        "period": period,
        "missing_warranty": missing_warranty,
        "missing_location": missing_location,
        "assigned_no_holder": assigned_no_holder,
        "duplicate_serials": duplicate_serials,
        "sent": bool(sent),
    }


@shared_task(name="send_daily_digest")
def send_daily_digest(today=None):
    """Daily 08:00 — yesterday's check-outs/check-ins summarized → admins (§14).

    Bucket = the local date the activity happened on, so a retry any time
    later that day (or a beat replay) never sends twice (§14/§15).
    """
    from apps.audit.models import ActivityLog
    from apps.audit.notify import send_alert

    today = today or timezone.localdate()
    yesterday = today - timedelta(days=1)
    rows = list(
        ActivityLog.objects.filter(
            created_at__date=yesterday, action__in=["check_out", "check_in"]
        ).order_by("created_at")[:50]
    )
    outs = [r for r in rows if r.action == "check_out"]
    ins = [r for r in rows if r.action == "check_in"]

    counts = f"{len(outs)} out / {len(ins)} in"
    sent = send_alert(
        "daily_digest",
        f"digest:{yesterday.isoformat()}",
        "daily_digest",
        {
            "day": yesterday.isoformat(),
            "outs": len(outs),
            "ins": len(ins),
            "lines": [
                f"{r.action} {r.object_repr} (by {r.actor.username if r.actor else 'system'})"
                for r in rows[:30]
            ],
        },
        subject=f"[IT Asset] Daily digest {yesterday.isoformat()} ({counts})",
    )
    log.info("send_daily_digest %s: %d out, %d in, sent=%s", yesterday, len(outs), len(ins), sent)
    return {"check_out": len(outs), "check_in": len(ins), "sent": bool(sent)}


@shared_task(name="send_scheduled_reports")
def send_scheduled_reports(cadence="weekly", today=None):
    """§4 scheduled report exports by email (§15 table).

    - weekly (beat: Mon 07:30): warranty-expiring + contract-renewals → IT lead
    - monthly (beat: 1st 08:00): inventory-by-site snapshot per site → that
      site's `lead_email` (falls back to the IT lead)

    Files are rendered by `reports.service.run_scheduled_report` (the same
    `_lookup`/`_execute` as the UI/API paths) and attached as CSV; delivery is
    one idempotent EmailAlert row keyed by ISO week / month (+ site), so a
    re-run in the same period sends nothing (§15).
    """
    from apps.audit.notify import resolve_recipients, send_alert
    from apps.people.models import Site
    from apps.reports.service import run_scheduled_report

    today = today or timezone.localdate()
    delivered = 0

    if cadence == "weekly":
        iso = today.isocalendar()
        period = f"{iso.year}-W{iso.week:02d}"
        recipients = resolve_recipients("scheduled_report")  # → IT lead (§14)
        if not recipients:
            log.info("send_scheduled_reports weekly: skipped (no recipients)")
            return {"emails": 0}
        attachments = []
        names = []
        for slug, fmt in (("warranty-expiring", "csv"), ("contract-renewals", "csv")):
            content, _ctype, filename, _rows = run_scheduled_report(slug, fmt)
            attachments.append((filename, content, "text/csv"))
            names.append(slug)
        sent = send_alert(
            "scheduled_report",
            f"reports_week:{period}",
            "scheduled_reports",
            {"cadence": cadence, "period": period, "reports": ", ".join(names)},
            subject=f"[IT Asset] Weekly reports {period} — warranties & contracts",
            recipients=recipients,
            attachments=attachments,
        )
        delivered = int(sent)
    elif cadence == "monthly":
        period = f"{today.year}-{today.month:02d}"
        for site in Site.objects.filter(is_active=True).order_by("code"):
            recipients = (
                [site.lead_email] if site.lead_email else resolve_recipients("scheduled_report")
            )
            if not any(recipients):
                log.info("send_scheduled_reports monthly: %s skipped (no recipient)", site.code)
                continue
            content, _ctype, filename, _rows = run_scheduled_report(
                "inventory-by-site", "csv", site=site
            )
            sent = send_alert(
                "scheduled_report",
                f"reports_month:{period}:site:{site.code}",
                "scheduled_reports",
                {"cadence": cadence, "period": period, "site": site.name},
                subject=f"[IT Asset] Inventory snapshot {period} — {site.name}",
                recipients=recipients,
                attachments=[(filename, content, "text/csv")],
            )
            delivered += int(sent)
    else:
        raise ValueError(f"unknown cadence: {cadence}")  # beat kwargs are ours; fail loud

    log.info("send_scheduled_reports %s %s: %d email(s)", cadence, today, delivered)
    return {"emails": delivered}
