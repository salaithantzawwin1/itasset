# Progress Log

**Project:** IT Asset Manager
**Purpose:** Living milestone log — updated per session

> The stable guide lives in DEVELOPMENT.md.

---

## Current Status

| | |
|---|---|
| Current milestone | M8 — Go-live |
| Status | M1–M7 complete; M8 not started (deployment up, DR/monitoring pending) |
| Last updated | 2026-10-22 |
| Next milestone | M8 — Go-live (+ spec-alignment track, see below) |
| Test suite | **341 passed + 90 subtests** (2026-10-22, local 264 s + server 108 s, exit 0) |

---

## Milestone Overview

| # | Name | Status |
|---|---|---|
| M1 | Foundation | ✅ Complete |
| M2 | Core flow | ✅ Complete |
| M3 | Labels & API | ✅ Complete |
| M4 | Alerts & licenses | ✅ Complete |
| M5 | LDAP & audit | ✅ Complete |
| M6 | Intake & lifecycle | ✅ Complete |
| M7 | Reporting & vendors | ✅ Complete |
| M8 | Go-live | ⏳ Not started |

---

## M1 — Foundation ✅

**Completed:** 2026-10-11

- Compose scaffold (docker-compose.dev.yml db+redis)
- Settings layer (config/settings/{base,dev,prod}.py)
- Models + admin CRUD
- Seed data
- /healthz endpoint (DB ping)
- Smoke tests: tests/test_smoke.py — 3 passed

---

## M2 — Core flow ✅

**Completed:** 2026-10 (was 🟡 "service layer done" as of session 3, 10-12; remaining items
verified present on 2026-10-15 — exact closing date not logged)

- Lifecycle service layer at apps/assets/services.py:
  check_out / check_in / handover / receive_asset, guards, typed errors
- Site/Asset/Person CRUD views (apps/assets/views.py, apps/people/views.py)
- Role checks on views (RoleRequiredMixin, apps/core/roles.py)
- CSV import: services.import_assets_csv + `manage.py import_csv` (dry-run default)
- Integration tests: test_crud_views.py, test_import.py

---

## M3 — Labels & API ✅

**Completed:** 2026-10 (verified present 2026-10-15)

- QR/PDF labels (apps/labels/services.py + tests)
- DRF API at /api/v1/: asset CRUD, scan payload, scanner token
  (apps/api/{urls,views,serializers,permissions,tokens}.py)
- Warranty/contract expiry endpoints
- Tests: apps/api/tests.py, apps/labels/tests.py

---

## M4 — Alerts & licenses ✅

**Completed:** 2026-10 (verified present 2026-10-15)

- Celery tasks (apps/audit/tasks.py): warranty buckets (90/30/7), contract notice,
  weekly license over-assignment, 24-month ActivityLog/EmailAlert purge
- Idempotent sending: `notify.send_alert` writes EmailAlert row before send (no double-send)
- Email templates: warranty_expiring, contract_renewal, license_over_assigned
- License register: SoftwareLicense + LicenseKey (apps/licenses)
- Tests: apps/audit/tests.py — 13 tests incl. idempotent reruns

---

## M5 — LDAP & audit ✅

**Completed:** 2026-10 (verified present 2026-10-15)

- LDAP/AD login: RoleMappingLDAPBackend (apps/accounts/ldap.py) with AD-group → Django-role
  sync (rolesync.py); `LDAP_ENABLED=1` opt-in, StartTLS, nested groups; local ModelBackend
  kept as break-glass fallback
- ActivityLog UI (apps/audit/views.py)
- Physical audit mode: AuditSession / AuditItem + report
- Tests: apps/accounts/tests.py, apps/audit/tests.py

---

## M6 — Intake & lifecycle ✅

**Completed:** 2026-10 (verified present 2026-10-15)

- Eight-stage flow wired end-to-end: Request → Approve (decide_request, admin-only,
  rejection reason) → Procure → Receive&Tag → Deploy → Maintain/Repair → Write-off →
  Sanitize → Dispose
- Transfer: site-to-site, bulk, IN_TRANSIT, arrival discrepancy → IN_REPAIR
- RepairTicket (RMA, cost, outcomes), WriteOff (police report, two-step decision),
  DisposalRecord (NIST methods, certificate no., second-person verify)
- Tests: apps/assets/tests/test_lifecycle.py, test_services.py

---

## M7 — Reporting & vendors ✅

**Completed:** 2026-10 (verified present 2026-10-15)

- Report suite: index + `reports/<slug>.<fmt>` (CSV + XLSX exporters),
  depreciation schedule (straight-line, XLSX) for finance
- Vendor / vendor-note / contract module (apps/vendors), expiry alerts (M4)
- Tests: apps/reports/tests.py (all formats render, auth required)
- Note: *scheduled/recurring export jobs* were scoped to v2 (DEVELOPMENT.md §27) and are
  not implemented — exports are on-demand

---

## M8 — Go-live ⏳

**Not started** (per DEVELOPMENT.md §28: "Ubuntu deploy, backup/DR drill, monitoring, docs";
done when "restore drill passed, Uptime Kuma green").

Partial infrastructure already in place:
- Production-style deployment live on LAN: nginx + gunicorn systemd units
  (`itasset-gunicorn`, WorkingDirectory `~/itasset`), 192.168.100.142
- Missing: tested backup/restore (DR drill), monitoring (Uptime Kuma), runbooks,
  UAT sign-off

---

## Spec-Alignment Track (added 2026-10-15)

Two new specifications were reviewed against this codebase:

- `docs/new/IT_Asset_Management_Technical_Specification_v1.0.md` (rewrite proposal)
- `docs/new/ITAM_Common_Asset_Fields_Category_Specific_Specifications_Master.md`

Deliverables produced:

| Doc | Purpose |
|---|---|
| `docs/new/ITAM_Gap_Analysis_Report_v1.0.md` | What exists / what's missing / effort (A: 23–37 pw; B: 13–24 wk) |
| `docs/new/ITAM_Status_Condition_Vocabulary_Master_v1.0.md` | Unified status/condition list (decisions D1–D9 open) |
| `docs/new/ITAM_Scope_RBAC_Design_v1.0.md` | Scope-based RBAC: schema, deny-by-default plan, IDOR tests |

Largest gap (and next hardening work): **scope-based RBAC** — current reads are open to any
authenticated user; no company/branch scoping exists.

**Stage A shipped 2026-10-15** (scope recording, no enforcement yet):
- `apps.core` app: `UserAccessScope` model (typed FKs + DB CHECK, `core.0001_initial`),
  `scopes.py` helpers (deny-by-default, fail-closed), admin UI (admin-role-only),
  `manage.py scope_backfill_report [--apply]`
- `SCOPE_ENFORCEMENT_ENABLED` setting (default **False** = Stage A/B; Stage C flips it)
- Backfill applied on server: `admin`, `itadmin` → GLOBAL; `ittech` listed for manual scope
- **Stage B + C shipped 2026-10-15** (same day): shadow "would-deny" logging via
  `scope_shadow_deny` ActivityLog events + flag-aware enforcement wired into assets/people
  views, DRF API (asset list/scan/expiries) and report exports; review command
  `manage.py scope_shadow_report`; `tests/test_scopes.py` — 20 tests (shadow + IDOR rows per
  design §6). Live server: **enforcement enabled** (`SCOPE_ENFORCEMENT_ENABLED=1` in `.env`,
  2026-10-15) after scopes were assigned — `admin`/`itadmin` GLOBAL, `ittech` SITE scopes for
  all three active sites (technician baseline).
- **Rows 15/22/23 shipped + transfer/approval writes 2026-10-16** (sessions 5–6, above):
  `Person.user` link + login auto-link + `/me/` self-view page + self-approval guard (service +
  API) + the attachments module with scope-checked downloads;
  `tests/test_scopes.py` 27 → 35 tests (+9 in `apps/attachments/tests.py`), full suite
  **186 passed + 60 subtests** with enforcement on.
- **Rows 17/20 shipped 2026-10-16 (session 7)** — the last deferred rows: a scope-write
  endpoint (`GET|POST /api/v1/users/{id}/scopes/`, `DELETE .../{scope_id}/`, admin-only) behind
  the `apps/core/scopeadmin.py` service (reason required → 400, typed columns + date window
  validated before save, `scope_grant`/`scope_revoke` ActivityLog from the API *and* the Django
  admin). **All 23 rows of design §6 now have an endpoint-level test**; suite **190 passed + 60
  subtests**; gap §3.1's last bullet ("audit + reason for privileged scope changes") is closed.

---

## Session Log

