"""Approval engine (gap §3.2 / Spec A §6.6) — templates, thresholds, steps,
immutable decision events.

Backward compatible by construction: with **no matching rule** the chain is
the legacy single admin step, which is exactly what the pre-engine tests
(`test_lifecycle.py`) already assert — they must stay green unchanged.
"""

from decimal import Decimal

import pytest
from django.contrib import admin as django_admin
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import RequestFactory
from rest_framework.test import APIClient

from apps.assets import services
from apps.assets.admin import ApprovalDecisionAdmin, ApprovalRuleAdmin
from apps.assets.models import ApprovalDecision, ApprovalRule, Category
from apps.audit.models import ActivityLog

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
def groups(db):
    return {
        n: Group.objects.get_or_create(name=n)[0]
        for n in ("admin", "technician", "auditor", "viewer")
    }


def _user(django_user_model, groups, username, role):
    u = django_user_model.objects.create_user(username, f"{username}@example.com", "pass12345!")
    u.groups.add(groups[role])
    return u


@pytest.fixture
def actors(django_user_model, groups):
    return {
        "requester": _user(django_user_model, groups, "ae_requester", "viewer"),
        "admin1": _user(django_user_model, groups, "ae_admin1", "admin"),
        "admin2": _user(django_user_model, groups, "ae_admin2", "admin"),
        "tech": _user(django_user_model, groups, "ae_tech", "technician"),
    }


@pytest.fixture
def make_request(site, category, actors):
    def _make(**extra):
        return services.create_request(
            requester=extra.pop("requester", actors["requester"]),
            category=extra.pop("category", category),
            site=extra.pop("site", site),
            **extra,
        )

    return _make


def _rule(name, step, **extra):
    return ApprovalRule.objects.create(name=name, step=step, **extra)


# --------------------------------------------------------------------------- default chain


def test_default_chain_is_the_legacy_single_admin_step(make_request, actors):
    """No rules → one implicit admin step (pre-engine behaviour, unchanged)."""
    req = make_request()
    steps = services.resolve_approval_steps(req)
    assert [(s["step"], s["rule"], s["required_role"]) for s in steps] == [(1, None, "admin")]

    admin1 = actors["admin1"]
    services.decide_request(req, approve=True, actor=admin1)
    assert req.status == req.Status.APPROVED and req.approved_by == admin1

    # …and the decision is still captured as an immutable event (rule=None)
    [event] = req.approval_decisions.all()
    assert event.step == 1
    assert event.action == ApprovalDecision.Action.APPROVE
    assert event.actor == admin1 and event.rule is None

    log = ActivityLog.objects.get(action="request_approve")
    assert log.actor == admin1
    assert log.details == {"reason": "", "step": 1, "steps_total": 1, "delegated_from": None}


def test_default_rejection_records_event_and_reason(make_request, actors):
    req = make_request()
    services.decide_request(req, approve=False, actor=actors["admin1"], reason="budget")
    assert req.status == req.Status.REJECTED and req.rejection_reason == "budget"
    [event] = req.approval_decisions.all()
    assert event.action == ApprovalDecision.Action.REJECT and event.comment == "budget"


# --------------------------------------------------------------------------- multi-step


def test_multi_step_chain_approves_in_order(make_request, actors):
    _rule("IT sign-off", step=1, required_role="admin")
    _rule("Finance sign-off", step=2, required_role="admin")
    req = make_request()
    assert len(services.resolve_approval_steps(req)) == 2

    services.decide_request(req, approve=True, actor=actors["admin1"])
    req.refresh_from_db()
    assert req.status == req.Status.PENDING  # intermediate step: not approved yet
    assert req.approved_by is None
    assert req.approval_decisions.count() == 1

    services.decide_request(req, approve=True, actor=actors["admin2"])
    req.refresh_from_db()
    assert req.status == req.Status.APPROVED and req.approved_by == actors["admin2"]
    assert [d.step for d in req.approval_decisions.all()] == [1, 2]


