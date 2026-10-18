"""Shared report execution (Spec A §4/§5.2: one service layer).

The HTML report views, the API export jobs and the scheduled §4 emails all
run through this module so the three paths can never drift:

- `run_report(request, ...)` — user path: the scope gate
  (pinned-to-in-scope-site rule) runs first, then query + render.
- `run_scheduled_report(slug, fmt, ...)` — system path for the §15 Celery
  tasks: no request/user exists, so instead of scope the audience is fixed by
  the §14 recipient rules (IT lead / site lead) and every send is recorded in
  the EmailAlert ledger.

Both share `_lookup` + `_execute`. Typed errors are raised *before* any query
executes, so callers can map them to clean 4xx responses without leaving job
rows behind.
"""

import inspect

from django.http import Http404
from django.shortcuts import get_object_or_404

from apps.core.scopes import (
    OutOfScope,
    check_scope,
    effective_scopes,
    enforcement_enabled,
    record_shadow,
)


class UnsupportedFormat(Exception):
    """The report exists but not in the requested format (→ 400)."""


class ReportForbidden(Exception):
    """Scope gate refused this export (§5.2 — same rule as the UI, → 403)."""


def _lookup(slug: str, fmt: str):
    """Registry lookup + format check, shared by every execution path.

    Raises `Http404` (unknown report) / `UnsupportedFormat` — always before
    any query executes.
    """
    from . import queries
    from .exporters import REGISTRY
    from .exporters import get as get_report

    # Build the registry once at import. Idempotent so a reloader double-import
    # can't duplicate entries (same guard as the HTML views).
    if not REGISTRY:
        queries._register_all()

    try:
        report = get_report(slug)
    except KeyError:
        raise Http404(f"unknown report: {slug}") from None
    if fmt not in report.formats:
        raise UnsupportedFormat(f"Format {fmt} not supported for {report.title}.")
    return report


def _execute(report, fmt: str, request, site):
    """Run the query + render — the drift-free tail both paths share.

    Only queries that declare a parameter accept it (`request` / `site`) —
    most reports are global (§4).
    """
    from .exporters import export

    params = inspect.signature(report.query).parameters
    kwargs = {}
    if "request" in params:
        kwargs["request"] = request
    if site is not None and "site" in params:
        kwargs["site"] = site
    headers, rows = report.query(**kwargs)
    content, ctype, filename = export(fmt, report.title, headers, rows)
    return content, ctype, filename, len(rows)


def run_report(request, slug, fmt, *, site_id=None, action="report_run"):
    """Scope-check + run + render one report for `request.user`.

    Returns `(content, content_type, filename, row_count)`. Raises:
    `Http404` (unknown report or site), `UnsupportedFormat`, `ReportForbidden`
    — all before the query executes.
    """
    from apps.people.models import Site

    report = _lookup(slug, fmt)

    accepts_site = "site" in inspect.signature(report.query).parameters
    site = get_object_or_404(Site, pk=site_id) if site_id else None

    # Scope gate (design §5.2: exports enforce the same scope as the UI).
    # A scoped user may only run a report pinned to an in-scope site, and the
    # report must honour `site` — otherwise its rows would leak globally.
    scopes = effective_scopes(request.user)
    if not scopes.global_access:
        allowed = site is not None and accepts_site
        if allowed:
            try:
                check_scope(request.user, site, action=action, path=request.path)
            except OutOfScope:
                raise ReportForbidden("That site is outside your scope.") from None
        elif enforcement_enabled():
            raise ReportForbidden(
                "This report is not scoped to your site — a global-scope account is required."
            )
        else:
            record_shadow(
                request.user,
                action=action,
                path=request.path,
                details={"report": slug, "site": site.pk if site else None},
            )

    return _execute(report, fmt, request, site)


def run_scheduled_report(slug: str, fmt: str, *, site=None):
    """System path for the §4 scheduled report emails (§15 Celery tasks).

    Celery has no user, so there is no scope gate — the constraint is the
    audience: recipients come from §14/`site.lead_email`, and each send is
    one idempotent `EmailAlert` row (never a public URL, never a job row).
    Shares `_lookup`/`_execute` with `run_report`, so the emailed numbers can
    never differ from the same report run in the UI.

    Returns `(content, content_type, filename, row_count)`. Raises
    `Http404` / `UnsupportedFormat` before any query executes.
    """
    report = _lookup(slug, fmt)
    return _execute(report, fmt, None, site)
