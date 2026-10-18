"""Approval delegation (gap §3.2, Spec A §6.6 extension — shipped 2026-10-17).

A delegate may exercise the *delegator's* role for a step while the window
covers today; decisions record `delegated_from`; segregation-of-duties counts
principals (one human — directly or via proxy — never covers two steps); a
delegation never widens authority and never enables self-approval by proxy.
"""

import pytest
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PASSWORD = "Str0ngPass!23"


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def group_setup(db):
    from django.contrib.auth.models import Group

    return {n: Group.objects.get_or_create(name=n)[0] for n in ("admin", "technician", "viewer")}


def _user(django_user_model, group_setup, name, role=None):
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(f"del_{name}", f"{name}@x.com", PASSWORD)
    if role:
        u.groups.add(group_setup[role])
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="delegation-test fixture",
        created_by=u,
    )
    return u


def _rules():
    """Chain: step 1 technician, step 2 admin (matches every request)."""
    from apps.assets.models import ApprovalRule

    ApprovalRule.objects.create(name="tech step", step=1, required_role="technician")
    ApprovalRule.objects.create(name="admin step", step=2, required_role="admin")


def _delegate_row(delegator, delegate, **extra):
    from apps.assets.models import ApprovalDelegation

    return ApprovalDelegation.objects.create(
        delegator=delegator, delegate=delegate, reason="on leave", **extra
    )


def _approve(api, user, pk, expect_status=200):
    api.logout()
    api.login(username=user.username, password=PASSWORD)
    r = api.post(f"/api/v1/requests/{pk}/approve/", {"reason": "ok"}, format="json")
    assert r.status_code == expect_status, f"{r.status_code}: {getattr(r, 'data', r.content)}"
    return r


# --------------------------------------------------------------------------- happy path


def test_delegate_without_delegation_is_denied(api, django_user_model, group_setup, category, site):
    from apps.assets.models import AssetRequest

    _rules()
    boss = _user(django_user_model, group_setup, "boss", "admin")
    tech = _user(django_user_model, group_setup, "tech", "technician")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)

    r = _approve(api, delegate, req.pk, expect_status=403)
    assert "technician" in str(r.data["detail"])  # the required role is named
    # sanity: the legitimate holders still pass step 1
    _approve(api, tech, req.pk)
    _approve(api, boss, req.pk)


def test_delegation_grants_the_step_and_is_recorded(
    api, django_user_model, group_setup, category, site
):
    from apps.assets.models import AssetRequest
    from apps.audit.models import ActivityLog

    _rules()
    tech = _user(django_user_model, group_setup, "tech", "technician")
    boss = _user(django_user_model, group_setup, "boss", "admin")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate)

    r = _approve(api, delegate, req.pk)
    assert r.json()["status"] == "PENDING"  # step 2 still open

    trail = api.get(f"/api/v1/requests/{req.pk}/approvals/").json()["decisions"]
    assert trail[0]["actor"] == "del_delegate"
    assert trail[0]["delegated_from"] == "del_tech"
    assert trail[0]["step"] == 1

    event = ActivityLog.objects.filter(action="request_approve", object_id=req.pk).latest(
        "created_at"
    )
    assert event.details["delegated_from"] == "del_tech"

    _approve(api, boss, req.pk)  # step 2 unchanged: admin, no delegation needed
    req.refresh_from_db()
    assert req.status == "APPROVED"


def test_delegation_never_widens_beyond_the_delegator(
    api, django_user_model, group_setup, category, site
):
    from apps.assets.models import AssetRequest

    _rules()  # step 2 needs admin; the technician delegator does not have it
    tech = _user(django_user_model, group_setup, "tech", "technician")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate)

    _approve(api, tech, req.pk)  # step 1 done legitimately
    _approve(api, delegate, req.pk, expect_status=403)  # step 2 needs admin — nope


# --------------------------------------------------------------------------- windows / active


def test_expired_delegation_is_denied(api, django_user_model, group_setup, category, site):
    from datetime import date, timedelta

    from apps.assets.models import AssetRequest

    _rules()
    tech = _user(django_user_model, group_setup, "tech", "technician")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate, valid_to=date.today() - timedelta(days=1))

    _approve(api, delegate, req.pk, expect_status=403)


def test_inactive_delegation_is_denied(api, django_user_model, group_setup, category, site):
    from apps.assets.models import AssetRequest

    _rules()
    tech = _user(django_user_model, group_setup, "tech", "technician")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate, active=False)

    _approve(api, delegate, req.pk, expect_status=403)


def test_delegator_must_hold_the_role(api, django_user_model, group_setup, category, site):
    from apps.assets.models import AssetRequest

    _rules()
    # delegator is a viewer — no technician role to lend
    lender = _user(django_user_model, group_setup, "lender", "viewer")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(lender, delegate)

    _approve(api, delegate, req.pk, expect_status=403)


# --------------------------------------------------------------------------- segregation + proxy


def test_segregation_counts_principals(api, django_user_model, group_setup, category, site):
    """One human never covers two steps — directly or through a delegate."""
    from apps.assets.models import ApprovalRule, AssetRequest

    ApprovalRule.objects.create(name="tech step A", step=1, required_role="technician")
    ApprovalRule.objects.create(name="tech step B", step=2, required_role="technician")
    tech = _user(django_user_model, group_setup, "tech", "technician")
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    requester = _user(django_user_model, group_setup, "requester")
    req = AssetRequest.objects.create(requester=requester, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate)

    _approve(api, delegate, req.pk)  # step 1 under delegation — principal: tech
    _approve(api, delegate, req.pk, expect_status=403)  # same human again
    _approve(api, tech, req.pk, expect_status=403)  # the delegator themselves


def test_requester_cannot_approve_by_proxy(api, django_user_model, group_setup, category, site):
    from apps.assets.models import AssetRequest

    _rules()
    tech = _user(django_user_model, group_setup, "tech", "technician")  # the requester
    delegate = _user(django_user_model, group_setup, "delegate", "viewer")
    req = AssetRequest.objects.create(requester=tech, category=category, site=site, quantity=1)
    _delegate_row(tech, delegate)

    r = _approve(api, delegate, req.pk, expect_status=403)
    assert "delegat" in str(r.data["detail"]).lower() or "own" in str(r.data["detail"]).lower()
