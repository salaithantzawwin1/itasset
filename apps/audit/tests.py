"""M4 tests (DEVELOPMENT.md §14 notification matrix, §15 Celery tasks, §20).

Covers: warranty scan → email to holder + IT lead at 90/30/7 buckets,
idempotency (re-run must not resend), contract renewal at 60/14 with the
contract's own notice period, weekly over-assigned license alert, retention
purge, and the /warranties/expiring/ + /contracts/expiring/ API (§10).
"""

from datetime import timedelta

import pytest
from django.core import mail
from django.utils import timezone

pytestmark = pytest.mark.django_db


def _any_user():
    from django.contrib.auth import get_user_model

    from apps.core.models import UserAccessScope

    User = get_user_model()
    u = User.objects.create_user("api_ro", "ro@example.com", "pass12345!")
    # Feature tests, not scope tests: GLOBAL scope keeps enforcement
    # transparent (deny-by-default cases live in tests/test_scopes.py).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


@pytest.fixture
def settings_it_lead(settings):
    settings.IT_LEAD_EMAIL = "itlead@example.com"
    settings.PROCUREMENT_EMAIL = "proc@example.com"
    return settings


@pytest.fixture
def asset_factory2(db, site, category):
    """Local factory so warranty tests control warranty_end explicitly."""
    from apps.assets.models import Asset

    counter = {"n": 0}

    def _make(warranty_days=None, **extra):
        counter["n"] += 1
        today = timezone.localdate()
        return Asset.objects.create(
            asset_tag=extra.pop("asset_tag", f"WR-{counter['n']:04d}"),
            category=extra.pop("category", category),
            site=extra.pop("site", site),
            status=extra.pop("status", "AVAILABLE"),
            condition="GOOD",
            serial_no=f"SN-WR-{counter['n']}",
            warranty_end=(
                today + timedelta(days=warranty_days) if warranty_days is not None else None
            ),
            **extra,
        )

    return _make


# ---------------------------------------------------------------- §15 scan_warranties
def test_warranty_30d_email_to_holder_and_it_lead(asset_factory2, person_factory, settings_it_lead):
    from apps.assets import services
    from apps.audit.tasks import scan_warranties

    asset = asset_factory2(warranty_days=30)
    holder = person_factory(employee_no="W1001", email="holder@example.com")
    services.check_out(asset, holder, actor=None)

    result = scan_warranties()
    assert result == {"alerts": 1}
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert "holder@example.com" in msg.to
    assert "itlead@example.com" in msg.to
    assert asset.asset_tag in msg.body
    assert "30" in msg.body


def test_warranty_bucket_escalation_90_30_7(asset_factory2, settings_it_lead):
    """One asset crossing 30d and then 7d gets exactly one email per bucket."""
    from apps.audit.models import EmailAlert
    from apps.audit.tasks import scan_warranties

    asset = asset_factory2(warranty_days=30)
    scan_warranties()
    assert len(mail.outbox) == 1

    # 25 days later the same asset falls into the 7d bucket
    asset.warranty_end = timezone.localdate() + timedelta(days=5)
    asset.save(update_fields=["warranty_end"])
    scan_warranties()
    assert len(mail.outbox) == 2  # second, tighter alert
    assert EmailAlert.objects.filter(kind="warranty").count() == 2


def test_warranty_idempotent_rerun(asset_factory2, settings_it_lead):
    from apps.audit.tasks import scan_warranties

    asset_factory2(warranty_days=6)
    scan_warranties()
    scan_warranties()
    scan_warranties()
    assert len(mail.outbox) == 1  # §14: no duplicate emails


def test_warranty_no_email_without_it_lead_or_holder(asset_factory2, settings):
    """No recipients configured → nothing sent, but no crash either."""
    from apps.audit.tasks import scan_warranties

    settings.IT_LEAD_EMAIL = ""
    asset_factory2(warranty_days=10)
    result = scan_warranties()
    assert result == {"alerts": 0}
    assert mail.outbox == []


