"""Category-specific specification catalogue tests (§5 master doc, ADR-0004).

Covers: catalogue integrity + migration seeding, the validation engine
(coercion, required, unknown keys, option sets, ranges, IP, multi-choice),
the dynamic AssetForm fields, category-change value preservation (§8.2),
detail-page rendering, admin round-trip, the API attrs contract, and
fulfill_request attrs.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.assets.forms import AssetForm
from apps.assets.models import Asset, AssetRequest, Category
from apps.assets.specs import (
    CATALOGUE,
    SPEC_FIELD_PREFIX,
    build_spec_form_fields,
    format_spec_value,
    merge_preserved,
    spec_fields,
    validate_schema_dict,
    validate_specs,
)
from apps.people.models import Site


def _site():
    return Site.objects.get_or_create(code="yangon", defaults={"name": "Yangon HQ"})[0]


def _category(fields, code="IT-TEST", save=False):
    cat = Category(code=code, name="Test", schema={"version": 1, "fields": fields})
    if save:
        cat.save()
    return cat


FULL_SCHEMA = [
    {"key": "cpu_model", "label": "CPU Model", "type": "string", "required": False},
    {
        "key": "cpu_cores",
        "label": "Cores",
        "type": "integer",
        "min": 1,
        "max": 128,
        "required": False,
    },
    {
        "key": "ram_gb",
        "label": "RAM",
        "type": "decimal",
        "unit": "GB",
        "min": 0.5,
        "required": False,
    },
    {"key": "encrypted", "label": "Encrypted", "type": "boolean", "required": False},
    {
        "key": "ram_type",
        "label": "RAM Type",
        "type": "choice",
        "choices": ["DDR4", "DDR5", "Other"],
        "required": False,
    },
    {
        "key": "inputs",
        "label": "Inputs",
        "type": "multi-choice",
        "choices": ["HDMI", "DP", "USB-C"],
        "required": False,
    },
    {"key": "bought", "label": "Bought", "type": "date", "required": False},
    {"key": "mgmt_ip", "label": "Mgmt IP", "type": "ip", "required": False},
]


# ---------------------------------------------------------------------------
# Catalogue integrity + seeding
# ---------------------------------------------------------------------------


class TestCatalogue(TestCase):
    def test_every_catalogue_schema_is_structurally_valid(self):
        for code, entry in CATALOGUE.items():
            with self.subTest(code=code):
                validate_schema_dict(entry["schema"])  # must not raise

    def test_every_catalogue_schema_has_unique_keys_and_known_types(self):
        known = {
            "string",
            "text",
            "integer",
            "decimal",
            "boolean",
            "choice",
            "multi-choice",
            "date",
            "ip",
        }
        for code, entry in CATALOGUE.items():
            keys = [f["key"] for f in entry["schema"]["fields"]]
            self.assertEqual(len(keys), len(set(keys)), f"{code}: duplicate keys")
            for fdef in entry["schema"]["fields"]:
                self.assertIn(fdef["type"], known)
                if fdef["type"] in ("choice", "multi-choice"):
                    self.assertTrue(fdef.get("choices"), f"{code}.{fdef['key']} needs choices")

    def test_migration_seeded_the_catalogue(self):
        """Migration 0008 created every catalogue category with its schema."""
        for code, entry in CATALOGUE.items():
            cat = Category.objects.filter(code=code).first()
            self.assertIsNotNone(cat, f"{code} missing after migration")
            if entry["schema"]["fields"]:
                self.assertTrue(cat.schema.get("fields"), f"{code} schema empty")

    def test_workstation_reuses_the_desktop_field_set(self):
        """§5.3: reuse the Desktop PC fields plus extras — never duplicate."""
        desktop = {f["key"] for f in CATALOGUE["IT-HW-DSK"]["schema"]["fields"]}
        work = {f["key"] for f in CATALOGUE["IT-HW-WKS"]["schema"]["fields"]}
        self.assertTrue(desktop < work)  # strict superset

    def test_catalogue_ships_no_required_fields_until_business_confirms(self):
        """§5 preface: 'Recommended' is not automatically mandatory."""
        for code, entry in CATALOGUE.items():
            for fdef in entry["schema"]["fields"]:
                self.assertFalse(
                    fdef.get("required"), f"{code}.{fdef['key']} should not be required"
                )

    def test_every_memory_category_declares_ram_speed_next_to_ram_type(self):
        """§5.1 pairs RAM Speed with RAM Type — wherever memory is specified
        its speed is recordable (Desktop/Workstation always had it; Laptop
        and Physical Server gained it in session 42). One shared key also
        means the dashboard's RAM card sees every category."""
        for code, entry in CATALOGUE.items():
            keys = [f["key"] for f in entry["schema"]["fields"]]
            if "ram_type" in keys:
                with self.subTest(code=code):
                    self.assertIn("ram_speed_mhz", keys)
                    self.assertEqual(keys.index("ram_speed_mhz"), keys.index("ram_type") + 1)

    def test_seeded_schemas_carry_ram_speed(self):
        """The DB rows (not just the code) expose the field — the dynamic
        form, detail card and validation all read Category.schema."""
        for code in ("IT-HW-DSK", "IT-HW-WKS", "IT-HW-LAP", "IT-HW-SRV"):
            cat = Category.objects.get(code=code)
            keys = [f["key"] for f in cat.schema["fields"]]
            with self.subTest(code=code):
                self.assertIn("ram_speed_mhz", keys)
                self.assertEqual(keys.index("ram_speed_mhz"), keys.index("ram_type") + 1)


