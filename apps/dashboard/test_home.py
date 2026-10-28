"""Tests for the dashboard home page (root URL) and the staff-only Admin link."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.assets.models import Asset, AssetRequest, Category
from apps.people.models import Site


def _login_global(client):
    """Act as an authorized GLOBAL-scope user.

    Baseline tests here assert real counts (KPIs, chart, alerts); with
    enforcement on — the server runs `SCOPE_ENFORCEMENT_ENABLED=1` — an
    anonymous or zero-scope caller correctly sees zeros instead. The deny-
    by-default behaviour itself is pinned by
    `test_dashboard_zero_scope_user_sees_zeros_when_enforcing`, so these
    tests authenticate instead of weakening their assertions. Same pattern
    as `_any_user()` in apps/audit/tests.py.
    """
    from apps.core.models import UserAccessScope

    user, _ = get_user_model().objects.get_or_create(username="dash_global")
    user.set_password("pw12345!")
    user.save()
    UserAccessScope.objects.get_or_create(
        user=user,
        scope_type=UserAccessScope.ScopeType.GLOBAL,
        defaults={"reason": "baseline dashboard test", "created_by": user},
    )
    client.force_login(user)
    return user


class DashboardHomeTests(TestCase):
    def _seed(self):
        site = Site.objects.create(name="Yangon HQ", code="yangon")
        cat = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]
        for i in range(3):
            Asset.objects.create(asset_tag=f"TAG-{i}", category=cat, site=site)
        return site, cat

    def test_root_is_dashboard_home(self):
        self._seed()
        _login_global(self.client)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "dashboard/home.html")
        self.assertEqual(resp.context["total_assets"], 3)
        self.assertEqual(resp.context["total_people"], 0)
        self.assertEqual(resp.context["total_sites"], 1)

    def test_status_summary_widgets_present(self):
        self._seed()
        _login_global(self.client)
        resp = self.client.get("/")
        # widgets render status/condition/site breakdowns + recent rows
        self.assertEqual(len(resp.context["by_status"]), 1)  # all 3 assets IN_STOCK
        self.assertEqual(resp.context["by_status"][0]["n"], 3)
        self.assertEqual(len(resp.context["recent"]), 3)
        self.assertContains(resp, "By status")
        self.assertContains(resp, "Recently added")

    def test_healthz_still_ok(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "ok")


class DashboardRamCardTests(TestCase):
    """RAM inventory card: type + speed breakdown from the §5 spec attrs.

    Two key spellings feed one card — installed devices record
    `ram_type`/`ram_speed_mhz`, the RAM-module category records
    `memory_type`/`speed_mhz` — and the coverage line says how much of the
    register actually has RAM recorded.
    """

    @classmethod
    def setUpTestData(cls):
        cls.site = Site.objects.create(name="Yangon HQ", code="yangon")
        cls.lap = Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})[0]
        cls.mod = Category.objects.get_or_create(
            code="IT-HW-RAM", defaults={"name": "RAM / Memory Module"}
        )[0]

    def _asset(self, tag, category, attrs):
        return Asset.objects.create(asset_tag=tag, category=category, site=self.site, attrs=attrs)

    def test_card_groups_types_and_speeds_across_both_key_spellings(self):
        self._asset("RAM-A", self.lap, {"ram_type": "DDR4", "ram_speed_mhz": 3200})
        self._asset("RAM-B", self.lap, {"ram_type": "DDR4", "ram_speed_mhz": 2666})
        self._asset("RAM-C", self.mod, {"memory_type": "DDR5", "speed_mhz": 4800})
        self._asset("RAM-D", self.lap, {})  # RAM not recorded yet

        _login_global(self.client)
        resp = self.client.get("/")

        self.assertEqual(resp.context["ram_recorded"], 3)
        self.assertEqual(
            resp.context["ram_types"], [{"label": "DDR4", "n": 2}, {"label": "DDR5", "n": 1}]
        )
        # speeds read fastest-first, like a spec sheet
        self.assertEqual(
            resp.context["ram_speeds"],
            [
                {"label": "4800 MHz", "n": 1},
                {"label": "3200 MHz", "n": 1},
                {"label": "2666 MHz", "n": 1},
            ],
        )
        self.assertContains(resp, "RAM type and speed")
        self.assertContains(resp, "4800 MHz")
        self.assertContains(resp, "RAM recorded for 3 of 4 assets")

    def test_card_offers_the_setup_hint_when_nothing_is_recorded(self):
        self._asset("RAM-E", self.lap, {})

        _login_global(self.client)
        resp = self.client.get("/")

        self.assertEqual(resp.context["ram_recorded"], 0)
        self.assertEqual(resp.context["ram_types"], [])
        self.assertEqual(resp.context["ram_speeds"], [])
        self.assertContains(resp, "No RAM details recorded yet")


class DashboardKpiAlertTests(TestCase):
    """Mockup layout: live KPIs, category chart and the alerts list (§ dashboard redesign)."""

    def _make(self, tag, *, warranty=None, serial="SN-1"):
        site = Site.objects.get(code="yangon")
        cat = Category.objects.get(code="IT-HW-LAP")
        return Asset.objects.create(
            asset_tag=tag,
            category=cat,
            site=site,
            serial_no=serial,
            warranty_end=warranty,
        )

    @classmethod
    def setUpTestData(cls):
        Site.objects.create(name="Yangon HQ", code="yangon")
        Category.objects.get_or_create(code="IT-HW-LAP", defaults={"name": "Laptop"})

    def test_kpis_and_alerts_from_real_queries(self):
        today = timezone.localdate()
        self._make("A-1", warranty=today + timedelta(days=3))  # → 7-day alert
        self._make("A-2", warranty=today + timedelta(days=10))  # → 30-day KPI only
        self._make("A-3", warranty=today + timedelta(days=200))  # → outside both
        _login_global(self.client)
        resp = self.client.get("/")
        kpis = {k["label_key"]: k for k in resp.context["kpis"]}
        self.assertEqual(kpis["dash.total_assets"]["value"], 3)
        self.assertEqual(kpis["dash.kpi.active"]["value"], 3)  # none retired/disposed
        self.assertEqual(kpis["dash.kpi.warranty"]["value"], 2)  # 3-day + 10-day
        self.assertEqual(kpis["dash.kpi.alerts"]["value"], 1)  # only the 7-day alert
        alerts = resp.context["alerts"]
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["key"], "alert.warranty_soon")
        self.assertEqual(alerts[0]["n"], 1)
        self.assertEqual(alerts[0]["tone"], "warn")
        self.assertContains(resp, "Alerts")
        self.assertContains(resp, "1 warranties expiring within 7 days")

    def test_retired_assets_leave_the_active_kpi(self):
        self._make("A-4")
        a = self._make("A-5")
        a.status = Asset.Status.RETIRED
        a.save(update_fields=["status"])
        _login_global(self.client)
        resp = self.client.get("/")
        kpis = {k["label_key"]: k for k in resp.context["kpis"]}
        self.assertEqual(kpis["dash.kpi.active"]["value"], 1)
        self.assertEqual(kpis["dash.total_assets"]["value"], 2)

    def test_no_alerts_state_renders(self):
        self._make("A-6")
        resp = self.client.get("/")
        self.assertEqual(resp.context["alerts"], [])
        self.assertContains(resp, "All clear")
        self.assertEqual(resp.context["kpis"][0]["value"], 0)  # critical-alerts KPI

    def test_approver_gets_action_tiles_and_pending_alert_first(self):
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group

        from apps.core.models import UserAccessScope

        user = get_user_model().objects.create_user("appr", "a@x.dev", "pw12345!")
        grp, _ = Group.objects.get_or_create(name="admin")
        user.groups.add(grp)
        user.is_staff = True  # app admins are staff — /admin/ links only resolve for them
        user.save(update_fields=["is_staff"])
        UserAccessScope.objects.create(
            user=user,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="approver dashboard test",
            created_by=user,
        )
        self.client.force_login(user)
        AssetRequest.objects.create(
            requester=user,
            category=Category.objects.get(code="IT-HW-LAP"),
            site=Site.objects.get(code="yangon"),
        )

        resp = self.client.get("/")
        kpis = resp.context["kpis"]
        self.assertEqual(kpis[0]["label_key"], "dash.kpi.pending")  # approver: action first
        self.assertEqual(kpis[0]["value"], 1)
        self.assertEqual(kpis[1]["label_key"], "dash.kpi.overdue")
        # pending alert is first in the list too (sorted for approvers)
        keys = [a["key"] for a in resp.context["alerts"]]
        self.assertEqual(keys[0], "alert.pending_approvals")
        # staff → deep link into the filtered admin changelist
        self.assertIn("/admin/assets/assetrequest/", resp.context["alerts"][0]["href"])
        self.assertIn("status__exact=PENDING", resp.context["alerts"][0]["href"])

    def test_viewer_keeps_baseline_tiles_and_data_alerts_link_to_filters(self):
        from datetime import timedelta

        from django.contrib.auth import get_user_model
        from django.utils import timezone

        from apps.core.models import UserAccessScope

        u = get_user_model().objects.create_user("viewr", "v@x.dev", "pw12345!")
        UserAccessScope.objects.create(
            user=u,
            scope_type=UserAccessScope.ScopeType.GLOBAL,
            reason="viewer dashboard test",
            created_by=u,
        )
        self.client.force_login(u)
        today = timezone.localdate()
        self._make("DL-1", warranty=today + timedelta(days=2))  # 7-day alert

        resp = self.client.get("/")
        kpis = {k["label_key"] for k in resp.context["kpis"]}
        self.assertIn("dash.kpi.alerts", kpis)  # no pending/overdue tiles for viewers
        self.assertNotIn("dash.kpi.pending", kpis)
        alert = resp.context["alerts"][0]
        self.assertEqual(alert["key"], "alert.warranty_soon")
        self.assertEqual(alert["href"], "/assets/?warranty_days=7")  # non-staff: list filter link

    def test_dashboard_kpis_respect_site_scope(self):
        """Enforcement on: a site-scoped user counts only their own site —
        KPIs, warranty window, chart and the alerts all narrow."""
        from django.contrib.auth import get_user_model

        from apps.core.models import UserAccessScope

        yangon = Site.objects.get(code="yangon")
        mandalay = Site.objects.create(name="Mandalay", code="mandalay")
        cat = Category.objects.get(code="IT-HW-LAP")
        today = timezone.localdate()
        Asset.objects.create(
            asset_tag="Y-1",
            category=cat,
            site=yangon,
            serial_no="Y1",
            warranty_end=today + timedelta(days=5),
        )
        Asset.objects.create(asset_tag="Y-2", category=cat, site=yangon, serial_no="Y2")
        Asset.objects.create(
            asset_tag="M-1",
            category=cat,
            site=mandalay,
            serial_no="M1",
            warranty_end=today + timedelta(days=5),
        )
        user = get_user_model().objects.create_user("scoped", "s@x.dev", "pw12345!")
        AssetRequest.objects.create(requester=user, category=cat, site=yangon)
        AssetRequest.objects.create(requester=user, category=cat, site=mandalay)
        UserAccessScope.objects.create(
            user=user,
            scope_type=UserAccessScope.ScopeType.SITE,
            site=yangon,
            reason="dashboard scope test",
            created_by=user,
        )
        self.client.force_login(user)

        with self.settings(SCOPE_ENFORCEMENT_ENABLED=True):
            resp = self.client.get("/")
        kpis = {k["label_key"]: k["value"] for k in resp.context["kpis"]}
        self.assertEqual(kpis["dash.total_assets"], 2)  # yangon only, M-1 hidden
        self.assertEqual(kpis["dash.kpi.warranty"], 1)  # mandalay's warranty hidden
        self.assertEqual(kpis["dash.kpi.active"], 2)
        # pending approvals: only yangon's request counts
        pending = [a for a in resp.context["alerts"] if a["key"] == "alert.pending_approvals"]
        self.assertEqual(pending[0]["n"], 1)
        # recent + chart narrow too
        self.assertEqual({a.asset_tag for a in resp.context["recent"]}, {"Y-1", "Y-2"})
        chart = {r["label"]: r["n"] for r in resp.context["by_category"]}
        self.assertEqual(chart, {"Laptop": 2})

    def test_dashboard_zero_scope_user_sees_zeros_when_enforcing(self):
        from django.contrib.auth import get_user_model

        self._make("Z-1", serial="SZ")  # data exists — just not visible to this user
        user = get_user_model().objects.create_user("noscope", "n@x.dev", "pw12345!")
        self.client.force_login(user)
        with self.settings(SCOPE_ENFORCEMENT_ENABLED=True):
            resp = self.client.get("/")
        kpis = {k["label_key"]: k["value"] for k in resp.context["kpis"]}
        self.assertEqual(kpis["dash.total_assets"], 0)  # deny by default
        self.assertEqual(resp.context["alerts"], [])

        # anonymous callers get the same zeros under enforcement
        self.client.logout()
        with self.settings(SCOPE_ENFORCEMENT_ENABLED=True):
            anon = self.client.get("/")
        self.assertEqual(anon.context["total_assets"], 0)
        self.assertEqual(anon.context["alerts"], [])

    def test_overdue_alert_links_to_loans_page(self):
        from apps.assets.models import Assignment

        asset = self._make("OV-1", serial="SOV")
        Assignment.objects.create(asset=asset, due_at=timezone.now() - timedelta(days=2))
        _login_global(self.client)
        resp = self.client.get("/")
        overdue = [a for a in resp.context["alerts"] if a["key"] == "alert.overdue_loans"]
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0]["href"], "/loans/overdue/")

    def test_category_chart_counts_and_others_bucket(self):
        self._make("A-7")
        self._make("A-8")
        Site2 = Site.objects.create(name="Mandalay", code="mandalay")
        cat2 = Category.objects.get_or_create(code="IT-HW-DSK", defaults={"name": "Desktop"})[0]
        Asset.objects.create(asset_tag="A-9", category=cat2, site=Site2, serial_no="SN-2")
        _login_global(self.client)
        resp = self.client.get("/")
        rows = resp.context["by_category"]
        self.assertEqual(
            [(r["label"], r["n"]) for r in rows], [("Laptop", 2), ("Desktop / Workstation", 1)]
        )
        self.assertEqual(rows[0]["pct"], 100)
        self.assertEqual(rows[1]["pct"], 50)
        self.assertFalse(any(r["others"] for r in rows))  # 2 categories → no bucket
        self.assertContains(resp, "Asset categories")


class AdminLinkVisibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User.objects.create_user("staffu", "s@example.com", "pw12345!", is_staff=True)
        self.plain = User.objects.create_user("plainu", "p@example.com", "pw12345!")

    def test_admin_link_hidden_for_anonymous(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "/admin/")

    def test_admin_link_hidden_for_non_staff_user(self):
        self.client.force_login(self.plain)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'href="/admin/"')

    def test_admin_link_shown_for_staff_user(self):
        self.client.force_login(self.staff)
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'href="/admin/"')

    def test_admin_link_shown_for_superuser(self):
        User = get_user_model()
        User.objects.create_superuser("adminu", "a@example.com", "pw12345!")
        self.client.force_login(self.staff)
        self.client.logout()
        self.client.force_login(User.objects.get(username="adminu"))
        resp = self.client.get("/")
        self.assertContains(resp, 'href="/admin/"')

    def test_url_name_home_resolves_to_root(self):
        self.assertEqual(reverse("home"), "/")
