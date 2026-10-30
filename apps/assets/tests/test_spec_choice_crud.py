"""SpecChoice CRUD — maintained option lists for choice spec fields.

Covers: the 0014 seed (RAM Type + Primary Storage Type) and the 0016 seed
(Secondary Storage Type), engine authority (a maintained list *replaces*
the schema's choices; keys without rows fall back to the schema), the
admin add/rename/delete flows with both in-use guards (single delete, bulk
delete, rename), the admin key filter listing schema keys that have NO rows
yet, and the main-app option-list page (technician-gated, same data guards
as the admin — no admin hop for day-to-day edits).
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
    """Migrations 0014 + 0016 ship the three requested lists."""

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

    def test_secondary_storage_seed_is_the_catalogue_default(self):
        """0016 backfills the third list with the same defaults the catalogue
        schema declares — stored values can never leave the allowed set."""
        self.assertEqual(
            list(SpecChoice.objects.filter(key="storage_2_type").values_list("value", flat=True)),
            ["HDD", "SATA SSD", "NVMe SSD", "Other"],
        )

    def test_secondary_storage_seed_rerun_is_idempotent(self):
        mig = importlib.import_module("apps.assets.migrations.0016_seed_storage_2_type")
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

    def test_key_filter_shows_schema_keys_without_rows(self):
        """The sidebar key filter must list schema keys with ZERO rows (a
        freshly-added or emptied list) — the stock values-only filter hid
        them, so such a key could never be filtered on."""
        resp = self.client.get(self._url("changelist"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "?key=ram_type")  # keys with rows keep working
        self.assertContains(resp, "?key=panel_type")  # a rowless schema key shows too
        self.assertEqual(SpecChoice.objects.filter(key="panel_type").count(), 0)

    def test_add_form_offers_only_live_schema_keys(self):
        resp = self.client.get(self._url("add"))
        self.assertEqual(resp.status_code, 200)
        keys = [value for value, _ in resp.context["adminform"].form.fields["key"].choices if value]
        self.assertIn("ram_type", keys)
        self.assertIn("storage_1_type", keys)
        self.assertIn("panel_type", keys)  # any choice field of any schema
        self.assertNotIn("bogus_key", keys)  # a typo'd key can never be selected

    def test_key_field_is_type_to_search(self):
        """The key control is a text input backed by a <datalist>: a couple of
        dozen keys meant scrolling one long select, so typing narrows the
        suggestions instead — validation still runs against the live keys
        (``test_unknown_key_is_refused``)."""
        resp = self.client.get(self._url("add"))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('list="id_key"', body)
        self.assertIn('<datalist id="id_key">', body)
        self.assertIn('<option value="ram_type">', body)
        self.assertIn('<option value="panel_type">', body)  # rowless keys suggest too
        self.assertIn("Type to search", body)
        self.assertNotIn('<select name="key"', body)

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


# ------------------------------------------------- main-app option-list page


class TestSpecChoiceOptionPage(TestCase):
    """/assets/spec-options/ — manage the lists without an admin hop.

    Technician-gated like the other maintenance pages, renders a section
    for every choice key (zero rows included), and runs the same
    data-safety guards as the admin CRUD on add/save/delete.
    """

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import Group

        cls.site = Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0]
        cls.dsk = Category.objects.get(code="IT-HW-DSK")
        cls.tech = get_user_model().objects.create_user(
            "spec_page_tech", "spec_page_tech@x.dev", "pass12345!"
        )
        cls.tech.groups.add(Group.objects.get_or_create(name="technician")[0])
        cls.viewer = get_user_model().objects.create_user(
            "spec_page_viewer", "spec_page_viewer@x.dev", "pass12345!"
        )
        cls.viewer.groups.add(Group.objects.get_or_create(name="viewer")[0])
        cls.used = Asset.objects.create(
            asset_tag="IT-HW-DSK-9101",
            category=cls.dsk,
            site=cls.site,
            attrs={"ram_type": "DDR4"},
        )

    def _url(self):
        return reverse("spec-options")

    def test_anonymous_redirects_and_viewers_are_refused(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

        self.client.force_login(self.viewer)
        self.assertEqual(self.client.get(self._url()).status_code, 403)

    def test_page_lists_every_schema_key_even_without_rows(self):
        self.client.force_login(self.tech)
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        # the three maintained lists render a section each …
        self.assertIn("(ram_type)", body)
        self.assertIn("(storage_1_type)", body)
        self.assertIn("(storage_2_type)", body)
        # … and so does a key with zero rows — that's where its list starts
        self.assertEqual(SpecChoice.objects.filter(key="panel_type").count(), 0)
        self.assertIn("(panel_type)", body)
        self.assertIn('name="add_value"', body)  # add form per section
        self.assertIn("NVMe SSD", body)  # seeded options visible

    def test_add_option_from_the_page(self):
        self.client.force_login(self.tech)
        resp = self.client.post(
            self._url(),
            {"action": "add", "key": "ram_type", "add_value": "DDR6", "add_order": "60"},
            follow=True,
        )
        self.assertEqual(resp.status_code, 200)
        row = SpecChoice.objects.get(key="ram_type", value="DDR6")
        self.assertEqual(row.order, 60)
        self.assertContains(resp, "DDR6")  # shows on the redirected page
        queued = list(resp.context["messages"])
        self.assertEqual([m.level for m in queued], [messages.SUCCESS])

    def test_add_refuses_case_duplicate_and_unknown_key(self):
        self.client.force_login(self.tech)
        resp = self.client.post(
            self._url(),
            {"action": "add", "key": "ram_type", "add_value": "ddr4", "add_order": "0"},
            follow=True,
        )
        self.assertFalse(SpecChoice.objects.filter(key="ram_type", value="ddr4").exists())
        self.assertIn("already exists", str(list(resp.context["messages"])[0]))

        resp = self.client.post(
            self._url(),
            {"action": "add", "key": "bogus_key", "add_value": "X", "add_order": "0"},
            follow=True,
        )
        self.assertFalse(SpecChoice.objects.filter(key="bogus_key").exists())
        self.assertIn("Unknown option list", str(list(resp.context["messages"])[0]))

    def test_save_updates_value_and_order(self):
        self.client.force_login(self.tech)
        row = SpecChoice.objects.get(key="ram_type", value="LPDDR")
        resp = self.client.post(
            self._url(),
            {"action": f"save:{row.pk}", f"value_{row.pk}": "LPDDR4X", f"order_{row.pk}": "45"},
            follow=True,
        )
        row.refresh_from_db()
        self.assertEqual((row.value, row.order), ("LPDDR4X", 45))
        self.assertContains(resp, "LPDDR4X")

    def test_save_refuses_renaming_an_option_assets_still_record(self):
        self.client.force_login(self.tech)
        row = SpecChoice.objects.get(key="ram_type", value="DDR4")
        resp = self.client.post(
            self._url(),
            {
                "action": f"save:{row.pk}",
                f"value_{row.pk}": "DDR4 Legacy",
                f"order_{row.pk}": "20",
            },
            follow=True,
        )
        row.refresh_from_db()
        self.assertEqual(row.value, "DDR4")  # unchanged — stored values keep matching
        self.assertIn("still recorded by 1 asset", str(list(resp.context["messages"])[0]))

    def test_delete_refuses_in_use_and_removes_unused(self):
        self.client.force_login(self.tech)
        used = SpecChoice.objects.get(key="ram_type", value="DDR4")
        resp = self.client.post(self._url(), {"action": f"delete:{used.pk}"}, follow=True)
        self.assertTrue(SpecChoice.objects.filter(pk=used.pk).exists())
        self.assertIn("Cannot delete", str(list(resp.context["messages"])[0]))

        unused = SpecChoice.objects.get(key="ram_type", value="LPDDR")
        self.client.post(self._url(), {"action": f"delete:{unused.pk}"})
        self.assertFalse(SpecChoice.objects.filter(pk=unused.pk).exists())

    def test_crafted_action_is_ignored_not_a_500(self):
        self.client.force_login(self.tech)
        resp = self.client.post(self._url(), {"action": "save:not-a-pk", "value_x": "y"})
        self.assertEqual(resp.status_code, 302)  # redirect, never a crash
        self.assertEqual(
            self.client.post(self._url(), {"action": "something-else"}).status_code, 302
        )
