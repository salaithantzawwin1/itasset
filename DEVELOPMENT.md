# IT Asset Manager — Development Guide

Multi-site IT asset management system for Ubuntu servers.
This document is the single source of truth for how we build, test, and deploy the project.

## Contents

1. Project Overview · 2. Asset Scope & Taxonomy · 3. Asset Lifecycle Policy · 4. Reporting & Dashboards ·
5. Tech Stack · 6. Repository Layout · 7. Local Development Setup · 8. Coding Conventions ·
9. Data Model · 10. API Conventions · 11. Auth & Roles ·
12. Vendor & Contract Management · 13. Data Quality Rules · 14. Notification Matrix · 15. Celery Tasks ·
16. Scanner / PWA Behavior · 17. Performance Targets · 18. Observability · 19. Environments ·
20. Testing · 21. Git Workflow · 22. Security Checklist · 23. Backup & Disaster Recovery ·
24. Deployment · 25. Compliance & Retention · 26. Documentation Set · 27. Integrations Roadmap ·
28. Milestones · 29. Definition of Done

---

## 1. Project Overview

Track hardware, software, network gear, cloud/SaaS records, and consumables across multiple
office sites: full asset lifecycle from request to certified disposal, QR label printing,
warranty and contract alerts, seat-based license management, reports/exports for audits and
finance, and LDAP/AD login.

**Target scale:** 10,000–100,000 assets · multiple sites · 100+ users.
(PostgreSQL handles this comfortably — no sharding required; indexing + pagination only.)

### Goals
- One register of truth for every asset, with full assignment history
- Fast check-out / check-in from a browser or a barcode scanner
- Proactive warranty, license, and contract-expiry alerts
- Complete audit trail: who changed what, when
- Standard reports and exports (CSV/XLSX/PDF) for audits, management, and finance

### Non-goals (v1)
- MDM / agent-based device control (we record assets; we do not manage them — see §27)
- Multi-step procurement approval chains (v1 records request → receive only, see §3)
- Real-time inventory sync with vendors

---

## 2. Asset Scope & Taxonomy

Everything the system tracks is an **asset record** with a category code. Categories are
configurable by `admin`, but the following tree is the default and the naming convention.

### Category tree

```
IT-HW     Hardware
  IT-HW-LAP   Laptop
  IT-HW-DSK   Desktop / Workstation
  IT-HW-SRV   Server / Storage / NAS
  IT-HW-NET   Network (switch, AP, router, firewall)
  IT-HW-PRN   Printer / Scanner
  IT-HW-MOB   Mobile (phone, tablet) — includes SIM cards
  IT-HW-MON   Monitor
  IT-HW-PER   Peripheral (dock, headset, webcam, keyboard, mouse)
IT-SW     Software & SaaS
  IT-SW-DESK  Desktop license (per-device)
  IT-SW-SAAS  SaaS subscription (per-seat)
  IT-SW-SRV   Server / CAL license
IT-INF    Infrastructure records
  IT-INF-CLD   Cloud account / instance
  IT-INF-DOM   Domain name / DNS
  IT-INF-CERT  SSL certificate
IT-CON    Consumable (toner, cable, mouse, media)
```

- `asset_tag` format: `{category-code}-{seq}` e.g. `IT-HW-LAP-0042` (human-readable, QR-encoded).
- **Contracts are not a category** — support/warranty/subscription contracts are their own
  model (§12) that *links to* the assets and licenses they cover.
- ISO/IEC 19770 alignment: every asset carries a unique, permanently assigned tag (§25).

### Custom fields policy
- Each `Category` may declare extra fields (schema: name, type, required, filterable).
- Values live in `Asset.attrs` (JSONB) — **validated against the category schema on save.**
- Any custom field used in list filters or reports **must be promoted to a real column**
  (with an index) — JSONB queries stay out of hot list views.
- Changing a category schema never deletes existing values; removed fields are kept but hidden.

### Common fields (every asset)

`asset_tag` · `category` · `manufacturer` · `model` · `serial_no` · `condition`
(NEW/GOOD/FAIR/POOR/DAMAGED) · `status` · `site` · `location` · holder (via current
`Assignment`) · `supplier` · `purchase_date` · `cost` · `warranty_end` · PO/invoice ref ·
`remarks` · created/updated audit fields.

### Category data fields (beyond common)

#### Computer — PC / Laptop (`IT-HW-LAP`, `IT-HW-DSK`)

| Field | Type | Req | Notes |
|---|---|---|---|
| `device_type` | laptop / desktop / all-in-one / mini-PC | ✓ | |
| `hostname` | char, unique per site | ✓ | network name — different from `asset_tag` |
| `cpu` | char | ✓ | e.g. `i7-1365U / 10C` |
| `ram_gb` | int | ✓ | |
| `storage` | char | ✓ | `512GB NVMe`; multi-drive → `attrs` list |
| `gpu` | char | — | |
| `os_family` / `os_version` / `os_edition` | enum / char | ✓ | see **OS tracking** below |
| `os_license_type` | OEM / volume / MAK-KMS / subscription / none | ✓ | |
| `encrypted` | bool | ✓ | BitLocker / FileVault state |
| `bundled_accessories` | FK list | — | dock, charger (also set on the accessory: `bundled_with`) |
| `last_seen_at` | datetime | — | discovery import (§27) |

#### Monitor (`IT-HW-MON`)

| Field | Type | Req | Notes |
|---|---|---|---|
| `screen_size_in` | decimal | ✓ | |
| `resolution` | 1080p / 1440p / 4K / 5K | ✓ | |
| `panel_type` | IPS / VA / TN / OLED | — | |
| `refresh_rate_hz` | int | — | |
| `inputs` | multi: HDMI / DP / USB-C / VGA | — | |
| `bundled_with` | FK → computer | — | ships with a PC; inherits that PC's holder |
| `powered_on_hours` | int | — | if reported by the monitor |

#### Server (`IT-HW-SRV`)