### 2026-10-22 (session 29 — employees & workstations link to assets: form-driven assignment, component parents, department report)
- **Person ↔ Asset is not User ↔ Asset** (question answered from the models):
  `Person` is the employee register (`employee_no`, department, optional
  `user`/`ldap_uid` link) — login accounts and employees are deliberately
  separate, so 100 staff need not mean 100 logins. Assignment itself already
  existed (`Assignment.to_person` via `services.check_out/check_in/handover`);
  what was missing were the three surfaces the request named.
- **(a) “Assigned to” picker on the asset form** (create + edit, main app
  *and* admin — `AssetAdmin` shares `AssetForm`): a declared non-model field
  that on save drives the existing services — new holder on IN_STOCK →
  `receive_asset(to_person=…)`, on AVAILABLE → `check_out`, holder change →
  `handover`, cleared → `check_in` — so status and the append-only trail
  stay single-sourced (one write path, §3 “state transitions happen only in
  services.py”); same-holder saves are a no-op. `clean_assigned_to`
  pre-validates feasibility (IN_REPAIR/RETIRED/DISPOSED/IN_TRANSIT refused
  with a “use the lifecycle flow” message) and any service failure surfaces
  as a form warning instead of a half-saved row. Detail page gained an
  “Assigned to” row (employee no + department) and the asset list a Holder
  column (one `Prefetch` of the open assignment per page, §17 no-N+1).
- **(b) `Asset.parent_asset` self-FK** (migration `assets.0011`, §6.1
  “recommended relationship”): a Monitor/UPS/Keyboard/Mouse records which
  workstation it sits on while keeping its own tag, warranty and independent
  holder; `SET_NULL` so deleting a parent never cascades components. Form
  guards refuse self-parent and parent loops (chain walk); the detail page
  lists Components with each component’s own holder, and a child links back
  to its parent. Both fields live in the Basics tab / admin fieldsets.
- **(c) Report `assets-by-department`** (“Assets by department (holder)”,
  CSV+XLSX): one row per open assignment grouped by the holder’s department
  (Person.department — a department move needs no asset edit), plus a
  completeness bucket: assets whose status says ASSIGNED with no open
  assignment row render as “Not assigned” (the seed data actually has one —
  IT-HW-DSK-0014 — which the report immediately surfaced).
- Gates: **352 passed + 90 subtests** locally (255 s) and on the server
  (109 s) — +11 new tests in `apps/assets/tests/test_form_assignment.py`
  (create/edit/handover/clear/forbidden transitions, component listing +
  loop refusal, report incl. the orphan bucket); ruff check + format clean,
  `makemigrations --check` clean, `check` clean. Verified in browser then by
  shell-rendered GETs (the preview panel was flaky): list Holder column,
  picker render + save → ASSIGNED with trail remark, components section
  both directions, admin change/add forms carry both fields with the
  picker prefilled.
- Deployed to 192.168.100.142 (LF archive sync → `migrate` applied
  `assets.0011` → server suite 352+90 → gunicorn restart): probe gate
  **18 ok / 0 failed** incl. throttle phase; live checks on the server
  (test client with the real host — prod ALLOWED_HOSTS correctly rejects
  `testserver`): `/reports/` 200 with the new card, CSV 200 with correct
  headers, admin add form 200 with `assigned_to` + `parent_asset`.
  Pushed `aa3a8f7..2c1e6d6`.

### 2026-10-22 (session 28 — responsive pass for big screens, laptop, tablet)
- **Wide-screen gutters fixed** (request, with screenshots: ~370px of dead
  space down both sides of every page on a 1920px display; laptop was fine):
  the layout used two fixed caps — main app `.page { max-width: 1180px }`
  (`base.html`) and admin `#content { max-width: 1240px }`
  (`_theme.css.html`) — so a large monitor never grew the content, it just
  centered the same column and left the surplus as margin. Added one
  breakpoint, `min-width: 1440px`, that lifts the caps to `.page → 1560px`
  (padding 28→36) and `#content → 1620px` (padding 30→40). One tier rather
  than fluid `vw` math: tables and charts use the screen, line lengths stay
  readable, and every rule below 1440px (1024/900/767/640) is untouched —
  laptop and tablet behavior is byte-for-byte what it was.
- Verified across all three requested sizes in the browser. **Desktop big
  (1920×1080):** container measures 1560px (gutters even at ~172px), all six
  KPI cards fit one row (was 5+1), dashboard/assets/admin/changelist fill the
  screen, `scrollWidth 1903 ≤ 1920` — no horizontal overflow. **Laptop
  (1366×768):** unchanged, the 1240px tier still applies (no regression).
  **Tablet (768×1024):** KPIs 2-col, topbar wraps, filters stack, assets and
  admin tables fit, no overflow.
- Gates: **341 passed + 90 subtests** locally (247 s), exit 0. Templates-only
  change — deployed to 192.168.100.142 (LF `git archive` sync of the two
  template files → gunicorn restart, no migrate/collectstatic): probe gate
  **18 ok / 0 failed** incl. throttle phase, `/healthz` ok, and both live
  pages serve the new rule (`/` → `.page` 1560, `/admin/login/` → `#content`
  1620). Pushed `492745d..0b31ecb`.

### 2026-10-22 (session 27 — create-modal content sizing + component categories)
- **Modal fine-tune** (request, with screenshots: empty wall under the form,
  doubled scrollbars, content flush to the frame edge): the New-asset dialog
  carried a fixed `height: min(88vh, 880px)` card, so a short Basics form sat
  in ~300 px of dead space while a tall Specifications form scrolled twice
  over. The card is now content-sized — `fit()` measures the framed page
  (`body.scrollHeight`; documentElement is the canvas and would round-trip
  the old height) and a ResizeObserver re-fits on tab switches and the live
  spec swap — capped at 88vh (full height ≤640 px) so tall forms scroll
  exactly once, inside the frame. The skin also stopped zeroing the main
  app's `.page` padding: `12px 16px` of breathing room instead of content
  flush against the border. Verified: Basics 347→371 px hug, Specs grows to
  the cap with a single inner scrollbar, no h-scroll at any width checked,
  dirty-close confirm still guards.
- **Component categories** (request: "HDD, RAM, Keyboard, Mouse စသဖြင့်"): five
  §6 entries added to `CATALOGUE` — `IT-HW-HDD` (5 fields), `IT-HW-SSD` (4),
  `IT-HW-RAM` (5), `IT-HW-KBD` (4), `IT-HW-MSE` (4) — all optional, with
  units/examples riding the new tooltip tips. Seeded by
  `assets.0010_seed_component_categories` scoped to those five codes with
  0008's create/fill-empty contract (an operator's deleted category stays
  deleted; a custom schema is never clobbered).
- Gates: ruff clean; **341 passed + 90 subtests** locally (264 s) and on the
  server (108 s) — the five new catalogue entries add five structural
  subtests. Browser-verified: dropdown lists all 23, Keyboard swap renders
  its 4 fields with auto-tag `IT-HW-KBD-0001`.
- Deployed to 192.168.100.142 (LF archive sync → `migrate` applied
  `assets.0010` → server suite → gunicorn restart): probe gate **18 ok /
  0 failed** incl. throttle phase; `/healthz` ok; prod Category count 23 with
  all five codes. Pushed `504e168..3416a6a`.

### 2026-10-22 (session 26 — field hints become label tooltips)
- **Help text → tooltip** (request: "e.g. Intel Core Ultra 5", (GB), (inches),
  "e.g. 1920x1080" should show as tooltips): every unit/example hint used to
  render as its own line under the input, which doubled the row height in
  session 25's column grids. Each hint now rides as a focusable ⓘ span inside
  the field's label; hover / focus / tap opens the themed `data-tip` bubble.
  The main app gained the bubble CSS (previously admin-only, session 22) with
  `text-transform: none` so the uppercase field labels stop leaking into the
  bubble text; the admin's global rules gained a `.help-tip:focus` override
  (plain `:focus-visible` on a span proved unreliable under automation and
  misses touch taps).
- Surface wiring: main app serves the tip from `partials/spec_fields.html`
  (server render **and** swap — one file) plus the generic field loop;
  the admin swap fragment (`admin/partials/spec_fields.html`) renders the
  same markup server-side, while the initial server-rendered fieldset keeps
  Django's stock `admin/includes/fieldset.html` and a 10-line pass in
  `change_form.html` folds each row's `.help` div into its label (no
  version-coupled template copy; no-JS keeps the inline help).
- Gates: **341 passed + 85 subtests** locally (241 s) and on the server
  (111 s). Browser-verified both surfaces × both themes: clean label rows,
  bubble content/case, keyboard focus, category swap serving tips
  server-side (Laptop 9 tips), zero leftover `.help` lines.
