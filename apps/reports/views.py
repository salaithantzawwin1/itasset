"""Report views (DEVELOPMENT.md §4, M7).

Listing + on-demand export. All execution — scope gate, queries, rendering —
lives in `apps.reports.service.run_report`, shared with the API export jobs
(§3.5), so the two paths can never drift. Heavy exports are meant to run in
Celery (§17); the request-cycle path is fine for a LAN internal tool at the
v1 scale.
"""

from django.contrib import messages
from django.http import HttpResponse, HttpResponseForbidden
from django.shortcuts import redirect
from django.views.generic import TemplateView

from apps.core.roles import RoleRequiredMixin

from . import queries
from .exporters import REGISTRY
from .service import ReportForbidden, UnsupportedFormat, run_report

# Build the registry once at import. Idempotent so a reloader double-import
# can't duplicate entries.
if not REGISTRY:
    queries._register_all()


class _ReportAccess(RoleRequiredMixin):
    """Reports are read-only — any authenticated user can read (§11 viewer+)."""

    roles_required = ()


class ReportIndex(_ReportAccess, TemplateView):
    template_name = "reports/index.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["reports"] = list(REGISTRY.values())
        return ctx


def _run_report(slug, fmt, request):
    """HTML path — a thin wrapper over the shared service (§4: one layer).

    Errors keep their historical responses: unsupported format → message +
    redirect, scope refusal → 403 text; an unknown report/site is now a 404
    (was an unhandled KeyError/Http404).
    """
    try:
        content, ctype, filename, _rows = run_report(
            request, slug, fmt, site_id=request.GET.get("site")
        )
    except UnsupportedFormat as exc:
        messages.error(request, str(exc))
        return redirect("report-index")
    except ReportForbidden as exc:
        return HttpResponseForbidden(str(exc))
    resp = HttpResponse(content, content_type=ctype)
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


class ReportRun(_ReportAccess, TemplateView):
    """Export one report in `fmt` (§4 formats: csv/xlsx/pdf).

    Access goes through `_ReportAccess` (any authenticated user) rather than
    a hand-rolled check, so it can never drift from `ReportIndex` — both are
    read-only, so §11's read rule applies to each equally.
    """

    def get(self, request, slug, fmt):
        return _run_report(slug, fmt, request)
