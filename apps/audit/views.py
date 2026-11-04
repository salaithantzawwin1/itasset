"""ActivityLog UI + physical audit sessions (DEVELOPMENT.md §11/§25, M5).

- ActivityLog list: read-only, filters by action/actor/search — admin+auditor.
- Audit session: technician+/auditor opens for a site, scans tags (scanner is
  keyboard-wedge, §16 — the scan box is a plain focused input), closes →
  found / missing / unexpected report.
"""

from django.contrib import messages
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import DetailView, ListView, View

from apps.assets.models import Asset
from apps.core.roles import RoleRequiredMixin, user_has_role
from apps.core.scopes import (
    OutOfScope,
    ScopeGuardMixin,
    check_scope,
    enforcement_enabled,
    record_shadow,
    scope_list,
    scope_queryset,
    user_in_site,
)

from .models import ActivityLog, AuditItem, AuditSession


class ActivityLogList(RoleRequiredMixin, ListView):
    """§9 audit trail viewer — filters by action, actor, free text."""

    roles_required = ("admin", "auditor")
    model = ActivityLog
    template_name = "audit/activitylog_list.html"
    paginate_by = 100

    def get_queryset(self):
        qs = ActivityLog.objects.select_related("actor", "content_type")
        action = self.request.GET.get("action", "").strip()
        actor = self.request.GET.get("actor", "").strip()
        q = self.request.GET.get("q", "").strip()
        if action:
            qs = qs.filter(action=action)
        if actor:
            qs = qs.filter(actor__username__icontains=actor)
        if q:
            qs = qs.filter(Q(object_repr__icontains=q) | Q(details__icontains=q))
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["actions"] = (
            ActivityLog.objects.values_list("action", flat=True).distinct().order_by("action")
        )
        ctx["cur_action"] = self.request.GET.get("action", "")
        ctx["cur_actor"] = self.request.GET.get("actor", "")
        ctx["cur_q"] = self.request.GET.get("q", "")
        return ctx


class AuditSessionList(RoleRequiredMixin, ListView):
    roles_required = ("admin", "technician", "auditor")
    model = AuditSession
    template_name = "audit/session_list.html"
    paginate_by = 25

    def get_queryset(self):
        qs = AuditSession.objects.select_related("site", "started_by")
        # record scope first (enforced → filtered; shadow → unchanged + log),
        # then the pre-existing own-site narrowing for non-admins
        qs = scope_list(self.request.user, qs, action="audit_session_list", path=self.request.path)
        if not user_has_role(self.request.user, "admin"):
            site = _user_site(self.request.user)
            qs = qs.filter(site=site) if site else qs.none()
        return qs

    def get_context_data(self, **kwargs):
        from apps.people.models import Site

        ctx = super().get_context_data(**kwargs)
        ctx["sites"] = scope_queryset(
            self.request.user,
            Site.objects.filter(is_active=True),
            site_field="pk",
        )
        return ctx


def _user_site(user):
    person = getattr(user, "person", None)
    return person.site if person else None


def _scoped_session(request, pk) -> AuditSession:
    """Fetch a session through the caller's scope; out-of-scope looks 404."""
    session = AuditSession.objects.select_related("site", "started_by").filter(pk=pk).first()
    if session is None:
        raise Http404("No AuditSession matches the given query.")
    try:
        check_scope(request.user, session, action="audit_session", path=request.path)
    except OutOfScope:
        raise Http404("No AuditSession matches the given query.") from None
    return session


