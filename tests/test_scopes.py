"""IDOR / scope-bypass tests (ITAM_Scope_RBAC_Design_v1.0 §6) + Stage B shadow.

Enforced tests force SCOPE_ENFORCEMENT_ENABLED=True (the Stage C gate); shadow
tests run with the default False and assert the UI is unchanged but a
scope_shadow_deny event is recorded for the Stage B review loop.

Shipped: #11 (transfer dispatch/receive API), #12/#13 (Django admin scoping,
Stage D), #21 (active-assignment partial unique index + race conversion,
plus a real-thread Postgres race), #15 (employee self-view: Person.user link
+ /me/ page + scope carve-out, design §4.4), #22 (self-approval: service
guard + /api/v1/requests/{id}/approve|reject/ → 403 over the wire), #23
(attachments module: scope-checked list/upload/download), and the transfer
write endpoints (POST/PATCH /api/v1/transfers/, sender-side scope gates), and #17/#20 (the
scope-write endpoint POST|DELETE /api/v1/users/{id}/scopes/: admin-only,
reason required, `scope_grant`/`scope_revoke` audit events — design §5.3).
All 23 rows of design §6 now have a test that runs against the real endpoint.
"""

from datetime import date, timedelta
from io import StringIO

import pytest
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from rest_framework.test import APIClient

from apps.assets.models import Asset, Category
from apps.audit.models import ActivityLog
from apps.core.models import UserAccessScope
from apps.core.scopes import SHADOW_ACTION, record_shadow
from apps.people.models import Department, Person, Site

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _shadow_default(settings):
    """Own the flag per test: the live server may set it to 1 in .env."""
    settings.SCOPE_ENFORCEMENT_ENABLED = False


@pytest.fixture
def sites(db):
    return (
        Site.objects.create(name="Site A", code="site-a"),
        Site.objects.create(name="Site B", code="site-b"),
    )


@pytest.fixture
def category(db):
    return Category.objects.create(code="IT-HW-LAP", name="Laptop")


@pytest.fixture
def assets(sites, category):
    site_a, site_b = sites
    return (
        Asset.objects.create(asset_tag="TAG-A-1", category=category, site=site_a),
        Asset.objects.create(asset_tag="TAG-B-1", category=category, site=site_b),
    )


def _user(django_user_model, username, *groups):
    u = django_user_model.objects.create_user(username, f"{username}@itasset.dev", "pass12345!")
    for name in groups:
        g, _ = Group.objects.get_or_create(name=name)
        u.groups.add(g)
    return u


def _grant(user, scope_type, *, site=None, department=None, valid_to=None):
    return UserAccessScope.objects.create(
        user=user,
        scope_type=scope_type,
        site=site,
        department=department,
        valid_to=valid_to,
        reason="fixture grant",
        created_by=user,
    )


@pytest.fixture
def tech_a(django_user_model, sites):
    u = _user(django_user_model, "tech-a", "technician")
    _grant(u, UserAccessScope.ScopeType.SITE, site=sites[0])
    return u


@pytest.fixture
def root(django_user_model):
    return django_user_model.objects.create_superuser("rootx", "rootx@itasset.dev", "pass12345!")


@pytest.fixture
def api():
    return APIClient()


@pytest.fixture
def staff_tech_a(django_user_model, sites):
    u = _user(django_user_model, "staff-tech-a", "technician")
    _grant(u, UserAccessScope.ScopeType.SITE, site=sites[0])
    u.is_staff = True
    u.user_permissions.add(
        Permission.objects.get(codename="view_asset", content_type__app_label="assets"),
        Permission.objects.get(codename="change_asset", content_type__app_label="assets"),
    )
    u.save()
    return u


# ---------------------------------------------------------------------------
# Stage C — enforced (SCOPE_ENFORCEMENT_ENABLED=True)
# ---------------------------------------------------------------------------