class TestRamSpeedMigration(TestCase):
    """Migration 0013 merges the field into schemas 0008 already seeded.

    0008 only fills a schema that is *empty*, so production's populated
    Laptop/Server rows would never pick the field up on their own — the
    exact gap this migration closes.
    """

    @staticmethod
    def _run_migration():
        import importlib
        from types import SimpleNamespace

        from django.apps import apps as migration_apps
        from django.db import connection

        mig = importlib.import_module(
            "apps.assets.migrations.0013_add_ram_speed_to_category_schemas"
        )
        # the migration only reads schema_editor.connection.alias
        mig.add_ram_speed(migration_apps, SimpleNamespace(connection=connection))

    def test_pre_speed_schema_gains_the_field_without_losing_anything(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        definition = next(
            f for f in CATALOGUE["IT-HW-LAP"]["schema"]["fields"] if f["key"] == "ram_speed_mhz"
        )
        before = [f for f in cat.schema["fields"] if f["key"] != "ram_speed_mhz"]
        cat.schema = {**cat.schema, "fields": before}  # production's pre-0013 row
        cat.save(update_fields=["schema"])

        self._run_migration()

        cat.refresh_from_db()
        keys = [f["key"] for f in cat.schema["fields"]]
        self.assertIn("ram_speed_mhz", keys)
        self.assertEqual(keys.index("ram_speed_mhz"), keys.index("ram_type") + 1)
        self.assertEqual(
            next(f for f in cat.schema["fields"] if f["key"] == "ram_speed_mhz"), definition
        )
        # every pre-existing field survived untouched
        self.assertEqual([f for f in cat.schema["fields"] if f["key"] != "ram_speed_mhz"], before)

        # idempotent: a second run must not duplicate the field
        count_before = len(cat.schema["fields"])
        self._run_migration()
        cat.refresh_from_db()
        self.assertEqual(len(cat.schema["fields"]), count_before)

    def test_schemas_without_ram_type_are_left_alone(self):
        """Categories that never specify memory (a Monitor, a Switch) must
        not grow a speed field."""
        mon = Category.objects.get(code="IT-HW-MON")
        before = mon.schema
        self._run_migration()
        mon.refresh_from_db()
        self.assertEqual(mon.schema, before)
        self.assertNotIn("ram_speed_mhz", [f["key"] for f in mon.schema["fields"]])


class TestRamSpeedValidation(TestCase):
    def test_speed_is_coerced_and_bounded_like_the_other_integers(self):
        cat = _category(CATALOGUE["IT-HW-LAP"]["schema"]["fields"])
        cleaned = validate_specs(cat, {"ram_type": "ddr4", "ram_speed_mhz": "3200"})
        self.assertEqual(cleaned["ram_type"], "DDR4")
        self.assertEqual(cleaned["ram_speed_mhz"], 3200)
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"ram_speed_mhz": 0})  # min=1
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"ram_speed_mhz": "fast"})


# ---------------------------------------------------------------------------
# Validation engine
# ---------------------------------------------------------------------------


