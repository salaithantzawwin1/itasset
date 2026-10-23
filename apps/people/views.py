"""CRUD views for Site and Person (M2; DEVELOPMENT.md §9, §11).

Site/Person management = admin role (§11 user/site management).
Reads open to any authenticated user (auditor/viewer included).
"""

from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.roles import RoleRequiredMixin
from apps.core.scopes import OutOfScope, ScopeGuardMixin, check_scope, scope_list

from .forms import DepartmentForm, PersonForm, SiteForm
from .models import Department, Person, Site

# ----------------------------------------------------------------------------
# Site CRUD (manage = admin only)
# ----------------------------------------------------------------------------


class SiteList(RoleRequiredMixin, ListView):
    roles_required = ()
    model = Site
    template_name = "people/site_list.html"

    def get_queryset(self):
        # Sites ARE the org rows: scope filter runs on the pk itself.
        return scope_list(
            self.request.user,
            super().get_queryset(),
            site_field="pk",
            action="site_list",
            path=self.request.path,
        )


class SiteDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    roles_required = ()
    scope_action = "site_detail"
    model = Site
    template_name = "people/site_detail.html"


class SiteCreate(RoleRequiredMixin, CreateView):
    roles_required = ("admin",)
    model = Site
    form_class = SiteForm
    template_name = "people/site_form.html"
    success_url = reverse_lazy("site-list")


class SiteUpdate(ScopeGuardMixin, RoleRequiredMixin, UpdateView):
    roles_required = ("admin",)
    scope_action = "site_update"
    model = Site
    form_class = SiteForm
    template_name = "people/site_form.html"
    success_url = reverse_lazy("site-list")


class SiteDelete(ScopeGuardMixin, RoleRequiredMixin, DeleteView):
    roles_required = ("admin",)
    scope_action = "site_delete"
    model = Site
    template_name = "people/confirm_delete.html"
    success_url = reverse_lazy("site-list")
    cancel_url = "site-list"


# ----------------------------------------------------------------------------
# Person CRUD (manage = admin only)
# ----------------------------------------------------------------------------


class PersonList(RoleRequiredMixin, ListView):
    roles_required = ()
    model = Person
    template_name = "people/person_list.html"
    paginate_by = 50

    def get_queryset(self):
        return scope_list(
            self.request.user,
            super().get_queryset(),
            site_field="site",
            dept_field="department",
            action="person_list",
            path=self.request.path,
        )


class PersonDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    roles_required = ()
    scope_action = "person_detail"
    model = Person
    template_name = "people/person_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.assets.models import Assignment

        # Held now: open rows only, one select_related so the table never
        # N+1s per asset (§17); history keeps the full in/out trail but is
        # capped — the register, not this page, is where full archives live.
        ctx["held_now"] = Assignment.objects.filter(
            to_person=self.object, in_at__isnull=True
        ).select_related("asset", "asset__category", "asset__site")
        ctx["history_recent"] = (
            Assignment.objects.filter(to_person=self.object, in_at__isnull=False)
            .select_related("asset", "asset__category")
            .order_by("-out_at")[:20]
        )
        return ctx


class PersonCreate(RoleRequiredMixin, CreateView):
    roles_required = ("admin",)
    model = Person
    form_class = PersonForm
    template_name = "people/person_form.html"
    success_url = reverse_lazy("person-list")

    def form_valid(self, form):
        try:
            check_scope(
                self.request.user,
                form.instance.site,
                action="person_create",
                path=self.request.path,
            )
        except OutOfScope:
            return HttpResponseForbidden("That site is outside your scope.")
        return super().form_valid(form)


class PersonUpdate(ScopeGuardMixin, RoleRequiredMixin, UpdateView):
    roles_required = ("admin",)
    scope_action = "person_update"
    model = Person
    form_class = PersonForm
    template_name = "people/person_form.html"
    success_url = reverse_lazy("person-list")

    def form_valid(self, form):
        try:
            check_scope(
                self.request.user,
                form.instance.site,
                action="person_update",
                path=self.request.path,
            )
        except OutOfScope:
            return HttpResponseForbidden("That site is outside your scope.")
        return super().form_valid(form)


class PersonDelete(ScopeGuardMixin, RoleRequiredMixin, DeleteView):
    roles_required = ("admin",)
    scope_action = "person_delete"
    model = Person
    template_name = "people/confirm_delete.html"
    success_url = reverse_lazy("person-list")
    cancel_url = "person-list"


# ---------------------------------------------------------------------------
# Department (sessions 32/37): list with dept-held asset counts, detail
# (head + held inventory + members), edit (name/site/head, admin).
# ---------------------------------------------------------------------------


class DepartmentList(RoleRequiredMixin, ListView):
    """Every department with its head and department-held asset count.

    Read-only for any authenticated user; scope-narrowed on both axes
    (site rows via `site`, department-scoped users via `pk`) — the count is
    one annotated query over open `to_dept` rows, no N+1 (§17). The number
    links into the asset list's department filter, matching the detail
    page's "View assets in list".
    """

    roles_required = ()
    model = Department
    template_name = "people/department_list.html"

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("site", "head")
            .annotate(asset_count=Count("assignments", filter=Q(assignments__in_at__isnull=True)))
            .order_by("name")
        )
        return scope_list(
            self.request.user,
            qs,
            site_field="site",
            dept_field="pk",
            action="department_list",
            path=self.request.path,
        )


class DepartmentDetail(ScopeGuardMixin, RoleRequiredMixin, DetailView):
    """One department: its head, its department-held assets, its members.

    Read-only (roles_required = ()) like Site/Person detail, scope-guarded
    on the department row (site + department both recognized by
    `_org_ids_of`). "Department-held" means an open Assignment with
    `to_dept` set — assets held by individual members live on their own
    person pages, matching the department report's split.
    """

    roles_required = ()
    scope_action = "department_detail"
    model = Department
    template_name = "people/department_detail.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from apps.assets.models import Assignment

        ctx["head"] = (
            Person.objects.filter(pk=self.object.head_id)
            .select_related("site", "department")
            .first()
        )
        ctx["members"] = self.object.people.all()
        # same split as the person page: open rows now, capped history after
        # (select_related so the table never N+1s, §17)
        ctx["held_now"] = (
            Assignment.objects.filter(to_dept=self.object, in_at__isnull=True)
            .select_related("asset", "asset__category", "asset__site")
            .order_by("asset__asset_tag")
        )
        ctx["history_recent"] = (
            Assignment.objects.filter(to_dept=self.object, in_at__isnull=False)
            .select_related("asset")
            .order_by("-out_at")[:20]
        )
        return ctx


class DepartmentUpdate(ScopeGuardMixin, RoleRequiredMixin, UpdateView):
    """Edit a department in the main app (admin role, like Site/Person).

    The head (တာဝန်ခံ) can be changed here without the Django admin —
    scope re-checked against the target site on save, like PersonUpdate.
    """

    roles_required = ("admin",)
    scope_action = "department_update"
    model = Department
    form_class = DepartmentForm
    template_name = "people/department_form.html"
    success_url = reverse_lazy("department-list")

    def form_valid(self, form):
        try:
            check_scope(
                self.request.user,
                form.instance.site,
                action="department_update",
                path=self.request.path,
            )
        except OutOfScope:
            return HttpResponseForbidden("That site is outside your scope.")
        return super().form_valid(form)
