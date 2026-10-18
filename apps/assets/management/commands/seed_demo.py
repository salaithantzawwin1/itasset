"""`make seed` — deterministic demo data: sites, departments, categories, 50 assets."""

import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.assets.models import Asset, Category
from apps.people.models import Department, Person, Site

CATEGORIES = [
    ("IT-HW-LAP", "Laptop"),
    ("IT-HW-DSK", "Desktop / Workstation"),
    ("IT-HW-MON", "Monitor"),
    ("IT-HW-SRV", "Server"),
    ("IT-HW-PER", "Peripheral"),
    ("IT-CON", "Consumable"),
]

SITES = [
    ("yangon", "Yangon HQ"),
    ("mandalay", "Mandalay Office"),
    ("naypyitaw", "Naypyitaw Office"),
]


class Command(BaseCommand):
    help = "Load demo sites, departments, categories and 50 assets (dev only, §19)"

    def handle(self, *args, **options):
        rng = random.Random(1)  # deterministic
        sites = [Site.objects.get_or_create(code=c, defaults={"name": n})[0] for c, n in SITES]
        cats = [
            Category.objects.get_or_create(code=c, defaults={"name": n})[0] for c, n in CATEGORIES
        ]

        for i, site in enumerate(sites):
            for d in ("IT", "Finance", "Operations"):
                Department.objects.get_or_create(site=site, name=d)
            Person.objects.get_or_create(
                employee_no=f"E{i}01",
                defaults={"name": f"Demo Person {i + 1}", "site": site},
            )

        if Asset.objects.exists():
            self.stdout.write("Assets already present — nothing added.")
            return

        today = timezone.localdate()
        made = 0
        for n in range(1, 51):
            cat = cats[(n - 1) % 4]
            Asset.objects.create(
                asset_tag=f"{cat.code}-{n:04d}",
                category=cat,
                site=sites[n % len(sites)],
                status=Asset.Status.choices[n % 3][0],
                condition=rng.choice(Asset.Condition.choices)[0],
                manufacturer=rng.choice(["Dell", "HP", "Lenovo", "Samsung", "Apple"]),
                model_name=f"Model {rng.randint(100, 999)}",
                serial_no=f"SN{n:06d}{rng.randint(10, 99)}",
                purchase_date=today - timedelta(days=rng.randint(30, 1400)),
                cost=rng.randint(5, 30) * 100,
                warranty_end=date(2026, 1, 1) + timedelta(days=rng.randint(0, 700)),
            )
            made += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {made} assets."))
