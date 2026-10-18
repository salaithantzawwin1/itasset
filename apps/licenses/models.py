"""SoftwareLicense + LicenseKey — seat counting (DEVELOPMENT.md §9, M4).

Seat model: each `LicenseKey` row is one assigned seat, linked to an Asset
(and optionally the person it is assigned to). Over-assignment = active keys
> seats — flagged weekly by `scan_license_seats` (§14/§15).
"""

from django.db import models


class SoftwareLicense(models.Model):
    name = models.CharField(max_length=160)
    vendor = models.ForeignKey(
        "vendors.Vendor", null=True, blank=True, on_delete=models.SET_NULL, related_name="licenses"
    )
    license_key = models.CharField(max_length=200, blank=True)  # the entitlement key
    seats = models.PositiveIntegerField(default=1)  # entitled seats
    seats_soft_limit = models.PositiveIntegerField(null=True, blank=True)  # warn before hard cap
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default="MMK")
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "software license"

    def __str__(self) -> str:
        return f"{self.name} ({self.seats} seats)"

    @property
    def seats_assigned(self) -> int:
        """Active seats only — released keys free their seat."""
        return self.keys.filter(released_at__isnull=True).count()

    @property
    def over_assigned(self) -> bool:
        return self.seats_assigned > self.seats


class LicenseKey(models.Model):
    """One assigned seat: key row → asset (and the person holding it)."""

    license = models.ForeignKey(SoftwareLicense, on_delete=models.CASCADE, related_name="keys")
    key = models.CharField(max_length=200, blank=True)
    asset = models.ForeignKey(
        "assets.Asset", null=True, blank=True, on_delete=models.CASCADE, related_name="license_keys"
    )
    assigned_to = models.ForeignKey(
        "people.Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="license_keys",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    released_at = models.DateTimeField(null=True, blank=True)  # seat freed → not counted

    class Meta:
        ordering = ["-assigned_at"]
        verbose_name = "license seat"

    def __str__(self) -> str:
        target = self.asset or self.assigned_to or "—"
        return f"{self.license.name}: {target}"

    @property
    def is_active(self) -> bool:
        return self.released_at is None

    def release(self) -> None:
        """Free the seat (idempotent): stamps released_at once."""
        from django.utils import timezone

        if self.released_at is None:
            self.released_at = timezone.now()
            self.save(update_fields=["released_at"])
