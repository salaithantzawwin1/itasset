"""CRUD views for Asset (M2; DEVELOPMENT.md §2/§3/§9/§11).

Create/edit/check-out/check-in = technician or admin; delete = admin only.
Detail page shows full assignment history (§3 handover trail).
"""

from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.roles import RoleRequiredMixin, is_technician_or_admin, user_has_role
from apps.core.scopes import (
    OutOfScope,
    ScopeGuardMixin,
    check_scope,
    linked_person,
    scope_list,
)
from apps.people.models import Person

from . import services
from .forms import AssetForm
from .models import Asset, AssetRequest, Assignment


class AssetList(RoleRequiredMixin, ListView):
    roles_required = ()
    model = Asset
    template_name = "assets/asset_list.html"
    paginate_by = 50

    def get_queryset(self):
        from django.db.models import Q

        qs = Asset.objects.select_related("category", "site")
        status = self.request.GET.get("status")
        site = self.request.GET.get("site")
        q = self.request.GET.get("q", "").strip()
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
        ctx["can_lifecycle"] = is_technician_or_admin(self.request.user)
        ctx["conditions"] = Asset.Condition.choices
        ctx["people"] = scope_list(
            self.request.user,
            Person.objects.filter(is_active=True).select_related("site"),
            action="asset_detail_people",
            path=self.request.path,
        )
        return ctx


class SelfView(RoleRequiredMixin, ListView):
    """Employee self-view (design §4.4; §6 row 15).

    Own Assignment history + own AssetRequest rows for a user with no scope
    rows but a linked Person. Own-rows-only by construction — no org scope is
    consulted, and without a linked Person both lists stay empty (§4.4).
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
            .order_by("-created_at")
            if person is not None
            else AssetRequest.objects.none()
        )
        return ctx


class AssetCreate(RoleRequiredMixin, CreateView):
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


class AssetUpdate(ScopeGuardMixin, RoleRequiredMixin, UpdateView):
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
