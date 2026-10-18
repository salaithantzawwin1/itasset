"""CRUD views for Site and Person (M2; DEVELOPMENT.md §9, §11).

Site/Person management = admin role (§11 user/site management).
Reads open to any authenticated user (auditor/viewer included).
"""

from django.http import HttpResponseForbidden
from django.urls import reverse_lazy
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from apps.core.roles import RoleRequiredMixin
from apps.core.scopes import OutOfScope, ScopeGuardMixin, check_scope, scope_list

from .forms import PersonForm, SiteForm
from .models import Person, Site

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
