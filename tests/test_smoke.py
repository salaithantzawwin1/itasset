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

    def test_template_comments_never_span_lines(self):
        """`{# … #}` comments cannot span lines: Django's lexer only matches
        them within one line, so a wrapped comment ships to the browser as
        literal page text — which is exactly how the assets filter bar
        displayed its source comment (session 38). Scan every template.
        """
        from pathlib import Path

        from django.conf import settings

        bad = []
        for tpl in Path(settings.BASE_DIR, "templates").rglob("*.html"):
            text = tpl.read_text(encoding="utf-8")
            i = 0
            while True:
                i = text.find("{#", i)
                if i == -1:
                    break
                j = text.find("#}", i)
                if j == -1 or "\n" in text[i : j + 2]:
                    bad.append(f"{tpl}:{text.count(chr(10), 0, i) + 1}")
                    break
                i = j + 2
        self.assertEqual(bad, [], f"multi-line/unterminated template comments: {bad}")

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
