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
    ("IT-HW-SRV", "Physical Server"),
    ("IT-HW-PER", "Peripheral"),
    ("IT-CON", "Consumable"),
    # §5 catalogue categories (migration 0008 ships their field schemas)
    ("IT-HW-WKS", "Workstation"),
    ("IT-HW-VM", "Virtual Machine"),
    ("IT-HW-PRN", "Printer / Scanner / MFP"),
    ("IT-NET-SW", "Network Switch"),
    ("IT-NET-RT", "Router"),
    ("IT-NET-FW", "Firewall / Security Appliance"),
    ("IT-NET-AP", "Wireless Access Point"),
    ("IT-STG-NAS", "NAS / Storage Appliance"),
    ("IT-HW-UPS", "UPS"),
    ("IT-HW-MOB", "Mobile Phone / Tablet"),
    ("IT-SW-LIC", "Software License / Subscription"),
    ("IT-OTHER", "Other Physical Asset"),
]

# Deterministic sample values for the four demo categories (§5 catalogue
# field keys) so detail pages and reports show realistic specifications.
DEMO_SPECS = {
    "IT-HW-LAP": {
        "cpu_manufacturer": "Intel",
        "cpu_model": "Intel Core i5-1335U",
        "cpu_cores": 10,
        "ram_capacity_gb": 16.0,
        "ram_type": "DDR4",
        "storage_1_type": "NVMe SSD",
        "storage_1_capacity_gb": 512,
        "screen_size_in": 14.0,
        "screen_resolution": "1920x1080",
        "touchscreen": False,
        "battery_health_pct": 87,
        "battery_condition": "Good",
        "os_name": "Windows 11 Pro",
        "device_encryption": "Enabled",
    },
    "IT-HW-DSK": {
        "cpu_manufacturer": "AMD",
        "cpu_model": "Ryzen 7 7700",
        "cpu_cores": 8,
        "ram_capacity_gb": 32.0,
        "ram_type": "DDR5",
        "storage_1_type": "NVMe SSD",
        "storage_1_capacity_gb": 1000,
        "os_name": "Windows 11 Pro",
        "os_version": "23H2",
    },
    "IT-HW-MON": {
        "screen_size_in": 27.0,
        "panel_type": "IPS",
        "native_resolution": "2560x1440",
        "refresh_rate_hz": 75,
        "video_inputs": ["HDMI", "DisplayPort"],
    },
    "IT-HW-SRV": {
        "server_role": "Virtualization",
        "chassis_form_factor": "Rack",
        "cpu_model": "Intel Xeon Silver 4310",
        "ram_capacity_gb": 128.0,
        "ram_type": "DDR4",
        "os_name": "VMware ESXi",
        "os_version": "8.0",
        "rack_location": "DC1",
        "rack_unit": "U22",
    },
}

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
                attrs=dict(DEMO_SPECS.get(cat.code)) if n % 3 == 0 else {},
            )
            made += 1
        self.stdout.write(self.style.SUCCESS(f"Seeded {made} assets."))
