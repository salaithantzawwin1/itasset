"""Report export tests (DEVELOPMENT.md §4, §20).

Every registered report must execute against a seeded DB without raising and
return a well-formed payload in each of its declared formats. We also check the
content-type/filename wiring and that a report with an unsupported format is
refused rather than silently mangled. The API export-job endpoint
(/api/v1/exports/, §10.8 / gap §3.5) is covered at the bottom: roundtrip,
400/403 envelopes, owner-scoped downloads, pruning and FAILED rows.
"""

import inspect

import pytest
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from apps.reports import queries
from apps.reports.exporters import REGISTRY, export

pytestmark = pytest.mark.django_db


def _run(report, site):
    """Call a query with only the kwargs it declares (most are global reports)."""
    kwargs = {"request": None}
    if "site" in inspect.signature(report.query).parameters:
        kwargs["site"] = site
    return report.query(**kwargs)


@pytest.fixture(autouse=True)
def _registry():
    if not REGISTRY:
        queries._register_all()
    yield


def _seed(site, category):
    from apps.assets.models import Asset, Assignment
    from apps.people.models import Person

    holder = Person.objects.create(employee_no="R-1", name="Rep Holder", site=site)
    a1 = Asset.objects.create(
        asset_tag="RPT-1",
        category=category,
        site=site,
        status="AVAILABLE",
        cost=1000,
        warranty_end="2026-01-01",
    )
    a2 = Asset.objects.create(
        asset_tag="RPT-2",
        category=category,
        site=site,
        status="ASSIGNED",
        cost=2000,
        warranty_end="2026-12-31",
    )
    Assignment.objects.create(asset=a2, to_person=holder)
    return a1, a2


def test_all_reports_execute_clean(site, category):
    _seed(site, category)
    assert REGISTRY, "registry must be populated"
    for slug, report in REGISTRY.items():
        headers, rows = _run(report, site)
        assert isinstance(headers, list) and headers, f"{slug} returned no headers"
        assert isinstance(rows, list), f"{slug} rows not a list"


def test_each_format_renders_bytes(site, category):
    _seed(site, category)
    for slug, report in REGISTRY.items():
        headers, rows = _run(report, site)
        for fmt in report.formats:
            content, ctype, filename = export(fmt, report.title, headers, rows)
            assert isinstance(content, bytes) and len(content) > 0, f"{slug}.{fmt} empty"
            assert filename.endswith(f".{fmt}")
            if fmt == "csv":
                # CSV starts with a UTF-8 BOM (Excel-friendly export, §4)
                assert (
                    b"\xef\xbb\xbf" + headers[0].encode() in content
                    or headers[0].encode() in content
                )
            elif fmt == "xlsx":
                assert content[:2] == b"PK"  # zip magic
            elif fmt == "pdf":
                assert content.startswith(b"%PDF")


def test_export_refuses_unknown_format(site, category):
    _seed(site, category)
    report = REGISTRY["inventory-by-site"]
    with pytest.raises(ValueError):
        export("docx", report.title, *_run(report, site))


def test_report_index_and_export_view(client, django_user_model, site, category):
    from django.contrib.auth.models import Group

    _seed(site, category)
    Group.objects.get_or_create(name="viewer")
    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user("rpt_u", "r@x.com", "pass12345!")
    u.groups.add(Group.objects.get(name="viewer"))
    # Feature test, not a scope test: GLOBAL scope keeps enforcement
    # transparent (deny-by-default cases live in tests/test_scopes.py).
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    client.force_login(u)

    r = client.get("/reports/")
    assert r.status_code == 200

    r = client.get("/reports/warranty-expiring.csv")
    assert r.status_code == 200
    assert r["Content-Type"].startswith("text/csv")
    assert "attachment" in r["Content-Disposition"]


def test_report_requires_login(client, site, category):
    _seed(site, category)
    r = client.get("/reports/")
    assert r.status_code == 302 and "login" in r.headers["Location"]


def test_html_unknown_report_is_404(client, django_user_model, site, category):
    from apps.core.models import UserAccessScope

    _seed(site, category)
    u = django_user_model.objects.create_user("rpt_404", "r4@x.com", "pass12345!")
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    client.force_login(u)
    assert client.get("/reports/nope-nope.csv").status_code == 404


