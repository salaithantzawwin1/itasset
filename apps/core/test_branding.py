"""Sign-in page, branding logo and the anonymous-redirect contract."""

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from apps.core.models import Branding

# 1×1 transparent PNG — enough for ImageField/FileResponse; the view does not
# re-encode, it streams whatever was uploaded.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00"
    b"\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _branding(**extra):
    return Branding.objects.create(
        company_name=extra.pop("company_name", "Acme IT"),
        tagline=extra.pop("tagline", "Devices under control"),
        **extra,
    )


class AnonymousRedirectTests(TestCase):
    def test_root_sends_anonymous_visitors_to_the_sign_in_page(self):
        resp = self.client.get("/")
        self.assertRedirects(resp, "/accounts/login/?next=/", fetch_redirect_response=False)

    def test_sign_in_returns_to_the_requested_page(self):
        get_user_model().objects.create_user("tech", password="pw12345!")

        resp = self.client.post(
            reverse("login"),
            {"username": "tech", "password": "pw12345!", "next": "/assets/"},
        )

        self.assertRedirects(resp, "/assets/", fetch_redirect_response=False)

    def test_logout_lands_on_the_sign_in_page(self):
        user = get_user_model().objects.create_user("leaver", password="pw12345!")
        self.client.force_login(user)

        resp = self.client.post(reverse("logout"))

        self.assertRedirects(resp, reverse("login"), fetch_redirect_response=False)
        # the session is gone, so "/" bounces back to sign-in again
        followup = self.client.get("/")
        self.assertEqual(followup.status_code, 302)
        self.assertTrue(followup["Location"].startswith(reverse("login")))


class BrandingTests(TestCase):
    def test_current_returns_the_newest_row_or_none(self):
        self.assertIsNone(Branding.current())
        first = _branding(company_name="Older")
        second = _branding(company_name="Newer")
        self.assertEqual(Branding.current(), second)
        self.assertNotEqual(first, second)

    def test_logo_endpoint_404s_without_an_upload(self):
        self.assertEqual(self.client.get(reverse("branding-logo")).status_code, 404)
        _branding()
        self.assertEqual(self.client.get(reverse("branding-logo")).status_code, 404)

    def test_logo_endpoint_streams_the_uploaded_file(self):
        row = _branding(logo=SimpleUploadedFile("logo.png", PNG, content_type="image/png"))

        resp = self.client.get(reverse("branding-logo"))

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "image/png")
        self.assertIn("max-age", resp["Cache-Control"])
        self.assertEqual(b"".join(resp.streaming_content), PNG)
        self.assertTrue(row.logo.name.startswith("branding/logo"))

    def test_sign_in_page_shows_the_company_identity_and_logo(self):
        _branding(logo=SimpleUploadedFile("logo.png", PNG, content_type="image/png"))

        html = self.client.get(reverse("login")).content.decode()

        self.assertIn("Acme IT", html)
        self.assertIn("Devices under control", html)
        self.assertIn(reverse("branding-logo"), html)

    def test_sign_in_page_falls_back_to_the_default_name(self):
        html = self.client.get(reverse("login")).content.decode()
        self.assertIn("IT Asset Manager", html)
        self.assertNotIn(reverse("branding-logo"), html)

    def test_staff_admin_cannot_add_a_second_branding_row(self):
        admin = get_user_model().objects.create_superuser("root", "root@example.com", "pw12345!")
        self.client.force_login(admin)
        _branding()

        resp = self.client.get("/admin/core/branding/add/")

        self.assertEqual(resp.status_code, 403)


class BrandingAdminTests(TestCase):
    def test_admin_change_page_offers_the_logo_preview(self):
        admin = get_user_model().objects.create_superuser("root2", "r2@example.com", "pw12345!")
        row = _branding(logo=SimpleUploadedFile("logo.png", PNG, content_type="image/png"))
        self.client.force_login(admin)

        resp = self.client.get(f"/admin/core/branding/{row.pk}/change/")

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse("branding-logo"))