class AuditSessionStart(RoleRequiredMixin, View):
    roles_required = ("admin", "technician", "auditor")

    def post(self, request):
        site_id = request.POST.get("site")
        site = None
        if site_id:
            from apps.people.models import Site

            site = Site.objects.filter(pk=site_id, is_active=True).first()
        site = site or _user_site(request.user)
        if site is None:
            messages.error(request, "No site selected.")
            return redirect("audit-sessions")
        # opening a session is a write against that site: don't let a
        # technician start one for a site their scope does not cover
        if not user_in_site(request.user, site):
            if enforcement_enabled():
                raise Http404("Site not found")
            record_shadow(request.user, action="audit_start", path=request.path, obj=site)
        session = AuditSession.objects.create(site=site, started_by=request.user)
        ActivityLog.record(
            actor=request.user, action="audit_start", obj=session, object_repr=str(session)
        )
        return redirect("audit-session", pk=session.pk)


class AuditSessionDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    """Scan screen: one focused input, keyboard-wedge scanner friendly (§16)."""

    roles_required = ("admin", "technician", "auditor")
    scope_action = "audit_session"
    model = AuditSession
    template_name = "audit/session_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        session = self.object
        scanned = set(session.items.values_list("asset_tag", flat=True))
        ctx["scanned_count"] = len(scanned)
        ctx["items"] = session.items.select_related("asset", "scanned_by")
        expected = Asset.objects.filter(site=session.site).exclude(status="DISPOSED")
        ctx["expected_count"] = expected.count()
        # missing = expected at this site but not scanned (for closed sessions the
        # list is informative while open too)
        missing = [a.asset_tag for a in expected if a.asset_tag not in scanned][:200]
        ctx["missing_preview"] = missing
        ctx["is_admin"] = user_has_role(self.request.user, "admin")
        return ctx


class AuditSessionScan(RoleRequiredMixin, View):
    """POST asset_tag — idempotent per (session, tag); unknown tags recorded bare."""

    roles_required = ("admin", "technician", "auditor")

    def post(self, request, pk):
        session = _scoped_session(request, pk)
        if session.status != AuditSession.Status.OPEN:
            messages.error(request, "Session already closed.")
            return redirect("audit-session", pk=pk)
        tag = (request.POST.get("asset_tag") or "").strip()
        if tag:
            asset = Asset.objects.filter(asset_tag=tag).first()
            item, created = AuditItem.objects.get_or_create(
                session=session,
                asset_tag=tag,
                defaults={"asset": asset, "scanned_by": request.user},
            )
            if not created:
                messages.info(request, f"{tag} already scanned.")
            elif asset is None:
                messages.warning(request, f"{tag}: unknown tag recorded.")
        return redirect("audit-session", pk=pk)


class AuditSessionClose(RoleRequiredMixin, View):
    roles_required = ("admin", "technician", "auditor")

    def post(self, request, pk):
        session = _scoped_session(request, pk)
        if session.status == AuditSession.Status.OPEN:
            session.status = AuditSession.Status.CLOSED
            session.closed_at = timezone.now()
            session.notes = request.POST.get("notes", session.notes)
            session.save(update_fields=["status", "closed_at", "notes"])
            ActivityLog.record(
                actor=request.user, action="audit_close", obj=session, object_repr=str(session)
            )
        return redirect("audit-report", pk=pk)


class AuditReport(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    """Found / missing / unexpected (§4 \"Audit results\" report)."""

    roles_required = ("admin", "technician", "auditor")
    scope_action = "audit_report"
    model = AuditSession
    template_name = "audit/report.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        session = self.object
        scanned = set(session.items.values_list("asset_tag", flat=True))
        expected = list(Asset.objects.filter(site=session.site).exclude(status="DISPOSED"))
        expected_tags = {a.asset_tag for a in expected}
        ctx["found"] = [a for a in expected if a.asset_tag in scanned]
        ctx["missing"] = [a for a in expected if a.asset_tag not in scanned]
        # unexpected = scanned tags that are unknown, or belong to another site
        ctx["unexpected"] = [
            i for i in session.items.select_related("asset") if i.asset_tag not in expected_tags
        ]
        ctx["found_n"] = len(ctx["found"])
        ctx["missing_n"] = len(ctx["missing"])
        ctx["unexpected_n"] = len(ctx["unexpected"])
        return ctx
