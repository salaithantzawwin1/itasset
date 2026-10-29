"""SpecChoice CRUD — admin-maintained option lists for choice spec fields.

Covers: the 0014 seed (RAM Type + Primary Storage Type), engine authority
(a maintained list *replaces* the schema's choices; keys without rows fall
back to the schema), and the admin add/rename/delete flows including both
in-use guards (single delete, bulk delete, rename).
"""

import importlib
from types import SimpleNamespace

from django.apps import apps as migration_apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.test import TestCase
from django.urls import reverse

from apps.assets.models import Asset, Category, SpecChoice
from apps.assets.specs import build_spec_form_fields, validate_specs
from apps.people.models import Site


def _category(fields, code="IT-TEST"):
    return Category(code=code, name="Test", schema={"version": 1, "fields": fields})


class TestSpecChoiceSeed(TestCase):
    """Migration 0014 ships the two requested lists."""

    def test_ram_type_seed_is_the_catalogue_union_in_order(self):
        self.assertEqual(
            list(SpecChoice.objects.filter(key="ram_type").values_list("value", flat=True)),
            ["DDR3", "DDR4", "DDR5", "LPDDR", "Other"],
        )

    def test_primary_storage_seed_is_the_catalogue_default(self):
        self.assertEqual(
            list(SpecChoice.objects.filter(key="storage_1_type").values_list("value", flat=True)),
            ["HDD", "SATA SSD", "NVMe SSD", "Other"],
        )

    def test_seed_rerun_is_idempotent(self):
        mig = importlib.import_module("apps.assets.migrations.0014_specchoice")
        before = SpecChoice.objects.count()
        mig.seed_spec_choices(migration_apps, SimpleNamespace(connection=connection))
        self.assertEqual(SpecChoice.objects.count(), before)


class TestManagedChoiceEngine(TestCase):
    """The maintained list drives validation and dropdowns; schema is fallback."""

    def test_maintained_list_adds_options_the_schema_does_not_declare(self):
        SpecChoice.objects.create(key="ram_type", value="DDR6", order=60)
        cat = Category.objects.get(code="IT-HW-DSK")
        cleaned = validate_specs(cat, {"ram_type": "DDR6"})
        self.assertEqual(cleaned["ram_type"], "DDR6")

    def test_maintained_list_is_authoritative_over_schema_choices(self):
        """A value outside the maintained list is refused even when a (stale)
        category schema still declares it — otherwise CRUD delete would lie."""
        cat = _category(
            [
                {
                    "key": "ram_type",
                    "label": "RAM Type",
                    "type": "choice",
                    "choices": ["GDDR6"],
                    "required": False,
                }
            ]
        )
        with self.assertRaises(ValidationError) as ctx:
            validate_specs(cat, {"ram_type": "GDDR6"})
        self.assertIn("ram_type", ctx.exception.message_dict)

    def test_maintained_multi_choice_set_replaces_the_schema_list(self):
        SpecChoice.objects.create(key="inputs", value="VGA", order=90)
        cat = _category(
            [
                {
                    "key": "inputs",
                    "label": "Inputs",
                    "type": "multi-choice",
                    "choices": ["HDMI", "DP"],
                    "required": False,
                }
            ]
        )
        cleaned = validate_specs(cat, {"inputs": ["VGA"]})
        self.assertEqual(cleaned["inputs"], ["VGA"])
        with self.assertRaises(ValidationError):  # schema-only, not maintained
            validate_specs(cat, {"inputs": ["HDMI"]})

    def test_keys_without_rows_fall_back_to_schema_choices(self):
        cat = _category(
            [
                {
                    "key": "panel_type",
                    "label": "Panel Type",
                    "type": "choice",
                    "choices": ["IPS", "TN"],
                    "required": False,
                }
            ]
        )
        self.assertEqual(validate_specs(cat, {"panel_type": "TN"})["panel_type"], "TN")
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"panel_type": "OLED"})

    def test_dropdowns_offer_the_maintained_options(self):
        SpecChoice.objects.create(key="ram_type", value="DDR6", order=60)
        fields = build_spec_form_fields(Category.objects.get(code="IT-HW-DSK"))
        ram_options = [value for value, _ in fields["spec__ram_type"].choices]
        # LPDDR comes from the shared list although the Desktop schema lacks it,
        # and DDR6 appears the moment the admin adds it — no schema edits
        self.assertIn("LPDDR", ram_options)
        self.assertIn("DDR6", ram_options)
        storage_options = [value for value, _ in fields["spec__storage_1_type"].choices]
        self.assertIn("NVMe SSD", storage_options)

    def test_dropdown_falls_back_when_the_key_has_no_rows(self):
        fields = build_spec_form_fields(Category.objects.get(code="IT-HW-MON"))
        self.assertEqual(
            [value for value, _ in fields["spec__panel_type"].choices],
            ["", "IPS", "TN", "VA", "OLED", "Other"],
        )

    def test_multi_choice_value_counts_as_in_use(self):
        choice = SpecChoice.objects.create(key="inputs", value="HDMI", order=10)
        Asset.objects.create(
            asset_tag="IT-HW-DSK-9998",
            category=Category.objects.get(code="IT-HW-DSK"),
            site=Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0],
            attrs={"inputs": ["HDMI", "DP"]},
        )
        self.assertEqual(choice.assets_in_use(), 1)


