# IT Asset Manager — Development Guide

**Version:** 1.1.0
**Last updated:** 2026-10-12
**Owner:** IT Infrastructure Team
**Status:** Active Development (M2)

Multi-site IT asset management system for Ubuntu servers.
This document is the single source of truth for how we build, test, and deploy the project.

> 📌 Current milestone status: see docs/PROGRESS.md

## Contents

1. Project Overview · 2. Asset Scope & Taxonomy · 3. Asset Lifecycle Policy ·
4. Reporting & Dashboards · 5. Tech Stack · 6. Repository Layout · 7. Local Dev Setup ·
8. Coding Conventions · 9. Data Model · 10. API Conventions · 11. Auth & Roles ·
12. Vendor & Contract Management · 13. Data Quality Rules · 14. Notification Matrix ·
15. Celery Tasks · 16. Scanner / PWA Behavior · 17. Performance Targets · 18. Observability ·
19. Environments · 20. Testing · 21. Git Workflow · 22. Security Checklist ·
23. Backup & DR · 24. Deployment · 25. Compliance & Retention · 26. Documentation Set ·
27. Integrations Roadmap · 28. Milestones · 29. Definition of Done · 30. Glossary ·
31. Makefile Reference

---

## 1. Project Overview

Track hardware, software, network gear, cloud/SaaS records, and consumables across multiple
office sites: full asset lifecycle from request to certified disposal, QR label printing,
warranty and contract alerts, seat-based license management, reports/exports for audits and
finance, and LDAP/AD login.

**Target scale:** 10,000–100,000 assets · multiple sites · 100+ users.

### Goals
- One register of truth for every asset, with full assignment history
- Fast check-out / check-in from a browser or a barcode scanner
- Proactive warranty, license, and contract-expiry alerts
- Complete audit trail: who changed what, when
- Standard reports and exports (CSV/XLSX/PDF) for audits, management, and finance

### Non-goals (v1)
- MDM / agent-based device control
- Multi-step procurement approval chains
- Real-time inventory sync with vendors

---

## 2. Asset Scope & Taxonomy

Everything the system tracks is an **asset record** with a category code.

### Category tree

```
IT-HW     Hardware
  IT-HW-LAP   Laptop
  IT-HW-DSK   Desktop / Workstation
  IT-HW-SRV   Server / Storage / NAS
  IT-HW-NET   Network
  IT-HW-PRN   Printer / Scanner
  IT-HW-MOB   Mobile
  IT-HW-MON   Monitor
  IT-HW-PER   Peripheral
IT-SW     Software & SaaS
IT-INF    Infrastructure
IT-CON    Consumable
```

- asset_tag format: {category-code}-{seq} e.g. IT-HW-LAP-0042
- Contracts are not a category — they are their own model (§12)
- ISO/IEC 19770 aligned

### Common fields (every asset)

asset_tag · category · manufacturer · model · serial_no · condition · status · site ·
location · holder · supplier · purchase_date · cost · warranty_end · PO/invoice ref · remarks

> 📘 Category-specific fields: see docs/category-schema-design.md

---

## 3. Asset Lifecycle Policy

```
① Request → ② Approve → ③ Procure → ④ Receive & Tag → ⑤ Deploy/Assign
                                                    ↓
                       ⑧ Dispose ← ⑦ Sanitize ← ⑥ Maintain/Repair/Transfer
```

### Status flow

```
IN_STOCK → AVAILABLE → ASSIGNED ⇄ IN_REPAIR → AVAILABLE → RETIRED → DISPOSED
                    └──→ IN_TRANSIT ⇄ AVAILABLE        (site transfer)
```

- State transitions happen only in apps/assets/services.py
- An asset with any assignment history is never hard-deleted
- No asset may reach DISPOSED without a completed DisposalRecord

---

## 4. Reporting & Dashboards

### Standard reports (v1)

