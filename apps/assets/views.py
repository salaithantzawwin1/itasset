"""CRUD views for Asset (M2; DEVELOPMENT.md §2/§3/§9/§11).

Create/edit/check-out/check-in = technician or admin; delete = admin only.
Detail page shows full assignment history (§3 handover trail).
"""

from django.contrib import messages
from django.db.models import Prefetch
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
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
from apps.people.models import Department, Person, Site

from . import services
from .forms import AssetForm, AssetRequestForm
from .models import ApprovalDecision, Asset, AssetRequest, Assignment, Category
from .specs import SPEC_FIELD_PREFIX, spec_rows


class AssetList(RoleRequiredMixin, ListView):
    roles_required = ()
    model = Asset
    template_name = "assets/asset_list.html"
    paginate_by = 50

    def get_queryset(self):
        from datetime import timedelta

        from django.db.models import Exists, OuterRef, Q
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
            # holder search: the open assignment's person name or the
            # department the asset is checked out to (a closed row is
            # history, not a holder, so it does not match). Wrapped in
            # EXISTS so a second assignment row on the same asset can never
            # fan it out — counts stay exact without a DISTINCT.
            holder_hit = Assignment.objects.filter(asset=OuterRef("pk"), in_at__isnull=True).filter(
                Q(to_person__name__icontains=q) | Q(to_dept__name__icontains=q)
            )
            qs = qs.filter(
                Q(asset_tag__icontains=q)
                | Q(serial_no__icontains=q)
                | Q(hostname__icontains=q)
                | Q(model_name__icontains=q)
                | Exists(holder_hit)
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
        # department filter: match the holder's department (person) OR a
        # department-held asset (open assignment only)
        department = self.request.GET.get("department", "")
        if department.isdigit():
            qs = qs.filter(
                Q(
                    assignments__in_at__isnull=True,
                    assignments__to_person__department_id=int(department),
                )
                | Q(assignments__in_at__isnull=True, assignments__to_dept_id=int(department))
            ).distinct()
        # "assigned to me": assets held by the caller's linked Person
        if self.request.GET.get("mine"):
            person = linked_person(self.request.user)
            if person is None:
                qs = qs.none()  # no Person link → the filter answers nothing
            else:
                qs = qs.filter(
                    assignments__in_at__isnull=True,
                    assignments__to_person_id=person.pk,
                ).distinct()
        if self.request.GET.get("overdue"):
            # assets still out whose loan due-date has passed (§14 scan_loans)
            qs = qs.filter(
                assignments__in_at__isnull=True,
                assignments__due_at__lt=timezone.now(),
            ).distinct()
        # holder column: one prefetch of the active assignment per row (§17
        # no-N+1) so "who has this" is visible without opening each asset
        qs = qs.prefetch_related(
            Prefetch(
                "assignments",
                queryset=Assignment.objects.filter(in_at__isnull=True).select_related(
                    "to_person", "to_person__department", "to_dept"
                ),
                to_attr="active_assignments",
            )
        )
        return scope_list(self.request.user, qs, action="asset_list", path=self.request.path)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["statuses"] = Asset.Status.choices
        ctx["departments"] = Department.objects.select_related("site").order_by("name")
        # the orphan fix-up queue is technician-only — hide the link otherwise
        ctx["can_repair"] = is_technician_or_admin(self.request.user)
        # bulk dept check-out entry (same gate — both are technician writes)
        ctx["can_bulk"] = is_technician_or_admin(self.request.user)
        return ctx

    def render_to_response(self, context, **response_kwargs):
        """Live search: `?_fragment=1` answers with the three swappable
        regions (count, rows, pagination) as JSON instead of the page.

        Same URL, same queryset, same scope filter as the normal render —
        the debounced search box fetches this and swaps the DOM in place,
        so a keystroke never costs a navigation (no focus/scroll loss).
        All three regions render from the same partials the full page
        includes, so the two surfaces cannot drift apart.
        """
        if self.request.GET.get("_fragment"):
            return JsonResponse(
                {
                    "count": render_to_string(
                        "assets/_asset_count.html", context, request=self.request
                    ),
                    "rows": render_to_string(
                        "assets/_asset_list_rows.html", context, request=self.request
                    ),
                    "pagination": render_to_string(
                        "assets/_asset_list_pagination.html", context, request=self.request
                    ),
                }
            )
        return super().render_to_response(context, **response_kwargs)


class AssetDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    roles_required = ()
    scope_action = "asset_detail"
    model = Asset
    template_name = "assets/asset_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        active = (
            Assignment.objects.filter(asset=self.object, in_at__isnull=True)
            .select_related("to_person", "to_person__department", "to_person__site", "to_dept")
            .first()
        )
        ctx["current_holder"] = active.to_person if active else None
        ctx["current_dept"] = active.to_dept if active else None
        ctx["history"] = (
            Assignment.objects.filter(asset=self.object)
            .select_related("to_person", "assigned_by")
            .order_by("-out_at")
        )
        # §6.1 component relationship: peripherals linked to this asset, each
        # with its own (possibly different) holder — one batched query
        ctx["components"] = list(
            self.object.components.select_related("category").prefetch_related(
                Prefetch(
                    "assignments",
                    queryset=Assignment.objects.filter(in_at__isnull=True).select_related(
                        "to_person"
                    ),
                    to_attr="active_assignments",
                )
            )
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
        # department-as-holder picker (Server/NAS/Switch/laptop pools)
        ctx["departments"] = scope_list(
            self.request.user,
            Department.objects.select_related("site"),
            action="asset_detail_departments",
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


# Field buckets for the tabbed asset form (assets/asset_form.html). Category
# leads Basics: the tag auto-assign and the spec fields both depend on it.
# The "specs" bucket only ever holds the dynamic ``spec__*`` fields and is
# always kept — the live swap needs its panel present even when empty. Any
# field not listed falls into the last tab so a newly added model field is
# rendered somewhere instead of silently disappearing.
ASSET_FORM_TABS = (
    (
        "basics",
        "asset.tab.basics",
        [
            "category",
            "asset_tag",
            "status",
            "condition",
            "site",
            "assigned_to",
            "assigned_dept",
            "parent_asset",
        ],
    ),
    ("specs", "asset.tab.specs", []),
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
    are dropped except "specs", whose panel must exist for the live swap to
    fill (an empty specs tab hides itself as soon as the tab script runs).
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
        if buckets[key] or key == "specs"
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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request  # picker scope + the assignment's actor
        return kwargs

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
        response = super().form_valid(form)
        if getattr(form, "assignment_warning", None):
            messages.warning(self.request, form.assignment_warning)
        return response


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

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["request"] = self.request  # picker scope + the assignment's actor
        return kwargs

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
        response = super().form_valid(form)
        if getattr(form, "assignment_warning", None):
            messages.warning(self.request, form.assignment_warning)
        return response


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


def orphan_repair(request):
    """Fix-up queue for orphan assignments (status ASSIGNED, no open row).

    Seed/import artifacts where the register says "assigned" but the trail
    has no holder. One row per orphan with a holder picker; a POST repairs
    through `services.check_out` — the documented orphan-recovery path — so
    the repair lands as a normal check-out event (activity trail included),
    not as direct row surgery. Technician-gated and scope-narrowed like the
    forms that write the same data.
    """
    if not request.user.is_authenticated:
        return redirect("login")
    denied = _guard_technician(request)
    if denied:
        return denied
    # pk__in subquery, not exclude(assignments__in_at__isnull=True): the
    # multi-valued exclude compiles over-broad here (drops assets with no
    # assignment rows at all — verified: 0 of 20 survived).
    orphans = scope_list(
        request.user,
        Asset.objects.filter(status=Asset.Status.ASSIGNED)
        .exclude(pk__in=Assignment.objects.filter(in_at__isnull=True).values("asset_id"))
        .select_related("category", "site"),
        action="orphan_repair",
        path=request.path,
    )
    people_qs = scope_list(
        request.user,
        Person.objects.filter(is_active=True).select_related("site", "department"),
        action="orphan_repair_people",
        path=request.path,
    )
    departments_qs = scope_list(
        request.user,
        Department.objects.select_related("site"),
        action="orphan_repair_departments",
        path=request.path,
    )
    if request.method == "POST":
        asset = get_object_or_404(orphans, pk=request.POST.get("asset"))
        person_id = request.POST.get("to_person")
        dept_id = request.POST.get("to_dept")
        try:
            if person_id and not dept_id:
                target = {"person": Person.objects.get(pk=person_id)}
            elif dept_id and not person_id:
                target = {"department": Department.objects.get(pk=dept_id)}
            else:
                raise ValueError("exactly one holder must be picked")
        except (Person.DoesNotExist, Department.DoesNotExist, ValueError, TypeError):
            messages.error(request, "Pick an employee or a department as the holder.")
            return redirect("orphan-repair")
        try:
            check_scope(request.user, asset, action="orphan_repair", path=request.path)
        except OutOfScope:
            raise Http404("Asset not found") from None
        try:
            services.check_out(
                asset, actor=request.user, remarks="Orphan assignment repaired", **target
            )
            holder = next(iter(target.values()))
            messages.success(request, f"{asset.asset_tag} → {holder.name}")
        except services.AssetError as exc:
            messages.warning(request, str(exc))
        return redirect("orphan-repair")
    return render(
        request,
        "assets/orphan_repair.html",
        {"orphans": orphans, "people": people_qs, "departments": departments_qs},
    )


def attach_components(request, pk):
    """Bulk-link components to a workstation (§6.1 parent_asset).

    Candidates: same site as the workstation, not yet a child, not the
    workstation itself — optionally narrowed by `?category=`. A POST sets
    `parent_asset` for each ticked asset (structural metadata, not a
    lifecycle transition: direct write + one batched ActivityLog event) and
    re-derives the candidate set before writing, so a crafted POST cannot
    attach another site's asset.
    """
    if not request.user.is_authenticated:
        return redirect("login")
    denied = _guard_technician(request)
    if denied:
        return denied
    parent = get_object_or_404(Asset, pk=pk)
    try:
        check_scope(request.user, parent, action="asset_attach", path=request.path)
    except OutOfScope:
        raise Http404("Asset not found") from None

    def candidates():
        qs = (
            Asset.objects.filter(site=parent.site, parent_asset__isnull=True)
            .exclude(pk=parent.pk)
            .select_related("category")
            .order_by("asset_tag")
        )
        cat = request.GET.get("category", "")
        if cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        return qs

    if request.method == "POST":
        chosen = list(candidates().filter(pk__in=request.POST.getlist("assets")))
        for component in chosen:
            component.parent_asset = parent
        Asset.objects.bulk_update(chosen, ["parent_asset"])
        if chosen:
            from apps.audit.models import ActivityLog

            ActivityLog.record(
                actor=request.user,
                action="component_attach",
                obj=parent,
                details={"components": [c.pk for c in chosen]},
            )
            messages.success(
                request,
                f"{len(chosen)} component(s) attached to {parent.asset_tag}.",
            )
        else:
            messages.warning(request, "Nothing selected — tick the components to attach.")
        return redirect("asset-detail", pk=parent.pk)

    candidates_qs = candidates()
    category_ids = Asset.objects.filter(site=parent.site, parent_asset__isnull=True).values_list(
        "category_id", flat=True
    )
    return render(
        request,
        "assets/attach_components.html",
        {
            "parent": parent,
            "candidates": candidates_qs,
            "categories": Category.objects.filter(pk__in=set(category_ids)).order_by("code"),
        },
    )


def bulk_dept_checkout(request):
    """Bulk check-out: tick many AVAILABLE assets → one department (session 36).

    Same shape as `attach_components`: technician-gated, scope-narrowed, and
    candidates are re-derived server-side before writing — a crafted POST pk
    (wrong status, other site/out of scope, already assigned) simply isn't
    in the candidate set and gets dropped. Each chosen asset runs through
    `services.check_out`, so status sync + the per-asset ActivityLog trail
    are the normal lifecycle path, not row surgery. Orphans (ASSIGNED with
    no row) stay with the repair queue — candidates are AVAILABLE only.
    """
    from django.db.models import Q

    if not request.user.is_authenticated:
        return redirect("login")
    denied = _guard_technician(request)
    if denied:
        return denied

    # scope once per request (the flag-aware helper logs a would-deny event
    # eagerly, so building it inside the filter helper would double-log)
    scoped = scope_list(
        request.user,
        Asset.objects.filter(status=Asset.Status.AVAILABLE),
        action="bulk_checkout",
        path=request.path,
    )

    def candidates():
        qs = scoped.select_related("category", "site").order_by("asset_tag")
        site = request.GET.get("site", "")
        if site.isdigit():
            qs = qs.filter(site_id=int(site))
        cat = request.GET.get("category", "")
        if cat.isdigit():
            qs = qs.filter(category_id=int(cat))
        q = request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(
                Q(asset_tag__icontains=q) | Q(serial_no__icontains=q) | Q(model_name__icontains=q)
            )
        return qs

    if request.method == "POST":
        try:
            dept = Department.objects.get(pk=request.POST.get("to_dept"))
        except (Department.DoesNotExist, TypeError, ValueError):
            messages.error(request, "Pick a department to assign the assets to.")
            return redirect("asset-bulk-checkout")
        try:
            check_scope(request.user, dept, action="bulk_checkout", path=request.path)
        except OutOfScope:
            raise Http404("Department not found") from None
        chosen = list(candidates().filter(pk__in=request.POST.getlist("assets")))
        if not chosen:
            messages.warning(request, "Nothing selected — tick the assets to assign.")
            return redirect("asset-bulk-checkout")
        done: list[str] = []
        failed: list[str] = []
        for asset in chosen:
            try:
                services.check_out(
                    asset,
                    actor=request.user,
                    department=dept,
                    remarks="Bulk department check-out",
                )
                done.append(asset.asset_tag)
            except services.AssetError as exc:
                failed.append(str(exc))
        if done:
            messages.success(request, f"{len(done)} asset(s) checked out → {dept.name}.")
        if failed:
            shown = "; ".join(failed[:3])
            if len(failed) > 3:
                shown += f" (+{len(failed) - 3} more)"
            messages.warning(request, shown)
        return redirect("asset-bulk-checkout")

    rows = candidates()
    # filter options derive from the unfiltered candidate set (status +
    # scope only), so picking a category doesn't collapse its own list
    category_ids = scoped.values_list("category_id", flat=True)
    site_ids = scoped.values_list("site_id", flat=True)
    return render(
        request,
        "assets/bulk_checkout.html",
        {
            "candidates": rows,
            "categories": Category.objects.filter(pk__in=category_ids).order_by("code"),
            "sites": Site.objects.filter(pk__in=site_ids).order_by("name"),
            "departments": scope_list(
                request.user,
                Department.objects.select_related("site"),
                action="bulk_checkout_departments",
                path=request.path,
            ),
        },
    )


def asset_field_suggest(request):
    """Spec-field fragment + next asset tag for a chosen category.

    Powers the live field swap on the asset forms: picking a category GETs
    this endpoint and the page replaces its spec fields (and, on a tagless
    create, the auto-assigned ``<CODE>-NNNN`` tag) without a reload. Read-only,
    but gated like the forms that consume it (technician/admin).
    """
    if not request.user.is_authenticated:
        return JsonResponse({"detail": "Authentication required."}, status=401)
    denied = _guard_technician(request)
    if denied:
        return denied
    try:
        category = Category.objects.filter(pk=request.GET.get("category")).first()
    except (TypeError, ValueError):
        category = None
    if category is None:
        return JsonResponse({"html": "", "next_tag": None}, status=400)
    form = AssetForm(data={"category": str(category.pk)})
    fields = [form[name] for name in form.fields if name.startswith(SPEC_FIELD_PREFIX)]
    template = (
        "admin/partials/spec_fields.html"
        if request.GET.get("surface") == "admin"
        else "partials/spec_fields.html"
    )
    return JsonResponse(
        {
            "html": render_to_string(template, {"fields": fields}, request=request),
            "next_tag": services.next_asset_tag(category),
            "code": category.code,
        }
    )


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
        dept_id = request.POST.get("to_dept")
        remarks = request.POST.get("remarks", "")
        # exactly one target: an employee or a department (server/network
        # kit is held by a dept, not an individual)
        try:
            if person_id and not dept_id:
                target = {"person": Person.objects.get(pk=person_id)}
            elif dept_id and not person_id:
                target = {"department": Department.objects.get(pk=dept_id)}
            else:
                return redirect("asset-detail", pk=pk)
        except (Person.DoesNotExist, Department.DoesNotExist, ValueError, TypeError):
            return redirect("asset-detail", pk=pk)
        try:
            services.check_out(asset, actor=request.user, remarks=remarks, **target)
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