def test_same_person_may_not_cover_two_steps(make_request, actors):
    """Spec A §6.6 segregation of duties → 403 (`ApprovalSegregationError`)."""
    _rule("IT sign-off", step=1)
    _rule("Finance sign-off", step=2)
    req = make_request()
    admin1 = actors["admin1"]

    services.decide_request(req, approve=True, actor=admin1)
    with pytest.raises(services.ApprovalSegregationError):
        services.decide_request(req, approve=True, actor=admin1)
    assert issubclass(services.ApprovalSegregationError, services.NotAuthorized)

    req.refresh_from_db()
    assert req.status == req.Status.PENDING
    assert req.approval_decisions.count() == 1  # nothing was double-written


def test_each_step_gates_on_its_own_role(make_request, actors):
    _rule("IT sign-off", step=1, required_role="admin")
    _rule("Technician verification", step=2, required_role="technician")
    req = make_request()

    # wrong role for step 1 → NotAuthorized (maps to 403 over HTTP)
    with pytest.raises(services.NotAuthorized):
        services.decide_request(req, approve=True, actor=actors["tech"])

    services.decide_request(req, approve=True, actor=actors["admin1"])
    # admin has no technician role → cannot close step 2
    with pytest.raises(services.NotAuthorized):
        services.decide_request(req, approve=True, actor=actors["admin1"])

    services.decide_request(req, approve=True, actor=actors["tech"])
    req.refresh_from_db()
    assert req.status == req.Status.APPROVED
    assert req.approved_by == actors["tech"]


def test_rejection_is_final_at_any_step(make_request, actors):
    _rule("IT sign-off", step=1)
    _rule("Finance sign-off", step=2)
    req = make_request()

    services.decide_request(req, approve=True, actor=actors["admin1"])
    services.decide_request(req, approve=False, actor=actors["admin2"], reason="too expensive")
    req.refresh_from_db()
    assert req.status == req.Status.REJECTED
    assert req.rejection_reason == "too expensive"
    assert [d.action for d in req.approval_decisions.all()] == [
        ApprovalDecision.Action.APPROVE,
        ApprovalDecision.Action.REJECT,
    ]

    with pytest.raises(services.RequestStateError):
        services.decide_request(req, approve=True, actor=actors["admin1"])


# --------------------------------------------------------------------------- matching


def test_rules_match_by_quantity_site_and_category(make_request, actors, site):
    big = _rule("Bulk order sign-off", step=1, min_quantity=3)
    elsewhere = _rule("Mandalay only", step=2, site=site)  # site matches this request
    other_category = Category.objects.get_or_create(code="IT-HW-SRV", defaults={"name": "Server"})[
        0
    ]
    _rule("Servers only", step=3, category=other_category)  # must NOT match below

    small = make_request(quantity=1)
    # big (min_quantity 3) and wrong_cat do not match; elsewhere does
    assert [s["rule"] for s in services.resolve_approval_steps(small)] == [elsewhere]

    bulk = make_request(quantity=5)
    assert [s["rule"] for s in services.resolve_approval_steps(bulk)] == [big, elsewhere]


def test_amount_threshold_only_matches_when_the_cost_is_known(make_request):
    costly = _rule("Over 1000 sign-off", step=1, min_amount=Decimal("1000.00"))

    unknown = make_request()
    assert costly not in [s["rule"] for s in services.resolve_approval_steps(unknown)]

    unknown.estimated_cost = Decimal("1500.00")
    unknown.save()
    assert costly in [s["rule"] for s in services.resolve_approval_steps(unknown)]

    cheap = make_request()
    cheap.estimated_cost = Decimal("10.00")
    cheap.save()
    assert costly not in [s["rule"] for s in services.resolve_approval_steps(cheap)]


def test_inactive_rules_are_ignored(make_request):
    _rule("Paused sign-off", step=1, active=False)
    req = make_request()
    assert services.resolve_approval_steps(req) == [
        {"step": 1, "rule": None, "required_role": "admin"}
    ]


# --------------------------------------------------------------------------- immutability


def test_decisions_are_append_only(make_request, actors):
    req = make_request()
    services.decide_request(req, approve=True, actor=actors["admin1"])
    event = req.approval_decisions.get()

    event.comment = "rewritten history"
    with pytest.raises(ValidationError):
        event.save()
    event.refresh_from_db()
    assert event.comment == ""  # unchanged

    # one decision per step is a DB guarantee, not just app code
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            ApprovalDecision.objects.create(
                request=req, step=1, action=ApprovalDecision.Action.APPROVE, actor=actors["admin2"]
            )