| Field | Type | Req | Notes |
|---|---|---|---|
| `hostname` | char, unique | ✓ | |
| `server_role` | DC / DNS / DHCP / DB / APP / FILE / PRINT / BACKUP / VIRTUAL-HOST / OTHER | ✓ | |
| `environment` | prod / staging / dev | ✓ | |
| `form_factor` | rack / tower / blade | ✓ | |
| `rack_position` | char | rack only | `Rm-A / Rack-03 / U22` |
| `cpu` | char | ✓ | `2× Xeon Silver 4310 / 24C` |
| `ram_gb` | int | ✓ | |
| `storage` | char | ✓ | `4× 1.92TB SSD RAID-10` |
| `hypervisor` | ESXi / Proxmox / KVM / bare-metal | — | |
| `mgmt_ip` | IP | phys. | iLO / iDRAC address |
| `os_family` / `os_version` + `os_license_type` | — | ✓ | Datacenter / volume licensing |
| `support_contract` | FK → Contract (§12) | — | |

#### Other IT Accessories (`IT-HW-PER`, `IT-CON`)

| Field | Type | Req | Notes |
|---|---|---|---|
| `accessory_type` | dock / cable / adapter / charger / headset / webcam / keyboard / mouse / toner / other | ✓ | |
| `connection` | USB-C / USB-A / HDMI / DP / Bluetooth / none | — | |
| `bundled_with` | FK → parent asset | — | inherits the parent's holder |
| `quantity` | int | consumables only | bulk items use one tag + quantity, not per-item rows |
| `serial_no` | — | — | rarely present; not required for this category |

- Required (`✓`) fields are enforced on forms, API, and CSV import (§13).
- Fields used in filters/reports must be promoted columns (policy above).

### OS tracking

- Fields: `os_family` (WIN10 / WIN11 / WS2019 / WS2022 / MACOS / LINUX / OTHER / NONE),
  `os_version`, `os_edition`, `os_license_type` (OEM / VOLUME / MAK / KMS / SUBSCRIPTION /
  NONE), optional `os_key`, `activation_status`.
- Applies to computers and servers; monitors and accessories are `NONE`.
- **Promoted columns:** `os_family`, `os_license_type` — feed the OS-inventory and
  license-compliance reports (§4).
- Raw product keys are stored encrypted in `attrs`; for volume/subscription licensing the
  seat lives as a `SoftwareLicense` — reports join through `LicenseKey → Asset` (§9).
- OS install/upgrade writes an `ActivityLog` entry (`os_change`).

---

## 3. Asset Lifecycle Policy

Eight stages. The system enforces this flow — **state transitions happen only in
`apps/assets/services.py`, never directly in views or the UI.**

```
① Request → ② Approve → ③ Procure → ④ Receive & Tag → ⑤ Deploy/Assign
                                                    ↓
                       ⑧ Dispose ← ⑦ Sanitize ← ⑥ Maintain/Repair/Transfer
```

| # | Stage | Created/changed records | Allowed roles |
|---|---|---|---|
| ① | Request | `AssetRequest` (pending) | any logged-in user |
| ② | Approve | request → approved/rejected | `admin` |
| ③ | Procure | PO no., supplier, cost attached to request | `admin` |
| ④ | Receive & Tag | **`Asset` created**, status `IN_STOCK`, QR label printed | `technician`+ |
| ⑤ | Deploy/Assign | `Assignment` created, status `ASSIGNED` | `technician`+ |
| ⑥ | Maintain/Repair | `RepairTicket` (+ RMA no.), status `IN_REPAIR` | `technician`+ |
| ⑦ | Retire & Sanitize | status `RETIRED`, then `DisposalRecord` (sanitization) | `admin` sign-off |
| ⑧ | Dispose | status `DISPOSED`, disposal certificate PDF generated | `admin` sign-off |

### Status flow

```
IN_STOCK → AVAILABLE → ASSIGNED ⇄ IN_REPAIR → AVAILABLE → RETIRED → DISPOSED
                    └──→ IN_TRANSIT ⇄ AVAILABLE        (site transfer)
```

- Person-to-person **handover is not a status** — it closes the current `Assignment`
  and opens a new one (see Transfers below).
- Site transfer uses a `Transfer` record + the `IN_TRANSIT` status (see Transfers below).
- Illegal transitions raise an exception in the service layer (tested in §20).
- An asset with any assignment history is **never hard-deleted** — retire it instead.

### Transfers

| Kind | Mechanism | Status effect |
|---|---|---|
| Person-to-person handover | close current `Assignment` (`in_at`) + open a new one in one transaction; condition recorded; receiver named | none — not a status |
| Site-to-site move | `Transfer` record: from/to site, assets (bulk OK), tracking no., dispatched/received timestamps, received_by | assets → `IN_TRANSIT` on dispatch, back on receipt |

- On receipt: `Asset.site` = destination, `ActivityLog` written per asset, `Transfer` closed.
- Arrival discrepancy (missing / damaged): record an exception → auto damage entry (below) + alert (§14).
- Permissions: `technician`+ dispatches; destination `technician`+ confirms receipt.
- Bulk supported (batch label reprint on dispatch); per-asset history is always preserved.

### Damage entry & repair (အပျက်စာရင်း)

**Report (any user):** fault category (screen / battery / power / storage / board / liquid /
accident / other), severity, description, photo (≤5 MB) → creates `RepairTicket`, asset →
`IN_REPAIR`, alerts per §14.

**Check-in with damage:** a returning asset found damaged → `condition = DAMAGED` +
auto `RepairTicket`.

**Repair fields:** reported fault, category, vendor, RMA no., sent date, returned date,
cost, outcome (`REPAIRED` / `REPLACED` / `WRITTEN_OFF`). Replacement creates a **new**
asset record (new serial) linked via `replaces_asset`.

