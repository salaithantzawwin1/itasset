"""Seed the §5 category-specific specification catalogue into Category.schema.

Hybrid spec model (ADR-0004): Category.schema is the declarative layer-2
schema that drives dynamic asset forms, validation and the detail view.

- Missing categories from the catalogue are created (code + name + schema).
- Existing categories keep their schema unless it is empty — an operator's
  custom schema is never clobbered (§4.3: configuration changes are explicit).

Data-only migration: reversing changes nothing (seeded rows stay; they are
harmless master data).
"""

from django.db import migrations


def seed_catalogue(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    for code, entry in CATALOGUE.items():
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
        ("assets", "0007_approvaldecision_delegated_from_approvaldelegation"),
    ]

    operations = [
        migrations.RunPython(seed_catalogue, migrations.RunPython.noop),
    ]
