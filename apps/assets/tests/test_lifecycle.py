"""M6 lifecycle tests (DEVELOPMENT.md §3 eight-stage flow, §11 roles, §20).

Covers the full state machine in services.py: request → approve → procure →
fulfill (creates IN_STOCK asset), dispatch/receive transfer (IN_TRANSIT +
arrival-damage), report/resolve repair, write-off admin sign-off → RETIRED,
and the disposal guard (no DISPOSED without a completed DisposalRecord).
"""

import pytest
from django.contrib.auth.models import Group

from apps.assets import services
from apps.assets.models import Asset, AssetRequest, DisposalRecord, RepairTicket, Transfer

pytestmark = pytest.mark.django_db


@pytest.fixture
def roles(db):
    return {
        n: Group.objects.get_or_create(name=n)[0]
        for n in ("admin", "technician", "auditor", "viewer")
    }


def _user(django_user_model, roles, username, role):
    u = django_user_model.objects.create_user(username, f"{username}@x.com", "pass12345!")
    u.groups.add(roles[role])
    return u


@pytest.fixture
def actors(django_user_model, roles):
    return {
        "viewer": _user(django_user_model, roles, "lc_viewer", "viewer"),
        "tech": _user(django_user_model, roles, "lc_tech", "technician"),
        "admin": _user(django_user_model, roles, "lc_admin", "admin"),
    }


# ---------------------------------------------------------------- request flow
def test_request_approve_procure_fulfill(actors, site, category):
    viewer, tech, admin = actors["viewer"], actors["tech"], actors["admin"]

    # ① any user requests
    req = services.create_request(
        requester=viewer, category=category, site=site, quantity=1, justification="need a laptop"
    )
    assert req.status == AssetRequest.Status.PENDING

    # ② technician cannot approve — admin can (§11)
    with pytest.raises(services.NotAuthorized):
        services.decide_request(req, approve=True, actor=tech)
    services.decide_request(req, approve=True, actor=admin)
    assert req.status == AssetRequest.Status.APPROVED and req.approved_by == admin

    # ③ procure
    services.mark_procured(req, actor=admin, po_number="PO-001", supplier="ACME")
    assert req.status == AssetRequest.Status.PROCURED

    # ④ fulfill → creates the asset IN_STOCK
    [asset] = services.fulfill_request(req, actor=tech, specs=[{"asset_tag": "REQ-ASSET-1"}])
    assert asset.status == Asset.Status.IN_STOCK and asset.site == site
    req.refresh_from_db()
    assert req.status == AssetRequest.Status.FULFILLED
    assert req.assets.filter(pk=asset.pk).exists()


def test_viewer_cannot_approve(actors, site, category):
    req = services.create_request(requester=actors["viewer"], category=category, site=site)
    with pytest.raises(services.NotAuthorized):
        services.decide_request(req, approve=True, actor=actors["viewer"])


def test_reject_request(actors, site, category):
    admin = actors["admin"]
    req = services.create_request(requester=actors["viewer"], category=category, site=site)
    services.decide_request(req, approve=False, actor=admin, reason="budget")
    assert req.status == AssetRequest.Status.REJECTED and req.rejection_reason == "budget"


