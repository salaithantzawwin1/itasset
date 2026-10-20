"""Sites, departments, and the people assets are assigned to (DEVELOPMENT.md §9)."""

from django.conf import settings
from django.db import models


class Site(models.Model):
    """An office location. Mandatory on Asset/Person/Assignment (§9)."""

    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=20, unique=True)
    address = models.TextField(blank=True)
    # §4 scheduled reports ("monthly inventory snapshot per site → site lead"):
    # the per-site recipient; falls back to IT_LEAD_EMAIL when blank.
    lead_email = models.EmailField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "site"

    def __str__(self) -> str:
        return self.name


class Department(models.Model):
    name = models.CharField(max_length=120)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="departments")

    class Meta:
        ordering = ["name"]
        unique_together = [("site", "name")]
        verbose_name = "department"

    def __str__(self) -> str:
        return f"{self.name} ({self.site.code})"


class Person(models.Model):
    """An employee. Linked to LDAP uid when directory login exists (§11)."""

    employee_no = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    email = models.EmailField(blank=True)
    ldap_uid = models.CharField(max_length=120, blank=True, db_index=True)
    # Employee self-view link (ITAM_Scope_RBAC_Design_v1.0 §4.4): the one
    # carve-out to deny-by-default — a zero-scope user linked to a Person may
    # read their own assignments/requests and their currently-assigned assets.
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="person",
    )
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="people", null=True, blank=True
    )
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="people")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "person"
        verbose_name_plural = "people"  # Django's naive plural was "persons"

    def __str__(self) -> str:
        return f"{self.name} ({self.employee_no})"
