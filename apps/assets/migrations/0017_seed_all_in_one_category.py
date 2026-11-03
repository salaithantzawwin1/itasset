"""Seed the All-in-One (PC + Monitor) category from the §5 catalogue.

An all-in-one is one physical unit holding both the workstation and its
screen, so it needs its own category — registering it as a Desktop and a
Monitor separately double-counted the device. Same contract as 0008/0010:
create the category when missing, fill only an empty schema (an operator's
custom schema is never clobbered, §4.3).

Data-only migration: reversing changes nothing (the row is harmless master
data, and a blind reverse could not tell it apart from one created by hand).
"""

from django.db import migrations

CODE = "IT-HW-AIO"


def seed_all_in_one(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    entry = CATALOGUE[CODE]
    cat = Category.objects.using(db_alias).filter(code=CODE).first()
    if cat is None:
        Category.objects.using(db_alias).create(
            code=CODE, name=entry["name"], schema=entry["schema"]
        )
    elif not cat.schema:
        cat.schema = entry["schema"]
        cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0016_seed_storage_2_type"),
    ]

    operations = [
        migrations.RunPython(seed_all_in_one, migrations.RunPython.noop),
    ]
