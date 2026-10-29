"""Renumber every person onto the auto-assigned EMP-#### series.

Legacy values (EMP1, EMP02, E201, free text) become ``EMP-NNNN`` and keep
their trailing number when one exists; rows already in the series reserve
their number first so a legacy row can never displace a canonical one.
Rows with no number at all — or whose number is already taken — take the
lowest free number.

Every row that moves is parked on a temporary value first (two-phase), so
the unique constraint on ``employee_no`` can never fire mid-run.

Irreversible by design: the old values are not stored, so reversing is a
no-op.
"""

import re

from django.db import migrations

SERIES = re.compile(r"^EMP-(\d+)$")
TRAILING = re.compile(r"(\d+)$")


def renumber_employee_nos(apps, schema_editor):
    del schema_editor  # single-table write; nothing to record
    Person = apps.get_model("people", "Person")
    rows = list(Person.objects.all().order_by("pk"))

    used: set[int] = set()
    targets: dict[int, str] = {}

    # Pass 1 — rows already in the series keep (and normalise) their number.
    deferred = []
    for p in rows:
        m = SERIES.match(p.employee_no.strip())
        if not m:
            continue
        n = int(m.group(1))
        canonical = f"EMP-{n:04d}"
        if n in used:
            deferred.append(p)  # same number twice — reassign below
        else:
            used.add(n)
            if canonical != p.employee_no:
                targets[p.pk] = canonical

    # Pass 2 — legacy rows take their trailing number when free, otherwise
    # the lowest number still unused.
    legacy = [r for r in rows if r not in deferred and not SERIES.match(r.employee_no.strip())]
    for p in deferred + legacy:
        m = TRAILING.search(p.employee_no.strip())
        n = int(m.group(1)) if m else None
        if n is None or n in used:
            n = 1
            while n in used:
                n += 1
        used.add(n)
        value = f"EMP-{n:04d}"
        if value != p.employee_no:
            targets[p.pk] = value

    if not targets:
        return

    # Two-phase: park every mover on a temporary unique value, then land.
    for pk in targets:
        Person.objects.filter(pk=pk).update(employee_no=f"__renumber-{pk}")
    for pk, value in targets.items():
        Person.objects.filter(pk=pk).update(employee_no=value)


class Migration(migrations.Migration):
    dependencies = [
        ("people", "0006_department_head"),
    ]

    operations = [
        migrations.RunPython(renumber_employee_nos, migrations.RunPython.noop),
    ]