def test_check_activity_shows_the_checkout_operator(django_user_model, site, category):
    """'By (out)' comes from the check-out event's actor — and must not touch
    `.username` on a Person (Assignment.assigned_by is a Person: every real
    checkout used to crash this report with AttributeError)."""
    from apps.assets import services
    from apps.assets.models import Asset
    from apps.people.models import Person

    _seed(site, category)
    operator = django_user_model.objects.create_user("act_tech", "act_tech@x.com", "pw123456!")
    holder = Person.objects.create(employee_no="ACT-1", name="Act Holder", site=site)
    asset = Asset.objects.create(
        asset_tag="ACT-OUT-1",
        category=category,
        site=site,
        status="AVAILABLE",
        condition="GOOD",
        serial_no="SN-ACT-1",
    )
    services.check_out(asset, holder, actor=operator)

    headers, rows = queries.check_activity()
    assert rows, "the fresh check-out must be in the 30-day window"
    first = next(r for r in rows if r[0] == "ACT-OUT-1")
    assert first[-1] == "act_tech"  # operator's username, not the holder's name


# ---------------------------------------------------------------------------
# API export jobs (§10.8, gap §3.5) — one shared scope gate with the views
# ---------------------------------------------------------------------------


def _api_user(django_user_model, username, *groups):
    """User with GLOBAL scope: the gate stays transparent, as in the view test."""
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope

    u = django_user_model.objects.create_user(username, f"{username}@itasset.dev", "pass12345!")
    for g in groups:
        grp, _ = Group.objects.get_or_create(name=g)
        u.groups.add(grp)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        reason="feature-test fixture (not a scope test)",
        created_by=u,
    )
    return u


def test_export_job_create_list_download(django_user_model, site, category):
    from apps.audit.models import ActivityLog

    _seed(site, category)
    u = _api_user(django_user_model, "exp_owner")
    api = APIClient()
    api.force_authenticate(u)

    r = api.post(
        "/api/v1/exports/", {"report": "warranty-expiring", "format": "csv"}, format="json"
    )
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["status"] == "READY" and body["report"] == "warranty-expiring"
    assert isinstance(body["row_count"], int) and body["download"]
    job_id = body["id"]

    # audit: every export is an ops-visible event (§10.8 evidence)
    assert ActivityLog.objects.filter(action="export_create", actor=u).exists()

    listed = api.get("/api/v1/exports/").json()
    assert job_id in [row["id"] for row in listed["results"]]

    dl = api.get(f"/api/v1/exports/{job_id}/download/")
    assert dl.status_code == 200
    assert dl["Content-Type"].startswith("text/csv")
    assert "attachment" in dl["Content-Disposition"]
    payload = b"".join(dl.streaming_content)  # FileResponse streams
    assert b"Warranty" in payload  # headers made it into the file


def test_export_job_unknown_report_400(django_user_model, site, category):
    from apps.reports.models import ExportJob

    u = _api_user(django_user_model, "exp_bad_slug")
    api = APIClient()
    api.force_authenticate(u)
    r = api.post("/api/v1/exports/", {"report": "does-not-exist", "format": "csv"}, format="json")
    assert r.status_code == 400
    body = r.json()
    assert "unknown report" in body["detail"]
    assert body["code"] and body["correlationId"]  # §10.9 envelope (not a field-error dict)
    assert not ExportJob.objects.filter(requested_by=u).exists()  # no dirty rows


def test_export_job_unsupported_format_400(django_user_model, site, category):
    from apps.reports.models import ExportJob

    u = _api_user(django_user_model, "exp_bad_fmt")
    api = APIClient()
    api.force_authenticate(u)
    # asset-aging is an xlsx-only report — csv must be refused before any query
    r = api.post("/api/v1/exports/", {"report": "asset-aging", "format": "csv"}, format="json")
    assert r.status_code == 400
    assert "not supported" in r.json()["detail"]
    assert r.json()["correlationId"]
    assert not ExportJob.objects.filter(requested_by=u).exists()  # rejected before any query


