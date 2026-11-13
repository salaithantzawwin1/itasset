"""Counted dashboard copy must not say "1 warranties" / "1 assets"."""

from types import SimpleNamespace

from django.template import Context, Template
from django.test import SimpleTestCase

TAG = "{% load t %}{% t key n=n %}"


class PluralAlertTests(SimpleTestCase):
    def render(self, key, n, lang="en"):
        context = Context(
            {
                "request": SimpleNamespace(session={"lang": lang}),
                "key": key,
                "n": n,
            }
        )
        return Template(TAG).render(context)

    def test_warranty_alert_uses_the_singular_for_one(self):
        self.assertEqual(
            self.render("alert.warranty_soon", 1),
            "1 warranty expiring within 7 days",
        )
        self.assertEqual(
            self.render("alert.warranty_soon", 3),
            "3 warranties expiring within 7 days",
        )

    def test_missing_serial_alert_uses_the_singular_for_one(self):
        self.assertEqual(
            self.render("alert.missing_serial", 1),
            "1 asset missing a serial number",
        )
        self.assertEqual(
            self.render("alert.missing_serial", 2),
            "2 assets missing a serial number",
        )

    def test_other_counted_alerts_use_the_singular_for_one(self):
        cases = (
            ("alert.overdue_loans", "1 loan overdue", "2 loans overdue"),
            (
                "alert.transfer_exceptions",
                "1 transfer in exception",
                "2 transfers in exception",
            ),
            (
                "alert.pending_approvals",
                "1 request awaiting approval",
                "2 requests awaiting approval",
            ),
        )
        for key, singular, plural in cases:
            with self.subTest(key=key):
                self.assertEqual(self.render(key, 1), singular)
                self.assertEqual(self.render(key, 2), plural)

    def test_myanmar_copy_is_unchanged_for_both_counts(self):
        one = self.render("alert.warranty_soon", 1, lang="my")
        many = self.render("alert.warranty_soon", 4, lang="my")

        self.assertEqual(one.replace("1", "{n}"), many.replace("4", "{n}"))
        self.assertIn("အာမခံ", one)