| Report | Formats |
|---|---|
| Inventory by site/category/status | CSV, XLSX, PDF |
| Asset aging | XLSX |
| Depreciation schedule | XLSX |
| Warranty expiring (30/60/90d) | CSV, PDF |
| License compliance | XLSX |
| Contract renewals | CSV |
| Orphan assets | CSV |
| Audit results | XLSX |
| Check-out/in activity | CSV |
| OS inventory | XLSX |
| Damage & write-off log | PDF |
| Disposal & sanitization log | PDF |

### Dashboard widgets
- Fleet totals by status/site/category
- Warranty expiring (30/60/90d buckets)
- Licenses over-assigned
- Contracts expiring next 90d
- Requests pending approval
- Last audit date

---

## 5. Tech Stack

| Layer | Choice | Version |
|---|---|---|
| OS (prod) | Ubuntu Server | 24.04 LTS |
| Language | Python | 3.12.x |
| Web framework | Django | 5.1.x |
| API | DRF | 3.15.x |
| DB | PostgreSQL | 16.x |
| Queue | Celery + Redis | 5.4.x / 7.4.x |
| Web server | Nginx + Gunicorn | 1.26.x / 22.x |
| LDAP | django-auth-ldap | 4.8.x |
| Labels | python-qrcode + reportlab | 8.x / 4.x |
| Export | openpyxl | 3.1.x |
| Containers | Docker + Compose | 27.x |

---

## 6. Repository Layout

```
itasset/
├── DEVELOPMENT.md
├── README.md
├── CHANGELOG.md
├── GLOSSARY.md
├── docker-compose.yml
├── pyproject.toml
├── Makefile
├── config/
├── apps/
│   ├── assets/       # Asset, Category, Assignment, ...
│   ├── people/       # Site, Department, Person
│   ├── licenses/     # SoftwareLicense, LicenseKey
│   ├── vendors/      # Vendor, Contract
│   ├── reports/      # report queries, exporters
│   ├── labels/       # QR generation
│   ├── audit/        # ActivityLog, audit mode
│   ├── api/          # DRF viewsets
│   ├── accounts/     # LDAP auth, roles
│   └── dashboard/    # home view
├── templates/
├── static/
├── locale/
├── scripts/
└── docs/
    ├── PROGRESS.md
    ├── category-schema-design.md
    ├── deploy-ubuntu.md
    ├── data-model.md
    ├── user-manual.md
    └── adr/
```

---

## 7. Local Development Setup

```bash
git clone <repo> itasset && cd itasset
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d db redis
make migrate
make seed
make run
```

Admin: `make superuser` (never ship a default password).

---

## 8. Coding Conventions

- Style: ruff (lint + format), line length 100
- Naming: snake_case for functions, CapWords for classes
- Boolean: is_/has_ prefix
- Business logic in services, never in views/serializers
- i18n: gettext with my + en

### Service layer example

```python
def check_out(asset, person, *, actor):
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
Site ─┬─ Location ─< Person
      └─< Asset >─ Category
             ├─< Assignment >─ Person
             ├─< ActivityLog
             ├─ Warranty / RepairTicket
             └─ DisposalRecord
AssetRequest ──> Asset
Transfer (site moves)
Vendor ─< Contract ─┬─ Asset
                    └─ SoftwareLicense
SoftwareLicense ─< LicenseKey ── Asset
```

- Assignment history is append-only
- Current assignment = row with in_at IS NULL
- Sites mandatory on Asset, Person, Assignment
- Indexes: asset_tag (unique), (site, status), (warranty_end), (person, in_at), serial_no

---

## 10. API Conventions

- Base path: /api/v1/
- Auth: session (web), token (scanner)
- Errors: RFC 7807 problem JSON
- Pagination: 100 default
- Filters: ?site=, ?status=, ?q=

### Core endpoints

```
GET/POST   /api/v1/assets/
GET        /api/v1/assets/{asset_tag}/
POST       /api/v1/assets/{asset_tag}/check-out/
POST       /api/v1/assets/{asset_tag}/check-in/
POST       /api/v1/assets/{asset_tag}/dispose/
GET        /api/v1/scan/{asset_tag}/
GET        /api/v1/reports/{slug}/?format=csv|xlsx|pdf
```

