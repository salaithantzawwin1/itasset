"""Create §11 role groups: admin / technician / auditor / viewer."""

from django.contrib.auth.models import Group
from django.db import migrations

ROLE_NAMES = ("admin", "technician", "auditor", "viewer")


def create_groups(apps, schema_editor):
    for name in ROLE_NAMES:
        Group.objects.get_or_create(name=name)


def remove_groups(apps, schema_editor):
    Group.objects.filter(name__in=ROLE_NAMES).delete()


class Migration(migrations.Migration):
    dependencies = [("people", "0001_initial")]

    operations = [migrations.RunPython(create_groups, remove_groups)]
