"""Admin UI/UX smoke: every registered ModelAdmin must actually render.

Guards the two things that silently break admin usability:
- changelist/add pages raising (bad list_filter/search/date_hierarchy columns)
- `autocomplete_fields` pointing at a ModelAdmin without `search_fields`
  (admin.E040 — explodes only when a staff user opens the form)
"""

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase
from django.urls import reverse


class AdminSmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            "admin_smoke", "admin_smoke@example.com", "pass12345!"
        )

    def test_autocomplete_targets_have_search_fields(self):
        """Every autocomplete_fields target's ModelAdmin must define search_fields."""
        for model, model_admin in admin.site._registry.items():
            for field_name in getattr(model_admin, "autocomplete_fields", ()):
                with self.subTest(model=model.__name__, field=field_name):
                    rel_model = model._meta.get_field(field_name).related_model
                    rel_admin = admin.site._registry.get(rel_model)
                    self.assertIsNotNone(rel_admin, f"no admin registered for {rel_model}")
                    self.assertTrue(
                        getattr(rel_admin, "search_fields", ()),
                        f"{model.__name__}.{field_name} → {rel_model.__name__} admin "
                        "must set search_fields for autocomplete",
                    )

    def test_every_changelist_and_add_page_renders(self):
        self.client.force_login(self.superuser)
        request = RequestFactory().get("/admin/")
        request.user = self.superuser
        for model, model_admin in admin.site._registry.items():
            opts = model._meta
            with self.subTest(model=f"{opts.app_label}.{opts.model_name}"):
                changelist = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
                self.assertEqual(self.client.get(changelist).status_code, 200)

                add_url = reverse(f"admin:{opts.app_label}_{opts.model_name}_add")
                expected = 200 if model_admin.has_add_permission(request) else 403
                self.assertEqual(self.client.get(add_url).status_code, expected)

                # exercise every custom SimpleListFilter's lookups + queryset()
                for f in model_admin.list_filter:
                    if isinstance(f, str):
                        continue
                    model_label = f"{opts.app_label}.{opts.model_name}"
                    with self.subTest(model=model_label, filter=f.__name__):
                        flt = f(request, {}, model, model_admin)
                        qs_values = flt.lookups(request, model_admin)
                        for value, _label in qs_values:
                            filtered = f"{changelist}?{flt.parameter_name}={value}"
                            self.assertEqual(self.client.get(filtered).status_code, 200)

    def test_admin_index_renders_with_branding(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:index"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["site_header"], "IT Asset Manager administration")
        # every app that ships models must be listed, not silently dropped
        labels = {app["app_label"] for app in resp.context["available_apps"]}
        for label in ("assets", "people", "audit", "vendors", "licenses"):
            self.assertIn(label, labels)
        # redesign: card dashboard markup, not Django's stock module tables
        self.assertContains(resp, "dash-grid")
        self.assertContains(resp, "dash-card")
        self.assertContains(resp, "Recent actions")

    def test_login_page_renders_redesigned_card(self):
        resp = self.client.get(reverse("admin:login"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "login-card")
        self.assertContains(resp, 'name="username"')
        self.assertContains(resp, 'name="password"')

    def test_app_index_renders_cards(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:app_list", args=["assets"]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "dash-grid")

    def test_sidebar_tree_renders_on_changelists(self):
        """Every admin page carries the model tree, with the current row marked."""
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:assets_asset_changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'class="anav"')
        self.assertContains(resp, "anav-group")
        self.assertContains(resp, "Back to site")
        self.assertContains(resp, 'aria-current="page"')

    def test_dashboard_kpi_strip_renders(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse("admin:index"))
        self.assertContains(resp, "kpi-grid")
        self.assertContains(resp, "kpi-card")
        self.assertContains(resp, "kpi-value")

    def test_admin_language_follows_session_switch(self):
        """Admin chrome speaks the same language as the app's ENG/MM switch."""
        resp = self.client.get(reverse("admin:login"))
        self.assertContains(resp, 'lang="en"')  # default matches {% t %}
        session = self.client.session
        session["lang"] = "my"
        session.save()
        resp = self.client.get(reverse("admin:login"))
        self.assertContains(resp, 'lang="my"')

    def test_category_plural_label(self):
        from apps.assets.models import Category

        self.assertEqual(Category._meta.verbose_name_plural, "categories")

    def test_asset_change_form_sections_into_tabs(self):
        """The long asset form splits into one tab per fieldset — and every
        field must still render (an unrendered field vanishes from the POST)."""
        from django.core.management import call_command

        from apps.assets.models import Asset

        self.client.force_login(self.superuser)
        call_command("seed_demo")
        asset = Asset.objects.first()
        resp = self.client.get(reverse("admin:assets_asset_change", args=[asset.pk]))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'role="tablist"')

        fieldsets = resp.context["adminform"].fieldsets
        titles = [fs[0] for fs in fieldsets]
        # four sections, category first in Basics; the category's spec fields
        # merge into "Specifications" instead of appending a fifth fieldset
        self.assertEqual(titles, ["Basics", "Specifications", "Device", "Procurement"])
        self.assertEqual(fieldsets[0][1]["fields"][0], "category")
        for i in range(len(fieldsets)):
            self.assertContains(resp, f'data-tab-panel="{i}"')

        for name in ("asset_tag", "category", "manufacturer", "purchase_date", "cost", "remarks"):
            self.assertContains(resp, f'name="{name}"')
        self.assertContains(resp, 'name="spec__')  # merged specs really render
