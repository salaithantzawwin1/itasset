# IT Asset Management System
# Gap Analysis — Specification vs Current Django Codebase

**Version:** 1.0
**Date:** 2026-10-15 · **last updated 2026-10-16** (progress re-baseline)
**Status:** For review
**Sources compared:**
- Spec A — `IT_Asset_Management_Technical_Specification_v1.0.md` (rewrite proposal: React/NestJS/Prisma)
- Spec B — `ITAM_Common_Asset_Fields_Category_Specific_Specifications_Master.md` (common + category-specific fields)
- Baseline — current Django codebase in this repository (last verified 2026-10-16: full test suite **204 passed + 64 subtests**, `SCOPE_ENFORCEMENT_ENABLED=1`, exit 0 on `itasset-dev`; 203 passed + 1 skip on sqlite)

**Companion document:** `ITAM_Status_Condition_Vocabulary_Master_v1.0.md` (status/condition vocabulary reconciliation).

**Progress re-baseline (2026-10-16).** Items marked ✅ below are already shipped: **workstream 2
(scope RBAC)**, **workstream 6 (attachments)**, the MVP slice of **4** (approval engine: rules,
thresholds, ordered steps, immutable decisions), slices of **7** (concurrency) and **13** (IDOR
security tests), and §3.8 doc hygiene. The §4 effort figures are still the original 2026-10-15
estimates — they have **not** been re-estimated; the partial slices of rows 4 and 7 are deliberately
not deducted from them. Evidence:
`docs/itasset-docs/docs/PROGRESS.md` (sessions 1–12) and `docs/new/ITAM_Scope_RBAC_Design_v1.0.md` §6.

---

## 1. Executive Summary

The current Django system already implements a meaningful portion of both specifications: the
asset register with category-specific fields, a guarded lifecycle state machine, request → approve →
procure → receive flow, transfers, repair/write-off/disposal with two-person verification, physical
audit sessions, license/contract/warranty tracking, QR labels, CSV import with dry-run, scoped CSV
reports, email alerts, EN/MM localization, and LDAP/AD login with group-to-role sync.

The largest gaps are structural, not cosmetic:

1. ~~**No scope-based authorization.**~~ ✅ **closed 2026-10-16.** `UserAccessScope` +
   deny-by-default now enforced on views, API, exports and Django admin behind
   `SCOPE_ENFORCEMENT_ENABLED=1` (live on the LAN server since 2026-10-15), plus the employee
   self-view carve-out and an audited, reason-required scope-administration endpoint. All 23 rows
   of the design §6 IDOR suite pass. *Still open from Spec A §5.1:* the Group/Company/Branch
   **hierarchy** itself (workstream 3) — `Site`/`Department` remain the only org units.
2. ~~**No multi-step approval engine.**~~ ⚠️ **MVP shipped 2026-10-16 (session 8).**
   `ApprovalRule` templates (category/site scope, quantity and amount thresholds, `required_role`,
   ordered `step`) drive a step-by-step chain with immutable `ApprovalDecision` events,
   self-approval blocked (**403**), and segregation of duties (one person may not cover two
   steps). *Still open vs Spec A §6.6:* delegation, escalation, timeout, parallel steps.
3. ~~**No attachments/documents module.**~~ ✅ **closed 2026-10-16** (`apps/attachments`: private
   storage, randomized keys, scope-checked upload/download, type/size validation). *Still open:*
   checksum, malware scanning, backup wiring (Spec A §6.13, Spec B §2.2).
4. **Concurrency control** ⚠️ **partial (2026-10-16).** Shipped: partial unique index
   `uniq_active_assignment_per_asset` + IntegrityError→`AssetAlreadyAssigned` conversion + a
   real-thread Postgres race test, so acceptance A §14.2 #5 now passes. *Still absent:* version
   column, row locks, idempotency keys, correlation IDs (Spec A §7.3, §10.1).
5. **Spec-field storage conflicts with the accepted ADR.** Spec B recommends typed definition/value
   tables; ADR 0004 accepted JSONB + promoted columns and rejected EAV (decision needed).
6. **Status/condition vocabularies disagree across all three sources** — see companion vocabulary
   document.

**Estimated effort (Scenario A — evolve Django, team of 2–3):** ≈ **23–37 person-weeks**
(≈ **4–5 months** calendar; a scope-RBAC + approval + attachments MVP core is ≈ 10–14 person-weeks
≈ 6–8 weeks). **Scenario B — full rewrite per Spec A:** the spec's own estimate is **13–24 weeks**
calendar for a 4–5 person team (≈ 60–100+ person-weeks) plus Django extraction and reconciliation,
on top of the discovery the spec itself says must come first.

**Recommendation:** treat both specs as the *requirements baseline* and evolve the Django system
unless there is an independent, business-driven reason to change stack. Spec A itself warns:
*"Do not migrate merely for novelty"* (§3) and *"Do not begin with a full production rewrite based
only on this document"* (§20).

