"""Vendor & Contract models (DEVELOPMENT.md §12, M4).

- `Supplier` on a purchase and `Vendor` on a contract may differ — both recorded
  (Supplier lives on the Asset/purchase side; Vendor here is the contract party).
- Contract covers many Assets and/or SoftwareLicenses (coverage rows, §9).
- Renewal alerts use `renewal_notice_days` (default 60) — §14 matrix, §15 task.
"""

from django.db import models


class Vendor(models.Model):
    class Category(models.TextChoices):
        HARDWARE = "hardware", "Hardware"
        SOFTWARE = "software", "Software"
        SERVICE = "service", "Service"

    name = models.CharField(max_length=120, unique=True)
    category = models.CharField(max_length=12, choices=Category.choices, default=Category.HARDWARE)
    contact_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=60, blank=True)
    website = models.URLField(blank=True)
    support_level = models.CharField(max_length=120, blank=True)  # SLA terms, §12
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "vendor"

    def __str__(self) -> str:
        return self.name


class VendorNote(models.Model):
    """Dated performance notes (§12): RMA speed, ticket quality."""

    vendor = models.ForeignKey(Vendor, on_delete=models.CASCADE, related_name="performance_notes")
    created_at = models.DateTimeField(auto_now_add=True)
    author = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="vendor_notes",
    )
    text = models.TextField()

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"note on {self.vendor.name} ({self.created_at:%Y-%m-%d})"


class Contract(models.Model):
    class Type(models.TextChoices):
        SUPPORT = "support", "Support"
        WARRANTY = "warranty", "Warranty"
        SUBSCRIPTION = "subscription", "Subscription"
        LEASE = "lease", "Lease"

    vendor = models.ForeignKey(Vendor, on_delete=models.PROTECT, related_name="contracts")
    contract_no = models.CharField(max_length=60, unique=True, blank=True)
    title = models.CharField(max_length=160)
    type = models.CharField(max_length=12, choices=Type.choices, default=Type.SUPPORT)
    start_date = models.DateField()
    end_date = models.DateField(db_index=True)  # required index, §9
    value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="MMK")
    payment_terms = models.CharField(max_length=120, blank=True)
    renewal_notice_days = models.PositiveIntegerField(default=60)  # §12 default
    auto_renew = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    # coverage rows (§9): a contract covers assets and/or licenses
    assets = models.ManyToManyField("assets.Asset", blank=True, related_name="contracts")
    licenses = models.ManyToManyField(
        "licenses.SoftwareLicense", blank=True, related_name="contracts"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["end_date", "title"]
        verbose_name = "contract"

    def __str__(self) -> str:
        return f"{self.title} ({self.vendor.name})"

    @property
    def days_to_end(self) -> int | None:
        from django.utils import timezone

        if self.end_date is None:
            return None
        return (self.end_date - timezone.localdate()).days
