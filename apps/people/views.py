"""CRUD views for Site and Person (M2; DEVELOPMENT.md §9, §11).

Site/Person management = admin role (§11 user/site management).
Reads open to any authenticated user (auditor/viewer included).
"""

from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.roles import RoleRequiredMixin, is_admin
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
# (head + held inventory + members), edit (name/site/head, admin), delete
# (admin, only while nothing references the row).
# ---------------------------------------------------------------------------


class DepartmentList(RoleRequiredMixin, ListView):
    """Every department with its head, member count and dept-held asset count.

    Read-only for any authenticated user; scope-narrowed on both axes
    (site rows via `site`, department-scoped users via `pk`) — both counts
    are annotations in the one query, no N+1 (§17). Each Count is
    `distinct=True`: aggregating two multi-valued joins (`assignments` ×
    `people`) would otherwise multiply each other's rows and inflate both
    numbers. The member count mirrors the detail page's members card
    (`department.people.all()` — the site list renders its people count the
    same plain way); the asset number links into the asset list's department
    filter, matching the detail page's "View assets in list".
    """

    roles_required = ()
    model = Department
    template_name = "people/department_list.html"

    def get_queryset(self):
        qs = (
            super()
            .get_queryset()
            .select_related("site", "head")
            .annotate(
                asset_count=Count(
                    "assignments", filter=Q(assignments__in_at__isnull=True), distinct=True
                ),
                member_count=Count("people", distinct=True),
            )
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
    """One department: its head, its held assets, its members.

    Read-only (roles_required = ()) like Site/Person detail, scope-guarded
    on the department row (site + department both recognized by
    `_org_ids_of`). Two asset cards, deliberately kept apart:

    - "Department-held" — open Assignment with `to_dept` set: the asset's
      accountability (and check-in) sits with the department.
    - "Held by department members" — open rows with `to_person` whose
      person belongs to this department: the same people as the members
      card, surfaced here so the department's whole footprint is visible
      without visiting every person page (their history stays there);
      matches the report's per-person buckets.

    Both cards are open-only, one select_related query each (no N+1, §17).

    `can_delete` gates the delete button: admins only, and only while the row
    is empty (no members, no assignment rows) — both PROTECT backstops are
    re-checked server-side in DepartmentDelete, so a stale page or a crafted
    URL still cannot produce a 500.
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
        # the members' own open rows (card #2): filtered through the
        # person's department, so membership == the members card above
        ctx["member_held"] = (
            Assignment.objects.filter(to_person__department=self.object, in_at__isnull=True)
            .select_related("asset", "asset__category", "asset__site", "to_person")
            .order_by("to_person__name", "asset__asset_tag")
        )
        ctx["history_recent"] = (
            Assignment.objects.filter(to_dept=self.object, in_at__isnull=False)
            .select_related("asset")
            .order_by("-out_at")[:20]
        )
        # delete button: admin AND nothing references the row (PROTECT FKs);
        # short-circuits so non-admins pay no extra queries
        ctx["can_delete"] = is_admin(self.request.user) and not (
            self.object.people.exists() or self.object.assignments.exists()
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


class DepartmentDelete(ScopeGuardMixin, RoleRequiredMixin, DeleteView):
    """Delete a department — admin role, and only while nothing references it.

    `Person.department` and `Assignment.to_dept` are both PROTECT, so the
    database refuses the row regardless; this view turns that refusal into a
    friendly flow instead of a ProtectedError 500. The confirm page (GET) and
    the write (POST — Django 5.2's DeletionMixin deletes in `form_valid`, not
    in `delete()`) both bounce back to the detail page with the reason.
    Closed assignment rows count too: history is accountability and stays.
    The detail page only shows the button to admins when the row is genuinely
    empty (`can_delete`), so the guards here are the backstop for stale pages
    and crafted URLs.
    """

    roles_required = ("admin",)
    scope_action = "department_delete"
    model = Department
    template_name = "people/confirm_delete.html"
    success_url = reverse_lazy("department-list")
    cancel_url = "department-list"

    @staticmethod
    def _block_reason(dept: Department) -> str | None:
        members = dept.people.count()
        if members:
            return f'Cannot delete "{dept.name}": {members} member(s) still belong to it.'
        rows = dept.assignments.count()
        if rows:
            return f'Cannot delete "{dept.name}": {rows} assignment record(s) still reference it.'
        return None

    def get(self, request, *args, **kwargs):
        self.object = self.get_object()
        reason = self._block_reason(self.object)
        if reason:
            messages.error(request, reason)
            return redirect("department-detail", pk=self.object.pk)
        return super().get(request, *args, **kwargs)

    def form_valid(self, form):
        reason = self._block_reason(self.object)
        if reason:
            messages.error(self.request, reason)
            return redirect("department-detail", pk=self.object.pk)
        name = self.object.name
        response = super().form_valid(form)
        messages.success(self.request, f'Department "{name}" deleted.')
        return response
