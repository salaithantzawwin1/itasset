"""Sites, departments, and the people assets are assigned to (DEVELOPMENT.md §9)."""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class Site(models.Model):
    """An office location. Mandatory on Asset/Person/Assignment (§9).

    Sites nest (``parent``): a head office can sit under its city/region, and
    branch offices under the head office, e.g. Yangon → HQ → Chan Yin,
    Fortune Office. Nesting is an org-chart detail only — every Asset, Person
    and Assignment still points at exactly one concrete site (the leaf it
    belongs to), so scope checks and reports are unchanged. A parent row may
    also hold people/assets of its own; the tree view in the Sites list makes
    the shape visible and each detail page links to its sub-sites.
    """

    name = models.CharField(max_length=120, unique=True)
    code = models.SlugField(max_length=20, unique=True)
    # PROTECT like the other org FKs: a site that still has sub-sites cannot
    # be deleted out from under them; SiteDelete turns that into a message.
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
        verbose_name="parent site",
    )
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

    def clean(self):
        """Reject a self-parent and any cycle (the FK alone cannot)."""
        super().clean()
        if self.parent_id is None:
            return
        if self.pk is not None and self.parent_id == self.pk:
            raise ValidationError({"parent": "A site cannot be its own parent."})
        seen = set()
        node = self.parent
        while node is not None:
            if node.pk in seen or (self.pk is not None and node.pk == self.pk):
                raise ValidationError(
                    {"parent": "That choice would create a loop in the site tree."}
                )
            seen.add(node.pk)
            node = node.parent

    @property
    def ancestors(self) -> list["Site"]:
        """Root-first chain above this site (empty for a top-level site)."""
        chain, seen = [], set()
        node = self.parent
        while node is not None and node.pk not in seen:
            seen.add(node.pk)
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    @property
    def full_path(self) -> str:
        """Breadcrumb label, e.g. ``Yangon / HQ / Chan Yin``."""
        return " / ".join([s.name for s in self.ancestors] + [self.name])


class Department(models.Model):
    name = models.CharField(max_length=120)
    site = models.ForeignKey(Site, on_delete=models.PROTECT, related_name="departments")
    # Department head (တာဝန်ခံ): the person accountable for this department's
    # assets — shown on the dept detail page next to the department-held
    # inventory. SET_NULL keeps the department intact when the person goes.
    head = models.ForeignKey(
        "Person",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="heading",
    )

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


# The person form assigns staff numbers automatically in this series
# (mirrors assets' <CATEGORY>-NNNN tag): a single scheme, never hand-invented.
EMPLOYEE_NO_PREFIX = "EMP-"


def next_employee_no() -> str:
    """Next free staff number: ``EMP-NNNN`` (highest existing suffix + 1).

    Only rows already in the series are counted, so legacy keys (``EMP1``,
    ``E101``) never poison the sequence; sparse or out-of-order numbers are
    fine. The winner is advisory — ``Person.employee_no`` stays unique, so a
    lost race surfaces as a normal form error rather than bad data (the same
    contract as ``services.next_asset_tag``).
    """
    highest = 0
    for value in Person.objects.values_list("employee_no", flat=True):
        if value and value.startswith(EMPLOYEE_NO_PREFIX):
            suffix = value[len(EMPLOYEE_NO_PREFIX) :]
            if suffix.isdigit() and int(suffix) > highest:
                highest = int(suffix)
    return f"{EMPLOYEE_NO_PREFIX}{highest + 1:04d}"
