"""Add the §5.1 ``ram_speed_mhz`` field to existing category schemas.

The catalogue already taught Desktop/Workstation the field, but migration
0008 only seeds a schema when a category row is missing *or empty* — an
operator's populated schema is never clobbered (§4.3). Production's Laptop
and Physical Server rows therefore still carry their pre-speed schemas, so
the field never reached the categories people actually ask about.

This appends the catalogue's own field definition wherever a schema declares
``ram_type`` but not ``ram_speed_mhz`` — the two spellings of "this category
specifies memory" — inserting it right after ``ram_type`` so the edit form
groups capacity/type/speed together instead of stranding the field at the
bottom. Idempotent (a schema that already has the field is left alone), and
reversing is a no-op for the same reason 0008's is: the field is
harmless master data, and a blind reverse could not tell this migration's
addition apart from the one 0008 seeded.
"""

from django.db import migrations

RAM_TYPE_KEY = "ram_type"
RAM_SPEED_KEY = "ram_speed_mhz"


def add_ram_speed(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    definition = next(
        (f for f in CATALOGUE["IT-HW-DSK"]["schema"]["fields"] if f["key"] == RAM_SPEED_KEY),
        None,
    )
    if definition is None:  # pragma: no cover - catalogue renamed the field
        return
    for cat in Category.objects.using(db_alias).all():
        schema = cat.schema or {}
        fields = schema.get("fields") or []
        keys = {f.get("key") for f in fields if isinstance(f, dict)}
        if RAM_SPEED_KEY in keys or RAM_TYPE_KEY not in keys:
            continue
        # slot it in beside RAM Type (the catalogue puts it there too)
        at = next(
            i for i, f in enumerate(fields) if isinstance(f, dict) and f.get("key") == RAM_TYPE_KEY
        )
        cat.schema = {**schema, "fields": [*fields[: at + 1], definition, *fields[at + 1 :]]}
        cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0012_assignment_to_dept_and_more"),
        # the catalogue itself lives in code, but the field definition this
        # migration copies is only guaranteed present from 0008 onward
        ("assets", "0008_seed_spec_catalogue"),
    ]

    operations = [
        migrations.RunPython(add_ram_speed, migrations.RunPython.noop),
    ]