def test_warranty_far_future_ignored(asset_factory2, settings_it_lead):
    from apps.audit.tasks import scan_warranties

    asset_factory2(warranty_days=200)
    assert scan_warranties() == {"alerts": 0}
    assert mail.outbox == []


# ---------------------------------------------------------------- §15 scan_contracts
@pytest.fixture
def contract_factory(db, site):
    from apps.vendors.models import Contract, Vendor

    vendor, _ = Vendor.objects.get_or_create(name="Test Vendor")
    counter = {"n": 0}

    def _make(days_to_end=30, notice=60, **extra):
        counter["n"] += 1
        today = timezone.localdate()
        return Contract.objects.create(
            vendor=extra.pop("vendor", vendor),
            title=extra.pop("title", f"Contract {counter['n']}"),
            contract_no=extra.pop("contract_no", f"C-{counter['n']:04d}"),
            start_date=today - timedelta(days=100),
            end_date=today + timedelta(days=days_to_end),
            renewal_notice_days=notice,
            **extra,
        )

    return _make


def test_contract_60d_and_14d_buckets(contract_factory, settings_it_lead):
    from apps.audit.tasks import scan_contracts

    contract_factory(days_to_end=55)  # inside 60d bucket
    result = scan_contracts()
    assert result == {"alerts": 1}
    assert len(mail.outbox) == 1
    assert "proc@example.com" in mail.outbox[0].to

    # crosses 14d → a second, tighter alert
    c = contract_factory  # noqa: F841 - readability
    from apps.vendors.models import Contract

    contract = Contract.objects.get(contract_no="C-0001")
    contract.end_date = timezone.localdate() + timedelta(days=10)
    contract.save(update_fields=["end_date"])
    scan_contracts()
    assert len(mail.outbox) == 2


def test_contract_notice_period_respected(contract_factory, settings_it_lead):
    """A contract with a 30d notice period is silent at day 55."""
    from apps.audit.tasks import scan_contracts

    contract_factory(days_to_end=55, notice=30)
    assert scan_contracts() == {"alerts": 0}
    assert mail.outbox == []


def test_contract_idempotent(contract_factory, settings_it_lead):
    from apps.audit.tasks import scan_contracts

    contract_factory(days_to_end=50)
    scan_contracts()
    scan_contracts()
    assert len(mail.outbox) == 1


# ---------------------------------------------------------------- §15 scan_license_seats
@pytest.fixture
def license_factory(db):
    from apps.licenses.models import LicenseKey, SoftwareLicense

    counter = {"n": 0}

    def _make(seats=2, assigned=0, **extra):
        counter["n"] += 1
        lic = SoftwareLicense.objects.create(
            name=extra.pop("name", f"License {counter['n']}"),
            seats=seats,
            **extra,
        )
        for i in range(assigned):
            LicenseKey.objects.create(license=lic, key=f"K-{counter['n']}-{i}")
        return lic

    return _make


def test_over_assigned_license_alerts_weekly(license_factory, settings_it_lead):
    from apps.audit.tasks import scan_license_seats

    license_factory(seats=2, assigned=5)
    result = scan_license_seats()
    assert result == {"alerts": 1}
    assert len(mail.outbox) == 1
    assert "itlead@example.com" in mail.outbox[0].to

    scan_license_seats()
    scan_license_seats()
    assert len(mail.outbox) == 1  # weekly bucket — no daily spam (§14)


def test_within_seats_no_alert(license_factory, settings_it_lead):
    from apps.audit.tasks import scan_license_seats

    lic = license_factory(seats=3, assigned=2)
    assert scan_license_seats() == {"alerts": 0}
    # released seat frees capacity — over-assignment is about active keys
    key = lic.keys.first()
    key.release()
    assert key.released_at is not None
    assert lic.seats_assigned == 1  # released keys are excluded