class TestValidateSpecs(TestCase):
    def test_coerces_raw_strings_to_canonical_types(self):
        cat = _category(FULL_SCHEMA)
        cleaned = validate_specs(
            cat,
            {
                "cpu_cores": "8",
                "ram_gb": "16",
                "encrypted": "yes",
                "ram_type": "ddr4",  # case-insensitive → canonical
                "inputs": "HDMI, DP",
                "bought": "2026-01-05",
                "mgmt_ip": "10.0.0.5",
            },
        )
        self.assertEqual(cleaned["cpu_cores"], 8)
        self.assertEqual(cleaned["ram_gb"], 16.0)
        self.assertIs(cleaned["encrypted"], True)
        self.assertEqual(cleaned["ram_type"], "DDR4")
        self.assertEqual(cleaned["inputs"], ["HDMI", "DP"])
        self.assertEqual(cleaned["bought"], "2026-01-05")
        self.assertEqual(cleaned["mgmt_ip"], "10.0.0.5")

    def test_blank_values_are_dropped(self):
        cat = _category(FULL_SCHEMA)
        self.assertEqual(validate_specs(cat, {"cpu_model": "", "encrypted": None}), {})

    def test_required_is_enforced_when_schema_sets_it(self):
        cat = _category([{**FULL_SCHEMA[0], "required": True}])
        with self.assertRaises(ValidationError) as ctx:
            validate_specs(cat, {})
        self.assertIn("cpu_model", ctx.exception.message_dict)

    def test_unknown_keys_are_rejected(self):
        cat = _category(FULL_SCHEMA)
        with self.assertRaises(ValidationError) as ctx:
            validate_specs(cat, {"cpu_model": "i5", "cpu_speeed": "typo"})
        self.assertIn("_unknown", ctx.exception.message_dict)

    def test_bad_choice_is_rejected(self):
        cat = _category(FULL_SCHEMA)
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"ram_type": "GDDR6"})

    def test_range_is_enforced(self):
        cat = _category(FULL_SCHEMA)
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"cpu_cores": 0})
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"cpu_cores": 999})

    def test_invalid_ip_and_date_are_rejected(self):
        cat = _category(FULL_SCHEMA)
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"mgmt_ip": "999.1.1.1"})
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"bought": "05/01/2026"})

    def test_multi_choice_rejects_values_outside_the_set(self):
        cat = _category(FULL_SCHEMA)
        with self.assertRaises(ValidationError):
            validate_specs(cat, {"inputs": ["HDMI", "VGA"]})

    def test_empty_category_accepts_empty_input(self):
        self.assertEqual(validate_specs(_category([]), {}), {})
        self.assertEqual(validate_specs(_category([]), None), {})


class TestMergePreserved(TestCase):
    def test_old_category_values_survive_a_category_change(self):
        new_cat = _category([{"key": "panel_type", "label": "Panel", "type": "string"}])
        old_attrs = {"cpu_model": "i7-13700", "ram_gb": 16}
        merged = merge_preserved(old_attrs, {"panel_type": "IPS"}, new_cat)
        self.assertEqual(merged["cpu_model"], "i7-13700")  # preserved (§8.2)
        self.assertEqual(merged["ram_gb"], 16)
        self.assertEqual(merged["panel_type"], "IPS")

    def test_values_in_the_new_schema_are_replaced_not_merged(self):
        cat = _category([{"key": "panel_type", "label": "Panel", "type": "string"}])
        merged = merge_preserved({"panel_type": "TN"}, {"panel_type": "IPS"}, cat)
        self.assertEqual(merged["panel_type"], "IPS")


# ---------------------------------------------------------------------------
# Dynamic form
# ---------------------------------------------------------------------------


def _form_payload(cat, site, **extra):
    data = {
        "asset_tag": "SPEC-0001",
        "category": cat.pk,
        "site": site.pk,
        "status": "IN_STOCK",
        "condition": "GOOD",
    }
    data.update(extra)
    return data


