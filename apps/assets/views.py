"""CRUD views for Asset (M2; DEVELOPMENT.md §2/§3/§9/§11).

Create/edit/check-out/check-in = technician or admin; delete = admin only.
Detail page shows full assignment history (§3 handover trail).
"""

from django.contrib import messages
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.roles import RoleRequiredMixin, is_technician_or_admin, user_has_role
from apps.core.scopes import (
    OutOfScope,
    ScopeGuardMixin,
    check_scope,
    linked_person,
    scope_list,
)
from apps.people.models import Person, Site

from . import services
from .forms import AssetForm, AssetRequestForm
from .models import ApprovalDecision, Asset, AssetRequest, Assignment
from .specs import SPEC_FIELD_PREFIX, spec_rows


class AssetList(RoleRequiredMixin, ListView):
    roles_required = ()
    model = Asset
    template_name = "assets/asset_list.html"
    paginate_by = 50

    def get_queryset(self):
        from datetime import timedelta

        from django.db.models import Q
        from django.utils import timezone

        qs = Asset.objects.select_related("category", "site")
        status = self.request.GET.get("status")
        site = self.request.GET.get("site")
        q = self.request.GET.get("q", "").strip()
        warranty_days = self.request.GET.get("warranty_days", "")
        if status:
            qs = qs.filter(status=status)
        if site:
            qs = qs.filter(site_id=site)
        if q:
            qs = qs.filter(
                Q(asset_tag__icontains=q)
                | Q(serial_no__icontains=q)
                | Q(hostname__icontains=q)
                | Q(model_name__icontains=q)
            )
        # quick filters used by the dashboard alert deep links (§ dashboard)
        if warranty_days.isdigit():
            today = timezone.localdate()
            qs = qs.filter(
                warranty_end__isnull=False,
                warranty_end__gte=today,
                warranty_end__lte=today + timedelta(days=int(warranty_days)),
            )
        if self.request.GET.get("missing_serial"):
            qs = qs.filter(serial_no="")
        if self.request.GET.get("overdue"):
            # assets still out whose loan due-date has passed (§14 scan_loans)
            qs = qs.filter(
                assignments__in_at__isnull=True,
                assignments__due_at__lt=timezone.now(),
            ).distinct()
        return scope_list(self.request.user, qs, action="asset_list", path=self.request.path)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = Asset.Status.choices
        return ctx


class AssetDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    roles_required = ()
    scope_action = "asset_detail"
    model = Asset
    template_name = "assets/asset_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["history"] = (
            Assignment.objects.filter(asset=self.object)
            .select_related("to_person", "assigned_by")
            .order_by("-out_at")
        )
        # category-specific specification values (§5 catalogue → Asset.attrs)
        ctx["spec_rows"] = spec_rows(self.object.category, self.object.attrs)
        ctx["can_lifecycle"] = is_technician_or_admin(self.request.user)
        ctx["conditions"] = Asset.Condition.choices
        ctx["people"] = scope_list(
            self.request.user,
            Person.objects.filter(is_active=True).select_related("site"),
            action="asset_detail_people",
            path=self.request.path,
        )
        return ctx


# status → (stages already done, current stage index) for the self-view
# stepper: requested(0) → approval(1) → procure(2) → receive(3)
_PROGRESS_BY_STATUS = {
    AssetRequest.Status.PENDING: (1, 1),
    AssetRequest.Status.APPROVED: (2, 2),
    AssetRequest.Status.PROCURED: (3, 3),
    AssetRequest.Status.FULFILLED: (4, None),
}
_PROGRESS_LABELS = {
    AssetRequest.Status.PENDING: ("prog.approval_wait", "prog.approval_wait_n"),
    AssetRequest.Status.APPROVED: ("prog.await_procure", "prog.await_procure"),
    AssetRequest.Status.PROCURED: ("prog.await_receive", "prog.await_receive"),
    AssetRequest.Status.FULFILLED: ("prog.fulfilled", "prog.fulfilled"),
    AssetRequest.Status.REJECTED: ("prog.rejected", "prog.rejected"),
    AssetRequest.Status.CANCELLED: ("prog.cancelled", "prog.cancelled"),
}


def _request_progress(req: AssetRequest) -> dict:
    """4-stage pipeline view of one request for the self-view stepper.

    The approval stage may itself be a multi-step chain (§6.6): `cur`/`total`
    come from `resolve_approval_steps` plus the immutable decisions already
    recorded, so an employee can see *which* approval step is holding their
    request instead of a flat "Pending".
    """
    chain = services.resolve_approval_steps(req)
    total = len(chain)
    approved = req.approval_decisions.filter(action=ApprovalDecision.Action.APPROVE).count()
    cur = min(approved, total - 1) + 1  # 1-based current approval step

    stages = [
        {"key": key, "n": i + 1, "state": "todo"}
        for i, key in enumerate(("requested", "approval", "procure", "receive"))
    ]
    single, multi = _PROGRESS_LABELS.get(req.status, ("prog.cancelled", "prog.cancelled"))
    if req.status == AssetRequest.Status.REJECTED:
        stages[0]["state"] = "done"
        stages[1]["state"] = "failed"
        label_key = single
    elif req.status == AssetRequest.Status.CANCELLED:
        label_key = single
    else:
        done_upto, current = _PROGRESS_BY_STATUS.get(req.status, (1, 1))
        for i in range(done_upto):
            stages[i]["state"] = "done"
        if current is not None:
            stages[current]["state"] = "current"
        label_key = multi if (req.status == AssetRequest.Status.PENDING and total > 1) else single

    return {"stages": stages, "label_key": label_key, "cur": cur, "total": total}