---

## 11. Auth & Roles

| Role | Can |
|---|---|
| admin | everything |
| technician | receive, check-out/in, transfers, damage, repair |
| auditor | read all + audit mode |
| viewer | read-only, site-scoped |

- Primary: LDAP/AD
- Fallback: local break-glass superuser
- 2FA mandatory for admin in prod

---

## 12. Vendor & Contract Management

### Vendor
- Name, category, contacts, SLA terms
- Supplier on a purchase and Vendor on a contract may differ

### Contract
- Type: support / warranty / subscription / lease
- Fields: vendor, start/end date, value, renewal notice (60d), auto-renew, PO no.
- Renewal alerts: 60d / 14d

---

## 13. Data Quality Rules

- Mandatory fields per category enforced on form + API + import
- serial_no trimmed + uppercased
- Duplicate detection warns on same serial
- CSV import: dry-run → preview → commit (max 5,000 rows)
- QR (primary) + Code 128
- Monthly data-quality report

---

## 14. Notification Matrix

| Event | Channel | Recipients | Timing |
|---|---|---|---|
| Warranty expiring | email | holder + IT lead | 90/30/7 days |
| Contract renewal | email | admin + procurement | 60/14 days |
| License over-assigned | email | admin | weekly |
| Request pending | email | approvers | 1 h |
| Loan overdue | email | holder + tech | due + 3 days |
| Damage reported | email | tech + lead | immediate |
| System error | Telegram | on-call | immediate |

---

## 15. Celery Tasks

| Task | Schedule |
|---|---|
| scan_warranties | daily 07:00 |
| scan_license_seats | daily 07:05 |
| scan_contracts | daily 07:10 |
| data_quality_report | monthly |
| purge_activity_log | monthly |
| send_daily_digest | daily 08:00 |

All tasks must be idempotent.

---

## 16. Scanner / PWA Behavior

- Mode 1: hardware scanner (keyboard-wedge)
- Mode 2: camera scan (PWA)
- Offline queue with idempotency_key
- Device tokens revocable by admin

---

## 17. Performance Targets

| Metric | Target |
|---|---|
| Page render p95 | < 500 ms |
| API p95 | < 300 ms |
| List query (100k rows) | < 100 ms |
| Batch labels (500 QRs) | < 10 s |
| Bulk import (5,000 rows) | < 60 s |

---

## 18. Observability

- Structured JSON logs
- GlitchTip (self-hosted error tracking)
- GET /healthz (DB + Redis)
- Slow queries > 500 ms logged
- Failed Celery beat → alert

---

## 19. Environments

| Env | DB | LDAP | Data |
|---|---|---|---|
| dev | Docker Postgres | off | seed |
| staging | separate PG | mock | anonymized |
| prod | production PG | real AD | real |

---

## 20. Testing

- pytest + pytest-django + factory_boy
- Coverage floor: 85% on services, 70% overall
- Critical paths 100%: check_out/check_in/handover/receive_asset

### Critical path coverage

- check_out / check_in / handover / receive_asset
- All lifecycle transitions
- DisposalRecord guard
- Permission checks
- Idempotency keys
- CSV import dry-run

---

## 21. Git Workflow

- main protected — PRs only
- Branch: feat/, fix/, chore/
- Commit: imperative mood, why over what
- One concern per PR
- ADR for architecture changes

---

## 22. Security Checklist

- [ ] .env, *.pem never committed
- [ ] DEBUG=0 in prod
- [ ] HTTPS + HSTS
- [ ] CSRF on every POST
- [ ] SQL via ORM only
- [ ] Uploads MIME whitelist, 5 MB cap
- [ ] Backups encrypted + offsite
- [ ] UFW + fail2ban
- [ ] Django autoescape ON
- [ ] Break-glass admin in secrets file
- [ ] pip-audit in CI
- [ ] gitleaks pre-commit
- [ ] CSP header
- [ ] Rate limit /api/v1/
- [ ] ActivityLog append-only
- [ ] Password policy (LDAP)
- [ ] Session timeout (8h admin, 30m viewer)