**Write-off / dead list (bulk):** `technician` prepares, `admin` decides — damage date,
cause (wear / accident / flood / fire / theft / unknown), description, photos, estimated vs
actual cost, decided_by + decision_at, police report no. if stolen. Result: status `RETIRED`
with reason `DAMAGED_BEYOND_REPAIR` (or `LOST/STOLEN`), then flows to ⑦ Sanitize →
⑧ Dispose. Theft: sanitization is marked N/A with justification, police report attached.

### Data sanitization (before disposal)
- `DisposalRecord`: method (`crypto_erase` / `factory_reset` / `physical_destruction`),
  tool used, operator, verified_by (second person), date, certificate no.
- Certificate PDF generated automatically; retained 7 years (§25).
- No asset may reach `DISPOSED` without a completed `DisposalRecord` (service-layer guard).

---

## 4. Reporting & Dashboards

Reports are **read-only queries over the register** — same service layer as the UI, exported
via CSV/XLSX (`openpyxl`) or PDF (`reportlab`).

### Standard reports (v1)

| Report | Answers | Formats |
|---|---|---|
| Inventory by site/category/status | What do we own, where? | CSV, XLSX, PDF |
| Asset aging | How old is the fleet? | XLSX |
| Depreciation schedule | Value for finance (straight-line, salvage) | XLSX |
| Warranty expiring (30/60/90d) | What needs renewal/replace? | CSV, PDF |
| License compliance | Seats assigned vs entitled, over-assign? | XLSX |
| Contract renewals (next 90d) | What must be renewed? | CSV |
| Orphan assets | Assigned to people who left / no holder? | CSV |
| Audit results | Found / missing / mismatched at last count | XLSX |
| Check-out/in activity | Who moved what this period? | CSV |
| OS inventory & versions | What OS runs where? | XLSX |
| Damage & write-off log | Why did assets leave service? | PDF |
| Disposal & sanitization log | Compliance evidence | PDF |

### Dashboard widgets (home page)
Fleet totals by status/site/category · warranty expiring · licenses over-assigned ·
contracts expiring · requests awaiting approval · last audit date.

### Scheduled reports
- Weekly (Mon 07:30): expiring warranties + contracts → IT lead
- Monthly (1st, 08:00): full inventory snapshot per site → site lead

Implemented 2026-10-17 as `send_scheduled_reports` (§15): CSV exports rendered
by `apps.reports.service.run_scheduled_report` (same `_lookup`/`_execute` as the
UI/API report paths) and attached to one idempotent email per period (per site
for the monthly run). The site lead address is `Site.lead_email`; blank →
`IT_LEAD_EMAIL`.
- Scheduling config lives in the `reports` app; sends through the notification matrix (§14).

**Custom/ad-hoc report builder (field picker + filters + save) is v2** — not in v1 scope.

---