def test_export_job_scope_gate_403(django_user_model, settings, site, category):
    from django.contrib.auth.models import Group

    from apps.core.models import UserAccessScope
    from apps.people.models import Site
    from apps.reports.models import ExportJob

    _seed(site, category)
    other_site = Site.objects.create(name="Other Site", code="other-site")
    settings.SCOPE_ENFORCEMENT_ENABLED = True

    u = django_user_model.objects.create_user("exp_tech", "et@x.com", "pass12345!")
    grp, _ = Group.objects.get_or_create(name="technician")
    u.groups.add(grp)
    UserAccessScope.objects.create(
        user=u,
        scope_type=UserAccessScope.ScopeType.SITE,
        site=site,
        reason="scope-gate test",
        created_by=u,
    )
    api = APIClient()
    api.force_authenticate(u)

    # no site pinned → not an in-scope-site report → 403 before any query
    r = api.post(
        "/api/v1/exports/", {"report": "inventory-by-site", "format": "csv"}, format="json"
    )
    assert r.status_code == 403
    assert "detail" in r.json() and "correlationId" in r.json()

    # pinned to a foreign site → 403 (same gate as the HTML export views)
    r = api.post(
        "/api/v1/exports/",
        {"report": "inventory-by-site", "format": "csv", "site": other_site.pk},
        format="json",
    )
    assert r.status_code == 403 and "outside your scope" in r.json()["detail"]

    # in-scope site passes
    r = api.post(
        "/api/v1/exports/",
        {"report": "inventory-by-site", "format": "csv", "site": site.pk},
        format="json",
    )
    assert r.status_code == 201, r.content
    assert ExportJob.objects.filter(requested_by=u).count() == 1  # only the pass created a row


def test_export_jobs_owner_scoped(django_user_model, site, category):
    _seed(site, category)
    owner = _api_user(django_user_model, "exp_owner_a")
    other = _api_user(django_user_model, "exp_other_b")
    admin = _api_user(django_user_model, "exp_admin_c", "admin")

    api_owner = APIClient()
    api_owner.force_authenticate(owner)
    job_id = api_owner.post(
        "/api/v1/exports/", {"report": "inventory-by-site", "format": "csv"}, format="json"
    ).json()["id"]

    api_other = APIClient()
    api_other.force_authenticate(other)
    listed = api_other.get("/api/v1/exports/").json()
    assert job_id not in [row["id"] for row in listed["results"]]
    # 404, not 403: a foreign id must not even confirm the job exists
    assert api_other.get(f"/api/v1/exports/{job_id}/download/").status_code == 404

    api_admin = APIClient()  # admins see every job (by design)
    api_admin.force_authenticate(admin)
    listed = api_admin.get("/api/v1/exports/").json()
    assert job_id in [row["id"] for row in listed["results"]]
    assert api_admin.get(f"/api/v1/exports/{job_id}/download/").status_code == 200


def test_export_jobs_prune_keeps_newest_20(django_user_model, site, category):
    import os

    from apps.reports.models import ExportJob

    u = _api_user(django_user_model, "exp_prune")
    paths = []
    for i in range(21):
        job = ExportJob(requested_by=u, report="asset-aging", format="xlsx", row_count=i)
        job.file.save(f"prune-{i:02d}.xlsx", ContentFile(b"PK\x03\x04stub"), save=True)
        paths.append(job.file.path)
    assert ExportJob.objects.count() == 21

    api = APIClient()
    api.force_authenticate(u)
    r = api.post(
        "/api/v1/exports/", {"report": "inventory-by-site", "format": "csv"}, format="json"
    )
    assert r.status_code == 201

    assert ExportJob.objects.count() == 20  # newest 20 kept per user (§10.8)
    leftover = int(r.json()["id"])
    assert leftover in set(ExportJob.objects.values_list("id", flat=True))
    # the oldest rows are gone, and their private files with them
    assert not os.path.exists(paths[0])
    assert not os.path.exists(paths[1])
    assert os.path.exists(paths[2])


def test_export_job_failure_records_failed_row(django_user_model, monkeypatch, site, category):
    from apps.reports.models import ExportJob

    u = _api_user(django_user_model, "exp_boom")

    def boom(*args, **kwargs):
        raise RuntimeError("render exploded")

    monkeypatch.setattr("apps.reports.service.run_report", boom)
    api = APIClient()
    api.force_authenticate(u)
    with pytest.raises(RuntimeError):
        api.post(
            "/api/v1/exports/",
            {"report": "inventory-by-site", "format": "csv", "site": site.pk},
            format="json",
        )

    job = ExportJob.objects.get(requested_by=u)
    assert job.status == ExportJob.Status.FAILED
    assert "render exploded" in job.error  # ops evidence, not a lost failure


def test_export_job_requires_login(client, site, category):
    _seed(site, category)
    r = client.post("/api/v1/exports/", {"report": "inventory-by-site", "format": "csv"})
    assert r.status_code == 401  # IsAuthenticated → 401 over the wire