class TestAssetFormSpecs(TestCase):
    def setUp(self):
        self.site = _site()

    def test_laptop_form_exposes_the_catalogue_fields(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        # spec fields appear once a category is chosen (posted or on instance)
        form = AssetForm(data={"category": cat.pk})
        self.assertIn(f"{SPEC_FIELD_PREFIX}cpu_model", form.fields)
        self.assertIn(f"{SPEC_FIELD_PREFIX}battery_health_pct", form.fields)
        self.assertNotIn(f"{SPEC_FIELD_PREFIX}vm_uuid", form.fields)  # VM-only key
        self.assertIsNotNone(cat)

    def test_create_saves_validated_specs(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        form = AssetForm(
            data=_form_payload(
                cat,
                self.site,
                **{
                    f"{SPEC_FIELD_PREFIX}cpu_model": "Intel Core i5-1335U",
                    f"{SPEC_FIELD_PREFIX}cpu_cores": "10",
                    f"{SPEC_FIELD_PREFIX}ram_capacity_gb": "16",
                    f"{SPEC_FIELD_PREFIX}ram_type": "DDR4",
                },
            )
        )
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.attrs["cpu_model"], "Intel Core i5-1335U")
        self.assertEqual(asset.attrs["cpu_cores"], 10)
        self.assertEqual(asset.attrs["ram_capacity_gb"], 16.0)

    def test_invalid_spec_value_blocks_save_with_inline_error(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        form = AssetForm(
            data=_form_payload(
                cat,
                self.site,
                **{f"{SPEC_FIELD_PREFIX}ram_type": "GDDR6"},
            )
        )
        self.assertFalse(form.is_valid())
        self.assertIn(f"{SPEC_FIELD_PREFIX}ram_type", form.errors)

    def test_category_change_requires_new_fields_and_keeps_old_values(self):
        lap = Category.objects.get(code="IT-HW-LAP")
        mon = Category.objects.get(code="IT-HW-MON")
        asset = Asset.objects.create(
            asset_tag="SPEC-OLD",
            category=lap,
            site=self.site,
            attrs={"cpu_model": "i7-13700", "screen_size_in": 14.0},
        )
        # switching to Monitor: screen_size_in belongs to BOTH schemas, but
        # cpu_model is laptop-only — it must be preserved, not lost (§8.2)
        form = AssetForm(
            data=_form_payload(mon, self.site, **{f"{SPEC_FIELD_PREFIX}screen_size_in": "27"}),
            instance=asset,
        )
        self.assertTrue(form.is_valid(), form.errors)
        asset = form.save()
        self.assertEqual(asset.category_id, mon.pk)
        self.assertEqual(asset.attrs["screen_size_in"], 27.0)
        self.assertEqual(asset.attrs["cpu_model"], "i7-13700")  # preserved

    def test_required_schema_blocks_save(self):
        cat = _category([{**FULL_SCHEMA[0], "required": True}], code="IT-REQ", save=True)
        form = AssetForm(data=_form_payload(cat, self.site))
        self.assertFalse(form.is_valid())
        self.assertIn(f"{SPEC_FIELD_PREFIX}cpu_model", form.errors)


# ---------------------------------------------------------------------------
# Detail rendering + fulfill + API
# ---------------------------------------------------------------------------


class TestDetailViewSpecs(TestCase):
    def setUp(self):
        from apps.core.models import UserAccessScope

        self.site = _site()
        self.user = get_user_model().objects.create_user(
            "spec_view", "spec_view@itasset.dev", "pass12345!"
        )
        # Feature test, not a scope test: GLOBAL scope keeps
        # SCOPE_ENFORCEMENT_ENABLED=1 transparent (deny-by-default cases
        # live in tests/test_scopes.py) — same fixture as test_crud_views.
        UserAccessScope.objects.create(
            user=self.user,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="feature-test fixture (not a scope test)",
            created_by=self.user,
        )

    def test_detail_page_renders_specification_card(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        asset = Asset.objects.create(
            asset_tag="SPEC-VIEW",
            category=cat,
            site=self.site,
            attrs={
                "cpu_model": "Intel Core i5-1335U",
                "ram_capacity_gb": 16.0,
                "touchscreen": False,
            },
        )
        self.client.force_login(self.user)
        resp = self.client.get(f"/assets/{asset.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Specifications")
        self.assertContains(resp, "CPU Model")
        self.assertContains(resp, "Intel Core i5-1335U")
        self.assertContains(resp, "16 GB")  # value + unit
        self.assertContains(resp, "Touchscreen")
        self.assertContains(resp, "No")  # boolean display

    def test_detail_page_hides_card_without_values(self):
        cat = Category.objects.get(code="IT-HW-MON")
        asset = Asset.objects.create(asset_tag="SPEC-EMPTY", category=cat, site=self.site, attrs={})
        self.client.force_login(self.user)
        resp = self.client.get(f"/assets/{asset.pk}/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Specifications")


class TestFulfillRequestSpecs(TestCase):
    def setUp(self):
        from apps.assets import services

        self.services = services
        self.site = _site()
        group, _ = Group.objects.get_or_create(name="technician")
        self.tech = get_user_model().objects.create_user(
            "spec_tech", "spec_tech@itasset.dev", "pass12345!"
        )
        self.tech.groups.add(group)

    def _request(self):
        return AssetRequest.objects.create(
            requester=self.tech,
            category=Category.objects.get(code="IT-HW-LAP"),
            site=self.site,
            quantity=1,
            status=AssetRequest.Status.APPROVED,
        )

    def test_fulfill_stores_validated_attrs(self):
        created = self.services.fulfill_request(
            self._request(),
            actor=self.tech,
            specs=[{"asset_tag": "SPEC-FUL-1", "attrs": {"cpu_cores": "10", "ram_type": "ddr4"}}],
        )
        self.assertEqual(created[0].attrs, {"cpu_cores": 10, "ram_type": "DDR4"})

    def test_fulfill_rejects_invalid_attrs(self):
        from apps.assets.services import LifecycleError

        with self.assertRaises(LifecycleError):
            self.services.fulfill_request(
                self._request(),
                actor=self.tech,
                specs=[{"asset_tag": "SPEC-FUL-2", "attrs": {"ram_type": "GDDR6"}}],
            )


class TestAPISerializerSpecs(TestCase):
    def setUp(self):
        from apps.api.serializers import AssetSerializer

        self.Serializer = AssetSerializer
        self.site = _site()
        self.cat = Category.objects.get(code="IT-HW-MON")

    def test_api_create_validates_and_cleans_attrs(self):
        ser = self.Serializer(
            data={
                "asset_tag": "API-SPEC-1",
                "category_id": self.cat.pk,
                "site_id": self.site.pk,
                "attrs": {"refresh_rate_hz": "144", "video_inputs": "HDMI, USB-C"},
            }
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        asset = ser.save()
        self.assertEqual(asset.attrs["refresh_rate_hz"], 144)
        self.assertEqual(asset.attrs["video_inputs"], ["HDMI", "USB-C"])

    def test_api_rejects_unknown_spec_keys(self):
        ser = self.Serializer(
            data={
                "asset_tag": "API-SPEC-2",
                "category_id": self.cat.pk,
                "site_id": self.site.pk,
                "attrs": {"refresh_ratezzz": 144},
            }
        )
        self.assertFalse(ser.is_valid())
        self.assertIn("attrs", ser.errors)

    def test_api_update_preserves_old_category_values(self):
        cat2 = Category.objects.get(code="IT-HW-LAP")
        asset = Asset.objects.create(
            asset_tag="API-SPEC-3",
            category=self.cat,
            site=self.site,
            attrs={"panel_type": "IPS"},
        )
        ser = self.Serializer(
            asset,
            data={
                "category_id": cat2.pk,
                "attrs": {"cpu_model": "i5"},
            },
            partial=True,
        )
        self.assertTrue(ser.is_valid(), ser.errors)
        asset = ser.save()
        self.assertEqual(asset.attrs["panel_type"], "IPS")  # preserved
        self.assertEqual(asset.attrs["cpu_model"], "i5")


# ---------------------------------------------------------------------------
# Admin round-trip
# ---------------------------------------------------------------------------


class TestAdminSpecs(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.superuser = get_user_model().objects.create_superuser(
            "spec_admin", "spec_admin@example.com", "pass12345!"
        )

    def test_asset_change_page_carries_dynamic_spec_fields(self):
        cat = Category.objects.get(code="IT-HW-LAP")
        asset = Asset.objects.create(
            asset_tag="SPEC-ADMIN",
            category=cat,
            site=_site(),
            attrs={"cpu_model": "i5-1335U"},
        )
        self.client.force_login(self.superuser)
        resp = self.client.get(f"/admin/assets/asset/{asset.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'name="{SPEC_FIELD_PREFIX}cpu_model"')
        self.assertContains(resp, "i5-1335U")  # initial value rendered

    def test_category_schema_edit_round_trips(self):
        self.client.force_login(self.superuser)
        cat = Category.objects.get(code="IT-OTHER")
        resp = self.client.get(f"/admin/assets/category/{cat.pk}/change/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'name="schema"')

    def test_category_admin_rejects_malformed_schema(self):
        self.client.force_login(self.superuser)
        cat = Category.objects.get(code="IT-OTHER")
        resp = self.client.post(
            f"/admin/assets/category/{cat.pk}/change/",
            {
                "code": cat.code,
                "name": cat.name,
                "schema": '{"fields": [{"key": "x", "label": "X", "type": "nope"}]}',
            },
        )
        self.assertEqual(resp.status_code, 200)  # re-rendered with errors
        self.assertContains(resp, "unknown type")


class TestFormatHelpers(TestCase):
    def test_format_spec_value_units_and_booleans(self):
        cat = _category(
            [
                {"key": "ram", "label": "RAM", "type": "decimal", "unit": "GB"},
                {"key": "enc", "label": "Enc", "type": "boolean"},
            ]
        )
        fields = {f["key"]: f for f in spec_fields(cat)}
        self.assertEqual(format_spec_value(fields["ram"], 16), "16 GB")
        self.assertEqual(format_spec_value(fields["enc"], True), "Yes")
        self.assertEqual(format_spec_value(fields["enc"], None), "Unknown")
        self.assertEqual(set(build_spec_form_fields(cat)), {"spec__ram", "spec__enc"})