def test_decision_admin_is_read_only(db, actors, django_user_model):
    root = django_user_model.objects.create_superuser("ae_root", "ae_root@x.com", "pass12345!")
    request = RequestFactory().get("/admin/assets/approvaldecision/")
    request.user = root
    model_admin = ApprovalDecisionAdmin(ApprovalDecision, django_admin.site)

    assert model_admin.has_add_permission(request) is False
    assert model_admin.has_change_permission(request) is False
    assert model_admin.has_delete_permission(request) is False


def test_rule_admin_is_gated_to_admin_role(db, django_user_model, groups):
    boss = _user(django_user_model, groups, "ae_boss", "admin")
    tech = _user(django_user_model, groups, "ae_ruletech", "technician")
    boss.is_staff = tech.is_staff = True
    boss.save()
    tech.save()
    model_admin = ApprovalRuleAdmin(ApprovalRule, django_admin.site)

    boss_request = RequestFactory().get("/admin/assets/approvalrule/")
    boss_request.user = boss
    tech_request = RequestFactory().get("/admin/assets/approvalrule/")
    tech_request.user = tech

    assert model_admin.has_add_permission(boss_request) is True
    assert model_admin.has_module_permission(tech_request) is False
    assert model_admin.has_add_permission(tech_request) is False


# --------------------------------------------------------------------------- over the wire


def _grant_global(user):
    from apps.core.models import UserAccessScope

    UserAccessScope.objects.create(
        user=user,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=user,
    )


def test_approvals_endpoint_reports_chain_and_trail(
    actors, make_request, django_user_model, groups
):
    """GET /api/v1/requests/{id}/approvals/ → chain, current step, events."""
    admin1, admin2 = actors["admin1"], actors["admin2"]
    for user in (admin1, admin2):
        _grant_global(user)

    _rule("IT sign-off", step=1)
    _rule("Finance sign-off", step=2)
    req = make_request()

    api = APIClient()
    api.force_authenticate(admin1)
    r = api.get(f"/api/v1/requests/{req.pk}/approvals/")
    assert r.status_code == 200, r.data
    assert r.data["status"] == "PENDING"
    assert r.data["steps_total"] == 2 and r.data["current_step"] == 1
    assert [c["required_role"] for c in r.data["chain"]] == ["admin", "admin"]
    assert r.data["decisions"] == []

    assert api.post(f"/api/v1/requests/{req.pk}/approve/").status_code == 200
    # the same approver cannot close step 2 (403 over the wire)
    again = api.post(f"/api/v1/requests/{req.pk}/approve/")
    assert again.status_code == 403 and "segregation" in again.json()["detail"]

    api.force_authenticate(admin2)
    done = api.post(f"/api/v1/requests/{req.pk}/approve/")
    assert done.status_code == 200 and done.json()["status"] == "APPROVED"

    trail = api.get(f"/api/v1/requests/{req.pk}/approvals/")
    assert trail.status_code == 200
    assert trail.data["current_step"] == trail.data["steps_total"] == 2
    assert [d["actor"] for d in trail.data["decisions"]] == ["ae_admin1", "ae_admin2"]
    assert [d["step"] for d in trail.data["decisions"]] == [1, 2]

    # anonymous is refused
    assert APIClient().get(f"/api/v1/requests/{req.pk}/approvals/").status_code == 401


def test_approvals_endpoint_out_of_scope_is_404(actors, make_request, django_user_model, groups):
    """Scope enforcement keeps the trail behind the same wall as the request."""
    from django.test import override_settings

    from apps.core.models import UserAccessScope
    from apps.people.models import Site

    admin1 = actors["admin1"]
    foreign_site = Site.objects.create(name="Mandalay", code="mdy")
    req = make_request(site=foreign_site)  # outside admin1's site
    UserAccessScope.objects.create(
        user=admin1,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=Site.objects.get(code="yangon"),
        reason="feature-test fixture (not a scope test)",
        created_by=admin1,
    )

    api = APIClient()
    api.force_authenticate(admin1)
    with override_settings(SCOPE_ENFORCEMENT_ENABLED=True):
        assert api.get(f"/api/v1/requests/{req.pk}/approvals/").status_code == 404
        assert api.get("/api/v1/requests/").status_code == 200
        assert [row["id"] for row in api.get("/api/v1/requests/").data["results"]] == []