- Deployed to 192.168.100.142 (LF archive sync → server suite → gunicorn
  restart): probe gate **18 ok / 0 failed** incl. throttle phase; `/healthz`
  ok. Pushed `db41b39..b9dc5ec`.

### 2026-10-22 (session 25 — spec fields share rows on both edit surfaces)
- **Spec fields laid out in rows** (request: CPU Manufacturer stretched the
  full width on `/assets/6/edit/`): the Specifications panel wrapped its
  dynamic fields in the `[data-spec-fields]` div, which collapsed the panel's
  column grid — every spec field stacked one-per-line while Basics read
  3-across. The wrapper now carries the same `auto-fit minmax(240px, 1fr)`
  grid, so CPU ×3, RAM ×3 and storage ×3 share a row; the long "CODE — Name"
  category select spans two columns instead of truncating.
- **Admin change-form parity** (request: should both URLs look the same?):
  structure and behaviour are already identical by design — same four tabs,
  same field order, same live swap + tag auto-assign — while the chrome
  intentionally differs (admin keeps label-left rows, History/Delete and the
  related-widget links). Density now matches too: the admin Specifications
  fieldset grids two-across at ≥1360 px (existing hairline borders double as
  the row/column rules; the cell before an even-count last row drops its stray
  half-rule), classic single column below.
- Gates: **341 passed + 85 subtests** locally (235 s) and on the server
  (108 s). Browser-verified: main app edit + create (3-col grid, category
  swap keeps the grid, auto-tag intact, 640 px falls back to 2-col), admin
  change form (2-col after a live swap; 20- and 23-field schemas both close
  their final row cleanly).
- Deployed to 192.168.100.142 (LF archive sync → server suite → gunicorn
  restart): probe gate **18 ok / 0 failed** incl. the throttle phase (429 +
  Retry-After 300); `/healthz` ok. Pushed `1f73874..0631ea2`.

### 2026-10-21 (session 24 — category drives the tag and the fields; modal confirm, mobile forms)
- **Category auto-assigns the asset tag** (request): `services.next_asset_tag(category)`
  scans the category's existing tags for the highest numeric suffix and returns
  `<CODE>-NNNN` (`IT-HW-LAP-0050`). Advisory by design — `Asset.asset_tag` stays
  unique, so a lost race surfaces as a normal form error. On create the tag field
  is filled for the picked category and marked `data-auto="1"`; typing in the field
  clears the flag and the manual value then survives every later category switch.
  The form's server side (`AssetForm.__init__`) back-fills the tag on a bound
  create POST with an empty tag, so a no-JS submit still gets the auto tag.
- **Live spec-field swap** (request: Laptop vs Monitor should show different
  fields): new read-only `GET /assets/field-suggest/?category=&surface=`
  (`views.asset_field_suggest`, technician-gated like the forms) returns the
  category's spec fields as an HTML fragment plus `next_tag`. `spec_swap.html`
  (shared by both surfaces) swaps the panel contents on every category change,
  preserves same-named values across a switch (stashes and restores them), hides
  the Specifications tab while the category is empty, and flashes the tab when
  fields appear. Verified in browser: Laptop 23 spec fields, Monitor 13.
- **Category leads Basics** (request): moved to the front of the first tab on the
  main app and in `AssetAdmin`'s fieldsets (where "Category & specs" becomes an
  always-present "Specifications" fieldset the dynamic fields merge into), and
  the create form autofocuses it — the two behaviours above both key off it.
- **Modal close uses a styled confirm** (request: no more "192.168.100.142 says"):
  `templates/partials/modal.html` replaces the dirty-form `window.confirm` with an
  in-dialog alertdialog (Keep editing / Discard, ESC cancels the confirm not the
  modal). One native confirm remains on `audit/session_detail.html` (session-close
  submit guard — a different flow, left as-is).
- **Responsive fix found by the audit** (request: check the whole system): admin
  change forms overflowed ~53 px horizontally at ≤767 px — Django's
  `responsive.css` sizes `.aligned .form-row > div` at `calc(100vw - 30px)` for
  full-bleed pages, which overshoots inside our padded card. Overridden in
  `_theme.css.html` scoped to `#content` (specificity, not source order —
  responsive.css loads after the extrastyle block) with fields set to fill and
  shrink. Audited 390 / 820 / 1440 px, light + dark, main app + admin: zero
  horizontal overflow anywhere.
- Gates: ruff clean; **341 passed + 85 subtests** locally (252 s) and on the
  server (110 s). Browser-verified both surfaces end-to-end: category swap,
  tag auto-assign + manual stickiness, modal dirty-close confirm (Keep/Discard,
  scroll-lock release), mobile/tablet/desktop overflow probes.
- Deployed to 192.168.100.142 (LF archive sync → server suite → gunicorn
  restart): probe gate **18 ok / 0 failed** incl. the throttle phase (429 +
  Retry-After 300), `/healthz` ok, live files carry the new fieldsets, the
  field-suggest route and the styled-confirm markup. Pushed `eca4621..7dd9d21`.

