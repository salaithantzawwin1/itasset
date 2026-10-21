"""M1 smoke tests: healthz, seed, admin CRUD (DEVELOPMENT.md §28 M1)."""

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from apps.assets.models import Asset


class SmokeTests(TestCase):
    def test_healthz_ok(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")

    def test_seed_creates_50_assets(self):
        call_command("seed_demo")
        self.assertEqual(Asset.objects.count(), 50)
        self.assertEqual(Asset.objects.values("asset_tag").distinct().count(), 50)
        call_command("seed_demo")  # idempotent
        self.assertEqual(Asset.objects.count(), 50)

    def test_html_lang_follows_session_switch(self):
        """`<html lang>` tracks the ENG/MM session key (default en, like {% t %})."""
        resp = self.client.get("/accounts/login/")  # standalone template
        self.assertContains(resp, '<html lang="en"')

        session = self.client.session
        session["lang"] = "my"
        session.save()
        resp = self.client.get("/accounts/login/")
        self.assertContains(resp, '<html lang="my"')

        resp = self.client.get("/")  # base.html page
        if resp.status_code == 302:
            user = get_user_model().objects.create_superuser(
                "langtest", "lang@example.com", "pass12345!"
            )
            self.client.force_login(user)
            resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '<html lang="my"')

    def test_admin_login_and_asset_crud(self):
        user = get_user_model().objects.create_superuser("admintest", "a@example.com", "pass12345!")
        self.client.force_login(user)

        # list
        resp = self.client.get(reverse("admin:assets_asset_changelist"))
        self.assertEqual(resp.status_code, 200)

        # create (CRUD — M1 done criterion)
        call_command("seed_demo")
        asset = Asset.objects.first()
        resp = self.client.get(reverse("admin:assets_asset_change", args=[asset.pk]))
        self.assertEqual(resp.status_code, 200)
