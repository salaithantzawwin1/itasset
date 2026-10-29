"""Add Category.color and paint the categories that already exist.

Every category on the assets list is a coloured badge, so the column can be
scanned by colour. New rows pick their colour in ``Category.save``; this
migration gives the existing ones theirs — the same deterministic palette
walk (15° hue steps from blue, first-unused wins), taken in pk order, which
is exactly what a fresh database would have produced row for row.

Cosmetic data: reversing drops the column and the colours regenerate the
same way on the next run.
"""

from django.db import migrations, models


def paint_existing_categories(apps, schema_editor):
    from apps.assets.models import default_category_color  # pure function, same walk

    Category = apps.get_model("assets", "Category")
    db_alias = schema_editor.connection.alias
    taken: list[str] = []
    for cat in Category.objects.using(db_alias).order_by("pk"):
        if not cat.color:
            cat.color = default_category_color(taken)
            cat.save(update_fields=["color"], using=db_alias)
        taken.append(cat.color)


class Migration(migrations.Migration):
    dependencies = [
        ("assets", "0014_specchoice"),
    ]

    operations = [
        migrations.AddField(
            model_name="category",
            name="color",
            field=models.CharField(
                blank=True,
                default="",
                help_text=(
                    "Badge colour on the assets list, #rrggbb — leave blank and one is "
                    "picked automatically (a hue no other category uses)."
                ),
                max_length=7,
            ),
        ),
        migrations.RunPython(paint_existing_categories, migrations.RunPython.noop),
    ]
