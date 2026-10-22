"""Seed the §6 component/accessory categories (HDD, SSD, RAM, Keyboard, Mouse).

Request: these parts were missing from the §5 catalogue that 0008 seeded, so
they never appeared on the asset forms' category picker. Same contract as
0008 — create missing categories, fill only empty schemas (an operator's
custom schema is never clobbered, §4.3) — but scoped to the five component
codes this migration introduces, so a later deletion in production stays
respected.

Data-only migration: reversing changes nothing (seeded rows stay; they are
harmless master data).
"""

from django.db import migrations

COMPONENT_CODES = ("IT-HW-HDD", "IT-HW-SSD", "IT-HW-RAM", "IT-HW-KBD", "IT-HW-MSE")


def seed_components(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    for code in COMPONENT_CODES:
        entry = CATALOGUE[code]
        cat = Category.objects.using(db_alias).filter(code=code).first()
        if cat is None:
            Category.objects.using(db_alias).create(
                code=code, name=entry["name"], schema=entry["schema"]
            )
        elif not cat.schema:
            cat.schema = entry["schema"]
            cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0009_alter_category_options"),
    ]

    operations = [
        migrations.RunPython(seed_components, migrations.RunPython.noop),
    ]
