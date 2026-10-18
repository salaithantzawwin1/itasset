"""Tests for the dashboard home page (root URL) and the staff-only Admin link."""

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from apps.assets.models import Asset, Category
from apps.people.models import Site


class DashboardHomeTests(TestCase):
    def _seed(self):
        site = Site.objects.create(name="Yangon HQ", code="yangon")
        cat = Category.objects.create(code="IT-HW-LAP", name="Laptop")
        for i in range(3):
            Asset.objects.create(asset_tag=f"TAG-{i}", category=cat, site=site)
        return site, cat

    def test_root_is_dashboard_home(self):
        self._seed()
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "dashboard/home.html")
        self.assertEqual(resp.context["total_assets"], 3)
        self.assertEqual(resp.context["total_people"], 0)
        self.assertEqual(resp.context["total_sites"], 1)

    def test_status_summary_widgets_present(self):
        self._seed()
        resp = self.client.get("/")
        # widgets render status/condition/site breakdowns + recent rows
        self.assertEqual(len(resp.context["by_status"]), 1)  # all 3 assets IN_STOCK
        self.assertEqual(resp.context["by_status"][0]["n"], 3)
        self.assertEqual(len(resp.context["recent"]), 3)
        self.assertContains(resp, "By status")
        self.assertContains(resp, "Recently added")

    def test_healthz_still_ok(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class AdminLinkVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staffu", "s@example.com", "pw12345!", is_staff=True)
        self.plain = User.objects.create_user("plainu", "p@example.com", "pw12345!")

    def test_admin_link_hidden_for_anonymous(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "/admin/")

    def test_admin_link_hidden_for_non_staff_user(self):
        self.client.force_login(self.plain)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'href="/admin/"')

    def test_admin_link_shown_for_staff_user(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'href="/admin/"')

    def test_admin_link_shown_for_superuser(self):
        User = get_user_model()
        User.objects.create_superuser("adminu", "a@example.com", "pw12345!")
        self.client.force_login(self.staff)
        self.client.logout()
        self.client.force_login(User.objects.get(username="adminu"))
        resp = self.client.get("/")
        self.assertContains(resp, 'href="/admin/"')

    def test_url_name_home_resolves_to_root(self):
        self.assertEqual(reverse("home"), "/")