# ---------------------------------------------------------------- §15 purge_activity_log
def test_purge_keeps_24_months(db):
    from apps.audit.models import ActivityLog
    from apps.audit.tasks import purge_activity_log

    old = ActivityLog.objects.create(action="check_out", object_repr="OLD")
    ActivityLog.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=800))
    ActivityLog.objects.create(action="check_in", object_repr="NEW")

    result = purge_activity_log()
    assert result["activity"] == 1
    assert not ActivityLog.objects.filter(object_repr="OLD").exists()
    assert ActivityLog.objects.filter(object_repr="NEW").exists()


# ---------------------------------------------------------------- §10 expiring API
@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


def test_warranties_expiring_api(api_client, asset_factory2, settings_it_lead):
    api_client.force_authenticate(user=_any_user())
    asset_factory2(warranty_days=10)
    asset_factory2(warranty_days=200)
    r = api_client.get("/api/v1/warranties/expiring/?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["days_left"] == 10


def test_contracts_expiring_api(api_client, contract_factory, settings_it_lead):
    api_client.force_authenticate(user=_any_user())
    contract_factory(days_to_end=45)
    r = api_client.get("/api/v1/contracts/expiring/?days=90")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["results"][0]["days_to_end"] == 45


# ------------------------------------------- §15 scheduled reports (M4 close-out)
# data_quality_report / send_daily_digest / send_scheduled_reports were
# documented in the §15 table but had no implementation; each test also pins
# §14/§15 idempotency (a re-run in the same bucket must not send twice).


def _attachment_bytes(att) -> bytes:
    """EmailMessage.attach decodes text/* attachments as UTF-8 (str in tests)."""
    content = att[1]
    return content if isinstance(content, bytes) else content.encode("utf-8")


def test_weekly_scheduled_reports_email(asset_factory2, contract_factory, settings_it_lead):
    from apps.audit.models import EmailAlert
    from apps.audit.tasks import send_scheduled_reports

    asset = asset_factory2(warranty_days=30)
    contract_factory(days_to_end=45)

    result = send_scheduled_reports(cadence="weekly")
    assert result == {"emails": 1}
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["itlead@example.com"]  # §4 weekly → IT lead
    assert "Weekly reports" in msg.subject
    assert len(msg.attachments) == 2  # warranty + contract exports
    assert all(att[0].endswith(".csv") for att in msg.attachments)
    blob = b"".join(_attachment_bytes(att) for att in msg.attachments)
    assert asset.asset_tag.encode() in blob  # a real export, not a stub

    # §15 idempotency: same ISO week → nothing more goes out
    assert send_scheduled_reports(cadence="weekly") == {"emails": 0}
    assert len(mail.outbox) == 1
    assert EmailAlert.objects.filter(kind="scheduled_report").count() == 1


def test_weekly_scheduled_reports_skip_without_recipients(settings):
    from apps.audit.tasks import send_scheduled_reports

    settings.IT_LEAD_EMAIL = ""
    assert send_scheduled_reports(cadence="weekly") == {"emails": 0}
    assert mail.outbox == []  # §14: no recipient → no email, no crash


def test_monthly_inventory_snapshot_per_site(category, site, settings_it_lead):
    from apps.assets.models import Asset
    from apps.audit.tasks import send_scheduled_reports
    from apps.people.models import Site

    other = Site.objects.create(
        name="Alpha Branch", code="alpha-b", lead_email="alpha@example.com", address="1 Road"
    )
    Asset.objects.create(
        asset_tag="ALPHA-1",
        category=category,
        site=other,
        status="AVAILABLE",
        condition="GOOD",
        serial_no="SN-ALPHA-1",
    )
    Asset.objects.create(
        asset_tag="YGN-1",
        category=category,
        site=site,
        status="AVAILABLE",
        condition="GOOD",
        serial_no="SN-YGN-1",
    )

    result = send_scheduled_reports(cadence="monthly")
    assert result == {"emails": 2}  # one per active site
    assert len(mail.outbox) == 2

    alpha = next(m for m in mail.outbox if "alpha@example.com" in m.to)  # site.lead_email
    yangon = next(m for m in mail.outbox if m.to == ["itlead@example.com"])  # fallback
    assert "Alpha Branch" in alpha.subject and site.name in yangon.subject

    # each snapshot is pinned to its own site (§4: "per site")
    alpha_csv = b"".join(_attachment_bytes(att) for att in alpha.attachments)
    assert b"alpha-b" in alpha_csv and site.code.encode() not in alpha_csv
    yangon_csv = b"".join(_attachment_bytes(att) for att in yangon.attachments)
    assert site.code.encode() in yangon_csv and b"alpha-b" not in yangon_csv

    # §15 idempotency: same month → one row per site, no resend
    assert send_scheduled_reports(cadence="monthly") == {"emails": 0}
    assert len(mail.outbox) == 2


def test_data_quality_report_lists_issues(asset_factory, site, settings_it_lead):
    from apps.assets.models import Asset
    from apps.audit.models import EmailAlert
    from apps.audit.tasks import data_quality_report

    asset_factory(serial="DUP-SN")  # first of the duplicate pair
    asset_factory(serial="DUP-SN")  # §13: duplicate serial numbers
    orphan = asset_factory(status=Asset.Status.ASSIGNED)  # ASSIGNED, no holder

    result = data_quality_report()
    assert result["missing_warranty"] >= 1  # factory assets carry no warranty
    assert result["missing_location"] >= 1  # site fixture has no address
    assert result["assigned_no_holder"] >= 1
    assert result["duplicate_serials"] == 1
    assert result["sent"] is True and result["period"]

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["itlead@example.com"]  # §14: issues → IT lead
    assert "Data-quality report" in msg.subject
    assert "DUP-SN" in msg.body  # serial examples rendered in the body
    assert orphan.asset_tag in msg.body  # holder examples = orphan report rows

    # monthly bucket idempotency
    assert data_quality_report()["sent"] is False
    assert len(mail.outbox) == 1
    assert EmailAlert.objects.filter(kind="data_quality").count() == 1


def test_daily_digest_counts_yesterday(settings):
    from apps.audit.models import ActivityLog
    from apps.audit.tasks import send_daily_digest

    settings.ADMIN_EMAIL = "admins@example.com"
    y = ActivityLog.record(actor=None, action="check_out", object_repr="DIGEST-1 → Person A")
    ActivityLog.record(actor=None, action="check_in", object_repr="DIGEST-1 back")
    # the check_out happened yesterday, the check_in just now → only yesterday counts
    ActivityLog.objects.filter(pk=y.pk).update(created_at=timezone.now() - timedelta(days=1))

    result = send_daily_digest()
    assert result == {"check_out": 1, "check_in": 0, "sent": True}
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["admins@example.com"]  # §14: daily digest → admins
    assert "Daily digest" in msg.subject
    assert "DIGEST-1" in msg.body  # activity lines rendered (either language)

    # §15 idempotency: same digest day → no resend
    assert send_daily_digest()["sent"] is False
    assert len(mail.outbox) == 1


def test_daily_digest_falls_back_to_it_lead(settings_it_lead):
    from apps.audit.tasks import send_daily_digest

    assert send_daily_digest()["sent"] is True
    assert mail.outbox[0].to == ["itlead@example.com"]  # no ADMIN_EMAIL → IT lead


def test_beat_schedule_covers_documented_tasks(settings):
    """Guard against doc/code drift: every §15 table row has a beat entry."""
    entries = list(settings.CELERY_BEAT_SCHEDULE.values())
    tasks = {e["task"] for e in entries}
    assert {
        "scan_warranties",
        "scan_license_seats",
        "scan_contracts",
        "scan_loans",
        "purge_activity_log",
        "data_quality_report",
        "send_daily_digest",
        "send_scheduled_reports",
    } <= tasks
    cadences = {
        e.get("kwargs", {}).get("cadence") for e in entries if e["task"] == "send_scheduled_reports"
    }
    assert cadences == {"weekly", "monthly"}  # both §4 schedules registered


def test_scheduled_reports_unknown_cadence_fails_loud():
    from apps.audit.tasks import send_scheduled_reports

    with pytest.raises(ValueError):
        send_scheduled_reports(cadence="yearly")


# ----------------------------------------------- §14 remaining notification rows
# request awaiting approval / loan overdue / damage / transfer exception.
# In-band sends are best-effort (never fail the business action); role lookup
# obeys deny-by-default scope, so an out-of-scope role holder is NOT told.


def _role_user(username, email, role, *, scoped=True):
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    user = get_user_model().objects.create_user(username, email, "pass12345!")
    if role:
        group, _ = Group.objects.get_or_create(name=role)
        user.groups.add(group)
    if scoped:
        UserAccessScope.objects.create(
            user=user,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="feature-test fixture (not a scope test)",
            created_by=user,
        )
    return user


def test_request_awaiting_approval_notifies_scoped_approvers(category, site):
    from apps.assets import services
    from apps.audit.models import EmailAlert

    _role_user("appr_scoped", "appr-scoped@x.com", "admin")
    _role_user("appr_zero", "appr-zero@x.com", "admin", scoped=False)  # zero-scope → silent
    requester = _role_user("req_user", "req-user@x.com", "viewer")

    req = services.create_request(requester=requester, category=category, site=site)

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert msg.to == ["appr-scoped@x.com"]  # role AND scope, nobody else (§5.2)
    assert "Approval needed" in msg.subject and category.name in msg.subject
    assert "REQ#" in msg.body  # the request renders in either language
    alert = EmailAlert.objects.get(kind="request_pending")
    assert alert.dedupe_key == f"request_pending:{req.pk}:step1"

    # idempotent bucket: re-notifying the same step sends nothing
    assert services.notify_pending_approvers(req) is False
    assert len(mail.outbox) == 1


def test_step_advance_notifies_next_step(category, site):
    from apps.assets import services
    from apps.assets.models import ApprovalRule
    from apps.audit.models import EmailAlert

    ApprovalRule.objects.create(name="tech step", step=1, required_role="technician")
    ApprovalRule.objects.create(name="admin step", step=2, required_role="admin")
    tech1 = _role_user("tech_one", "tech1@x.com", "technician")
    _role_user("tech_two", "tech2@x.com", "technician", scoped=False)  # out of scope
    admin = _role_user("boss_admin", "boss@x.com", "admin")
    requester = _role_user("req_two", "req2@x.com", "viewer")

    req = services.create_request(requester=requester, category=category, site=site)
    assert mail.outbox[0].to == ["tech1@x.com"]  # step 1 → in-scope technicians

    services.decide_request(req, approve=True, actor=tech1)  # chain advances
    assert req.status == "PENDING" and len(mail.outbox) == 2
    assert mail.outbox[1].to == ["boss@x.com"]  # step 2 → admins

    keys = set(EmailAlert.objects.values_list("dedupe_key", flat=True))
    assert f"request_pending:{req.pk}:step1" in keys
    assert f"request_pending:{req.pk}:step2" in keys

    # final approval leaves PENDING → nothing further to notify
    services.decide_request(req, approve=True, actor=admin)
    assert req.status == "APPROVED"
    assert services.notify_pending_approvers(req) is False
    assert len(mail.outbox) == 2


def test_loan_overdue_scan(category, site, person_factory, asset_factory):
    from apps.assets import services
    from apps.audit.models import EmailAlert
    from apps.audit.tasks import scan_loans

    tech = _role_user("issuer_tech", "issuer@x.com", "technician")
    holder = person_factory(employee_no="L1", name="Loan Holder", email="loan-holder@x.com")
    late = asset_factory()
    services.check_out(late, holder, actor=tech, due_at=timezone.now() - timedelta(days=4))
    # an ongoing loan with no due date promised → never alerts
    open_asset = asset_factory()
    services.check_out(
        open_asset,
        person_factory(employee_no="L2", name="Open Loan", email="open@x.com"),
        actor=tech,
    )

    assert scan_loans() == {"alerts": 1}
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert set(msg.to) == {"loan-holder@x.com", "issuer@x.com"}  # holder + issuing tech
    assert late.asset_tag in msg.subject and "4d" in msg.subject  # due + 4 overdue days

    # one bucket per assignment → catch-up runs send nothing more
    assert scan_loans() == {"alerts": 0}
    assert len(mail.outbox) == 1
    assert EmailAlert.objects.filter(kind="loan_overdue").count() == 1


def test_loan_overdue_counts_local_not_utc_days(category, site, person_factory, asset_factory):
    """days_overdue must use the local (Asia/Yangon) due date.

    A due time of 01:00 local sits on the *previous* UTC day, so a naive
    `.date()` on the raw UTC value reports 5d instead of 4d. Deterministic
    regardless of when the suite runs: the due timestamp is pinned to early
    local morning where UTC and local dates always disagree.
    """
    from datetime import datetime, time

    from apps.assets import services
    from apps.audit.tasks import scan_loans

    holder = person_factory(employee_no="LZ", name="TZ Holder", email="tz-holder@x.com")
    due = timezone.make_aware(
        datetime.combine(timezone.localdate() - timedelta(days=4), time(1, 0))
    )
    services.check_out(asset_factory(), holder, actor=None, due_at=due)

    assert scan_loans() == {"alerts": 1}
    msg = mail.outbox[0]
    assert "4d" in msg.subject, "overdue days must be counted on the local calendar"
    assert due.date().isoformat() in msg.body  # "Was due" shows the local date


def test_damage_report_notifies_scoped_techs_and_site_lead(
    category, site, asset_factory, monkeypatch
):
    from apps.assets import services
    from apps.audit.models import EmailAlert

    site.lead_email = "ygn-lead@x.com"
    site.save(update_fields=["lead_email"])
    _role_user("tech_inscope", "tech-in@x.com", "technician")
    _role_user("tech_out", "tech-out@x.com", "technician", scoped=False)
    actor = _role_user("bystander", "bystander@x.com", "viewer")
    asset = asset_factory()

    ticket = services.report_damage(asset=asset, actor=actor, description="cracked screen")
    assert ticket.pk
    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    assert set(msg.to) == {"tech-in@x.com", "ygn-lead@x.com"}  # scoped techs + site lead
    assert asset.asset_tag in msg.subject
    EmailAlert.objects.get(kind="damage_reported", dedupe_key=f"damage_report:{ticket.pk}")

    # SMTP outage must not fail the business action (in-band = best-effort)
    def boom(*args, **kwargs):
        raise RuntimeError("smtp down")

    monkeypatch.setattr("apps.audit.notify.send_mail", boom)
    ticket2 = services.report_damage(asset=asset_factory(), actor=actor, description="dead fan")
    assert ticket2.pk  # no exception surfaced
    # the failed send left no alert row → a later retry can still deliver
    assert not EmailAlert.objects.filter(dedupe_key=f"damage_report:{ticket2.pk}").exists()


def test_transfer_exception_notifies(category, site, asset_factory):
    from apps.assets import services
    from apps.assets.models import Transfer
    from apps.audit.models import EmailAlert
    from apps.people.models import Site

    dest = Site.objects.create(name="Dest Hub", code="dest-hub", lead_email="dest-lead@x.com")
    tech = _role_user("tx_tech", "tx-tech@x.com", "technician")  # global scope
    asset = asset_factory()
    transfer = Transfer.objects.create(from_site=site, to_site=dest)
    transfer.assets.add(asset)

    services.dispatch_transfer(transfer, actor=tech)
    got = services.receive_transfer(transfer, actor=tech, damaged_tags=[asset.asset_tag])
    assert got.status == Transfer.Status.EXCEPTION

    assert len(mail.outbox) == 1
    msg = mail.outbox[0]
    # destination-scoped technicians + destination site lead (§14)
    assert set(msg.to) == {"tx-tech@x.com", "dest-lead@x.com"}
    assert asset.asset_tag in msg.body  # the damaged tags are listed
    EmailAlert.objects.get(
        kind="transfer_exception", dedupe_key=f"transfer_exception:{transfer.pk}"
    )