---

## 23. Backup & Disaster Recovery

| | Target |
|---|---|
| RPO | 24 hours |
| RTO | 4 hours |

- pg_dump → restic encrypted → offsite
- Retention: 7 daily / 4 weekly / 6 monthly
- Quarterly restore drill

---

## 24. Deployment

```bash
git clone <repo> /opt/itasset && cd /opt/itasset
cp .env.example .env
docker compose up -d --build
docker compose exec web python manage.py migrate
certbot --nginx -d assets.example.com
```

### Rollback decision matrix

| Situation | Action |
|---|---|
| App bug, no schema change | git checkout + rebuild |
| Additive migration | Keep DB, rollback code |
| Destructive migration | Restore from backup |
| Data corruption | Full DR restore |
| Security incident | Rotate secrets, then rollback |

---

## 25. Compliance & Retention

| Data | Retention |
|---|---|
| ActivityLog | 24 months |
| Assignment history | lifetime + 7 years |
| Disposal records | 7 years |
| Person records | 2 years after exit |

- ISO/IEC 19770 aligned
- NIST SP 800-88 sanitization methods

---

## 26. Documentation Set

| Doc | Audience |
|---|---|
| README.md | devs |
| DEVELOPMENT.md | devs (this file) |
| CHANGELOG.md | all |
| docs/PROGRESS.md | devs |
| GLOSSARY.md | all |
| docs/user-manual.md | end users (Burmese) |
| docs/category-schema-design.md | devs |
| docs/deploy-ubuntu.md | ops |
| docs/adr/NNNN-*.md | devs |

---

## 27. Integrations Roadmap

| Phase | Integration |
|---|---|
| v1 | CSV/Excel import & export |
| v1.5 | Network discovery import |
| v2 | Intune / Entra ID |
| v2 | Finance export |
| v2 | Helpdesk bridge |

---

## 28. Milestones

| Phase | Deliverable | Done when |
|---|---|---|
| M1 — Foundation | Compose scaffold, models, admin | seed + CRUD works |
| M2 — Core flow | CRUD, check-out/in, roles, CSV | track 100 assets |
| M3 — Labels & API | QR/PDF, /api/v1/, scanner | label → scanned → assigned |
| M4 — Alerts & licenses | Celery tasks, email | test warranty email |
| M5 — LDAP & audit | AD login, audit mode | audit report |
| M6 — Intake & lifecycle | Request → dispose | full lifecycle |
| M7 — Reporting & vendors | report suite | depreciation XLSX |
| M8 — Go-live | deploy, DR drill | restore drill passed |

> 📌 Live status: see docs/PROGRESS.md

---

## 29. Definition of Done

1. Code follows §8; make lint passes
2. Tests cover new behavior; make test passes
3. Critical-path tests if applicable
4. Migration included (or 'no schema change')
5. Permissions enforced
6. Strings translated (my + en)
7. Retention/privacy impact checked
8. Security checklist re-reviewed
9. Docs updated
10. CHANGELOG entry

---

## 30. Glossary

See GLOSSARY.md for the full list.

---

## 31. Makefile Reference

| Target | Purpose |
|---|---|
| make install | Create venv + install deps |
| make up-db / make down-db | Start/stop dev DB |
| make run | runserver |
| make worker / make beat | Celery |
| make migrate | makemigrations + migrate |
| make seed | load demo data |
| make lint / make format | ruff |
| make test | pytest + coverage |
| make audit | pip-audit |
| make check-deploy | Django deploy check |
| make build / make up | Docker |
| make openapi | regenerate schema |
| make backup / make restore | scripts |

---

## Appendix — Version history

| Version | Date | Changes |
|---|---|---|
| 1.1.0 | 2026-10-12 | Header metadata; English only; moved progress log to docs/PROGRESS.md; added §30 Glossary + §31 Makefile; expanded §4 wireframe; §5 version pinning; §22 security items; §20 critical paths; §24 rollback matrix. |
| 1.0.0 | 2026-10-11 | Initial version. |

---

**End of Document**