### 2026-10-21 (session 23 — admin asset form gets the same tabs)
- Follow-up to session 22: `/admin/assets/asset/<pk>/change/` now sections the
  same way as the main app's edit page. `AssetAdmin` declares four named
  fieldsets (Basics / Category & specs / Device / Procurement — the readonly
  timestamps ride in the last one, keeping their old bottom-of-form position)
  and `get_fieldsets` merges the category's dynamic spec fields into
  "Category & specs" **on a fresh copy** of the class-level dicts (mutating
  them would leak the first request's spec fields into later renders); a
  defensive fallback still appends a "Specifications" fieldset if that
  fieldset is ever renamed.
- New scoped template `templates/admin/assets/asset/change_form.html`
  overrides `{% block field_sets %}`: each fieldset becomes a tab (server-
  rendered strip, arrow-key navigation, error fieldsets auto-open + dot-mark,
  invalid-in-hidden reveal as a backstop; no-JS → fieldsets stack under their
  own headings). Applies to the **add form** as well, so the modal New asset
  gets tabs too. Only asset's change form is affected — other models keep the
  stock single-scroll layout.
- Verified in browser both themes (tab switch, spec merge, readonly rows,
  save round-trip, empty-Category server error auto-opening the non-default
  tab with its dot, add form). Gates: ruff clean; **338 passed + 85
  subtests** locally and on the server.
- Deployed to 192.168.100.142 (sync → server suite → gunicorn restart): live
  authed GET as `itadmin` shows tablist + 4 panels + 22 merged spec fields on
  `/admin/assets/asset/6/change/`; `/healthz` ok. Pushed `efc2cea..8ac84ad`.

### 2026-10-21 (session 22 — tabbed asset form, calendar popup skin, icon tooltips, first authenticated probe)
- **Tabbed create/edit form** (request: the page was one endless scroll):
  `build_form_tabs()` in `apps/assets/views.py` buckets the form's fields into
  **Basics / Category & specs / Device / Procurement** — `spec__*` fields join
  the specs tab automatically, unknown future fields fall into the last tab so
  nothing can silently vanish (unrendered fields would vanish from POST too).
  Progressive enhancement: no JS → sections stack under their own headings;
  with JS → strip activates, server-side errors auto-open and dot-mark their
  section, and an invalid field in a hidden section reveals its panel before
  the native bubble (which would otherwise be "not focusable" and invisible).
  2–3-column grid per panel (textarea spans full width). Regression test
  asserts tablist + all four panels + every field on both create and edit.
- **Calendar popup re-skinned** (the follow-up request): stock `widgets.css`
  hardcoded `background: white` on the table (a white sheet in dark mode),
  sprite arrows and a solid accent caption — now token surfaces, ghost
  prev/next buttons, accent-filled selected day, ring on "today", quiet
  Yesterday/Today/Tomorrow bar and Cancel.
- **Icon tooltips** (follow-up): native `title` bubbles replaced by themed CSS
  bubbles (`data-tip` + `aria-label`, moved by a MutationObserver so
  DateTimeShortcuts' late-injected calendar trigger is dressed too); had to
  un-clip stock `forms.css`'s legacy `.form-row { overflow: hidden }` float
  clearfix (the floats it contained live in `ul.inline`/`h3`, not form rows) —
  it was slicing every bubble in half.
- Gates: ruff check + format clean; **337 passed + 85 subtests** locally and
  on the server (`SCOPE_ENFORCEMENT_ENABLED=1`); browser-verified both themes
  (tab switching, hidden-field reveal, server-error marking, save round-trip,
  calendar popup, tooltip bubble).
- Deployed to 192.168.100.142 (templates only: LF archive sync → gunicorn
  restart; no migrate/collectstatic). **First authenticated probe run** using
  operator-supplied break-glass credentials (not stored repo- or server-side
  config): `PROBE_USER=itadmin SKIP_THROTTLE=1` → **27 ok / 0 failed** (tokens,
  bad-ordering 400, idempotent create replay, stale 409, PATCH 200, PROBE asset
  cleanup), then the plain run → **18 ok / 0 failed** including the throttle
  (429 + Retry-After 300) — **45 checks green, exit 0 on both runs**. Live
  authed GETs: `/assets/6/edit/` serves all four panels + 34 fields (pk 2 does
  not exist in prod data — 404, not a defect); admin change form carries the
  tooltip script + calendar skin. Pushed `c345ee2..HEAD`.

### 2026-10-21 (session 21 — related-widget icons + date shortcuts re-skinned)
- The change-form FK cluster (Category/Site/…) shipped Django's stock 24 px
  multicolour icons (yellow pencil, green +, red X, blue eye) and DateTimeShortcuts'
  blue "Today | calendar" pair — a rainbow that fought the redesign in both themes
  (the request's two red boxes). `_theme.css.html` now redraws all of them as
  monochrome `currentColor` mask icons in a 28 px ghost-button group: quiet by
  default, accent on hover, danger-red for delete, focus ring; DOM order reworked
  via flex `order` so the destructive action sits last. "Today" becomes a quiet
  surface pill; the calendar icon gets the same ghost button.
- Field-width tidy in the same red box: `Cost` (and every admin number input) is
  capped at 220 px instead of stretching the full 560 px column; date inputs a
  consistent 150 px. Two Django rules outranked the first draft
  (`.related-widget-wrapper-link:link` and the theme's own 560 px grid rule) —
  fixed with a wrapper-scoped selector and `:not([type="number"])`, no
  `!important` needed.
- Gates: ruff clean; admin-smoke + smoke **13 passed + 69 subtests**, full suite
  **336 passed + 85 subtests**; browser-verified both themes (icon colors, mask
  icons, order, Today pill, widths via computed styles + screenshots).
- Deployed to 192.168.100.142 (CSS-in-template: LF archive sync → gunicorn
  restart, no collectstatic/migrate): `/admin/login/` serves the new rules
  (`field-icon` ×6), `/healthz` ok. Pushed `e8bfd12..6434406`.

### 2026-10-21 (session 20 — `<html lang>` follows the ENG/MM switch)
- `base.html` and `registration/login.html` hardcoded `<html lang="my">` while
  `{% t %}` (and session 18's `SessionLocaleMiddleware`, which sets
  `request.LANGUAGE_CODE`) default to English — every default-English page announced
  itself as Burmese to assistive tech. Both now emit
  `{{ request.LANGUAGE_CODE|default:'en' }}`, so the attribute tracks the same
  session key as the strings, admin chrome and `Content-Language`; guarded by a new
  smoke test (EN default → MM after the switch, standalone login + a base.html page).
- Gates: ruff clean; **336 passed + 85 subtests** locally (the host desktop session
  restart had killed the embedded Postgres — `scripts/start-pg.ps1` brought it back,
  crash-recovery checkpoint clean).
- Deployed to 192.168.100.142 (templates-only: no migrate/collectstatic): LF archive
  sync → `systemctl --user restart itasset-gunicorn` → `/accounts/login/` and `/`
  render `lang="en"`, `/healthz` `{"status":"ok","db":"ok"}`. Code commit `529275c`.

### 2026-10-20 (session 19 — UI/UX fine-tune + create-in-modal)
- **Create-in-modal** (`templates/partials/modal.html`, included from `base.html` +
  `admin/base_site.html`): admin object-tools **Add** links, dashboard **Add** chips and
  the site's **+ New asset / Request asset** buttons (`data-modal`) open the form in a
  same-origin iframe dialog instead of navigating away. The partial injects a skin into
  the framed document (hides topbar/sidebar/page-head), keeps validation errors inside
  the dialog, and on the post-save redirect closes + refreshes the parent while
  transplanting the flash message the iframe render would otherwise swallow; ESC/
  backdrop close guarded by a dirty-form `confirm`. Framed pages never init a nested
  instance (`window.top` check); Django `_popup` links and related-widget "add another"
  are excluded. `X_FRAME_OPTIONS` flips `DENY` → `SAMEORIGIN` (CSP `frame-ancestors
  'self'` already matched — cross-site framing stays blocked).
- **Changelist chrome fine-tune** (the two red-boxed areas from the request): model-named
  search placeholder (`admin/search_form.html` override), date-hierarchy links restyled
  as chips with a "By date" caption (`admin/date_hierarchy.html`), card-style actions
  bar with right-aligned counter, pill filter-rail actions (Show counts / Clear all),
  and a themed **empty state** (`admin/change_list_results.html` override — a zero-row
  changelist previously rendered a blank card) that distinguishes "nothing yet" from
  "no matches" with a clear-filters escape.
- **Django template gotcha, found twice in browser**: `{# ... #}` comments are
  single-line and non-greedy — a nested marker (or multi-line body) ends the comment
  early and the tail renders as literal text (one leaked into the empty state, one into
  every page). All comments in the new templates are single-line, marker-free.
- Gates: ruff check + format clean (183 files), `makemigrations --check` exit 0,
  **335 passed + 85 subtests** locally and on the server with
  `SCOPE_ENFORCEMENT_ENABLED=1`; browser-verified both themes (modal open/validation/
  save/close+message, empty states, chips, placeholder).
- Deployed to 192.168.100.142: `git -c core.autocrlf=false archive` LF sync → server
  suite green → migrate (0 pending; `assets.0008/0009`, `audit.0004`, `people.0005`
  already applied by session 18's worktree drop) → collectstatic (154 unmodified) →
  gunicorn restart → probe **18 ok / 0 failed** (anon; authenticated phase needs
  `PROBE_USER`/`PROBE_PASS`, not stored server-side) → headers verified live
  (`X-Frame-Options: SAMEORIGIN`, CSP, correlation id) and the modal/empty-state
  markup confirmed rendered on `/admin/login/` and `/`. Pushed `434490e..eaed9a9`.

### 2026-10-19 (session 18 — admin redesign v2 + live KPI dashboard)
- **Admin shell rebuilt around a model sidebar** (`apps/core/templatetags/admin_nav.py`):
  every admin page carries the same permission-filtered app/model tree (from
  `admin.site.get_app_list`, so scoped ModelAdmin gates still apply), with the
  current app expanded and the current model highlighted; collapses below 1024 px.
- **Dashboard**: six live KPI cards (total/active/assigned assets, pending requests,
  overdue loans, warranty ≤30 d) from a `{% admin_stats %}` tag, page-eyebrow header,
  refined app cards and recent actions; KPI grid is 3×2 on desktop, 2-col, then 1-col.
- **Page headers + forms**: shared eyebrow/h1/subtitle header, object tools aligned to it;
  fieldsets use a 210 px label / field grid on ≥960 px (the 22-field spec fieldset reads
  twice as fast); sticky save bar on long forms; refined changelist toolbar, filter rail
  (custom chevrons), badges and pagination.
- **One language per page**: new `SessionLocaleMiddleware` makes Django's admin chrome
  follow the same ENG/MM session switch as `{% t %}` (English when unset) — the admin no
  longer mixed Burmese headings with English content. Location is derived from the
  session key only, not cookies.
- `Category` plural fixed (`categorys` → `categories`, migration `assets.0009`).
- Fixed two layout defects found in browser verification: the shared topbar was being
  flex-shrunk to 35 px by `#container` (breaking every sticky offset), and a sticky
  `thead` inside the auto-scrolling `.results` container overlapped the first row.
- Gates: ruff check + format clean, **335 passed + 85 subtests, exit 0** (4 new admin tests).
- Deployed to 192.168.100.142: DB backup first, `assets.0009` applied, services restarted,
  post-deploy probe **26 ok / 0 failed**, admin verified live (dashboard, changelist,
  change form, ENG↔MM switch).

### 2026-10-17 (session 17 — the last §14 email rows: approvals, loan overdue, damage, transfer exception)
- **Request awaiting approval → approvers**: `services.notify_pending_approvers`
  fires **inline** the moment a request starts awaiting a step (and each time
  a chain advances — "within 1 h" by construction, no queue). Recipients =
  the step's `required_role` holders **in scope for the request's site**
  (`notify.role_emails`: group ∩ `ScopeSet.allows_site`, superusers always,
  deny-by-default applies to who gets told); nobody configured → §14
  fallback IT lead. Dedupe bucket `(request, step)`; no-op once PENDING ends.
- **Loan overdue** → new `scan_loans` (daily 07:15, new §15 row): assignments
  with `due_at` ≤ today−3 and not returned → holder + **issuing technician**,
  one bucket per assignment, no due date → never alerts. Damage and transfer
  exceptions fire **in-band** at the service call (`report_damage`,
  `receive_transfer` on EXCEPTION — one alert per transfer, not per tag) to
  destination-scoped technicians + `Site.lead_email`; all in-band sends go
  through `_best_effort` (SMTP failure → logged, the business action still
  succeeds — the loginaudit pattern; failed send leaves no alert row so a
  retry can deliver).
- **Bug found while wiring the above:** `Assignment.assigned_by` is a
  *Person* ("simplified" placeholder), yet `check-activity` read
  `.username` off it → **AttributeError on every real checkout** (only the
  never-assigned seed rows hid it). Both that report and `scan_loans` now
  read the operator from the `check_out` ActivityLog event — **one batched
  lookup, no N+1 (§17)** — falling back to `assigned_by.name`.
- Verified: +6 tests (scoped-only approver recipients + advance-to-step-2
  recipients + PENDING-noop, loan scan incl. no-due-date silence + one-bucket
  re-run, damage recipients incl. out-of-scope tech excluded + SMTP-outage
  resilience with no stale alert row, transfer-exception recipients to
  destination only, `check-activity` operator = checkout actor), beat
  doc-drift guard extended with `scan_loans`. Full suite **275 passed + 1
  skipped + 69 subtests** (sqlite), ruff clean (175 files),
  `makemigrations --check` exit 0, `check` clean. No schema changes this
  session — still **five migrations pending** for Monday. Remaining §14:
  Telegram system-error webhook (§14 in-app/workflow notifications are
  outside the email matrix).

### 2026-10-17 (session 16 — the three missing §15 Celery tasks: scheduled exports, digest, data-quality)
- **Ship gaps in the §15 task table** (all three were documented but had no
  code): `send_scheduled_reports` (§4 "Scheduled reports": weekly Mon 07:30
  expiring warranties + contract renewals → IT lead; monthly 1st 08:00
  inventory-by-site **per site** → `Site.lead_email`, a new field, blank →
  IT lead) with the CSV export **attached**; `send_daily_digest` (daily 08:00 →
  admins via new `ADMIN_EMAIL` env, falls back to IT lead; yesterday's
  check-outs/ins from `ActivityLog`); `data_quality_report` (monthly 1st 07:00
  → IT lead; §13's four checks — missing warranty, missing location
  (site-address data, since `Asset.site` is a mandatory FK), assigned-no-holder
  **reusing the `orphan-assets` report** so the two can never disagree,
  duplicate serials).
- Plumbing: `notify.send_alert` gained `recipients=` overrides and
  `attachments=` (EmailMessage path; text/* decodes to str — tests normalize),
  plus `daily_digest`/`scheduled_report`/`data_quality` recipient kinds and an
  `admin` resolver; `reports.service` gained `_lookup`/`_execute` shared by
  `run_report` **and** the new system path `run_scheduled_report` (no user →
  no scope gate; audience fixed by §14 recipients; verified no query reads
  `request`); beat schedule +4 entries; 3 bilingual templates; `.env.example`
  `ADMIN_EMAIL`.
- Verified: +8 tests in `apps/audit/tests.py` (weekly with real CSV bytes +
  no-recipient skip, monthly per-site pinning both ways + fallback recipient,
  data-quality counts + serial examples in body + monthly dedupe, digest
  yesterday-only + admin recipient + IT-lead fallback, a **doc-drift guard**
  asserting every §15 table row has a beat entry and both scheduled cadences,
  unknown-cadence ValueError). Full suite **269 passed + 1 skipped + 69
  subtests** (sqlite), ruff clean (175 files), `makemigrations --check` exit 0
  (`people.0004_site_lead_email`), `check` clean. **Not deployed** —
  `people.0004` joins `reports.0001` and the three earlier migrations:
  **five pending for Monday.**
- Open §14 rows (now the remaining notification gaps): request-approval email,
  loan-overdue, damage/transfer exception, Telegram system-error webhook.

### 2026-10-17 (session 15 — export jobs API: /api/v1/exports/, gap §3.5 closed)
- **`apps/reports/service.py::run_report`** extracted as the **single** execution layer
  shared by the HTML report views *and* the new API export jobs (Spec A §4/§5.2):
  scope gate (pinned-to-in-scope-site), registry lookup, queries and renderer cannot
  drift; typed errors (`Http404` unknown report/site, `UnsupportedFormat`,
  `ReportForbidden`) all raised **before** any query runs. Views and API are thin
  wrappers over it now.
- **Export jobs** (§10.8, gap §3.5's last missing API item): `ExportJob` (migration
  `reports.0001`, files in private `PrivateStorage`, status
  READY|RUNNING|FAILED, newest-20-per-user prune that deletes files too) +
  `POST /api/v1/exports/ {report, format, site?}` → `201
  {id, report, format, status, row_count, site, created_at, download}`,
  `GET /api/v1/exports/` (owner list; admins see all),
  `GET /api/v1/exports/{id}/download/` streaming from private storage
  (owner-scoped → foreign id **404**, never a file leak). Failures: `400`
  unknown report / unsupported format and `403` scope carry the §10.9
  `{detail, status, code, correlationId}` envelope; unexpected render errors
  leave a `FAILED` ops row before re-raising; every create writes an
  `export_create` ActivityLog. Read-only admin for jobs; all three routes in
  `/api/v1/schema` (`ExportJobViewSet: 0` schema warnings).
- Verified: +9 tests in `apps/reports/tests.py` (roundtrip + real CSV bytes
  from the stream, both 400s with envelope and **no dirty rows**, scope gate
  403×2 + in-scope 201, owner 404 vs admin 200, prune keeps newest 20 and
  removes their files, FAILED row, 401 anonymous, HTML unknown report → 404).
  Full suite **261 passed + 1 skipped + 69 subtests** (sqlite override), ruff
  + format clean (174 files), `makemigrations --check` exit 0, `check` clean.
  **Not deployed** — `reports.0001` joins the three migrations pending for
  Monday.

### 2026-10-17 (session 14 — Monday deploy probe script + approval delegation)
- **`deploy/probe-production.sh`** — the §7.3 checklist asserted as code: phase 1
  anonymous (healthz+db ok, 200s, generic 404, static from the admin page — the app
  homepage inlines its CSS — anon 401s, schema/docs 401|403, CSP + nosniff +
  `X-Correlation-ID`, envelope keys, 11-bad-logins → 429 + `Retry-After`), phase 2
  behind `PROBE_USER/PROBE_PASS` (token, /me, org, bad ordering → 400, create → 201,
  idempotent replay + header + no duplicate, version 1, stale PATCH → 409, current
  PATCH → 200, best-effort cleanup). Non-zero exit on any failure; `SKIP_THROTTLE=1`
  available. **Validated end-to-end against a local dev server on :18000: 28 ok,
  0 failed, exit 0** (found three real bugs while validating: JsonResponse's space
  after `:`, the inline-CSS homepage, and a token-parse/glob issue).
- **Approval delegation** (gap §3.2, workstream 4): `ApprovalDelegation` (admin-role
  only + audited `delegation_grant/change/revoke`, distinct-users DB check, window,
  `active`) + `services.delegation_for_role()` (deny-by-default: active + window +
  the **delegator must hold the role** — a delegation never widens authority) wired
  into `decide_request`: own role *or* delegation; self-approval by proxy → 403;
  segregation now counts **principals** (actor + delegator — one human never covers
  two steps directly or via proxy); `ApprovalDecision.delegated_from` (migration
  `assets.0007_…`) shows in the approvals trail and ActivityLog
  (`delegated_from` detail). The approve/reject endpoints now authorize in the
  **service** instead of a blanket `IsAdmin` gate — configured technician steps were
  unreachable over the wire before; existing IDOR/role tests still pass because they
  assert the service's 403 (legacy default chain = admin step).
- Verified: new `tests/test_approval_delegation.py` — 8 tests (no-delegation denied
  with the required role named, happy path with trail + audit, never widens, expired
  and inactive windows, delegator-without-role, principal segregation both directions,
  proxy self-approval). Full local suite **252 passed + 1 skipped + 68 subtests**
  (sqlite), ruff clean (169 files), `makemigrations --check` exit 0. One existing
  audit-dict assertion updated to the intentional new key (`delegated_from: None`).
  **Not deployed** — three migrations now pending for Monday.

### 2026-10-17 (session 13 — org reference endpoint, ordering allowlist, break-glass runbook, Monday deploy checklist)
- **`GET /api/v1/org/sites/`** (gap §3.5 org endpoints): sites with nested departments,
  code-sorted — the form choices (site pickers, transfer destinations) clients were
  missing. Reference data by design: deny-by-default scoping stays on *records*;
  the scoped org model waits on the hierarchy decision (gap §6 / workstream 3).
  Anonymous → 401.
- **Ordering allowlist** (§3.5 "sort/filter allowlists … not policy-driven"): `?ordering=`
  on the asset list with a 10-field policy allowlist — unknown field → **400** naming the
  offender *and* the allowed fields (never silently ignored, never fed to `order_by`);
  multi-field and `-` descending supported; default order unchanged. Filters were already
  fixed params by construction. Transfers/requests expose no ordering param at all.
- **Break-glass runbook** (§3.6 "documented procedure with reason/incident capture"):
  `docs/runbooks/break-glass.md` — 7-step procedure + evidence map splitting the
  automatic half (ActivityLog `login` event, IT-lead alert email) from the operator half
  (reason/incident entry within 15 min, credential rotation). Notes that prod runs
  `LDAP_ENABLED=0` → the alert path is dormant by design.
- **§7 Production Deploy Checklist** added to the gap report (user request): Monday
  2026-10-19 pre-flight → sync → migrate (`assets.0006`, `core.0002`) → collectstatic →
  gunicorn restart → probe gate (schema gating, CSP + correlation id, 429, version/
  idempotency/me, create-201, nginx 30m) → ops extras (first real backup, restore drill,
  optional audit-deps/monitoring) → rollback steps.
- Verified: new `tests/test_api_surface.py` — 5 tests (org tree anon 401 + tree shape,
  default order, allowlist applies, invalid field 400 with allowed list + envelope).
  Full local suite **244 passed + 1 skipped + 65 subtests** (sqlite), ruff `check` +
  `format --check` clean (167 files), `makemigrations --check` exit 0.
  **Not deployed** — laptop development continues; production drop planned Monday.

### 2026-10-17 (session 12 — ops tooling: dependency scanning, backup script + runbooks, CSRF + migration guards)
- **Dependency scanning** (gap §4 workstream 11, last open item): `pip-audit` added to
  the dev extras + `make audit-deps`; first run **clean** ("No known vulnerabilities
  found" — only the local `itasset` package itself skipped, as expected). Workstream 11
  is now fully done.
- **Backup tooling + runbooks** (§3.7 / sequence step 8): `deploy/backup.sh`
  (`pg_dump --format=custom` + private-attachments `tar.gz`, 14-copy retention,
  DATABASE_URL from env or `~/itasset/.env`, clear failures when pg_dump or the env
  are missing) + `make backup`; `docs/runbooks/backup-restore.md` (schedule incl.
  systemd timer recipe, fresh-DB restore procedure, drill checklist with an honest
  "drill not yet run" row) and `docs/runbooks/incidents.md` (symptom→action table
  built around the new correlation ids, throttle/Redis fail-open behaviour,
  break-glass evidence, escalation notes). The restore **drill itself** and
  monitoring still need the server.
- **CSRF + migration guards** (§4 workstream 13): a real-enforcement CSRF test
  (`Client(enforce_csrf_checks=True)` — session POST without token → 403, with
  cookie+header → through; the throttle deliberately does not count CSRF 403s) and
  `tests/test_migrations_guard.py` (`makemigrations --check` as a test, so a model
  edit without its migration fails CI instead of surprising the server).
- Verified: new tests 2+1 (CSRF, migration guard — the latter needs the
  `django_db` marker because makemigrations introspects applied state); full local
  suite **239 passed + 1 skipped + 65 subtests** (sqlite), ruff `check` +
  `format --check` clean (165 files), `bash -n deploy/backup.sh` ok,
  `pip-audit` run exit 0. **Not yet deployed** — deploy still deferred by request.

### 2026-10-17 (session 11 — API identity + observability: /api/v1/me, correlation id, error envelope, §3.6 session revocation)
- **`GET /api/v1/me/`** (gap §3.5, §10.2): caller identity + roles + effective
  scopes (deny-by-default set from design §4.3, sites/departments resolved to
  code+name) — clients can render "who am I, what can I see" and understand an
  empty view instead of guessing.
- **Correlation id** (§10.1): new `CorrelationMiddleware` (outermost) echoes or
  mints `X-Correlation-ID` on *every* response (client value sanitized to
  `[A-Za-z0-9_.-]`, capped 64; minted uuid4 otherwise) and stashes it on the
  request for error bodies.
- **Consistent error envelope** (§10.9): DRF errors go through the new
  `apps/api/exceptions.py::api_exception_handler` — detail-style bodies gain
  `code` (exception default_code, with a status→code fallback for Django's
  converted Http404/PermissionDenied) + `correlationId`; field-error maps stay
  untouched. The hand-written `_error()` helper (and the 12 inline
  `Response({"detail": …})` bodies in views.py) now emit the same fields, so
  every 4xx is `detail` + `status` + `code` + `correlationId`.
- **§3.6 disabled-account session revocation**: investigation showed Django's
  ModelBackend already refuses inactive users at authentication time (next
  request = anonymous; DRF refuses their tokens too) — the revocation window
  was already zero. New `ActiveUserMiddleware` closes the only remainder: when
  a session claims an identity the backend refused (account deactivated or
  deleted), the orphaned session row is flushed so the cookie dies too. Zero
  cost on the happy path.
- Verified: new `tests/test_api_identity.py` — 10 tests (/me anon 401 + envelope,
  identity/roles/scopes + SITE-scope rendering, correlation mint/echo/sanitize,
  404 and hand-rolled 409 envelopes with matching correlation ids, field-error
  shape preserved, session revocation + row flush, inactive token refused).
  Full local suite **237 passed + 1 skipped + 65 subtests** (sqlite), ruff
  `check` + `format --check` clean (162 files), middleware classes resolve.
  **Not yet deployed** — deploy still deferred by request.

### 2026-10-17 (session 10 — workstream 7 complete: optimistic version lock, Idempotency-Key, asset-create fix)
- **Optimistic lock on assets** (gap §3.5 / Spec A §10.1): new `Asset.version` column
  (migration `assets.0006_asset_version`, default 1). `PATCH|PUT /api/v1/assets/{tag}/`
  compares a payload-borne `version` against the row — stale → **409** and the row is
  untouched; a payload without `version` keeps last-write-wins for simple clients; on
  success the version increments (`version` is read-only in the serializer, so the view
  owns the write after its check). Every lifecycle service (`check_out`, `check_in`,
  `receive_asset`, transfer dispatch/receive, damage, repair close, write-off, dispose)
  calls `bump_version()` too, so a lifecycle change between read and write is also caught.
- **Idempotency-Key replay protection** (§10.1): new `core.IdempotencyRecord` model
  (migration `core.0002_idempotencyrecord`, unique `(user, key)`)
  + `IdempotencyMiddleware` on every `/api/v1/` write that carries the header: first
  request runs and its response (status < 500) is stored; a replay returns it with
  `Idempotency-Replayed: true` and never reaches the view (side-effect-free echo — safe
  to return before the CSRF check); key reuse with a different payload/path/method →
  409, duplicate while the original is still running → 409. Keys are per-user; bodies
  over 1 MB (attachment uploads) bypass the feature; rows are pruned after 7 days
  (opportunistic delete, no extra cron). The middleware resolves DRF Token clients
  itself — session identity arrives from AuthenticationMiddleware, but the scanner's
  `Authorization: Token …` is otherwise only authenticated inside the view. Admin:
  read-only evidence view.
- **Live defect found & fixed while testing the above**: `POST /api/v1/assets/` answered
  **500** (`NOT NULL constraint failed: assets_asset.site_id`) because category/site were
  read-only nested serializers — create could never fill them. Writable
  `category_id`/`site_id` PrimaryKeyRelatedFields now back the nested read output, which
  is unchanged; missing FKs → clean 400 (tests pin both).
- Verified: new `tests/test_api_hardening.py` — 14 tests (create fills FKs + version 1,
  400 not 500, current-version increment, stale-version 409 with the row untouched,
  no-version last-write-wins, non-integer version 400, services bump the version, replay
  never duplicates, 400 replays deterministically, key reuse 409, in-progress duplicate
  409, per-user key scoping, PATCH replay runs the view once, header-less requests
  unaffected). Full local suite **227 passed + 1 skipped + 65 subtests** (sqlite), ruff
  `check` + `format --check` clean (160 files), `makemigrations --check` exit 0.
  **Not yet deployed** — production drop still deferred by request; two migrations
  (`assets.0006`, `core.0002`) will need `migrate` on the server.

### 2026-10-17 (session 9 — security pass: headers, login throttle, admin-only OpenAPI, login audit + break-glass alert)
- **Security headers** (gap §3.5, Spec A §11.3): new `apps/core/middleware.py` —
  `SecurityHeadersMiddleware` sets a same-origin `Content-Security-Policy` on every HTML
  response (admin/swagger/static/QR labels are all same-origin; `unsafe-inline` retained
  because the Django admin requires it); `nosniff` + `Referrer-Policy: same-origin` come from
  Django settings. JSON responses deliberately get nosniff but no CSP.
- **Credential throttling** (§3.5/§3.6): `LoginThrottleMiddleware` counts *failed* POSTs to
  `/accounts/login/`, `/admin/login/` and `/api/v1/auth/token/` per IP+path (default 10 /
  300 s, `LOGIN_THROTTLE_ATTEMPTS`/`LOGIN_THROTTLE_WINDOW` env-tunable); over the cap →
  **429 + `Retry-After`**; a successful login resets the budget; CSRF 400s don't count.
  **Fail-open**: if the cache backend is unreachable the request proceeds — a Redis outage
  can never lock people out of login.
- **Shared cache for the counter**: base defaults `CACHES` to locmem (`CACHE_URL`
  env-overridable); `config.settings.prod` re-points it at Redis (`…:6379/1`) because
  gunicorn runs 2×CPU+1 workers — per-worker memory would multiply the budget by worker count.
- **Admin-only OpenAPI** (closes the §3.5 documented-vs-actual finding from session 7):
  `SPECTACULAR_SETTINGS` sets `SERVE_PERMISSIONS = [apps.api.permissions.IsAdmin]` +
  `SERVE_PUBLIC = False` — `/api/v1/schema/` and `/api/v1/docs/` no longer answer 200
  anonymously (anon 401/403, authenticated non-admin 403, admin 200).
- **Login audit + break-glass alerting** (§3.6, Spec A §11.2): `apps/accounts/loginaudit.py`
  (wired from `AccountsConfig.ready()`, same pattern as `personlink`) writes an `ActivityLog`
  event for every `user_logged_in` / `user_login_failed` — username + IP + backend, **never
  the password**. When `LDAP_ENABLED=1`, a local-ModelBackend sign-in is break-glass: it
  additionally emails the IT lead (`templates/email/breakglass_login.txt`, time-stamped
  dedupe key so *every* occurrence alerts) and never blocks the login if the alert fails.
- Verified: new `tests/test_security_hardening.py` — 10 tests (admin-only schema + docs,
  CSP/nosniff headers and their absence on JSON, throttle cap + 429 + Retry-After, admin and
  token paths, success-resets-counter, fail-open on a broken cache backend, login audit
  without the password, break-glass email on/off); full local suite **213 passed + 1 skipped
  + 64 subtests** (sqlite), ruff `check` + `format --check` clean (157 files).
  **Not yet deployed** — the production drop of this pass is deferred; at deploy time set
  `CACHE_URL` (or rely on the prod Redis default) and restart `itasset-gunicorn`.
- Still open in step 8: restore test/DR drill, monitoring, runbooks, dependency scanning,
  documented break-glass procedure (reason/incident capture), disabled-account session
  revocation window (§3.6).

### 2026-10-16 (session 8 — approval engine MVP: rules, thresholds, steps, immutable events)
- **Approval engine** (gap §3.2 / Spec A §6.6 → `apps/assets`): `ApprovalRule` template table
  (category/site scope, `min_quantity` / `min_amount` thresholds, `required_role`, `step`,
  `active`) + `ApprovalDecision` immutable event (append-only `save()` refuses updates, DB unique
  `(request, step)`); migration `assets.0005_approvalrule_approvaldecision_and_more`.
- **Service:** `resolve_approval_steps()` builds the chain — *no matching rule → the legacy single
  admin step*, so shipping the engine changes nothing until rules are configured (the pre-engine
  lifecycle tests pass untouched). `decide_request` now approves **step by step** (each step gated
  by its own `required_role`; request turns APPROVED only after the last step, intermediate stays
  PENDING), rejects finally at any step, refuses the same approver covering two steps
  (`ApprovalSegregationError` → 403), and writes an `ApprovalDecision` plus ActivityLog with
  `step`/`steps_total` for every decision — decisions are events, not mutable state (§6.6).
- **API:** `GET /api/v1/requests/{id}/approvals/` → configured chain (steps + required roles),
  current step and the immutable trail (scoped: out-of-scope → 404; anonymous → 401). Approve /
  reject endpoints unchanged except the sharper 403 messages. **Admin:** `ApprovalRuleAdmin` is
  admin-role-only and audited (`approval_rule_create` / `approval_rule_change`);
  `ApprovalDecisionAdmin` is read-only evidence.
- Verified: local `ruff check` + `format --check` clean; local suite **203 passed + 1 skipped + 64
  subtests** (sqlite), server suite **204 passed + 64 subtests, 62.7 s, exit 0** with
  `SCOPE_ENFORCEMENT_ENABLED=1`; `makemigrations --check` clean on both sides; migration applied;
  gunicorn restarted; live probes through nginx → `/api/v1/requests/1/approvals/` **401**,
  `/api/v1/requests/1/approve/` **401**, `/admin/assets/approvalrule/` **302** (login), healthz 200.
  New tests: `apps/assets/tests/test_approval_engine.py` — 14 tests (default chain unchanged,
  multi-step ordering, per-step roles, segregation of duties, final rejection, quantity/site/
  category/amount matching, inactive rules, append-only + unique-step, admin gating, wire trail,
  out-of-scope 404).
- **Still open in §3.2:** delegation, escalation, timeout, and the SUBMITTED/IN_REVIEW/CLOSED
  request states (companion vocabulary decision).

### 2026-10-16 (session 7 — :80 deployment verified; scope-write endpoint closes rows 17/20)
- **Deployment to `192.168.100.142:80` verified end-to-end**: nginx → gunicorn (systemd *user*
  units `itasset-gunicorn` + `itasset-runserver`, `config.settings.prod`) — `/` and
  `/admin/login/` 200 with static CSS 200, `/healthz` `{"status":"ok","db":"ok"}`,
  `/api/v1/assets/` 401 anonymous, generic 404 (DEBUG off); all migrations applied,
  `makemigrations --check` clean, `collectstatic` 154 files unmodified, **159 source files
  md5-identical local↔server**, gunicorn restarted after the last source write (no stale
  workers), `docs/new/*` synced. One live defect found and fixed at the source: nginx
  `client_max_body_size 10m` rejects uploads the app accepts (12 MB POST → **413** through :80,
  direct gunicorn → 401) — `deploy/nginx-itasset.conf` now says **30m** (25 MB attachment cap +
  overhead). **Applying it still needs root on the server**
  (`ssh itasset-dev 'sudo bash ~/itasset/deploy/install-nginx.sh'`) — the only open deploy item.
- **Row 17 — scope escalation closed:** `GET|POST /api/v1/users/{id}/scopes/` and
  `DELETE /api/v1/users/{id}/scopes/{scope_id}/` in `apps/api/views.py`, both `IsAdmin`-gated,
  routed through the new `apps/core/scopeadmin.py`. Technician POST/GET/DELETE → **403** before
  the payload is read; anonymous → **401**.
- **Row 20 — audited scope changes closed:** missing/blank `reason` → **400** with no row
  written; `scope_typed_columns` pairing and `valid_from/valid_to` window validated before save
  (a bad payload can never surface as the DB CHECK's IntegrityError 500); every grant/revoke
  emits `scope_grant` / `scope_revoke` with actor, target user, scope and reason — and
  `UserAccessScopeAdmin.save_model`/`delete_model`/`delete_queryset` now emit the same events, so
  the Django-admin path is audited too (gap §3.1 last bullet).
- Verified: local `ruff check` + `format --check` clean (152 files), local suite **189 passed + 1
  skipped + 60 subtests** (sqlite; race test skips); server suite **190 passed + 60 subtests,
  50.6 s, exit 0** with `SCOPE_ENFORCEMENT_ENABLED=1`; `tests/test_scopes.py` 35 → **38 tests**
  (+1 in `apps/core/test_scope_rbac_admin.py` for the admin-path audit); gunicorn restarted.
  **Live replay through nginx with temporary accounts: 20/20 expectations** — 403 technician,
  401 anonymous, 400 no-reason and SITE-without-site (0 rows, 0 audit events written), 201 grant
  with `created_by` = acting admin + exactly one `scope_grant`, 204 revoke + exactly one
  `scope_revoke`, then **zero leftover** users/scope rows/audit rows (marker search clean).
- **Gap report re-baselined** (2026-10-16): `docs/new/ITAM_Gap_Analysis_Report_v1.0.md` annotated
  with what is finished — workstreams 2 (scope RBAC) and 6 (attachments) ✅, 7 and 13 partial,
  §3.1 5-of-6 rows closed (org hierarchy still open), §3.4 attachments and §3.8 doc hygiene marked
  shipped, §2 API/OpenAPI/reports/tests rows refreshed (125 → **190** tests), §4/§5 progress notes
  (Scenario A remaining ≈ **14–31 pw**; approval engine = next in sequence). Estimates were **not**
  re-derived — only status was added. *Finding while writing it:* `/api/v1/schema/` and
  `/api/v1/docs/` answer **200 anonymously** on `:80` (drf-spectacular default
  `SERVE_PERMISSIONS = AllowAny`, `SERVE_PUBLIC = True`) although `DEVELOPMENT.md` §10/§18
  documents both as *admin-only UI* — documented-vs-actual mismatch recorded in the report's §3.5
  row; gating it is an open decision.

### 2026-10-16 (session 6 — second drop: attachments, transfer writes, approval API)
- **Attachments module** (gap §3.4 → new app `apps/attachments`): `Attachment` model with typed
  owner FKs + DB CHECK `attachment_exactly_one_owner` (exactly one of asset/request/transfer),
  private storage (`PRIVATE_MEDIA_ROOT` env setting, `base_url=None` → Django refuses to build a
  URL, so nothing can serve the dir), extension/size validation (25 MB, whitelist),
  `attachment_exactly_one_owner` migration `attachments.0001_initial`. API:
  `GET/POST /api/v1/attachments/` (scope-filtered list, technician+ upload — requester allowed on
  own request) + `GET /api/v1/attachments/{id}/download/` → **IDOR row 23 green** (foreign token →
  404, union rule for transfer cargo, §4.4 self-view reaches their own asset's file). The canary
  test was retired for the real assertions; 9 module tests in `apps/attachments/tests.py`.
- **Transfer write endpoints** (closing “transfer create/edit = admin UI only”): service
  `create_transfer` / `edit_transfer` (technician+, PENDING-only, assets must sit at `from_site`
  and be AVAILABLE) + `POST /api/v1/transfers/` and `PATCH /api/v1/transfers/{id}/` (no PUT/DELETE):
  forged `from_site`/cargo → 403, same site twice → 400, wrong role → 403, receiver-side edit → 403
  (sender-side mutation), dispatched record frozen → 409.
- **Approval over the wire** (row 22 second half): `GET /api/v1/requests/` (+ detail, site-scoped)
  and `POST /api/v1/requests/{id}/approve|reject/` (admin) — self-approval → **403** in the
  response body, non-admin → 403, out-of-scope admin → 404, decided → 409.
- **Real-thread concurrency test** (row 21 hardening): two live connections race `check_out` on
  Postgres via `transactional_db` + barrier — exactly one active assignment. Skips on sqlite
  locally (server runs it; 186 = 185 + this test).
- Business decisions recorded: transfer visibility **stays union** (receiver sees incoming cargo
  before receipt; edits sender-side — D-transfer), attachments cover assets/requests/transfers,
  approval surface is API-only.
- Verified: local `ruff check` + `format --check` clean, suite **185 passed + 1 skipped**
  (sqlite; race test skips by design); server suite **186 passed + 60 subtests, exit 0** with
  `SCOPE_ENFORCEMENT_ENABLED=1`; migrations `makemigrations --check` clean, `attachments.0001`
  applied; gunicorn restarted; anonymous live checks `/api/v1/{attachments,transfers,requests}/`
  → 401. **Live authenticated self-view**: temporary zero-scope employee (own Person link) logged
  in on the live server — `/me/` 200 with own assignment only, own asset detail 200, foreign
  detail 404, list own-rows-only — then the account/person/assets/assignment/audit rows were
  removed again.

### 2026-10-16 (session 5)
- IDOR rows 15 / 22 / 23 closed out (design §6 — the last open items from session 4):
  - **Row 15 — employee self-view (§4.4):** `Person.user` OneToOne
    (`apps/people/models.py`, migration `people.0003_person_user`) + login auto-link
    (`apps/accounts/personlink.py`: `ldap_uid` first, else a unique active email; ambiguous →
    no link, link failure never blocks login); scope carve-out in `apps/core/scopes.py`
    (`linked_person` / `self_view_q` / `_self_view_allows`, active **only** when the scope set is
    empty) wired into `scope_queryset` + `check_scope`; new `/me/` page (`assets.SelfView`,
    `templates/assets/self_view.html`, "My assets" nav entry) showing own assignments + own
    requests. Zero-scope user without a linked Person still gets nothing (row 14 unchanged).
  - **Row 22 — self-approval:** `services.decide_request` now raises `SelfApprovalForbidden`
    (subclass of `NotAuthorized` → 403) when the requester tries to approve *or* reject their
    own request; another admin can still decide it.
  - **Row 23 — attachments:** module still absent (gap §3.4); held by the canary
    `test_attachment_download_route_absent_until_scope_guarded`, which fails the moment an
    attachment-download route appears until the real row-23 test lands with it.
    *(Superseded by session 6 below: the module shipped and the canary was retired for the real
    row-23 tests.)*
- `tests/test_scopes.py` 27 → **31 tests**; full suite **173 passed + 56 subtests, exit 0** on
  `itasset-dev` with `SCOPE_ENFORCEMENT_ENABLED=1`; migration applied, gunicorn restarted,
  live checks `/me/` 302 → login, `/assets/` 302, `/api/v1/assets/` 401
- Still open: transfer create/edit endpoints (admin UI only), `to_site` cargo visibility rule
  (business confirm), IDOR rows 17/20 (no scope-write endpoint; covered by unit tests)

### 2026-10-15 (session 4)
- Reviewed 2 new ITAM specifications; produced gap analysis + vocabulary + RBAC design docs
- Unified Django admin chrome with main app topbar (templates/admin/base_site.html,
  app_index.html) — admin now shares the View Site navigation
- RBAC Stage A implemented and deployed to the server in two drops (migrate + gunicorn restart);
  backfill applied (2 GLOBAL scopes); verified live at /admin/core/useraccessscope/
- RBAC Stage B + C: shadow logging + enforcement wiring + scope_shadow_report + 20 IDOR/shadow
  tests; then Stage D (ScopedAdminMixin admin scoping, IDOR rows 12/13 green) + ittech site
  scopes + live enforcement flip (.env flag=1). Full suite **164 passed + 56 subtests, exit 0**
  with enforcement on; feature-test fixtures granted GLOBAL scope (scope behaviour is tested
  only in tests/test_scopes.py — 27 tests). Transfer dispatch/receive API
  (`/api/v1/transfers/{id}/dispatch|receive/`, scope-gated: sender = from_site + cargo,
  receiver = to_site) + active-assignment concurrency backstop: partial unique index
  `uniq_active_assignment_per_asset` (assets.0004) with IntegrityError → AssetAlreadyAssigned
  conversion. Full suite **169 passed + 56 subtests, exit 0** with enforcement on

### 2026-10-12 (session 3)
- Added category schema design doc (docs/category-schema-design.md)
- Reviewed progress: M2 service layer complete
- Next: CRUD views

### 2026-10-11 (session 2)
- Service layer written and tested
- 28 tests passing
- Runtime wiring on dev server

### 2026-10-10 (session 1)
- M1 foundation complete
- First smoke tests

---

## Blockers

Decisions required before spec-alignment work can start (owners needed):

1. Status/condition vocabulary sign-off — D1–D9 in the vocabulary doc
2. Org hierarchy: single-company vs multi-company (Spec A §18#1 → D-org in RBAC design)
3. Spec-field storage: typed value tables vs current JSONB hybrid → ADR 0005 (pending)
4. Direction decision: evolve Django (Scenario A) vs rewrite (Scenario B) — gap report §4

---

## Notes

- Dev server runs gunicorn/nginx as systemd units (`itasset-gunicorn`) — not tied to SSH session
- Attachments live in `~/itasset/private_attachments` (mode 700) — **outside** `media/`, served
  only through `/api/v1/attachments/{id}/download/`; include it in backups next to the DB
- Docker containers have restart unless-stopped policy
- pytest-django truncates DB between tests — no cross-test instance caching
- **Running tests:** repo DB lives on the dev server. Run via
  `ssh itasset-dev 'cd ~/itasset && .venv/bin/pytest -q'`. A local run needs a local PostgreSQL
  on 127.0.0.1:5432 (default in base.py; workstation has no `.env` and no Docker) and will
  otherwise fail with connection errors — or override the backend with
  `DATABASE_URL=sqlite:///test_local.db .venv/Scripts/python.exe -m pytest -q` — final state
  2026-10-16: **185 passed + 1 skipped** (the Postgres-only real-thread race skips on sqlite) vs
  **186 passed + 60 subtests** on the server, which runs it)

---

**End of Document**
