"""Add ``cpu_cores`` to server category schemas.

Desktops, laptops, workstations and all-in-ones declare CPU cores, but the
Physical Server schema only asked for sockets and installed CPU count — so the
dashboard CPU matrix (model × cores) could never show a server, and a server's
core count had nowhere to live. This appends the catalogue's ``cpu_cores``
definition wherever a schema declares ``cpu_model`` but not ``cpu_cores``,
inserting it after the installed-CPU count so the processor fields stay
together. Idempotent; reversing is a no-op (harmless master data).
"""

from django.db import migrations

CPU_MODEL_KEY = "cpu_model"
CPU_CORES_KEY = "cpu_cores"
AFTER_KEYS = ("cpu_installed_count", "cpu_socket_count", CPU_MODEL_KEY)


def add_cpu_cores(apps, schema_editor):
    from apps.assets.specs import CATALOGUE

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    definition = next(
        (f for f in CATALOGUE["IT-HW-SRV"]["schema"]["fields"] if f["key"] == CPU_CORES_KEY),
        None,
    )
    if definition is None:  # pragma: no cover - catalogue renamed the field
        return
    for cat in Category.objects.using(db_alias).all():
        schema = cat.schema or {}
        fields = schema.get("fields") or []
        keys = {f.get("key") for f in fields if isinstance(f, dict)}
        if CPU_CORES_KEY in keys or CPU_MODEL_KEY not in keys:
            continue
        at = max(
            (i for i, f in enumerate(fields) if isinstance(f, dict) and f.get("key") in AFTER_KEYS),
            default=-1,
        )
        cat.schema = {**schema, "fields": [*fields[: at + 1], definition, *fields[at + 1 :]]}
        cat.save(update_fields=["schema"], using=db_alias)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0017_seed_all_in_one_category"),
        ("assets", "0008_seed_spec_catalogue"),
    ]

    operations = [
        migrations.RunPython(add_cpu_cores, migrations.RunPython.noop),
    ]