## 5. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| OS (prod) | Ubuntu Server 24.04 LTS | only supported deploy target |
| Language | Python 3.12+ | pinned in `.python-version` |
| Web framework | Django 5.x | built-in admin for internal tooling |
| API | Django REST Framework + drf-spectacular | `/api/v1/`, OpenAPI at `/api/v1/schema` |
| DB | PostgreSQL 16 | `utf8`/locale `C.UTF-8` |
| Queue | Celery + Redis | warranty emails, batch label jobs |
| Web server | Nginx + Gunicorn | reverse proxy + TLS |
| TLS | Certbot (Let's Encrypt) | auto-renew |
| LDAP | `django-auth-ldap` (ldap3) | AD login, local fallback admin |
| Labels | `python-qrcode` + `reportlab` | QR + PDF label sheets |
| PDF export | `reportlab` | reports, disposal certificates |
| Export | `openpyxl` | CSV/XLSX import & export |
| Error tracking | GlitchTip (self-hosted, Sentry-compatible) | §18 |
| Containers | Docker + Docker Compose | app, db, redis, nginx, certbot |
| Monitoring | Uptime Kuma (external) + Django health endpoint | §18 |

Local dev can run Django directly in a venv; **production always runs through Docker Compose.**

---

## 6. Repository Layout

```
itasset/
├── DEVELOPMENT.md            # this file
├── README.md                 # quickstart for end users
├── CHANGELOG.md              # Keep a Changelog format
├── GLOSSARY.md               # asset_tag vs serial, RMA, SAM, ITIL (§26)
├── docker-compose.yml        # prod services
├── docker-compose.dev.yml    # local dev overrides
├── .env.example              # all supported env vars (no secrets)
├── pyproject.toml            # deps + tool config (ruff, pytest)
├── Makefile                  # make lint / test / run / migrate
├── manage.py               # Django entrypoint (DJANGO_ENV picks settings)
├── config/
│   ├── settings/             # base.py, dev.py, prod.py
│   ├── urls.py  celery.py  wsgi.py
├── apps/
│   ├── assets/       # Asset, Category, Assignment, AssetRequest, Transfer, RepairTicket, DisposalRecord
│   ├── people/       # Site, Department, Person (employee)
│   ├── licenses/     # SoftwareLicense, LicenseKey
│   ├── vendors/      # Vendor, Contract (§12)
│   ├── reports/      # report queries, exporters, schedules (§4)
│   ├── labels/       # QR generation, PDF label sheets
│   ├── audit/        # ActivityLog, audit/physical-count mode
│   ├── api/          # DRF viewsets, serializers, routers, OpenAPI schema
│   ├── accounts/     # LDAP auth, roles/groups, local fallback
│   └── dashboard/    # home view, aggregate stats
├── templates/        # Django templates (incl. templates/email/)
├── static/           # css/js/fonts (collected by collectstatic)
├── locale/           # translation files (my, en)
├── apps/<app>/management/commands/   # import_csv, scan_warranties, seed_demo
├── scripts/          # backup.sh, restore.sh (§23)
├── tests/            # integration tests (apps keep unit tests inline)
└── docs/
    ├── deploy-ubuntu.md
    ├── remote-dev.md       # SSH + VS Code Remote-SSH dev setup
    ├── data-model.md        # ERD
    ├── user-manual.md       # Burmese, per-role workflows
    ├── openapi.yaml         # generated by `make openapi` (§7)
    └── adr/                 # NNNN-title.md architecture decision records
```

**Rules**
- One Django app per business domain. No cross-app model imports except through
  explicit FKs (`apps.assets.models.Asset` → `apps.people.models.Site`).
- Business logic lives in services (`apps/<app>/services.py`), not in views,
  serializers, or models' `save()`.
- Settings are read from environment variables (`django-environ`); `.env` is
  never committed.

---

## 7. Local Development Setup

```bash
# 1. clone and enter
git clone <repo> itasset && cd itasset

# 2. Python env
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. environment
cp .env.example .env          # defaults work for local dev

# 4. database (docker only for the DB)
docker compose -f docker-compose.dev.yml up -d db redis

# 5. migrate + seed
make migrate
make seed                      # demo sites, departments, 50 assets

# 6. run
make run                      # http://127.0.0.1:8000
make worker                   # celery worker (only needed for alert tasks)
```

Admin account: `make createsuperuser` (never ship a default password).

### Useful commands

| Command | Purpose |
|---|---|
| `make lint` | `ruff check` + `ruff format --check` |
| `make format` | auto-fix lint/format |
| `make test` | `pytest -q` with coverage |
| `make migrate` | `python manage.py makemigrations && migrate` |
| `make seed` | load demo data (dev only) |
| `make shell` | Django shell |
| `make import FILE=x.csv` | bulk asset import |
| `make openapi` | regenerate `docs/openapi.yaml` |

---

## 8. Coding Conventions

- **Style:** `ruff` (lint + format), line length 100. No personal config — it lives in `pyproject.toml`.
- **Naming:** modules and functions `snake_case`, classes `CapWords`, Django model fields `snake_case`.
  Boolean fields start with `is_`/`has_` (`is_assigned`, `has_warranty`).
- **Models**
  - Every model defines `__str__`, `Meta.ordering`, and `Meta.verbose_name`.
  - Soft state changes only — never `DELETE` an asset that has history;
    set `status = RETIRED` and record an `ActivityLog` entry.
  - `Asset.asset_tag` is the external unique identifier (printed in QR).
    `serial_no` is indexed but **not** required unique (vendors repeat them).
  - Datetimes are `DateTimeField` in **UTC**; display in local time at template layer.
- **Views:** function-based views for simple pages, class-based only when reuse is real.
  POST endpoints always go through a form or serializer — never `request.POST` raw in logic.
- **Templates:** block inheritance from `base.html`; no inline JS/CSS beyond small widgets.
- **Messages:** all user-facing success/error messages go through Django `messages`.
- **i18n:** wrap user-facing strings in `gettext` (`_()`); default language `my` (Burmese) + `en`.
- **No** `print()` debugging — use `logging` with the standard logger hierarchy.

### Service layer example

```python
# apps/assets/services.py
def check_out(asset: Asset, person: Person, *, actor: User) -> Assignment:
    if asset.status != Asset.Status.AVAILABLE:
        raise AssetNotAvailable(asset)
    assignment = Assignment.objects.create(asset=asset, person=person, out_at=now())
    asset.status = Asset.Status.ASSIGNED
    asset.save(update_fields=["status", "updated_at"])
    ActivityLog.record(actor=actor, action="check_out", obj=asset)
    return assignment
```

---

## 9. Data Model (summary)

```
Site ─┬─ Location ─< Person (employee, linked to LDAP uid)
      └─< Asset >─ Category
             ├─< Assignment >─ Person        # out_at / due_at / in_at history
             ├─< ActivityLog                 # audit trail
             ├─ Warranty / RepairTicket      # incl. RMA no.
             └─ DisposalRecord               # sanitization + certificate
AssetRequest ──(on receive)──> Asset         # request → approve → procure → receive
Transfer (site moves, in-transit)            # §3 Transfers
Vendor ─< Contract ─┬─ Asset                 # support/warranty coverage
                    └─ SoftwareLicense
SoftwareLicense ─< LicenseKey ── Asset       # seat counting
Consumable, Supplier, Manufacturer           # supporting tables
```

- **Status flow** (full policy in §3): `IN_STOCK → AVAILABLE → ASSIGNED ⇄ IN_REPAIR →
  AVAILABLE → RETIRED → DISPOSED`, plus `IN_TRANSIT` during site transfers. Transitions are
  enforced in `apps/assets/services.py`, not in the UI.
- **Assignment history is append-only.** Current assignment = row with `in_at IS NULL`.
- **Sites are mandatory** on `Asset`, `Person`, and `Assignment` — every query in list
  views is site-scoped for non-admin users.
- Indexes (required): `asset_tag (unique)`, `(site, status)`, `(warranty_end)`,
  `(person, in_at)`, `serial_no`, `Contract.end_date`, `AssetRequest(status, created_at)`.
- Migration policy: every schema change lands with its migration in the same PR;
  migrations in already-deployed environments are **never edited, only reverted/reapplied**.

---

## 10. API Conventions

- Base path: `/api/v1/`. Breaking changes require `/api/v2/` — never mutate v1 incompatibly.
- Auth: session auth for the web app, **token auth for scanner clients** (§16).
- Errors: RFC 7807 problem JSON (`{"detail": ..., "status": ...}`).
- Pagination: cursor/page pagination, page size 100 default.
- Every list endpoint supports `?site=`, `?status=`, `?q=` (search) filters.
- OpenAPI schema served by drf-spectacular: `/api/v1/schema` + `/api/v1/docs` (admin-only UI).

Core endpoints:

```
GET/POST   /api/v1/assets/
GET        /api/v1/assets/{asset_tag}/          # lookup by QR tag
POST       /api/v1/assets/{asset_tag}/receive/
POST       /api/v1/assets/{asset_tag}/check-out/
POST       /api/v1/assets/{asset_tag}/check-in/
POST       /api/v1/assets/{asset_tag}/repair/
POST       /api/v1/assets/{asset_tag}/dispose/   # requires DisposalRecord
GET        /api/v1/scan/{asset_tag}/            # fast scanner payload
GET/POST   /api/v1/requests/                    # asset requests
POST       /api/v1/assets/{asset_tag}/report-damage/
POST       /api/v1/transfers/
POST       /api/v1/transfers/{id}/receive/
GET        /api/v1/contracts/expiring/?days=90
GET        /api/v1/warranties/expiring/?days=90
GET        /api/v1/reports/{slug}/?format=csv|xlsx|pdf
```

Mutations must verify the same permission rules as the UI (shared service layer).

---

## 11. Auth & Roles

- **Primary:** LDAP/AD bind via `django-auth-ldap` (groups → Django groups mapping).
- **Fallback:** one local break-glass superuser (offline/AD outage), stored hashed,
  credentials in the server's secrets file — never in the repo.
- Roles (Django Groups):

| Role | Can |
|---|---|
| `admin` | everything: approve requests, disposal sign-off, user/site management |
| `technician` | receive & tag, check-out/in, transfers, damage entry, repair, edit assets, print labels, run audits |
| `auditor` | read all + audit mode, no edits |
| `viewer` | read-only, site-scoped; can submit asset requests |

- LDAP is **enabled via env var** (`LDAP_ENABLED=1`); in dev it is off by default.
- 2FA (TOTP) for `admin` role is mandatory in production.
- Scope rule: non-admin users only see their `site` (enforced in the queryset, not just the UI).

---

## 12. Vendor & Contract Management

### Vendor
- Name, category (hardware / software / service), contacts, support level/SLA terms,
  website, account notes; dated performance notes (RMA speed, ticket quality).
- `Supplier` on a purchase and `Vendor` on a contract may differ — both are recorded.

### Contract
- Type: `support` / `warranty` / `subscription` / `lease`.
- Fields: vendor, start/end date, value + currency, payment terms, **renewal notice period
  (default 60d)**, auto-renew flag, PO/contract no., notes.
- Links: one contract covers many `Asset`s and/or `SoftwareLicense`s (coverage rows).
- Attachments (signed PDF): private storage (never `static/`), MIME-validated, 5 MB cap.
- Renewal alerts (60d / 14d before end) → Notification matrix (§14), task in §15.

### Reports
- "Contracts expiring (90d)" and "annual spend per vendor" are part of §4 standard reports.

---

## 13. Data Quality Rules

- **Mandatory fields per category** — the `✓` rows in the §2 category tables
  (server: serial + warranty + location; consumable: category only) — enforced on
  forms, API, and import alike.
- **Normalization:** `serial_no` trimmed + uppercased; `asset_tag` generated by the system,
  never hand-typed.
- **Duplicate detection:** saving/importing warns when the same normalized `serial_no`
  already exists (same model). Import marks duplicates and **skips** them into an error file.
- **CSV import:** column-mapping step → dry-run preview (row counts, errors, duplicates) →
  commit. Max 5,000 rows/file. Every import writes an `ActivityLog` entry with file hash.
- **Barcode symbology:** QR (primary — encodes `asset_tag` URL) + Code 128 human-readable
  line. Label reprints are allowed and logged.
- **Monthly data-quality report** (§14): missing warranty, missing location, assigned asset
  with no holder, duplicate serials.

---

## 14. Notification Matrix

| Event | Channel | Recipients | Timing |
|---|---|---|---|
| Warranty expiring | email | asset holder + IT lead | 90 / 30 / 7 days |
| Contract / license renewal | email | admin + procurement | 60 / 14 days |
| License over-assigned | email | admin | weekly |
| Asset request awaiting approval | email | approvers | within 1 h |
| Loan overdue (check-out past due) | email | holder + technician | due + 3 days |
| Damage reported / transfer exception | email | technician + site lead | immediate |
| Data-quality issues | email | IT lead | monthly, 1st |
| Daily activity digest | email | admins | daily 08:00 |
| System error / failed task | webhook (Telegram) | on-call | immediate |

- Escalation: no acknowledgement within 48 h → next level (holder → IT lead → admin).
- All templates live in `templates/email/`, translated (`my` + `en`), tested in §20.
- Recipients are env-driven (§19): `IT_LEAD_EMAIL`, `PROCUREMENT_EMAIL`, and
  `ADMIN_EMAIL` for the daily digest (falls back to the IT lead when blank);
  the monthly inventory snapshot addresses `Site.lead_email` (same fallback).
- All email rows above shipped 2026-10-17: approval heads-ups fire **inline**
  when a request starts awaiting a step (within 1 h by construction) and when
  a chain advances; damage + transfer-exception alerts fire at the service call
  (one per event); loan overdue runs via `scan_loans` (new §15 row). In-band
  sends are best-effort — an SMTP failure logs, never fails the user's action;
  role-based recipients obey deny-by-default scope (an out-of-scope role holder
  is not told). The Telegram system-error webhook remains open.
- Every alert type is idempotent: a `last_sent_at` row prevents duplicate emails (§15).

---

## 15. Celery Tasks

| Task | Schedule | Purpose |
|---|---|---|
| `scan_warranties` | daily 07:00 | warranty alerts per §14 |
| `scan_license_seats` | daily 07:05 | flag over-assigned licenses |
| `scan_contracts` | daily 07:10 | contract renewal alerts (§12) |
| `scan_loans` | daily 07:15 | loan overdue: due + 3 days → holder + issuing technician (§14) |
| `data_quality_report` | monthly, 1st 07:00 | issues list → IT lead |
| `purge_activity_log` | monthly | retention (24 months, §25) |
| `send_daily_digest` | daily 08:00 | summary of yesterday's check-outs/ins |
| `send_scheduled_reports` | weekly/monthly per §4 | report exports by email |

Tasks must be idempotent — a re-run must not send duplicate emails
(status row records the last-alerted date).

---

## 16. Scanner / PWA Behavior

- **Mode 1 — hardware scanner (USB/Bluetooth, keyboard-wedge):** scan input behaves as
  keyboard + Enter; the scan field keeps focus. This is the primary warehouse/front-desk flow.
- **Mode 2 — camera scan:** light PWA (`html5-qrcode`, `BarcodeDetector` where available)
  for users without hardware scanners.
- **Offline tolerance:** scans queue locally (IndexedDB) and sync when back online.
  Every mutation carries a client-generated `idempotency_key` — replayed requests must
  **not** double check-out.
- **Conflict handling:** server is the source of truth; on sync failure show the reason
  (already assigned, retired, unknown tag) with the current holder.
- **Device auth:** long-lived scanner tokens bound to a registered device; revocable by
  `admin` if a device is lost. Tokens never embed user passwords.

---

## 17. Performance Targets

| Metric | Target |
|---|---|
| Page render (server-side) p95 | < 500 ms |
| API p95 | < 300 ms |
| Asset list query (100k rows, filtered) | < 100 ms DB time |
| Search-as-you-type | 300 ms debounce; only indexed fields |
| Batch label generation (500 QRs) | < 10 s |
| Bulk import (5,000 rows) | < 60 s |

Rules:
- **No N+1:** `select_related` / `prefetch_related` on every list; `nplusone` raises in dev.
- Every new list query gets an `EXPLAIN ANALYZE` review in its PR; indexes land with the query.
- Heavy exports and label batches run in Celery (§15), never in the request cycle.
- Index usage reviewed at each milestone (§28).

---

## 18. Observability

- **Structured JSON logs** (`ts`, `level`, `request_id`, `user`, `path`, `duration_ms`) —
  Django + Gunicorn; 14-day logrotate.
- **Error tracking:** GlitchTip (self-hosted) — DSN via env var; release tag = git SHA.
  Alert → Telegram webhook (§14) on new error fingerprint.
- **Health:** `GET /healthz` pings DB + Redis; Uptime Kuma checks every minute from outside.
- **Slow queries:** any query > 500 ms logged with SQL + params (redacted) for review.
- **Auditability of the monitor itself:** failed Celery beat tasks raise an alert — a silent
  scheduler failure must never go unnoticed.

---

## 19. Environments

| Env | DB | LDAP | Data | Purpose |
|---|---|---|---|---|
| `dev` | Postgres in Docker (local) | off | `make seed` demo data | daily development |
| `staging` | separate Postgres | mock/dedicated OU | anonymized copy | release verification |
| `prod` | production Postgres | real AD | real data only | live service |

- Same Compose files everywhere; only `.env` differs (§24).
- **`seed`/demo data must never run in prod** (guarded by `DJANGO_ENV`).
- Migrations run on staging before prod when the change is non-trivial.
- prod → staging data sync (for debugging) only via masked, manual dump.

---

## 20. Testing

- Framework: `pytest` + `pytest-django` + `factory_boy`.
- **Every service function needs unit tests.** Every API mutation needs an integration test.
- Auth matrix (permission × role) is tested for each protected endpoint.
- Lifecycle: illegal status transitions (§3) each have a test asserting they raise.
- Notification templates: each §14 event renders for `my` and `en` without missing strings.
- LDAP is tested against a mock connection — never against a real directory in CI.
- Coverage floor: **85%** on `apps/*/services.py`, 70% overall (`make test`).
- Tests use the `postgres` test DB (not SQLite) — we must not develop on SQL we don't run.

```bash
make test               # full suite
pytest apps/assets      # one app
pytest -k check_out     # one behavior
```

Before every PR: `make lint && make test` must pass locally and in CI.

---

## 21. Git Workflow

- `main` is always deployable; protected — PRs only, no direct pushes.
- Branch: `feat/<short-name>`, `fix/<short-name>`, `chore/<short-name>`.
- Commit message: imperative mood, why over what —
  `fix(checkout): block assigning an asset already out to a person`
- One concern per PR; include migration + tests + docs for the change.
- Architecture changes: add an ADR in `docs/adr/` in the same PR (§26).
- CI runs `ruff`, `pytest`, `docker compose config` validation on every PR.

---

## 22. Security Checklist

- [ ] `.env`, `*.pem`, dumps, and uploads never committed (`.gitignore` enforced)
- [ ] `DEBUG=0` in prod; `ALLOWED_HOSTS` explicit
- [ ] HTTPS only; HSTS enabled; secure/session/httpOnly cookies
- [ ] CSRF on every POST; DRF tokens rotated on personnel change / device loss (§16)
- [ ] SQL only via ORM/parameters — no string-built queries
- [ ] Uploads: extension + MIME whitelist (CSV/XLSX/PNG/PDF), 5 MB cap; contract files
      in private storage only
- [ ] Backups per §23 (RPO 24 h, encrypted, offsite, quarterly restore drill)
- [ ] UFW: 22 (restricted), 80, 443 only. fail2ban on ssh + nginx.
- [ ] All user content escaped in templates (Django autoescape stays ON)
- [ ] Break-glass admin credentials stored in server secrets file — tested quarterly (§23)

---

## 23. Backup & Disaster Recovery

### Targets

| | Target |
|---|---|
| **RPO** (max data loss) | 24 hours (daily 02:00 dump) |
| **RTO** (max downtime) | 4 hours |

### Backup scheme
- `scripts/backup.sh`: `pg_dump` → age/age or `restic` **encrypted** → offsite
  (rclone to S3-compatible storage **or** a second office server). Never only-local.
- Retention: **7 daily / 4 weekly / 6 monthly** snapshots.
- Includes: DB dump + private uploads (contract PDFs, label assets).
- A failed backup sends a Telegram alert (§14) — silence is a failure.

### Restore drill (quarterly — recorded in `docs/`)
1. Spin up clean container from latest backup on a scratch host
2. `scripts/restore.sh <snapshot>` → `manage.py check --deploy`
3. Verify: asset counts, last 10 assignments, one contract PDF opens
4. Record date + duration + issues; RTO breach → fix before next quarter

### Server rebuild (total loss)
Repo + `.env` secrets + offsite backup are sufficient: fresh Ubuntu 24.04 → §24 steps →
restore snapshot → verify health endpoint. This runbook is tested by the same drill.

---

## 24. Deployment (summary — full runbook in `docs/deploy-ubuntu.md`)

```bash
# on Ubuntu 24.04
git clone <repo> /opt/itasset && cd /opt/itasset
cp .env.example .env           # then fill real secrets
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
certbot --nginx -d assets.example.com
# backup: cron runs scripts/backup.sh daily at 02:00 (§23)
```

- Env split: `config/settings/dev.py` vs `prod.py` selected by `DJANGO_ENV` (§19).
- Deploys are: `git pull` → `docker compose up -d --build` → `migrate` → health check.
- Rollback: `docker compose up -d` on the previous git tag; DB rollback only via
  a reviewed reverse migration.
- Health endpoint: `GET /healthz` (DB + Redis ping) — monitored by Uptime Kuma (§18).

---

## 25. Compliance & Retention

### Retention schedule

| Data | Retention |
|---|---|
| `ActivityLog` | 24 months (auto-purge, §15) |
| Assignment history | lifetime of asset + 7 years |
| Asset + `DisposalRecord` + certificates | 7 years after disposal |
| `Person` records | 2 years after exit — name anonymized, ID kept for history |
| Contract/invoice attachments | contract lifetime + 7 years |
| Backups | 7 daily / 4 weekly / 6 monthly (§23) |

### Standards
- **ISO/IEC 19770:** unique permanent tag per asset; first-party inventory is the source
  of truth; tags are never reused even after disposal.
- **Audit readiness:** one export bundles current register + assignment history + disposal
  certificates for the requested period (zip via `reports` app).
- **Sanitization evidence:** `DisposalRecord` fields match NIST SP 800-88 methods
  (purge / clear / destroy), verified by a second person.
- Statutory retention periods for finance documents: **confirm with finance** and update
  this table; it is the authority for the purge tasks.

---

## 26. Documentation Set

| Doc | Audience | Content |
|---|---|---|
| `README.md` | devs | quickstart, links |
| `DEVELOPMENT.md` | devs | this file |
| `CHANGELOG.md` | all | Keep a Changelog format, per release tag |
| `docs/user-manual.md` | end users | **Burmese**, per-role workflows w/ screenshots |
| `docs/deploy-ubuntu.md` | ops | full runbook (§24) |
| `docs/remote-dev.md` | devs | SSH + VS Code Remote-SSH workstation setup |
| `docs/data-model.md` | devs | ERD from `graph_models` |
| `docs/adr/NNNN-*.md` | devs | one record per architecture decision |
| OpenAPI `/api/v1/docs` | API consumers | drf-spectacular, admin-only UI |
| `GLOSSARY.md` | all | asset_tag vs serial, RMA, SAM, ITIL terms |

Rule: a merged behavior change updates its docs in the same PR (see §29).

---

## 27. Integrations Roadmap

Import-based only — we consume exports/files or scan results; we never control devices.

| Phase | Integration | Notes |
|---|---|---|
| v1 | CSV / Excel import & export | column mapping + dry-run (§13) |
| v1.5 | Network discovery import | ARP/nmap scan output → match by MAC, flag unknown devices |
| v2 | Microsoft Intune / Entra ID | CSV export first, Graph API later |
| v2 | Finance export | annual depreciation XLSX for accounting |
| v2 | Helpdesk bridge | outbound webhook on check-out/repair events |

**Explicit non-integrations (v1):** MDM control, agent-based inventory, real-time vendor
sync. All imports go through the shared import service (dry-run + `ActivityLog`).

---

## 28. Milestones

| Phase | Deliverable | Done when |
|---|---|---|
| **M1 — Foundation** | Compose scaffold, settings, models, admin | `make seed` + admin CRUD works |
| **M2 — Core flow** | Site/Asset/Person CRUD, check-out/in, roles, CSV import | tech team can track 100 real assets |
| **M3 — Labels & API** | QR/PDF labels, `/api/v1/`, scanner check-out | label printed → scanned → assigned |
| **M4 — Alerts & licenses** | Celery warranty/license/contract tasks, email templates | test warranty triggers an email |
| **M5 — LDAP & audit** | AD login, ActivityLog UI, physical audit mode | login with AD account, audit report |
| **M6 — Intake & lifecycle** | Request → receive, transfers, damage/write-off, retire → sanitize → dispose | full lifecycle on one test asset |
| **M7 — Reporting & vendors** | report suite, scheduled exports, vendor/contract module | finance receives depreciation XLSX |
| **M8 — Go-live** | Ubuntu deploy, backup/DR drill, monitoring, docs | restore drill passed, Uptime Kuma green |

Each milestone ends with a demo to stakeholders and an updated `docs/` .

### 28.1 Progress log (2026-10-14)

**M1 — Foundation: complete.**

- Compose scaffold (`docker-compose.dev.yml` db+redis) and settings layer in place.
- Models, admin CRUD, seed data, and `/healthz` (DB ping) verified live on the
  dev server (192.168.100.142:8000, SSH alias `itasset-dev` in `~/.ssh/config`).
- Smoke tests: `tests/test_smoke.py` — 3 passed.

**M2 — Core flow: in progress (service layer done).**

- Lifecycle service layer at `apps/assets/services.py` (§3/§9):
  - `check_out(asset, person, actor, due_at, condition_out, remarks)` → `CheckOutResult`
  - `check_in(asset, condition_in, remarks)` → `CheckInResult`
    (`condition_in=DAMAGED` → status `IN_REPAIR`, else `AVAILABLE`)
  - `handover(asset, from_person, to_person, actor, ...)` → `(closed, new)` —
    close current assignment + open a new one, one logical operation
  - `receive_asset(asset, actor, to_person, condition, remarks)` → `ReceiveResult`
    (IN_STOCK → AVAILABLE, optionally assigns on receive)
  - guards: `active_assignment(asset)`, `can_assign(asset)`
  - errors: `AssetError`, `AssetNotAvailable`, `AssetAlreadyAssigned`,
    `AssetNotAssigned`, `InvalidStatusTransition`, `AssignmentError`
  - semantics: a new assignment carries `out_at` set / `in_at = NULL`;
    `in_at` is stamped only at check-in/handover-close.
- Service-layer tests: `apps/assets/tests/test_services.py` —
  **28 passed** (M1 smoke 3 + M2 services 25), covers happy paths,
  preconditions, illegal transitions, and teardown-safe factories
  (per-test `get_or_create`; no cross-test instance caching — pytest-django
  truncates between tests).
- Site/Asset/Person CRUD views + role checks are in (`RoleRequiredMixin`,
  admin-only site mutations, technician+ asset/person mutations).
- CSV import (§13): `apps/assets/services.py::import_assets_csv` — column
  mapping, dry-run preview (`make import FILE=assets.csv`), commit with
  `--commit`, duplicate detection (asset_tag + serial/model), serial
  normalisation, 5000-row cap, one `ActivityLog` entry with the file hash.
  Management command: `apps/assets/management/commands/import_csv.py`.
- Audit app (`apps/audit`): `ActivityLog` model (actor, action, generic
  target via ContentType, `object_repr`, JSON details, file hash);
  lifecycle services record check-out/check-in/receive/transfer entries.
- **M2 — Core flow: complete.**

**M3 — Labels & API: complete.**

- Labels (`apps/labels`): QR PNG per asset, A4 L7160 label sheets (3×7,
  QR + human-readable Code-128, §13) via reportlab; print view
  `/labels/print/?ids=…` (technician+), preview `/labels/<pk>/`.
- REST API (`apps/api`) at `/api/v1/` (DRF):
  - assets CRUD with `?site=/?status=/?q=` filters, detail by `asset_tag`
  - lifecycle actions: `POST /assets/{tag}/check-out|check-in|receive/`
    (same service layer as the UI; conflicts → 409, unknown person → 404)
  - `GET /scan/{tag}/` — fast scanner payload (§16): status, holder,
    `can_check_out` / `can_check_in` flags
  - token auth for scanner clients (`POST /auth/token/`, revocable),
    session auth for the web app; anonymous → 401, wrong role → 403
  - OpenAPI schema + Swagger UI at `/api/v1/schema/` and `/api/v1/docs/`
- Tests: **81 passed** — service layer, CRUD views + role matrix, CSV
  import, labels (PNG/PDF bytes, role guard), API auth matrix
  (anonymous/viewer/technician/admin, token flow + revocation),
  lifecycle actions, scanner payload.
- `make lint` (ruff check + format) green; `makemigrations --check` clean;
  pytest config collects `test_*.py` everywhere, so `apps/core/tests.py`
  is now picked up (was silently skipped before).

**M4 — Alerts & licenses: complete.**

- Vendors & contracts (§12): `apps/vendors` — `Vendor` (+dated
  `VendorNote` performance log), `Contract` (type, value/currency,
  `renewal_notice_days` default 60, auto-renew flag, M2M coverage rows to
  assets + licenses).
- Licenses (§9 seat counting): `apps/licenses` — `SoftwareLicense`
  (entitled `seats`, `seats_assigned` counts active keys only) +
  `LicenseKey` (one assigned seat → asset/person; `release()` frees it).
- Notification matrix (§14): `apps/audit/notify.py::send_alert` — bilingual
  templates in `templates/email/` (my/en), role-based recipients
  (holder + `IT_LEAD_EMAIL`, + `PROCUREMENT_EMAIL`; env-driven, §19).
  Idempotency via `EmailAlert` row per (kind, object, bucket) — created
  *before* send, deleted on failure so the next run retries.
- Celery tasks (§15) in `apps/audit/tasks.py` + beat schedule
  (`config/settings/base.py`, Yangon time): `scan_warranties` daily 07:00
  (90/30/7d buckets), `scan_license_seats` 07:05 (weekly per-license
  bucket → no daily spam), `scan_contracts` 07:10 (60/14d buckets,
  respects each contract's own notice period), `purge_activity_log`
  monthly 1st (24-month retention, §25).
- API (§10): `GET /api/v1/warranties/expiring/?days=90`,
  `GET /api/v1/contracts/expiring/?days=90`.
- Tests: **96 passed** (+13 audit/M4) — warranty trigger → email to
  holder+IT lead, bucket escalation (30d → 7d = 2 emails, 1 per bucket),
  idempotent re-runs, no-recipient safety, contract notice-period
  respect, weekly license bucket, retention purge, expiring APIs.

**Runtime wiring on the dev server.**

- runserver runs as a **systemd user unit**
  `~/.config/systemd/user/itasset-runserver.service` — `enable --now`,
  `Restart=on-failure`, not tied to any SSH session; survives reboot
  (user lingering already enabled).
- Dev containers `itasset-db-1` / `itasset-redis-1` use Docker
  **`restart unless-stopped`** policy — they come back up after host reboot.
- Verified: `systemctl --user is-active` → active; `GET /healthz` →
  `{"status": "ok", "db": "ok"}`; port 8000 LISTEN.

---

## 29. Definition of Done (every ticket)

1. Code follows §8 conventions; `make lint` passes.
2. Tests cover the new behavior; `make test` passes.
3. Migration included (or "no schema change" stated).
4. Permissions enforced for all new endpoints.
5. User-facing strings translated (`my` + `en`).
6. Retention/privacy impact checked (§25) if new data is stored.
7. README/docs updated if behavior or commands changed (§26).