---

## 2. What Already Exists (spec area → current implementation)

| Spec area | Spec ref | Current implementation | Status |
|---|---|---|---|
| Asset register, unique tag, indexed serial | A §6.3 | `Asset` model: unique `asset_tag`, indexed non-unique `serial_no`, category FK | ✅ |
| Controlled vocabularies (status/condition) | A §6.3 | `Asset.Status` / `Asset.Condition` TextChoices | ⚠️ vocab conflict (companion doc) |
| Category-specific fields | B §4 | Hybrid model: `Category.schema` (declarative JSON) + `Asset.attrs` (JSONB) + promoted columns — ADR 0004 | ⚠️ design decision vs Spec B |
| Lifecycle state machine, server-side transitions | A §7.3 | `apps/assets/services.py` — check_out/check_in/handover/receive, guards, typed errors | ✅ |
| Request → approve flow | A §6.5 | `AssetRequest` (PENDING/APPROVED/REJECTED/PROCURED/FULFILLED/CANCELLED), `decide_request` through the approval chain (no rule ⇒ legacy single admin step), rejection reason; approve/reject + immutable trail over the wire (`POST .../approve/`, `.../reject/`, `GET .../approvals/`) | ✅ engine MVP 2026-10-16; delegation/escalation/timeout still open |
| Assignment history, one active per asset | A §6.7 | `Assignment` append-only, `in_at IS NULL` = active; condition_out/in | ✅ race-protected 2026-10-16: partial unique index + real-thread race test |
| Site transfer with transit + exception | A §6.8 | `Transfer` (PENDING/IN_TRANSIT/RECEIVED/EXCEPTION), bulk, damage discrepancy → IN_REPAIR | ✅ (site-level, not company) |
| Repair tracking, RMA, cost | A §6.10 | `RepairTicket` (fault, vendor, RMA, cost, outcome) | ⚠️ no preventive maintenance / cost thresholds |
| Retirement, write-off, sanitization evidence | A §8.5 | `WriteOff` (police report, decide step), `DisposalRecord` (NIST methods, cert no., second-person verify) | ✅ stronger than spec baseline |
| Warranty/contract tracking | A §6.11 | `Contract` + vendor, expiry queries & API, email alerts | ✅ |
| License register | A §6.11 | `SoftwareLicense` + `LicenseKey` | ✅ (verify secret handling) |
| Physical audit | A §6.12 | `AuditSession` / `AuditItem` + audit views | ✅ |
| Audit trail | A §9.1 | `ActivityLog` append-only, 24-month retention task; `scope_grant`/`scope_revoke` events since 2026-10-16 | ⚠️ no correlation/request IDs |
| Email notifications | A §6.14 | Celery tasks + `EmailAlert` dedup ledger: warranty/contract/license alerts; **2026-10-17 am: daily digest (`ADMIN_EMAIL` → admins), monthly data-quality report → IT lead, scheduled §4 report exports with CSV attachments (weekly → IT lead; monthly per-site → `Site.lead_email`); 2026-10-17 pm: the last §14 email rows — request-awaiting-approval heads-ups inline per approval step (role **+ scope** recipients, dedupe (request, step)), loan overdue via new `scan_loans` (due + 3 days → holder + issuing technician), damage-reported and transfer-exception alerts fired in-band at the service call (best-effort: SMTP failure logs, never fails the action; one alert per event)** | ⚠️ only the Telegram system-error webhook + in-app/workflow notifications remain open |
| Reports + exports | A §6.14 | `apps/reports` queries, CSV exporters, views | ✅ caller-scope enforced since 2026-10-15 (design §6 rows 8/9) |
| CSV import with dry-run | A §13 | `import_assets_csv` + `manage.py import_csv` (dry-run default) | ⚠️ assets only, no job/exception ledger |
| QR/barcode labels | A §6.3 | `apps/labels` | ✅ |
| API | A §10 | `/api/v1/` DRF: asset CRUD, scan, scanner token, warranty/contract expiring, requests (list/detail/approve/reject), transfers (create/edit), attachments (list/upload/download), scope admin, export jobs (create/list/download — §3.5); OpenAPI at `/api/v1/schema` + `/api/v1/docs` | ⚠️ **shipped 2026-10-17:** export jobs (`POST/GET /api/v1/exports/`, `GET /api/v1/exports/{id}/download/` — shared `run_report` scope gate, private-storage files, owner-scoped 404s, newest 20 per user) alongside `/api/v1/me` (identity + roles + effective scopes), org sites tree, correlation ids and the consistent error envelope |
| Authentication AD/LDAP | A §11 | `RoleMappingLDAPBackend` (group→role sync, M5), LDAPS/StartTLS settings, local ModelBackend fallback as break-glass | ⚠️ no OIDC/SAML, no break-glass alerting |
| Localization (EN/MM) | A §15 | Session-language `{% t %}` tag, i18n dictionary | ✅ |
| Dashboard | A §6.14 | `apps/dashboard` | ✅ |
| Health check, ops scaffold | A §16 | `/healthz`, systemd units, nginx, compose, bootstrap script; LAN deployment live at `http://192.168.100.142` (nginx → gunicorn, verified 2026-10-16) | ⚠️ no restore test/runbooks in repo |
| Tests | A §14 | 204 tests + 64 subtests (smoke, services, lifecycle, CRUD, API, labels, audit, accounts, **scope/IDOR suite, attachments, concurrency, approval engine**) | ⚠️ no perf tests (IDOR/security rows now covered) |

