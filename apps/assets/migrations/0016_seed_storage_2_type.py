from django.db import migrations

# Secondary Storage Type — the third managed list (0014 shipped RAM Type
# and Primary Storage Type). Same defaults the catalogue schemas already
# declare for the key, seeded idempotently so a re-run — or a production
# backfill done before this code is deployed — stays safe.
SEED_CHOICES = {
    "storage_2_type": ["HDD", "SATA SSD", "NVMe SSD", "Other"],
}


def seed_spec_choices(apps, schema_editor):
    """Idempotent: get_or_create keeps a re-run (or a prod backfill) safe."""
    SpecChoice = apps.get_model("assets", "SpecChoice")
    for key, values in SEED_CHOICES.items():
        for position, value in enumerate(values, start=1):
            SpecChoice.objects.get_or_create(
                key=key, value=value, defaults={"order": position * 10}
            )


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0015_category_color"),
    ]

    operations = [
        migrations.RunPython(seed_spec_choices, migrations.RunPython.noop),
    ]