# ---------------------------------------------------------------- transfer
def test_dispatch_receive_transfer(actors, site, category):
    from apps.people.models import Site

    tech = actors["tech"]
    asset = Asset.objects.create(
        asset_tag="TR-1", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    dest = Site.objects.create(name="Dest", code="dest")
    tr = Transfer.objects.create(from_site=site, to_site=dest)
    tr.assets.add(asset)

    services.dispatch_transfer(tr, actor=tech)
    asset.refresh_from_db()
    assert asset.status == Asset.Status.IN_TRANSIT and tr.status == Transfer.Status.IN_TRANSIT

    services.receive_transfer(tr, actor=tech)
    asset.refresh_from_db()
    assert asset.site == dest and asset.status == Asset.Status.AVAILABLE
    assert tr.status == Transfer.Status.RECEIVED


def test_receive_transfer_with_damage(actors, site, category):
    from apps.people.models import Site

    tech = actors["tech"]
    asset = Asset.objects.create(
        asset_tag="TR-D", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    dest = Site.objects.create(name="Dest2", code="dest2")
    tr = Transfer.objects.create(from_site=site, to_site=dest)
    tr.assets.add(asset)
    services.dispatch_transfer(tr, actor=tech)
    services.receive_transfer(tr, actor=tech, damaged_tags=["TR-D"])

    asset.refresh_from_db()
    assert asset.status == Asset.Status.IN_REPAIR  # auto damage entry (§3)
    assert tr.status == Transfer.Status.EXCEPTION
    assert RepairTicket.objects.filter(asset=asset).exists()


# ---------------------------------------------------------------- repair
def test_report_and_resolve_repair(actors, site, category):
    tech = actors["tech"]
    asset = Asset.objects.create(
        asset_tag="RP-1", category=category, site=site, status=Asset.Status.ASSIGNED
    )

    ticket = services.report_damage(
        asset=asset, actor=tech, fault_category="screen", description="cracked"
    )
    asset.refresh_from_db()
    assert asset.status == Asset.Status.IN_REPAIR and ticket.outcome == RepairTicket.Outcome.OPEN

    services.resolve_repair(ticket, actor=tech, outcome=RepairTicket.Outcome.REPAIRED, cost=120)
    asset.refresh_from_db()
    assert asset.status == Asset.Status.AVAILABLE
    ticket.refresh_from_db()
    assert ticket.outcome == RepairTicket.Outcome.REPAIRED


def test_viewer_cannot_resolve_repair(actors, site, category):
    ticket = services.report_damage(
        asset=Asset.objects.create(asset_tag="RP-2", category=category, site=site),
        actor=actors["tech"],
    )
    with pytest.raises(services.NotAuthorized):
        services.resolve_repair(
            ticket, actor=actors["viewer"], outcome=RepairTicket.Outcome.REPAIRED
        )


# ---------------------------------------------------------------- write-off → dispose
def _retired_asset(category, site, tag):
    return Asset.objects.create(
        asset_tag=tag, category=category, site=site, status=Asset.Status.RETIRED
    )


def test_write_off_sign_off_retires(actors, site, category):
    from apps.assets.models import WriteOff

    tech, admin = actors["tech"], actors["admin"]
    asset = Asset.objects.create(
        asset_tag="WO-1", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    wo = WriteOff.objects.create(
        asset=asset, damage_date="2026-01-01", cause="wear", prepared_by=tech
    )

    # tech prepares but cannot decide (§11 admin-only)
    with pytest.raises(services.NotAuthorized):
        services.decide_write_off(wo, actor=tech, approve=True)

    services.decide_write_off(wo, actor=admin, approve=True)
    asset.refresh_from_db()
    assert asset.status == Asset.Status.RETIRED and wo.decided


def test_disposal_requires_completed_record(actors, site, category):
    tech, admin = actors["tech"], actors["admin"]

    # not RETIRED → guarded
    live = Asset.objects.create(
        asset_tag="DP-LIVE", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    with pytest.raises(services.DisposalGuardError):
        services.dispose_asset(asset=live, actor=admin, method="factory_reset")

    # tech cannot dispose (§11 admin-only)
    retired = _retired_asset(category, site, "DP-1")
    with pytest.raises(services.NotAuthorized):
        services.dispose_asset(asset=retired, actor=tech, method="factory_reset")

    # admin disposes a RETIRED asset → record + DISPOSED (§3 never DISPOSED without record)
    record = services.dispose_asset(
        asset=retired,
        actor=admin,
        method="crypto_erase",
        tool_used="blktool",
        certificate_no="CERT-1",
    )
    retired.refresh_from_db()
    assert retired.status == Asset.Status.DISPOSED
    assert isinstance(record, DisposalRecord) and record.verified_by is None
    assert DisposalRecord.objects.filter(asset=retired, certificate_no="CERT-1").exists()


def test_theft_write_off_still_needs_disposal_record(actors, site, category):
    """§3: theft → RETIRED(LOST/STOLEN), then sanitize N/A + dispose with record."""
    from apps.assets.models import WriteOff

    tech, admin = actors["tech"], actors["admin"]
    asset = Asset.objects.create(
        asset_tag="ST-1", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    wo = WriteOff.objects.create(
        asset=asset,
        damage_date="2026-02-01",
        cause="theft",
        police_report_no="PR-9",
        prepared_by=tech,
    )
    services.decide_write_off(wo, actor=admin, approve=True)
    asset.refresh_from_db()
    assert asset.status == Asset.Status.RETIRED

    record = services.dispose_asset(
        asset=asset, actor=admin, method="not_applicable", certificate_no="CERT-ST1"
    )
    asset.refresh_from_db()
    assert asset.status == Asset.Status.DISPOSED and record.method == "not_applicable"
