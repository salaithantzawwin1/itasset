"""Add per-slot RAM capacities (slot_1_gb / slot_2_gb) to PC category schemas.

The catalogue already teaches Desktop/Workstation/All-in-One the slot fields,
but the schema rows in a live database were seeded earlier — a code-only
change never reaches them. Without this migration the edit form still asks
only for one RAM total, which cannot express a 2 GB + 4 GB machine.

Only categories whose catalogue entry declares the slot fields are touched,
only missing keys are added, and the field is inserted right after
``ram_capacity_gb`` so capacity and its slots stay together. An operator's
renamed/reordered schema is preserved. Reverse is a no-op: removing the
definitions would orphan slot values already stored in Asset.attrs.
"""

from copy import deepcopy

from django.db import migrations

SLOT_KEYS = ("slot_1_gb", "slot_2_gb")


def add_pc_slot_fields(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias

    for code, entry in CATALOGUE.items():
        wanted = [
            deepcopy(field)
            for field in entry["schema"]["fields"]
            if field["key"] in SLOT_KEYS
        ]
        if not wanted:
            continue  # category does not record slots (monitor, switch, …)

        cat = Category.objects.using(db_alias).filter(code=code).first()
        if cat is None:
            continue  # not seeded on this install — nothing to update

        schema = cat.schema or {"version": 1, "fields": []}
        if not isinstance(schema, dict) or not isinstance(schema.get("fields"), list):
            continue  # custom shape — never guess at an operator's schema

        fields = schema["fields"]
        existing = {field.get("key") for field in fields if isinstance(field, dict)}
        missing = [field for field in wanted if field["key"] not in existing]
        if not missing:
            continue

        fields = deepcopy(fields)
        anchor = next(
            (
                i
                for i, field in enumerate(fields)
                if isinstance(field, dict) and field.get("key") == "ram_capacity_gb"
            ),
            len(fields) - 1,
        )
        fields[anchor + 1 : anchor + 1] = missing
        cat.schema = {**schema, "fields": fields}
        cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0020_add_ram_slot_capacities"),
    ]

    operations = [
        migrations.RunPython(add_pc_slot_fields, migrations.RunPython.noop),
    ]