class SelfView(RoleRequiredMixin, ListView):
    """Employee self-view (design §4.4; §6 row 15).

    Own Assignment history (needs the linked Person) + own AssetRequest rows
    — requests are always shown by `requester=user`, own-rows-only by
    construction, even when no Person is linked: the employee request form
    (§6.5 stage ①) lets scope-holding users file requests before any person
    link exists, and hiding them again would make the submit flow look broken.
    """

    roles_required = ()
    model = Assignment
    context_object_name = "assignments"
    template_name = "assets/self_view.html"
    paginate_by = 25

    def get_queryset(self):
        person = linked_person(self.request.user)
        if person is None:
            return Assignment.objects.none()
        return (
            Assignment.objects.filter(to_person=person)
            .select_related("asset", "asset__site", "to_person")
            .order_by("-out_at")
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        person = linked_person(self.request.user)
        ctx["person"] = person
        ctx["requests"] = (
            AssetRequest.objects.filter(requester=self.request.user)
            .select_related("category", "site")
            .prefetch_related("approval_decisions")
            .order_by("-created_at")
        )
        ctx["request_rows"] = [
            {"req": req, "progress": _request_progress(req)} for req in ctx["requests"]
        ]
        return ctx


# Field buckets for the tabbed asset form (assets/asset_form.html). The
# category-specific ``spec__*`` fields join the "specs" tab automatically;
# anything not listed here falls into the last tab so a newly added model
# field is rendered somewhere instead of silently disappearing.
ASSET_FORM_TABS = (
    ("basics", "asset.tab.basics", ["asset_tag", "status", "condition", "site"]),
    ("specs", "asset.tab.specs", ["category"]),
    ("device", "asset.tab.device", ["manufacturer", "model_name", "serial_no", "hostname"]),
    (
        "procurement",
        "asset.tab.procurement",
        ["purchase_date", "cost", "warranty_end", "remarks"],
    ),
)


def build_form_tabs(form):
    """Partition the form's fields into labelled tab panels for the template.

    Returns [{key, i18n_key, fields: [BoundField, ...]}, ...]; empty buckets
    are dropped (e.g. "specs" when the category defines no specification).
    """
    buckets = {key: [] for key, _, _ in ASSET_FORM_TABS}
    grouped = set()
    for key, _, names in ASSET_FORM_TABS:
        for name in names:
            if name in form.fields:
                buckets[key].append(form[name])
                grouped.add(name)
    last_key = ASSET_FORM_TABS[-1][0]
    for name in form.fields:
        if name in grouped:
            continue
        target = "specs" if name.startswith(SPEC_FIELD_PREFIX) else last_key
        buckets[target].append(form[name])
    return [
        {"key": key, "i18n_key": i18n_key, "fields": buckets[key]}
        for key, i18n_key, _ in ASSET_FORM_TABS
        if buckets[key]
    ]


class FormTabsMixin:
    """Expose build_form_tabs() as ``form_tabs`` for asset_form.html."""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        if ctx.get("form") is not None:
            ctx["form_tabs"] = build_form_tabs(ctx["form"])
        return ctx


class AssetCreate(FormTabsMixin, RoleRequiredMixin, CreateView):
    roles_required = ("admin", "technician")
    model = Asset
    form_class = AssetForm
    template_name = "assets/asset_form.html"
    success_url = reverse_lazy("asset-list")

    def form_valid(self, form):
        form.instance.status = Asset.Status.IN_STOCK  # §3 stage ④: receive & tag
        try:
            check_scope(
                self.request.user,
                form.instance.site,
                action="asset_create",
                path=self.request.path,
            )
        except OutOfScope:
            return HttpResponseForbidden("That site is outside your scope.")
        return super().form_valid(form)


def _requestable_site_ids(user) -> set:
    """Sites this user may file an asset request against.

    Flag-aware scope list (`site_field="id"` — the queryset *is* the Site
    model) plus the §4.4 self carve-out: an employee with no org scope rows
    may always request for the site of their own linked Person.
    """
    ids = set(
        scope_list(
            user,
            Site.objects.filter(is_active=True),
            site_field="id",
            action="asset_request_create",
            path=reverse("request-create"),
        ).values_list("pk", flat=True)
    )
    person = linked_person(user)
    if person is not None and person.site_id:
        ids.add(person.site_id)
    return ids


class RequestCreate(RoleRequiredMixin, CreateView):
    """Employee self-service asset request (Spec A §6.5 stage ①).

    Any authenticated user may file one (roles_required = ()); the site list
    is scope-narrowed with the own-site carve-out; the row starts PENDING for
    the approval chain. Admins created these rows by hand before this existed.
    """

    roles_required = ()
    form_class = AssetRequestForm
    template_name = "assets/request_form.html"
    success_url = reverse_lazy("self-view")

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        form.fields["site"].queryset = Site.objects.filter(
            pk__in=_requestable_site_ids(self.request.user), is_active=True
        ).order_by("name")
        return form

    def form_valid(self, form):
        # re-check against a crafted POST (the select may have been bypassed)
        if form.instance.site_id not in _requestable_site_ids(self.request.user):
            return HttpResponseForbidden("That site is outside your scope.")
        form.instance.requester = self.request.user  # never client-supplied
        response = super().form_valid(form)
        messages.success(
            self.request,
            f"Request REQ#{form.instance.pk} submitted — awaiting approval.",
        )
        return response


class OverdueLoans(RoleRequiredMixin, ListView):
    """Loans past their due date (§14 `scan_loans` made visible).

    Was email-only: the dashboard alert fired but had no page to open. Now
    the alert deep-links here. Read-only, scope-narrowed on the asset's site
    (deny-by-default: no scope rows → empty list, like every other list).
    """

    roles_required = ()
    model = Assignment
    context_object_name = "loans"
    template_name = "assets/loan_overdue.html"
    paginate_by = 50

    def get_queryset(self):
        qs = (
            Assignment.objects.filter(in_at__isnull=True, due_at__lt=timezone.now())
            .select_related("asset", "asset__site", "to_person")
            .order_by("due_at")
        )
        return scope_list(
            self.request.user,
            qs,
            site_field="asset__site",
            action="loan_overdue",
            path=self.request.path,
        )

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        now = timezone.localtime()
        for loan in ctx.get("loans") or []:
            # whole days late (floor), minimum 1 — "just late" reads as 1d
            loan.days_late = max(1, (now - loan.due_at).days)
        return ctx


class AssetUpdate(FormTabsMixin, ScopeGuardMixin, RoleRequiredMixin, UpdateView):
    roles_required = ("admin", "technician")
    scope_action = "asset_update"
    model = Asset
    form_class = AssetForm
    template_name = "assets/asset_form.html"
    success_url = reverse_lazy("asset-list")

    def form_valid(self, form):
        try:
            check_scope(
                self.request.user,
                form.instance.site,
                action="asset_update",
                path=self.request.path,
            )
        except OutOfScope:
            return HttpResponseForbidden("That site is outside your scope.")
        return super().form_valid(form)


class AssetDelete(ScopeGuardMixin, RoleRequiredMixin, DeleteView):
    roles_required = ("admin",)
    scope_action = "asset_delete"
    model = Asset
    template_name = "assets/asset_confirm_delete.html"
    success_url = reverse_lazy("asset-list")


def _guard_technician(request) -> HttpResponseForbidden | None:
    if not request.user.is_authenticated:
        return None  # caller redirects to login instead
    if not user_has_role(request.user, "admin", "technician"):
        return HttpResponseForbidden("Technician or admin role required.")
    return None


def check_out_view(request, pk):
    """Assign the asset to a person (technician+); §3 stage ⑤."""
    if not request.user.is_authenticated:
        return redirect("login")
    denied = _guard_technician(request)
    if denied:
        return denied
    asset = get_object_or_404(Asset, pk=pk)
    try:
        check_scope(request.user, asset, action="asset_check_out", path=request.path)
    except OutOfScope:
        raise Http404("Asset not found") from None
    if request.method == "POST":
        person_id = request.POST.get("to_person")
        try:
            person = Person.objects.get(pk=person_id)
        except (Person.DoesNotExist, ValueError, TypeError):
            return redirect("asset-detail", pk=pk)
        remarks = request.POST.get("remarks", "")
        try:
            services.check_out(asset, person, actor=request.user, remarks=remarks)
        except services.AssetError:
            pass
    return redirect("asset-detail", pk=pk)


def check_in_view(request, pk):
    """Return the asset (technician+); closes the active assignment."""
    if not request.user.is_authenticated:
        return redirect("login")
    denied = _guard_technician(request)
    if denied:
        return denied
    asset = get_object_or_404(Asset, pk=pk)
    try:
        check_scope(request.user, asset, action="asset_check_in", path=request.path)
    except OutOfScope:
        raise Http404("Asset not found") from None
    if request.method == "POST":
        condition = request.POST.get("condition_in", Asset.Condition.GOOD)
        remarks = request.POST.get("remarks", "")
        try:
            services.check_in(asset, condition_in=condition, remarks=remarks)
        except services.AssetError:
            pass
    return redirect("asset-detail", pk=pk)
