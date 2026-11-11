"""Add module_count / module_capacity_gb to the RAM category schema.

A RAM record can stand for a single module or for the pair installed in a
workstation. Without these two fields an 8 GB kit is indistinguishable from
one 8 GB stick, so the detail page cannot say "2 × 4 GB (2 slots)".

Only the IT-HW-RAM row is touched, and only when a key is missing — an
operator's customised schema (renamed labels, added fields) is preserved.
Reverse is a no-op: removing the definitions would orphan any values already
stored in Asset.attrs.
"""

from copy import deepcopy

from django.db import migrations


def add_ram_layout_fields(apps, schema_editor):
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
        if field["key"] in {"module_count", "module_capacity_gb"}
    ]
    existing = {field.get("key") for field in schema["fields"] if isinstance(field, dict)}
    missing = [deepcopy(field) for field in wanted if field["key"] not in existing]
    if not missing:
        return

    schema = deepcopy(schema)
    # Keep capacity first, then the layout pair, then the old type/speed rows.
    insert_at = 0
    for i, field in enumerate(schema["fields"]):
        if isinstance(field, dict) and field.get("key") == "capacity_gb":
            insert_at = i + 1
            break
    schema["fields"][insert_at:insert_at] = missing
    cat.schema = schema
    cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0018_add_cpu_cores_to_server_schemas"),
    ]

    operations = [
        migrations.RunPython(add_ram_layout_fields, migrations.RunPython.noop),
    ]