class TestSpecChoiceAdmin(TestCase):
    """The admin CRUD: add, rename, delete — with in-use data guards."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = get_user_model().objects.create_superuser(
            "spec_admin", "spec_admin@example.com", "pass12345!"
        )
        cls.site = Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0]
        cls.dsk = Category.objects.get(code="IT-HW-DSK")
        cls.used_asset = Asset.objects.create(
            asset_tag="IT-HW-DSK-9001",
            category=cls.dsk,
            site=cls.site,
            attrs={"ram_type": "DDR4", "storage_1_type": "NVMe SSD"},
        )

    def setUp(self):
        self.client.force_login(self.admin_user)

    def _url(self, name, *args):
        return reverse(f"admin:assets_specchoice_{name}", args=args)

    def test_changelist_lists_options_with_usage_visible(self):
        resp = self.client.get(self._url("changelist"))
        self.assertEqual(resp.status_code, 200)
        rows = {str(option): option for option in resp.context["cl"].result_list}
        self.assertIn("ram_type: DDR4", rows)
        self.assertIn("storage_1_type: NVMe SSD", rows)
        self.assertEqual(rows["ram_type: DDR4"].assets_in_use(), 1)

    def test_add_form_offers_only_live_schema_keys(self):
        resp = self.client.get(self._url("add"))
        self.assertEqual(resp.status_code, 200)
        keys = [value for value, _ in resp.context["adminform"].form.fields["key"].choices if value]
        self.assertIn("ram_type", keys)
        self.assertIn("storage_1_type", keys)
        self.assertIn("panel_type", keys)  # any choice field of any schema
        self.assertNotIn("bogus_key", keys)  # a typo'd key can never be selected

    def test_add_option_via_admin_becomes_selectable_everywhere(self):
        resp = self.client.post(
            self._url("add"),
            {"key": "ram_type", "value": "DDR6", "order": "60", "_save": "Save"},
        )
        self.assertEqual(resp.status_code, 302)
        row = SpecChoice.objects.get(key="ram_type", value="DDR6")
        self.assertEqual(row.order, 60)
        # immediately live: accepted by validation and offered in the dropdown
        self.assertEqual(validate_specs(self.dsk, {"ram_type": "DDR6"})["ram_type"], "DDR6")
        fields = build_spec_form_fields(self.dsk)
        self.assertIn("DDR6", [value for value, _ in fields["spec__ram_type"].choices])

    def test_unknown_key_is_refused(self):
        resp = self.client.post(
            self._url("add"),
            {"key": "ram_tpyo", "value": "DDR6", "order": "0", "_save": "Save"},
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with an error
        self.assertFalse(SpecChoice.objects.filter(key="ram_tpyo").exists())

    def test_case_variant_duplicate_is_refused(self):
        resp = self.client.post(
            self._url("add"),
            {"key": "ram_type", "value": "ddr5", "order": "0", "_save": "Save"},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(SpecChoice.objects.filter(key="ram_type", value="ddr5").exists())
        self.assertContains(resp, "already exists")

    def test_rename_of_in_use_option_is_refused(self):
        row = SpecChoice.objects.get(key="ram_type", value="DDR4")
        resp = self.client.post(
            self._url("change", row.pk),
            {"key": "ram_type", "value": "DDR4 Legacy", "order": "20", "_save": "Save"},
        )
        self.assertEqual(resp.status_code, 200)
        row.refresh_from_db()
        self.assertEqual(row.value, "DDR4")  # unchanged — stored values keep matching
        self.assertContains(resp, "still recorded by 1 asset")

    def test_rename_of_unused_option_succeeds(self):
        row = SpecChoice.objects.get(key="ram_type", value="LPDDR")
        resp = self.client.post(
            self._url("change", row.pk),
            {"key": "ram_type", "value": "LPDDR4X", "order": "40", "_save": "Save"},
        )
        self.assertEqual(resp.status_code, 302)
        row.refresh_from_db()
        self.assertEqual(row.value, "LPDDR4X")

    def test_in_use_option_cannot_be_deleted(self):
        row = SpecChoice.objects.get(key="ram_type", value="DDR4")
        # GET: refused before the confirmation page, with an explanation
        resp = self.client.get(self._url("delete", row.pk), follow=True)
        self.assertEqual(resp.status_code, 200)
        queued = list(resp.context["messages"])
        self.assertEqual([m.level for m in queued], [messages.ERROR])
        self.assertIn("Cannot delete", str(queued[0]))
        # a direct POST cannot slip past the guard either
        self.client.post(self._url("delete", row.pk), {"post": "yes"})
        self.assertTrue(SpecChoice.objects.filter(pk=row.pk).exists())

    def test_unused_option_can_be_deleted(self):
        row = SpecChoice.objects.get(key="ram_type", value="LPDDR")
        resp = self.client.get(self._url("delete", row.pk))
        self.assertEqual(resp.status_code, 200)  # normal confirmation page
        self.assertContains(resp, "Are you sure")
        resp = self.client.post(self._url("delete", row.pk), {"post": "yes"})
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(SpecChoice.objects.filter(pk=row.pk).exists())

    def test_bulk_delete_is_refused_while_any_selection_is_in_use(self):
        used = SpecChoice.objects.get(key="ram_type", value="DDR4")
        unused = SpecChoice.objects.get(key="ram_type", value="LPDDR")
        selection = {
            "action": "delete_selected",
            "_selected_action": [str(used.pk), str(unused.pk)],
        }
        resp = self.client.post(self._url("changelist"), selection)
        self.assertEqual(resp.status_code, 200)  # confirmation page, protected listed
        self.assertContains(resp, "still recorded by 1 asset")
        # confirming anyway deletes nothing — Django skips protected selections
        resp = self.client.post(self._url("changelist"), {**selection, "post": "yes"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(SpecChoice.objects.filter(pk__in=[used.pk, unused.pk]).count(), 2)