---

## 3. Gap Detail (missing → spec ref → impact)

### 3.1 Authorization and organization (highest impact)

**Status 2026-10-16: 5 of 6 rows closed** (Stages A–D shipped, enforcement live). Only the org
hierarchy remains → workstream 3.

| Gap | Spec ref | Notes |
|---|---|---|
| Group → Company → Branch → Department/Location hierarchy | A §5.1, §9.1 | Only `Site` + `Department` + `Person` exist. No company concept anywhere. **Still open (workstream 3).** |
| Record-scope model (`user_access_scopes`, valid_from/to) | A §5.2, §9.1 | ✅ **Shipped** — `apps.core.UserAccessScope` (typed FKs + DB CHECK, validity window) + deny-by-default helpers. |
| Deny-by-default reads | A §5.3 | ✅ **Shipped** — the old "reads open to any authenticated user" rule is gone; flag-aware `check_scope` / `scope_list` on views, API, exports; Stage C live since 2026-10-15. |
| Object-level enforcement on list/detail/export/attachment endpoints | A §5.3 | ✅ **Shipped** — including attachments and Django admin (404, not a redirect, for out-of-scope change URLs). |
| IDOR / cross-scope test suite | A §14.2 (#1, #2, #13) | ✅ **Shipped** — design §6: all 23 rows have endpoint-level tests (rows 17/20 closed 2026-10-16). |
| Audit + reason for privileged scope changes | A §5.3 | ✅ **Shipped** — `POST` / `DELETE` on `/api/v1/users/{id}/scopes/`: admin-only (403), reason required (400, no row), `scope_grant`/`scope_revoke` from API **and** Django admin. |

**Impact:** ✅ the specs' central success criterion ("No user can read or modify records outside
their authorized scope through UI, API, exports, or direct object IDs") is now met and regression-
tested for the 23 IDOR rows — except for the org hierarchy (workstream 3), which still limits the
scope vocabulary to site/department/GLOBAL. This workstream also unblocks Spec B §9.4 tenancy
scoping.

### 3.2 Workflow and approvals

**Status 2026-10-17: MVP + delegation shipped (sessions 8, 14)** — templates, thresholds,
ordered steps, immutable decisions and now **delegation** are live; escalation/timeout, the
extra request states and inspection routing remain open.

| Gap | Spec ref | Notes |
|---|---|---|
| Approval templates (by company/type/threshold/department) | A §6.6 | ✅ **Shipped 2026-10-16** — `ApprovalRule` (category/site scope, `min_quantity`/`min_amount`, `required_role`, ordered `step`), admin-role-only + audited in Django admin; no matching rule ⇒ the legacy single admin step, so behaviour is unchanged until rules are configured. |
| Sequential/parallel steps, delegation, escalation, timeout | A §6.6 | ⚠️ **Partial (2026-10-17)**: sequential steps shipped (ordered chain, per-step role gate, intermediate approvals stay PENDING, one person may not cover two steps → 403, rejection final at any step) **and delegation** (`ApprovalDelegation`: admin-managed, windowed, active flag; the delegator must hold the role so a delegation never widens authority; decisions record `delegated_from` in the trail + ActivityLog; segregation counts *principals* — one human never covers two steps directly or by proxy; self-approval by proxy → 403). The approve/reject endpoints now authorize in the **service** (per-step role + delegation) instead of a blanket admin gate, so configured technician steps work over the wire. **Still absent:** parallel steps, escalation, timeout. |
| Immutable approval decisions as events | A §6.6 | ✅ **Shipped 2026-10-16** — `ApprovalDecision` append-only (`save()` refuses updates; DB unique per request+step) and readable at `GET /api/v1/requests/{id}/approvals/` alongside the chain; the status row stays the workflow projection. |
| Self-approve prohibition | A §6.5 | ✅ **Enforced 2026-10-16** — `SelfApprovalForbidden` → 403 in the service and over `POST /api/v1/requests/{id}/approve/` (and `.../reject/`); another admin may still decide it. |
| Request states SUBMITTED/IN_REVIEW/CLOSED | A §7.2 | Current set lacks them (see companion vocab doc). |
| Receive/inspection routing after return (AVAILABLE vs UNDER_INSPECTION vs IN_MAINTENANCE) | A §8.2 | Today: DAMAGED → IN_REPAIR, otherwise back to previous flow; no inspection state. |

### 3.3 Data model

| Gap | Spec ref | Notes |
|---|---|---|
| UUID primary keys | A §9 | BigAutoField everywhere; matters only if Scenario B. |
| `version` + optimistic concurrency / row locks | A §7.3, §10.1 | ⚠️ **Partial (2026-10-16)**: the double-checkout race is closed by the partial unique index `uniq_active_assignment_per_asset` + IntegrityError→`AssetAlreadyAssigned` + a real-thread test (A §14.2 #5 passes). **Still missing:** version column, row locks, idempotency keys, correlation IDs. |
| `currency` on Asset (cost is bare NUMERIC) | A §6.3, B §3.4 | `Contract` has currency; `Asset.cost` does not. |
| `warranty_start`, purchase reference/PO on asset | A §6.3 | Only `warranty_end` + `purchase_date` exist. |
| `created_by` / `updated_by` | A §9.1, B §3.5 | Absent on all models (actor is only in ActivityLog). |
| `legacy_source` + `legacy_id` (unique pair) | A §9.1 | Needed for Scenario B migration; cheap to add either way. |
| company/branch/location FKs, cost_center, criticality | B §3.2 | Absent (site only). |
| Non-serialized stock + movements | A §6.9 | No `stock_items`/`stock_movements`; request `quantity` is the only counter. |
| `asset_events` (typed, JSONB details, correlation ID) | A §9.1 | ActivityLog is generic action logging, not per-asset event stream. |
| Status history table | B §2.2 (`asset_status_history`) | Only current status + ActivityLog actions. |
| Soft-delete/activation policy on master data | A §9.2 | `Site.is_active` exists; categories/vendors lack explicit deactivation rules. |

### 3.4 Attachments and documents — ✅ shipped 2026-10-16

`apps/attachments` adds the project's first file-storage models: `Attachment` with typed owner FKs
(asset / request / transfer) + DB CHECK `attachment_exactly_one_owner`, **private storage**
(`PRIVATE_MEDIA_ROOT`, `base_url=None` so Django itself refuses to build a URL), **randomized
keys** (`attachments/{uuid4}.{ext}` — the client's filename never touches disk), **type/size
validation** (extension whitelist, 25 MB cap) and **entity-level download authorization** through
the owning record's scope. API: `GET|POST /api/v1/attachments/` + `GET .../{id}/download/`
(IDOR row 23 green).

**Still open vs the original gap list:** checksum, malware scanning, dedicated upload/download
audit events, and backup-with-DB wiring (workstream 12). `DisposalRecord.certificate_no` and repair
evidence remain text-only — the module makes those files possible but the disposal/repair flows do
not attach anything yet.

> *Original gap statement (2026-10-15): no `FileField`/`ImageField`/`upload_to` anywhere in the
> project; gap included private storage, randomized keys, entity-level download authorization,
> checksum, type/size validation, malware scanning, upload/download audit, backup with DB.*

### 3.5 API surface and hardening

| Gap | Spec ref | Notes |
|---|---|---|
| `/api/v1/me`, org endpoints, request/approval/transfer commands, attachment endpoints, export jobs | A §10.2–10.8 | ⚠️ **Partial 2026-10-16**: requests (list/detail/approve/reject), transfers (create/edit), attachments (list/upload/download) and scope admin are live, plus the HTML `/me/` self-view page. **Shipped 2026-10-17:** export jobs — `POST /api/v1/exports/ {report, format, site?}` → `201 {id, report, format, status, row_count, site, created_at, download}` (same `run_report` scope gate as the HTML reports: `400` unknown report/unsupported format, `403` scope, both with `code` + `correlationId`), `GET /api/v1/exports/` (owner list; admins see all), `GET /api/v1/exports/{id}/download/` (private file, owner-scoped `404`, `Content-Disposition: attachment`; newest 20 jobs per user kept, failed rows recorded for ops). Also `GET /api/v1/me/` (identity, roles, effective scopes) and `GET /api/v1/org/sites/` (sites + departments reference tree — the *scoped* org model waits on the hierarchy decision, workstream 3). **Fixed:** `POST /api/v1/assets/` was a live 500 (category/site were read-only → NOT NULL violation) — it now accepts `category_id`/`site_id` and is covered by tests. |
| OpenAPI/Swagger contract | A §3 | ✅ **Configured** — drf-spectacular: `/api/v1/schema` + `/api/v1/docs`, `make openapi`. ⚠️ **but served anonymously** (drf-spectacular default `SERVE_PERMISSIONS = AllowAny`, `SERVE_PUBLIC = True`; verified 2026-10-16: both URLs answer **200** with no cookie on `:80`), ✅ **gated 2026-10-17** — `SPECTACULAR_SETTINGS.SERVE_PERMISSIONS = [apps.api.permissions.IsAdmin]` + `SERVE_PUBLIC = False`: anonymous → 401/403, authenticated non-admin → 403, admin → 200 (pinned by `tests/test_security_hardening.py`); `DEVELOPMENT.md` §10/§18 now matches reality. |
| Idempotency-Key, ETag/If-Match, correlation ID in responses | A §10.1 | ✅ **partly shipped 2026-10-17**: `Idempotency-Key` replay protection on every `/api/v1/` write (per-user keys; replay → stored response + `Idempotency-Replayed: true`; key misuse or an in-flight duplicate → 409) plus an optimistic `version` field on assets (stale write → **409**, every lifecycle service bumps it) — the version field supersedes ETag/If-Match. Correlation ID shipped the same day (see the envelope row). |
| Consistent error envelope (`code`, `correlationId`) | A §10.9 | ✅ **shipped 2026-10-17** — DRF errors go through `apps/api/exceptions.py` (adds `code` + `correlationId` to detail-style bodies; field-error maps untouched) and the hand-written `_error()` responses carry the same fields; `X-Correlation-ID` is echoed or minted by `CorrelationMiddleware` on every response, so a user-reported id joins to the server log. |
| Sort/filter allowlists | A §10.1 | ✅ **shipped 2026-10-17** — filters are fixed query params by construction (`site`, `status`, `q`) and `?ordering=` on the asset list is a policy allowlist: an unknown field → **400** naming the offender *and* the allowed fields (never silently ignored, never fed to `order_by`); transfers/requests expose no ordering param at all. |
| Rate limiting / brute-force controls | A §11.3 | ✅ **shipped 2026-10-17** — per-IP `LoginThrottleMiddleware` counts *failed* credential POSTs to `/accounts/login/`, `/admin/login/` and `/api/v1/auth/token/` (default 10 / 5 min, `LOGIN_THROTTLE_*` env); over the cap → **429 + `Retry-After`**, a success resets the budget, cache outage fails open. prod points `CACHES` at Redis so every gunicorn worker shares one counter. |
| Security headers (CSP etc.) | A §11.3 | ✅ **shipped 2026-10-17** — `SecurityHeadersMiddleware` sets a same-origin CSP on every HTML response (admin/swagger/static/QR are all same-origin; `unsafe-inline` kept because the Django admin requires it), plus Django's `X-Content-Type-Options: nosniff`, `Referrer-Policy: same-origin`, `X-Frame-Options: DENY`. |

### 3.6 Authentication

LDAP/AD with group→role sync and a local fallback exists (Spec A §11.1 direct-LDAP path, StartTLS
on). ✅ **shipped 2026-10-17**: every login success/failure is audited to `ActivityLog` (username
and IP, never the password), and when LDAP is the normal path a local-backend sign-in is treated
as break-glass — it emails the IT lead (`templates/email/breakglass_login.txt`) while still
completing the login; rate limiting on all three credential paths landedthe same day (§3.5). ✅ **2026-10-17 addendum:** the disabled-account session revocation window is
closed — Django's backend already refuses inactive users at authentication time (next request
anonymous), DRF refuses their tokens, and `ActiveUserMiddleware` now flushes the orphaned session
row too. **2026-10-17 addendum 2:** the documented break-glass procedure with reason/incident
capture ships as `docs/runbooks/break-glass.md` — 7 steps + an evidence map splitting the
automatic half (ActivityLog `login` event + IT-lead alert) from the operator half (reason/
incident entry, credential rotation); prod runs `LDAP_ENABLED=0`, so the alert path is dormant
by design. Missing vs spec: OIDC/SAML federation preference only.

### 3.7 Migration, import, ops (Scenario B–critical)

Spec A §13 phases A–E (discovery, mapping, rehearsal, pilot, cutover), `import_jobs`,
`migration_exceptions`, reconciliation checklist, rollback plan — none exist as tooling. For
Scenario A the relevant subset is: extend `import_assets_csv` to all entities with per-category
templates, row-level error preview, and a migration-exception ledger. **2026-10-17:** the backup
tooling and runbooks now exist (`deploy/backup.sh` + `make backup` with 14-copy retention,
`docs/runbooks/backup-restore.md` incl. restore procedure + drill checklist,
`docs/runbooks/incidents.md`) — still owed: the restore **drill evidence** on the host and
monitoring (§16).

### 3.8 Documentation hygiene — ✅ closed 2026-10-16

`docs/itasset-docs/docs/PROGRESS.md` was reconciled: the milestone table now shows M1–M7 ✅ and M8
current ("deployment up, DR/monitoring pending"), and the session log runs through session 14
(scope RBAC, attachments, rows 17/20, the `192.168.100.142:80` deployment, the security pass,
workstream 7, API identity/observability, ops tooling, org/ordering/break-glass, the Monday
deploy checklist, probe script + approval delegation). No further action —
reviewers can rely on it.

---

## 4. Effort Estimates

Assumptions: team of **2–3 developers** already familiar with this repo; business stakeholders
available for decision sign-off; no unrelated in-flight projects. Person-weeks (pw) ≈ one person
for one week. Calendar assumes 2–3 people working in parallel on separable workstreams.

### Scenario A — Evolve the Django system (specs as requirements)

| # | Workstream | Scope summary | Person-weeks |
|---|---|---|---:|
| 1 | Decision/policy pack | Vocab sign-off, org structure, tag policy, approval matrix, retention | 1–2 |
| 2 | Scope-based RBAC | Scope model + deny-by-default enforcement across views/API/exports + IDOR tests — **✅ done 2026-10-16** (hierarchy half → row 3) | 4–6 |
| 3 | Organization hierarchy | Group/Company/Branch (or mapped Site model) + admin CRUD + data migration | 2–3 |
| 4 | Approval engine | Templates, thresholds, multi-step, delegation, immutable decisions — **partly done 2026-10-17**: templates/thresholds/ordered steps/immutable events (10-16); **delegation** shipped (10-17: `ApprovalDelegation`, windowed + audited, principal-based segregation, `delegated_from` evidence); escalation/timeout open | 3–4 |
| 5 | Spec-field model decision + build | ADR 0005 (typed vs JSONB hybrid), then implement + migrate specs data | 3–5 |
| 6 | Attachments module | Private storage, authz download, validation, audit, backup wiring — **✅ done 2026-10-16** (backup wiring → row 12) | 2–3 |
| 7 | Concurrency + API hardening | version/locks/partial unique, 409s, idempotency, OpenAPI, endpoint expansion — **✅ done 2026-10-17**: partial unique index, wrong-state/frozen 409s, OpenAPI, endpoint expansion (10-16); optimistic version lock, Idempotency-Key replay protection, asset-create fix (10-17) | 2–3 |
| 8 | Status/condition migration | Vocabulary adoption (choices, services, templates, reports, seed, tests) | 1–2 |
| 9 | Stock/inventory (optional per A §18#11) | Stock items + movements + negative-stock guard | 1–2 |
| 10 | Import jobs + exceptions | All-entity import, per-category templates, ledger, previews | 1–2 |
| 11 | Security hardening | Break-glass alerting, rate limit, headers/CSP, dependency scanning — **✅ done 2026-10-17**: alerting, rate limits, headers/CSP **and** dependency scanning (`make audit-deps` via pip-audit — clean first run) | 1–2 |
| 12 | Ops: backup/restore + runbooks | Tested restore, monitoring, incident runbooks (A §12.3, §16) | 1–2 |
| 13 | Test/UAT hardening | Security tests (IDOR/CSRF/upload), migration tests, perf pass — **partly done 2026-10-17**: the 23-row IDOR/security suite (10-16); a real-CSRF enforcement test and the `makemigrations --check` deploy guard (10-17; upload limits already pinned by the attachments module); perf pass open | 2–3 |
| | **Total** | | **23–37 pw** |

- Calendar at 2–3 people: ≈ **4–5 months** full scope; ordering by risk puts RBAC + approval +
  attachments first.
- **MVP core** (rows 1, 2, 3, 4, 6, 8): ≈ **10–14 pw** ≈ **6–8 weeks** calendar at 2 people.
- **Progress 2026-10-16:** 2 of the 6 MVP rows are fully shipped (row 2 scope RBAC ✅, row 6
  attachments ✅) and row 4's MVP slice (rules + thresholds + ordered steps + immutable events)
  landed the same day → MVP remaining = rows 1, 3, 8 plus the delegation/escalation half of row 4.
  Scenario A total remaining ≈ **14–31 pw** (23–37 minus the 6–9 pw of rows 2 + 6; the partial
  slices of rows 4 and 7 are deliberately not deducted).
- Row 5 (spec model) depends on the ADR decision; a "keep JSONB hybrid + tighten validation" path
  lands at the low end (3 pw), typed-value rebuild at the high end (5 pw).

### Scenario B — Rewrite per Spec A (React/NestJS/Prisma)

| Phase | Spec estimate | Notes |
|---|---|---|
| Discovery pack + policy pack | 1–2 wk | Spec A §19 #1–2 — mandatory before any build |
| Architecture + prototype | 2–3 wk | |
| Core platform + master data | 3–5 wk | Org, identity, scope, asset register |
| Lifecycle + workflows | 3–5 wk | Request/approval/issue/return/transfer/maintenance |
| Migration rehearsal + integrations | 2–4 wk | Django extraction, mapping workbook, reconciliation |
| UAT/security/pilot | 2–3 wk | |
| Cutover + stabilization | 1–2 wk | |
| **Calendar total** | **13–24 wk** | Spec A §17, at 4–5 FTE (backend, frontend, QA, lead, infra) |

- Implied effort ≈ **60–100+ person-weeks** — roughly **2–3× Scenario A**.
- Excludes re-implementing and re-testing the working, verified parts listed in §2 (state machine,
  tests, i18n, labels, reports) in a new language.
- Reuses nothing of this repository directly except as a behavior reference and data source.

### Decision framing

| Criterion | Scenario A (evolve Django) | Scenario B (rewrite) |
|---|---|---|
| Time to scoped-RBAC + approvals | ~6–8 weeks | ~6–9 months |
| Existing verified behavior/tests | Preserved (204 tests keep passing) | Rebuilt from spec text |
| Team skill fit | Current team (Python/Django) | Requires TS full-stack team |
| UI consistency with "View Site" | Already unified (admin = app chrome) | New design system to adopt |
| Spec A caveats | N/A | Spec explicitly forbids rewrite on this document alone |
| Long-term module boundaries | Django apps already mirror spec modules | Cleaner module walls, at cost above |

---

## 5. Recommended Sequence (Scenario A)

1. **Decisions** — sign off companion vocabulary document + Spec A §18 / Spec B §16 checklists
   (org structure, tag policy, approval thresholds, spec-storage ADR 0005). *(open)*
2. **Scope RBAC** — hierarchy + `user_access_scopes` + deny-by-default; IDOR test suite as gate.
   ✅ **done 2026-10-16** except the org hierarchy (→ step 1 / workstream 3).
3. **Approval engine** — templates/thresholds/steps; immutable decisions. ⚠️ **MVP shipped
   2026-10-16** (rules + thresholds + ordered steps + immutable events + segregation of duties);
   **delegation shipped 2026-10-17**, escalation/timeout open → sequence continues at
   step 6 / the import work.
4. **Attachments** — private storage with authorized downloads. ✅ **done 2026-10-16**
   (backup wiring still owed under step 8).
5. **Concurrency + API hardening** — partial unique active-assignment index, version field, 409s.
   ✅ **done 2026-10-17**: index + wrong-state 409s + OpenAPI + endpoint expansion (10-16);
   optimistic version lock + Idempotency-Key + asset-create fix (10-17).
6. **Spec-field model** per ADR 0005 outcome; migrate `Category.schema`/`Asset.attrs` if typed.
   *(open)*
7. **Imports/stock/notifications** as business priority dictates. *(open — every §14 **email** row shipped 2026-10-17 (scheduled exports, digest, data-quality, approval heads-ups, loan overdue, damage, transfer exception); in-app/workflow notifications and the Telegram webhook still open; imports untouched)*
8. **Ops + security pass** — restore test, break-glass alerting, headers, rate limits.
   ⚠️ **mostly shipped 2026-10-17**: headers/CSP, per-IP rate limits, admin-only OpenAPI,
   login audit + break-glass alerting, dependency scanning, backup script + both runbooks;
   the restore **drill** (evidence) and monitoring still open — both need the server.
9. Re-baseline this report and Spec A §18 decisions before any Scenario B reconsideration.
   *(this 2026-10-16 update is the first re-baseline; the full one follows step 8)*

---

## 6. Open Decisions (blocks sequencing)

- [ ] Org model: adopt Group/Company/Branch, or extend current `Site` to carry company/branch roles
- [ ] Spec storage: typed definition/value tables vs current JSONB hybrid (ADR 0005)
- [ ] Status/condition vocabulary sign-off (companion document)
- [ ] Stock/non-serialized inventory in release one? (Spec A §18#11)
- [ ] Licenses and secrets handling review (Spec B §5.15)
- [ ] RPO/RTO, retention, and backup target approval (Spec A §12.3)
- [ ] Scenario A vs B as the committed direction

---

## 7. Production Deploy Checklist — 192.168.100.142:80 (planned Monday 2026-10-19)

Recorded 2026-10-17: everything below is **local-only** until Monday — sessions 9–14
have not been copied to the server, and three migrations are pending. Tick in order; the
probes at the end are the acceptance gate (each row says what a pass looks like).
**One-shot:** `bash deploy/probe-production.sh http://192.168.100.142` asserts §7.3
phase 1 end-to-end; add `PROBE_USER=… PROBE_PASS=…` for the authenticated phase (me,
org, ordering, create-201, idempotent replay, stale-version 409, cleanup). It was
validated locally (28 ok / 0 failed against a dev server on 2026-10-17).

### 7.1 Pre-flight (laptop, before touching the server)

- [ ] `ruff check . && ruff format --check .` clean (was clean at 2026-10-17, 167 files)
- [ ] `pytest -q` green — was **244 passed + 1 skipped + 65 subtests** (sqlite)
- [ ] `manage.py makemigrations --check` exit 0 (also pinned by `tests/test_migrations_guard.py`)
- [ ] Diff review: sessions 9–14 touch `apps/core/{middleware,models,admin}.py`,
  `apps/accounts/{loginaudit,apps}.py`, `apps/api/{views,urls,serializers,exceptions}.py`,
  `apps/assets/{models,services,admin}.py`, `config/settings/{base,prod}.py`,
  `templates/email/breakglass_login.txt`, `Makefile`, `pyproject.toml`, `deploy/backup.sh`,
  `deploy/probe-production.sh`, `tests/*`, `docs/*`

### 7.2 Sync + migrate (server `ssh itasset-dev`, same flow as sessions 6–7)

- [ ] Sync the tree to `~/itasset` (source + `docs/` + `deploy/`; never `.env`, never
  `private_attachments/`, never `.venv/`)
- [ ] `manage.py makemigrations --check` on the server (catches sync gaps)
- [ ] Server test suite: `pytest -q` with `SCOPE_ENFORCEMENT_ENABLED=1` (was 190 at
  session 7 — expect 252+ now)
- [ ] `manage.py migrate` — **three pending migrations**: `assets.0006_asset_version`
  (adds `asset.version`, default 1), `core.0002_idempotencyrecord` (new table) and
  `assets.0007_…` (`ApprovalDecision.delegated_from` + `ApprovalDelegation`)
- [ ] `manage.py collectstatic --noinput` (no new static assets expected; run anyway)
- [ ] `systemctl --user restart itasset-gunicorn` **after** the last source write
- [ ] Env review in `~/itasset/.env`: no new keys are *required*. Optional:
  `LOGIN_THROTTLE_ATTEMPTS`/`LOGIN_THROTTLE_WINDOW` (defaults 10/300), `CACHE_URL`
  (prod defaults to `redis://127.0.0.1:6379/1` — Redis already listens on :6379;
  verify `…/.venv/bin/python -c "import redis; print(redis.Redis().ping())"`).
  `LDAP_ENABLED` stays 0 → the break-glass email path stays dormant by design.

### 7.3 Probes (acceptance gate — through nginx on :80)

- [ ] `/healthz` → `{"status":"ok","db":"ok"}`; `/` and `/admin/login/` → 200; a static
  asset → 200; unknown path → generic 404 (DEBUG off)
- [ ] `/api/v1/assets/`, `/api/v1/requests/`, `/api/v1/transfers/`, `/api/v1/me/` → **401** anonymous
- [ ] `/api/v1/schema/` and `/api/v1/docs/` → **401/403 anonymous** (was 200 before session 9)
- [ ] HTML login page carries `Content-Security-Policy` + `X-Content-Type-Options: nosniff`;
  every response carries `X-Correlation-ID`; a 404 body has `code` + `correlationId`
- [ ] Throttle: 11 bad POSTs to `/accounts/login/` (same IP) → **429** + `Retry-After: 300`;
  then wait/`redis-cli`-flush DB 1 or restart gunicorn to clear the test counter
- [ ] `POST /api/v1/assets/` with token + `category_id`/`site_id` → **201** (was a live 500);
  `GET /api/v1/me/` → identity + roles + scopes
- [ ] Stale-version `PATCH /api/v1/assets/{tag}/` → **409**; replay with the same
  `Idempotency-Key` → identical body + `Idempotency-Replayed: true`, one row created
- [ ] `POST /api/v1/auth/token/` for a deactivated user → **401** (and their session dies
  on the next request)
- [ ] `nginx -T | grep client_max_body_size` → `30m` (applied session 7; re-verify)

### 7.4 Ops extras (same day, closes more of step 8 on the host)

- [ ] First real backup: `bash ~/itasset/deploy/backup.sh` → dump + attachments archive in
  `~/itasset-backups`, then install the systemd timer from
  `docs/runbooks/backup-restore.md`
- [ ] Run the **restore drill** from that runbook against the fresh dump and tick its
  checklist (the evidence row is still empty)
- [ ] Optional: `make audit-deps` on the server (pip-audit — laptop run was clean)
- [ ] Optional monitoring: point Uptime Kuma (or cron+curl) at `/healthz`

### 7.5 Rollback

- [ ] Pre-deploy: `cp .env .env.bak-$(date +%F)` and keep the last known-good tree copy
  (pattern: `~/itasset.bak-20261014`)
- [ ] Bad deploy → restore tree, `migrate assets 0005 && migrate core 0001` (drops the new
  column/table — additive-only migrations, so reverse is safe), restart gunicorn
- [ ] Data doubt → restore per `docs/runbooks/backup-restore.md` (fresh DB, never in place)

---

**End of Document**