def test_list_isolation_html(client, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(tech_a)
    r = client.get(reverse("asset-list"))
    assert r.status_code == 200
    assert b"TAG-A-1" in r.content and b"TAG-B-1" not in r.content


def test_list_isolation_api(api, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    api.force_authenticate(tech_a)
    r = api.get("/api/v1/assets/")
    assert r.status_code == 200
    assert [row["asset_tag"] for row in r.data["results"]] == ["TAG-A-1"]


def test_detail_by_id_out_of_scope_is_404_html(client, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(tech_a)
    asset_a, asset_b = assets
    assert client.get(reverse("asset-detail", args=[asset_a.pk])).status_code == 200
    assert client.get(reverse("asset-detail", args=[asset_b.pk])).status_code == 404


def test_detail_by_id_out_of_scope_is_404_api(api, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    api.force_authenticate(tech_a)
    asset_a, asset_b = assets
    assert api.get(f"/api/v1/assets/{asset_a.asset_tag}/").status_code == 200
    assert api.get(f"/api/v1/assets/{asset_b.asset_tag}/").status_code == 404


def test_mutation_by_id_out_of_scope_is_404(client, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(tech_a)
    asset_a, asset_b = assets
    assert client.post(reverse("asset-check-out", args=[asset_b.pk]), {}).status_code == 404
    # own-site asset passes the scope gate (invalid person → safe redirect)
    assert client.post(reverse("asset-check-out", args=[asset_a.pk]), {}).status_code == 302


def test_mutation_by_id_out_of_scope_is_404_api(api, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    api.force_authenticate(tech_a)
    _, asset_b = assets
    r = api.post(f"/api/v1/assets/{asset_b.asset_tag}/check-out/", {"employee_no": "E-9"})
    assert r.status_code == 404


def test_forged_site_field_rejected(client, tech_a, sites, category, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(tech_a)
    site_a, site_b = sites
    payload = {
        "asset_tag": "FORGED-1",
        "category": category.pk,
        "status": Asset.Status.IN_STOCK,
        "condition": Asset.Condition.GOOD,
    }
    r = client.post(reverse("asset-create"), {**payload, "site": site_b.pk})
    assert r.status_code == 403
    assert not Asset.objects.filter(asset_tag="FORGED-1").exists()

    r2 = client.post(reverse("asset-create"), {**payload, "asset_tag": "OK-1", "site": site_a.pk})
    assert r2.status_code == 302  # redirect to list on success
    assert Asset.objects.filter(asset_tag="OK-1", site=site_a).exists()


def test_export_enforces_site_scope(client, tech_a, root, sites, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    client.force_login(tech_a)
    # global report without ?site= → 403 (would leak global rows)
    assert client.get("/reports/depreciation.xlsx").status_code == 403
    # report ignores ?site= → still global → 403
    assert client.get(f"/reports/depreciation.xlsx?site={site_a.pk}").status_code == 403
    # site-aware report pinned to own site → 200
    assert client.get(f"/reports/inventory-by-site.csv?site={site_a.pk}").status_code == 200
    # pinned to the other site → 403
    assert client.get(f"/reports/inventory-by-site.csv?site={site_b.pk}").status_code == 403
    # global-scope user unaffected
    client.force_login(root)
    assert client.get("/reports/depreciation.xlsx").status_code == 200


def test_scan_endpoint_scope_404(api, tech_a, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    api.force_authenticate(tech_a)
    asset_a, asset_b = assets
    assert api.get(f"/api/v1/scan/{asset_a.asset_tag}/").status_code == 200
    assert api.get(f"/api/v1/scan/{asset_b.asset_tag}/").status_code == 404


def test_zero_scope_user_denied_everywhere(client, django_user_model, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    u = _user(django_user_model, "zero-scope")
    client.force_login(u)
    asset_a, _ = assets
    r = client.get(reverse("asset-list"))
    assert r.status_code == 200 and b"TAG-" not in r.content
    assert client.get(reverse("asset-detail", args=[asset_a.pk])).status_code == 404


def test_expired_scope_denied(client, django_user_model, sites, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    u = _user(django_user_model, "expired-scope", "technician")
    _grant(
        u,
        UserAccessScope.ScopeType.SITE,
        site=sites[0],
        valid_to=date.today() - timedelta(days=1),
    )
    client.force_login(u)
    asset_a, _ = assets
    assert client.get(reverse("asset-detail", args=[asset_a.pk])).status_code == 404


def test_department_scope_people_list(client, django_user_model, sites, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    dept_a = Department.objects.create(name="Finance", site=site_a)
    dept_b = Department.objects.create(name="HR", site=site_b)
    Person.objects.create(employee_no="E-1", name="Alice", site=site_a, department=dept_a)
    Person.objects.create(employee_no="E-2", name="Bob", site=site_b, department=dept_b)
    u = _user(django_user_model, "deptuser", "viewer")
    _grant(u, UserAccessScope.ScopeType.DEPARTMENT, department=dept_a)
    client.force_login(u)
    r = client.get(reverse("person-list"))
    assert r.status_code == 200
    assert b"Alice" in r.content and b"Bob" not in r.content


def test_role_gate_applies_independently_of_scope(
    client, django_user_model, sites, assets, settings
):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    viewer = _user(django_user_model, "viewer-a", "viewer")
    _grant(viewer, UserAccessScope.ScopeType.SITE, site=sites[0])
    client.force_login(viewer)
    asset_a, _ = assets
    # read within scope: allowed (viewer role)
    assert client.get(reverse("asset-detail", args=[asset_a.pk])).status_code == 200
    # lifecycle action: wrong role → 403 (role gate, not scope)
    assert client.post(reverse("asset-check-out", args=[asset_a.pk]), {}).status_code == 403


def test_admin_changelist_scoped(client, staff_tech_a, assets, settings):
    """Design §6 row 12 — admin changelist shows only in-scope rows."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(staff_tech_a)
    r = client.get(reverse("admin:assets_asset_changelist"))
    assert r.status_code == 200
    assert b"TAG-A-1" in r.content and b"TAG-B-1" not in r.content


def test_admin_change_page_out_of_scope_404(client, staff_tech_a, assets, settings):
    """Design §6 row 13 — direct admin change URL for a foreign asset 404s."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    client.force_login(staff_tech_a)
    asset_a, asset_b = assets
    assert client.get(reverse("admin:assets_asset_change", args=[asset_a.pk])).status_code == 200
    assert client.get(reverse("admin:assets_asset_change", args=[asset_b.pk])).status_code == 404


# ---------------------------------------------------------------------------
# Transfers (design §10.6, IDOR row 11) + concurrency backstop (row 21)
# ---------------------------------------------------------------------------


def _transfer_with_asset(from_site, to_site, *assets):
    from apps.assets.models import Transfer

    t = Transfer.objects.create(from_site=from_site, to_site=to_site)
    for a in assets:
        t.assets.add(a)
    return t


def test_transfer_dispatch_out_of_scope_is_404(api, django_user_model, sites, assets, settings):
    """Row 11 — dispatch/receive on a foreign transfer (or foreign cargo)."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    tech = _user(django_user_model, "tech-transfer", "technician")
    _grant(tech, UserAccessScope.ScopeType.SITE, site=site_a)
    api.force_authenticate(tech)
    asset_a, asset_b = assets

    # from_site out of scope → 404
    t1 = _transfer_with_asset(site_b, site_a, asset_b)
    assert api.post(f"/api/v1/transfers/{t1.pk}/dispatch/").status_code == 404

    # from_site in scope but a carried asset is not → 404 (no foreign cargo)
    t2 = _transfer_with_asset(site_a, site_b, asset_a, asset_b)
    assert api.post(f"/api/v1/transfers/{t2.pk}/dispatch/").status_code == 404

    # receive requires the destination side → 404 for the sender
    t3 = _transfer_with_asset(site_a, site_b, asset_a)
    assert api.post(f"/api/v1/transfers/{t3.pk}/receive/").status_code == 404


def test_transfer_dispatch_receive_flow_scoped(
    api, django_user_model, root, sites, assets, settings
):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    tech_a = _user(django_user_model, "tech-ta", "technician")
    tech_b = _user(django_user_model, "tech-tb", "technician")
    _grant(tech_a, UserAccessScope.ScopeType.SITE, site=site_a)
    _grant(tech_b, UserAccessScope.ScopeType.SITE, site=site_b)
    asset_a = assets[0]
    t = _transfer_with_asset(site_a, site_b, asset_a)

    api.force_authenticate(tech_a)  # sender dispatches
    r = api.post(f"/api/v1/transfers/{t.pk}/dispatch/")
    assert r.status_code == 200 and r.json()["status"] == "IN_TRANSIT"
    asset_a.refresh_from_db()
    assert asset_a.status == "IN_TRANSIT"

    api.force_authenticate(tech_b)  # receiver confirms
    r2 = api.post(f"/api/v1/transfers/{t.pk}/receive/")
    assert r2.status_code == 200 and r2.json()["status"] == "RECEIVED"
    asset_a.refresh_from_db()
    assert asset_a.site_id == site_b.pk and asset_a.status == "AVAILABLE"

    # scope gate fires before the state guard for the sender now: the cargo
    # moved to site B → his re-dispatch is 404 (no foreign cargo). The pure
    # state guard (LIFECYCLE 409) is checked with a global-scope account.
    api.force_authenticate(tech_a)
    assert api.post(f"/api/v1/transfers/{t.pk}/dispatch/").status_code == 404
    api.force_authenticate(root)
    assert api.post(f"/api/v1/transfers/{t.pk}/dispatch/").status_code == 409


def test_transfer_list_scoped_to_involved_sites(api, django_user_model, sites, assets, settings):
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    tech = _user(django_user_model, "tech-tlist", "technician")
    _grant(tech, UserAccessScope.ScopeType.SITE, site=site_a)
    api.force_authenticate(tech)
    _transfer_with_asset(site_b, site_b, assets[1])  # foreign on both ends
    own = _transfer_with_asset(site_a, site_b, assets[0])

    r = api.get("/api/v1/transfers/")
    assert [row["id"] for row in r.data["results"]] == [own.pk]


def test_active_assignment_partial_unique_enforced(db, sites, category):
    """Row 21 (DB backstop): the database itself refuses a second active row."""
    from apps.assets.models import Assignment

    site = sites[0]
    asset = Asset.objects.create(asset_tag="RACE-1", category=category, site=site)
    person = Person.objects.create(employee_no="E-R1", name="Racer", site=site)
    Assignment.objects.create(asset=asset, to_person=person)
    with pytest.raises(IntegrityError), transaction.atomic():
        Assignment.objects.create(asset=asset, to_person=person)  # second active row


def test_concurrent_check_out_converts_integrity_error(db, monkeypatch, sites, category):
    """Row 21 (service): a lost race surfaces as AssetAlreadyAssigned (→409)."""
    from apps.assets import services

    site = sites[0]
    asset = Asset.objects.create(
        asset_tag="RACE-2", category=category, site=site, status=Asset.Status.AVAILABLE
    )
    person = Person.objects.create(employee_no="E-R2", name="Racer Two", site=site)
    services.check_out(asset, person, actor=None)
    # simulate the race window: the guard sees nothing, the DB disagrees
    monkeypatch.setattr(services, "active_assignment", lambda a: None)
    asset.status = Asset.Status.AVAILABLE
    with pytest.raises(services.AssetAlreadyAssigned):
        services.check_out(asset, person, actor=None)


# ---------------------------------------------------------------------------
# Employee self-view (design §4.4, IDOR row 15) + approval (row 22)
# ---------------------------------------------------------------------------


def test_employee_self_view_own_rows_only(client, django_user_model, sites, category, settings):
    """Row 15 — linked Person: own assignments/requests only; foreign detail 404."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    from apps.assets import services

    site_a, site_b = sites
    employee = _user(django_user_model, "emp-15")
    colleague = _user(django_user_model, "emp-16")
    person = Person.objects.create(employee_no="E-15", name="Employee", site=site_a, user=employee)
    other_person = Person.objects.create(
        employee_no="E-16", name="Colleague", site=site_a, user=colleague
    )
    mine = Asset.objects.create(
        asset_tag="SELF-A", category=category, site=site_a, status=Asset.Status.AVAILABLE
    )
    theirs = Asset.objects.create(
        asset_tag="SELF-B", category=category, site=site_b, status=Asset.Status.AVAILABLE
    )
    services.check_out(mine, person, actor=None)
    services.check_out(theirs, other_person, actor=None)
    services.create_request(requester=employee, category=category, site=site_a)
    services.create_request(requester=colleague, category=category, site=site_a)

    client.force_login(employee)
    # asset list → own rows only (no scope rows, no roles: deny-by-default + §4.4)
    r = client.get(reverse("asset-list"))
    assert r.status_code == 200
    assert b"SELF-A" in r.content and b"SELF-B" not in r.content
    # /me/ → exactly my assignment and my request
    r = client.get(reverse("self-view"))
    assert r.status_code == 200
    assert b"SELF-A" in r.content and b"SELF-B" not in r.content
    assert len(r.context["assignments"]) == 1
    assert [row.asset_id for row in r.context["assignments"]] == [mine.pk]
    assert len(r.context["requests"]) == 1
    assert r.context["requests"][0].requester_id == employee.pk
    # detail: my currently-assigned asset reads, the colleague's is 404
    assert client.get(reverse("asset-detail", args=[mine.pk])).status_code == 200
    assert client.get(reverse("asset-detail", args=[theirs.pk])).status_code == 404
    # no linked Person → nothing (the carve-out is the ONLY exception, §4.4)
    stranger = _user(django_user_model, "emp-17")
    client.force_login(stranger)
    assert len(client.get(reverse("self-view")).context["assignments"]) == 0
    assert len(client.get(reverse("self-view")).context["requests"]) == 0
    assert client.get(reverse("asset-detail", args=[mine.pk])).status_code == 404


def test_person_autolinked_on_login(client, django_user_model, sites, settings):
    """§4.4 resolution order: ldap_uid first, else a unique email — never guess."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a = sites[0]

    # unique email match → linked
    emp = _user(django_user_model, "emp-auto")
    by_email = Person.objects.create(
        employee_no="E-A1", name="By Email", site=site_a, email=emp.email
    )
    client.force_login(emp)  # force_login sends user_logged_in
    by_email.refresh_from_db()
    assert by_email.user_id == emp.pk

    # ldap_uid wins over an email candidate
    bob = _user(django_user_model, "ldapbob")
    uid_hit = Person.objects.create(
        employee_no="E-L1", name="By Uid", site=site_a, ldap_uid="ldapbob"
    )
    email_hit = Person.objects.create(
        employee_no="E-L2", name="By Email 2", site=site_a, email=bob.email
    )
    client.force_login(bob)
    uid_hit.refresh_from_db()
    email_hit.refresh_from_db()
    assert uid_hit.user_id == bob.pk
    assert email_hit.user_id is None

    # ambiguous email → no link (the link is a security boundary)
    dup = _user(django_user_model, "emp-dup")
    Person.objects.create(employee_no="E-D1", name="Dup One", site=site_a, email=dup.email)
    Person.objects.create(employee_no="E-D2", name="Dup Two", site=site_a, email=dup.email)
    client.force_login(dup)
    assert not Person.objects.filter(user=dup).exists()


def test_self_approval_forbidden(db, django_user_model, sites, category):
    """Row 22 — a requester never decides their own request (callers → 403)."""
    from apps.assets import services

    requester_admin = _user(django_user_model, "req-admin", "admin")
    peer_admin = _user(django_user_model, "req-peer", "admin")
    req = services.create_request(requester=requester_admin, category=category, site=sites[0])

    # NotAuthorized maps to 403 at the HTTP layer, so the subtype is the
    # design's expected status for row 22.
    assert issubclass(services.SelfApprovalForbidden, services.NotAuthorized)
    with pytest.raises(services.SelfApprovalForbidden):
        services.decide_request(req, approve=True, actor=requester_admin)
    with pytest.raises(services.SelfApprovalForbidden):
        services.decide_request(req, approve=False, actor=requester_admin, reason="nope")
    assert req.status == "PENDING"  # nothing changed

    # another admin may still decide it (segregation of duties, not a lock-out)
    services.decide_request(req, approve=False, actor=peer_admin, reason="budget")
    assert req.status == "REJECTED"


# ---------------------------------------------------------------------------
# Attachments (IDOR row 23) + transfer write endpoints + approval over the
# wire (row 22) + a real-thread concurrency run (row 21 on Postgres)
# ---------------------------------------------------------------------------

ATT_API = "/api/v1/attachments/"


def _upload(api, owner_field, owner, name="a.pdf"):
    return api.post(
        ATT_API,
        {owner_field: owner.pk, "file": SimpleUploadedFile(name, b"%PDF-1.4 payload")},
        format="multipart",
    )


def test_attachment_download_out_of_scope_is_404(api, django_user_model, sites, category, settings):
    """Row 23 — user B's token cannot fetch A's attachment by ID."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    site_a, site_b = sites
    tech_a = _user(django_user_model, "att-a", "technician")
    tech_b = _user(django_user_model, "att-b", "technician")
    _grant(tech_a, UserAccessScope.ScopeType.SITE, site=site_a)
    _grant(tech_b, UserAccessScope.ScopeType.SITE, site=site_b)
    asset_a = Asset.objects.create(asset_tag="ATT-A-1", category=category, site=site_a)

    api.force_authenticate(tech_a)
    created = _upload(api, "asset", asset_a, name="invoice-A.pdf")
    assert created.status_code == 201, created.data
    pk = created.data["id"]

    ok = api.get(f"{ATT_API}{pk}/download/")  # owning site → the file
    assert ok.status_code == 200 and "invoice-A.pdf" in ok["Content-Disposition"]

    api.force_authenticate(tech_b)  # other site → identical to nonexistent
    assert api.get(f"{ATT_API}{pk}/download/").status_code == 404
    assert api.get(f"{ATT_API}{pk}/").status_code == 404
    assert [row["id"] for row in api.get(ATT_API).data["results"]] == []


def test_attachment_visibility_follows_owner(api, django_user_model, sites, category, settings):
    """Row 23 extras: transfer attachments follow either end (v1 union rule,
    confirmed 2026-10-16); a zero-scope employee reaches the attachment on
    their own currently-assigned asset (§4.4 self-view)."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    from apps.assets import services

    site_a, site_b = sites
    site_c = Site.objects.create(name="Site C", code="site-c")
    techs = {}
    for name, site in (("ta", site_a), ("tb", site_b), ("tc", site_c)):
        techs[name] = _user(django_user_model, f"att-{name}", "technician")
        _grant(techs[name], UserAccessScope.ScopeType.SITE, site=site)

    moving = Asset.objects.create(
        asset_tag="ATT-T-1", category=category, site=site_a, status=Asset.Status.AVAILABLE
    )
    transfer = _transfer_with_asset(site_a, site_b, moving)
    api.force_authenticate(techs["ta"])
    pk = _upload(api, "transfer", transfer, name="note.pdf").data["id"]
    api.force_authenticate(techs["tb"])
    assert api.get(f"{ATT_API}{pk}/download/").status_code == 200  # receiver (union)
    api.force_authenticate(techs["tc"])
    assert api.get(f"{ATT_API}{pk}/download/").status_code == 404  # uninvolved site

    holder_user = _user(django_user_model, "att-holder")
    person = Person.objects.create(
        employee_no="E-ATT", name="Holder", site=site_a, user=holder_user
    )
    held = Asset.objects.create(
        asset_tag="ATT-H-1", category=category, site=site_a, status=Asset.Status.AVAILABLE
    )
    services.check_out(held, person, actor=None)
    api.force_authenticate(techs["ta"])
    own_pk = _upload(api, "asset", held, name="handover.pdf").data["id"]
    api.force_authenticate(holder_user)  # zero scopes, linked Person (§4.4)
    assert api.get(f"{ATT_API}{own_pk}/download/").status_code == 200


def test_transfer_create_and_edit_are_sender_scoped(
    api, django_user_model, sites, category, settings
):
    """Transfer write endpoints: forged site/cargo → 403; wrong state → 409;
    right scope but wrong role → 403; receiver may read but not edit."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    from apps.assets.models import Transfer

    site_a, site_b = sites
    tech_a = _user(django_user_model, "tw-a", "technician")
    tech_b = _user(django_user_model, "tw-b", "technician")
    viewer_a = _user(django_user_model, "tw-v", "viewer")
    for user, site in ((tech_a, site_a), (tech_b, site_b), (viewer_a, site_a)):
        _grant(user, UserAccessScope.ScopeType.SITE, site=site)
    mine = Asset.objects.create(
        asset_tag="TW-A-1", category=category, site=site_a, status=Asset.Status.AVAILABLE
    )
    foreign = Asset.objects.create(
        asset_tag="TW-B-1", category=category, site=site_b, status=Asset.Status.AVAILABLE
    )
    payload = {"from_site": site_a.pk, "to_site": site_b.pk, "asset_tags": [mine.asset_tag]}

    api.force_authenticate(tech_a)
    created = api.post("/api/v1/transfers/", payload, format="json")
    assert created.status_code == 201, created.data
    tid = created.data["id"]

    assert (
        api.post(
            "/api/v1/transfers/",
            {"from_site": site_b.pk, "to_site": site_a.pk, "asset_tags": [mine.asset_tag]},
            format="json",
        ).status_code
        == 403  # forged from_site
    )
    assert (
        api.post(
            "/api/v1/transfers/",
            {**payload, "asset_tags": [foreign.asset_tag]},
            format="json",
        ).status_code
        == 403  # foreign cargo
    )
    assert (
        api.post("/api/v1/transfers/", {**payload, "to_site": site_a.pk}, format="json").status_code
        == 400  # same site twice
    )
    assert Transfer.objects.count() == 1  # none of the rejects created a row

    api.force_authenticate(viewer_a)  # right scope, wrong role (row 19 pattern)
    assert api.post("/api/v1/transfers/", payload, format="json").status_code == 403

    api.force_authenticate(tech_b)
    # the receiver reads the transfer (union visibility) but edits are
    # sender-side: in-scope object, forbidden action → 403 (design §5.2)
    assert api.patch(f"/api/v1/transfers/{tid}/", {"tracking_no": "NOPE"}).status_code == 403

    api.force_authenticate(tech_a)
    edited = api.patch(f"/api/v1/transfers/{tid}/", {"tracking_no": "TRK-1"}, format="json")
    assert edited.status_code == 200 and edited.data["status"] == "PENDING"

    assert api.post(f"/api/v1/transfers/{tid}/dispatch/").status_code == 200
    assert (
        api.patch(f"/api/v1/transfers/{tid}/", {"tracking_no": "TRK-2"}, format="json").status_code
        == 409  # dispatched record is frozen (§3 trail)
    )

    api.force_authenticate(tech_b)  # union list visibility after the write
    assert tid in [row["id"] for row in api.get("/api/v1/transfers/").data["results"]]


def test_request_approval_over_the_wire(api, django_user_model, sites, category, settings):
    """Row 22 over HTTP: self-approval → 403, other admin → 200, non-admin →
    403, out-of-scope admin → 404, already decided → 409."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    from apps.assets import services

    site_a, site_b = sites
    requester_admin = _user(django_user_model, "ap-admin", "admin")
    peer_admin = _user(django_user_model, "ap-peer", "admin")
    tech = _user(django_user_model, "ap-tech", "technician")
    foreign_admin = _user(django_user_model, "ap-foreign", "admin")
    for user, site in (
        (requester_admin, site_a),
        (peer_admin, site_a),
        (tech, site_a),
        (foreign_admin, site_b),
    ):
        _grant(user, UserAccessScope.ScopeType.SITE, site=site)
    req = services.create_request(requester=requester_admin, category=category, site=site_a)

    api.force_authenticate(requester_admin)  # row 22: the wire says 403
    r = api.post(f"/api/v1/requests/{req.pk}/approve/")
    assert r.status_code == 403 and "self-approval" in r.json()["detail"]
    assert api.post(f"/api/v1/requests/{req.pk}/reject/", {"reason": "mine"}).status_code == 403

    api.force_authenticate(tech)  # role gate, not scope
    assert api.post(f"/api/v1/requests/{req.pk}/approve/").status_code == 403

    api.force_authenticate(foreign_admin)  # in role, out of scope → 404
    assert api.post(f"/api/v1/requests/{req.pk}/approve/").status_code == 404
    assert [row["id"] for row in api.get("/api/v1/requests/").data["results"]] == []

    api.force_authenticate(peer_admin)  # another admin may decide it
    r = api.post(f"/api/v1/requests/{req.pk}/approve/")
    assert r.status_code == 200 and r.json()["status"] == "APPROVED"
    assert api.post(f"/api/v1/requests/{req.pk}/approve/").status_code == 409  # already decided

    api.force_authenticate(peer_admin)  # scoped list shows it to site A only
    assert [row["id"] for row in api.get("/api/v1/requests/").data["results"]] == [req.pk]


def test_row17_scope_write_is_admin_only(api, tech_a, django_user_model, settings):
    """Row 17: no scope-write path is reachable by a non-admin — not to
    escalate self, not to escalate someone else, not to revoke (design §5.3)."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    target = _user(django_user_model, "row17-target")
    payload = {"scope_type": "GLOBAL", "reason": "self-escalation attempt"}
    own_scope = tech_a.access_scopes.get()

    api.force_authenticate(tech_a)  # technician, right scope, wrong role
    assert api.post(f"/api/v1/users/{tech_a.pk}/scopes/", payload, format="json").status_code == 403
    assert api.post(f"/api/v1/users/{target.pk}/scopes/", payload, format="json").status_code == 403
    assert api.get(f"/api/v1/users/{tech_a.pk}/scopes/").status_code == 403
    assert api.delete(f"/api/v1/users/{tech_a.pk}/scopes/{own_scope.pk}/").status_code == 403

    # nothing granted, nothing revoked, nothing audited as a scope change
    assert not UserAccessScope.objects.filter(user=target).exists()
    assert UserAccessScope.objects.filter(pk=own_scope.pk).exists()
    assert not ActivityLog.objects.filter(action__startswith="scope_").exists()

    # anonymous is refused even earlier (TokenAuthentication → 401, base.py)
    anon = APIClient()
    assert (
        anon.post(f"/api/v1/users/{tech_a.pk}/scopes/", payload, format="json").status_code == 401
    )


def test_row20_grant_requires_reason_and_is_audited(api, django_user_model, sites, settings):
    """Row 20: grant without a reason → 400 + no row + no audit; with one →
    201, created_by = acting admin, exactly one `scope_grant` event."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    granter = _user(django_user_model, "row20-admin", "admin")
    target = _user(django_user_model, "row20-target")
    api.force_authenticate(granter)
    site_payload = {"scope_type": "SITE", "site": sites[0].pk}

    assert (
        api.post(f"/api/v1/users/{target.pk}/scopes/", site_payload, format="json").status_code
        == 400
    )
    assert (
        api.post(
            f"/api/v1/users/{target.pk}/scopes/",
            {**site_payload, "reason": "   "},
            format="json",
        ).status_code
        == 400  # blank reason counts as missing
    )
    assert not UserAccessScope.objects.filter(user=target).exists()
    assert not ActivityLog.objects.filter(action="scope_grant").exists()

    # typed-column mismatch must be a 400, not an IntegrityError 500 (DB CHECK)
    assert (
        api.post(
            f"/api/v1/users/{target.pk}/scopes/",
            {"scope_type": "GLOBAL", "site": sites[0].pk, "reason": "typed"},
            format="json",
        ).status_code
        == 400
    )
    # inverted validity window → 400 (model clean), still no row
    assert (
        api.post(
            f"/api/v1/users/{target.pk}/scopes/",
            {
                **site_payload,
                "reason": "window",
                "valid_from": "2026-10-01",
                "valid_to": "2026-09-01",
            },
            format="json",
        ).status_code
        == 400
    )
    assert not UserAccessScope.objects.filter(user=target).exists()

    granted = api.post(
        f"/api/v1/users/{target.pk}/scopes/",
        {**site_payload, "reason": "contractor on site-a", "valid_to": "2026-12-31"},
        format="json",
    )
    assert granted.status_code == 201, granted.data
    scope = UserAccessScope.objects.get(user=target)
    assert scope.created_by == granter and scope.reason == "contractor on site-a"

    log = ActivityLog.objects.get(action="scope_grant")  # exactly one
    assert log.actor == granter
    assert log.details["target_user"] == "row20-target"
    assert log.details["reason"] == "contractor on site-a"
    assert log.details["site"] == sites[0].code


def test_row20_revoke_is_admin_only_and_audited(api, django_user_model, sites, settings):
    """Row 20 revocation half: admin DELETE → 204 + `scope_revoke`; another
    user's scope id must look exactly like a missing one (404, design §5.2)."""
    settings.SCOPE_ENFORCEMENT_ENABLED = True
    granter = _user(django_user_model, "revoker", "admin")
    target = _user(django_user_model, "revoked-target")
    stranger = _user(django_user_model, "revoked-stranger")
    scope = _grant(target, UserAccessScope.ScopeType.SITE, site=sites[0])

    api.force_authenticate(granter)
    # scoped under the wrong user → 404 (no cross-user scope poking)
    assert api.delete(f"/api/v1/users/{stranger.pk}/scopes/{scope.pk}/").status_code == 404
    assert UserAccessScope.objects.filter(pk=scope.pk).exists()

    r = api.delete(f"/api/v1/users/{target.pk}/scopes/{scope.pk}/")
    assert r.status_code == 204
    assert not UserAccessScope.objects.filter(pk=scope.pk).exists()
    log = ActivityLog.objects.get(action="scope_revoke")
    assert log.actor == granter and log.details["target_user"] == "revoked-target"
    assert log.details["scope_id"] == scope.pk


def test_concurrent_check_out_real_threads(transactional_db):
    """Row 21 (real race, Postgres): two live connections check_out at once —
    exactly one active assignment survives, driven by the DB index itself."""
    import threading

    from django.db import connections

    from apps.assets import services
    from apps.assets.models import Assignment
    from apps.people.models import Site

    if connections["default"].vendor != "postgresql":
        pytest.skip("real-thread race needs Postgres; sqlite serializes writes")

    site = Site.objects.create(name="Race Live", code="race-live")
    race_cat = Category.objects.create(code="IT-HW-RACE", name="Racer")
    asset = Asset.objects.create(
        asset_tag="RACE-LIVE", category=race_cat, site=site, status=Asset.Status.AVAILABLE
    )
    person = Person.objects.create(employee_no="E-RL", name="Racer Live", site=site)

    barrier = threading.Barrier(2, timeout=15)
    outcomes: list[str] = []

    def worker():
        try:
            barrier.wait()
            services.check_out(asset, person, actor=None)
            outcomes.append("assigned")
        except services.AssetAlreadyAssigned:
            outcomes.append("denied")
        except Exception as exc:  # pragma: no cover - surfaced by the assertion
            outcomes.append(f"unexpected:{type(exc).__name__}")
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert sorted(outcomes) == ["assigned", "denied"], outcomes
    assert Assignment.objects.filter(asset=asset, in_at__isnull=True).count() == 1
    asset.refresh_from_db()
    assert asset.status == Asset.Status.ASSIGNED


# ---------------------------------------------------------------------------
# Stage B — shadow mode (flag off): UI unchanged, would-deny events recorded
# ---------------------------------------------------------------------------


def test_shadow_list_allows_but_logs(client, tech_a, assets, settings):
    assert settings.SCOPE_ENFORCEMENT_ENABLED is False
    client.force_login(tech_a)
    r = client.get(reverse("asset-list"))
    assert r.status_code == 200
    assert b"TAG-A-1" in r.content and b"TAG-B-1" in r.content  # UI unchanged
    events = ActivityLog.objects.filter(action=SHADOW_ACTION, actor=tech_a)
    assert events.exists()
    assert events.first().details["would_hide"] >= 1


def test_shadow_detail_allows_but_logs(client, tech_a, assets, settings):
    assert settings.SCOPE_ENFORCEMENT_ENABLED is False
    client.force_login(tech_a)
    _, asset_b = assets
    r = client.get(reverse("asset-detail", args=[asset_b.pk]))
    assert r.status_code == 200  # shadow: unchanged behaviour
    assert ActivityLog.objects.filter(
        action=SHADOW_ACTION, actor=tech_a, object_repr__contains="TAG-B-1"
    ).exists()


def test_shadow_api_list_allows_but_logs(api, tech_a, assets, settings):
    assert settings.SCOPE_ENFORCEMENT_ENABLED is False
    api.force_authenticate(tech_a)
    r = api.get("/api/v1/assets/")
    assert {row["asset_tag"] for row in r.data["results"]} == {"TAG-A-1", "TAG-B-1"}
    assert ActivityLog.objects.filter(action=SHADOW_ACTION, actor=tech_a).exists()


def test_shadow_export_allows_but_logs(client, tech_a, assets, settings):
    assert settings.SCOPE_ENFORCEMENT_ENABLED is False
    client.force_login(tech_a)
    r = client.get("/reports/depreciation.xlsx")
    assert r.status_code == 200  # unchanged for everyone
    assert ActivityLog.objects.filter(
        action=SHADOW_ACTION, actor=tech_a, details__report="depreciation"
    ).exists()


def test_global_user_produces_no_shadow_events(client, root, assets, settings):
    assert settings.SCOPE_ENFORCEMENT_ENABLED is False
    client.force_login(root)
    client.get(reverse("asset-list"))
    client.get(reverse("asset-detail", args=[assets[0].pk]))
    assert not ActivityLog.objects.filter(action=SHADOW_ACTION).exists()


def test_shadow_report_command_summarises_events(db, django_user_model):
    u = _user(django_user_model, "shadower", "technician")
    record_shadow(u, action="asset_detail", path="/assets/1/", details={"would_hide": 1})
    record_shadow(u, action="asset_list", path="/assets/")
    out = StringIO()
    call_command("scope_shadow_report", stdout=out)
    text = out.getvalue()
    assert "shadower" in text
    assert "asset_list" in text and "asset_detail" in text


def test_shadow_report_command_clean_state(db):
    out = StringIO()
    call_command("scope_shadow_report", stdout=out)
    assert "no scope_shadow_deny events" in out.getvalue()
