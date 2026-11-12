"""Dashboard deep-link audit: every tile/alert opens the list it counted.

The tiles are scope-aware and some use subtle predicates (warranty window,
retired/disposed exclusion, overdue loans, pending approvals, transfers from
*either* site). Each link is opened with the same scoped caller and its row
count compared to the number on the tile, so a link cannot silently drift
from the count it claims to answer.
"""

from datetime import timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.assets.admin import AssetRequestAdmin, TransferAdmin
from apps.assets.models import Asset, AssetRequest, Assignment, Category, Transfer
from apps.core.models import UserAccessScope
from apps.people.models import Site

pytestmark = pytest.mark.django_db


class DashboardDeepLinkTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="Yangon HQ", code="yangon")
        cls.other = Site.objects.create(name="Mandalay", code="mandalay")
        cls.cat = Category.objects.get_or_create(
            code="IT-HW-LAP", defaults={"name": "Laptop"}
        )[0]

    def _user(self, *, staff=True, role=None):
        user = get_user_model().objects.create_user("audit_user", password="pw12345!")
        user.is_staff = staff
        user.save()
        if role:
            user.groups.add(Group.objects.get_or_create(name=role)[0])
        UserAccessScope.objects.create(
            user=user,
            scope_type=UserAccessScope.ScopeType.SITE,
            site=self.site,
            reason="deep-link audit fixture",
            created_by=user,
        )
        return user

    @staticmethod
    def _count(resp):
        page_obj = resp.context.get("page_obj")
        return page_obj.paginator.count if page_obj else len(resp.context["object_list"])

    @override_settings(SCOPE_ENFORCEMENT_ENABLED=True)
    def test_asset_kpi_links_open_lists_with_the_same_count(self):
        """Warranty/Active/Total: same scope, same rows, same number."""
        today = timezone.localdate()
        Asset.objects.create(
            asset_tag="A-1",
            category=self.cat,
            site=self.site,
            serial_no="S1",
            warranty_end=today + timedelta(days=5),
        )
        Asset.objects.create(
            asset_tag="A-2",
            category=self.cat,
            site=self.site,
            serial_no="S2",
            status=Asset.Status.RETIRED,
            warranty_end=today + timedelta(days=3),
        )
        Asset.objects.create(
            asset_tag="A-3",
            category=self.cat,
            site=self.other,
            serial_no="S3",
            warranty_end=today + timedelta(days=2),
        )
        self.client.force_login(self._user())

        resp = self.client.get("/")
        kpis = {k["label_key"]: k for k in resp.context["kpis"]}
        for key in ("dash.kpi.warranty", "dash.kpi.active", "dash.total_assets"):
            url = kpis[key]["href"]
            page = self.client.get(url)
            self.assertEqual(page.status_code, 200, url)
            self.assertEqual(self._count(page), kpis[key]["value"], f"{key} → {url}")
        # the excluded rows really are excluded (not a vacuous equality):
        # in scope are A-1 (active) and A-2 (retired); A-3 is another site
        self.assertEqual(kpis["dash.kpi.active"]["value"], 1)
        self.assertEqual(kpis["dash.total_assets"]["value"], 2)

    @override_settings(SCOPE_ENFORCEMENT_ENABLED=True)
    def test_overdue_kpi_opens_the_same_loans(self):
        mine = Asset.objects.create(asset_tag="L-1", category=self.cat, site=self.site)
        outside = Asset.objects.create(
            asset_tag="L-2", category=self.cat, site=self.other
        )
        late = timezone.now() - timedelta(days=2)
        Assignment.objects.create(asset=mine, due_at=late)
        Assignment.objects.create(asset=outside, due_at=late)
        # the overdue tile is an approver tile (admin/technician role)
        self.client.force_login(self._user(role="technician"))

        resp = self.client.get("/")
        kpi = {k["label_key"]: k for k in resp.context["kpis"]}["dash.kpi.overdue"]
        page = self.client.get(kpi["href"])
        self.assertEqual(page.status_code, 200)
        self.assertEqual(self._count(page), kpi["value"])
        self.assertEqual(kpi["value"], 1)

    @override_settings(SCOPE_ENFORCEMENT_ENABLED=True)
    def test_pending_and_transfer_tiles_match_their_admin_lists(self):
        """Admin changelists must show exactly the rows the tiles counted."""
        user = self._user(role="technician")
        AssetRequest.objects.create(
            requester=user,
            site=self.site,
            category=self.cat,
            quantity=1,
            status=AssetRequest.Status.PENDING,
        )
        AssetRequest.objects.create(
            requester=user,
            site=self.other,
            category=self.cat,
            quantity=1,
            status=AssetRequest.Status.PENDING,
        )
        # destination-side exception: the receiving site must see it
        Transfer.objects.create(
            from_site=self.other,
            to_site=self.site,
            status=Transfer.Status.EXCEPTION,
        )
        Transfer.objects.create(
            from_site=self.other,
            to_site=self.other,
            status=Transfer.Status.EXCEPTION,
        )
        self.client.force_login(user)

        resp = self.client.get("/")
        kpis = {k["label_key"]: k for k in resp.context["kpis"]}
        alerts = {a["key"]: a for a in resp.context["alerts"]}

        request = RequestFactory().get("/admin/")
        request.user = user
        pending_qs = AssetRequestAdmin(AssetRequest, AdminSite()).get_queryset(request)
        self.assertEqual(
            pending_qs.filter(status=AssetRequest.Status.PENDING).count(),
            kpis["dash.kpi.pending"]["value"],
        )
        transfer_qs = TransferAdmin(Transfer, AdminSite()).get_queryset(request)
        self.assertEqual(
            transfer_qs.filter(status=Transfer.Status.EXCEPTION).count(),
            alerts["alert.transfer_exceptions"]["n"],
        )
        self.assertEqual(alerts["alert.transfer_exceptions"]["n"], 1)  # inbound only

    def test_pending_tile_has_no_link_without_a_matching_list(self):
        """A technician without admin access has no approval queue to open."""
        self.client.force_login(self._user(staff=False, role="technician"))
        resp = self.client.get("/")
        kpi = {k["label_key"]: k for k in resp.context["kpis"]}["dash.kpi.pending"]
        self.assertIsNone(kpi["href"])
        self.assertNotIn('href="None"', resp.content.decode())
