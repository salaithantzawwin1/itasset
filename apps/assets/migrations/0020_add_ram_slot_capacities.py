"""Add per-slot capacities (slot_1_gb / slot_2_gb) to the RAM schema.

Two slots are the common desktop/laptop layout, and they need not hold equally
sized modules: a 12 GB machine is often one 4 GB + one 8 GB stick, which the
``module_count`` / ``module_capacity_gb`` pair cannot express.

Only the IT-HW-RAM row is touched, and only when a key is missing — an
operator's customised schema (renamed labels, added fields) is preserved.
Reverse is a no-op: removing the definitions would orphan any values already
stored in Asset.attrs.
"""

from copy import deepcopy

from django.db import migrations


def add_ram_slot_fields(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    cat = Category.objects.using(db_alias).filter(code="IT-HW-RAM").first()
    if cat is None:
        return

    schema = cat.schema or {"version": 1, "fields": []}
    if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
        return  # custom shape — never guess at an operator's schema

    wanted = [
        field
        for field in CATALOGUE["IT-HW-RAM"]["schema"]["fields"]
        if field["key"] in {"slot_1_gb", "slot_2_gb"}
    ]
    existing = {field.get("key") for field in schema["fields"] if isinstance(field, dict)}
    missing = [deepcopy(field) for field in wanted if field["key"] not in existing]
    if not missing:
        return

    schema = deepcopy(schema)
    # Keep capacity/layout together: insert after the equal-pair fields when
    # they are present, otherwise straight after capacity.
    insert_at = 0
    for i, field in enumerate(schema["fields"]):
        if isinstance(field, dict) and field.get("key") in {
            "module_capacity_gb",
            "capacity_gb",
        }:
            insert_at = i + 1
    schema["fields"][insert_at:insert_at] = missing
    cat.schema = schema
    cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0019_add_ram_module_fields"),
    ]

    operations = [
        migrations.RunPython(add_ram_slot_fields, migrations.RunPython.noop),
    ]
