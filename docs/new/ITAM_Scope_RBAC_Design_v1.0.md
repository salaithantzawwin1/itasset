# IT Asset Management System
# Scope-Based RBAC — Design

**Version:** 1.0
**Date:** 2026-10-15
**Status:** Proposed for review (implementation not started)
**Sources:** Spec A §5, §9.1 (`roles/permissions/user_access_scopes`), §10, §14.2;
Spec B §9.4, §11; gap report workstreams 2–3 (`ITAM_Gap_Analysis_Report_v1.0.md` §3.1).
**Estimated effort:** 4–6 person-weeks (gap report row 2) + 2–3 pw org hierarchy (row 3).

---

## 1. Design Principles

1. **Role = what actions. Scope = which records.** (Spec A §5.2.) Current code has only the
   first half — this design adds the second.
2. **Deny by default.** No scope row → no access (except the employee self-view in §4.4).
   Errors, missing data, and exceptions fail **closed**, never open.
3. **Server-side, every layer.** Views, API, admin, exports, and reports all enforce the same
   helper — hiding UI controls is cosmetic only (Spec B §9.4).
4. **No ambiguous polymorphic FKs.** Spec A §9.1 warns against `scope_type + generic id`
   patterns; use typed columns validated by DB constraints.
5. **Never trust client org fields.** `site_id`/`department_id` submitted by the browser is
   validated against the caller's scope, never used to grant access (Spec A §5.3).
6. **Every privileged scope change is audited with a reason** (Spec A §5.3).

---

## 2. Organization Hierarchy Decision

Spec A §5.1 proposes `Group → Company → Branch → Department / Location`. The current system has
**`Site` + `Department` + `Person`** — a single legal entity with multiple sites (verified: no
Company/Group model exists anywhere; `Asset.site` is the only org reference).

### 2.1 Options

| Option | Description | Verdict |
|---|---|---|
| **O1** | Adopt full Group→Company→Branch now | Rejected for now — no multi-entity business requirement confirmed (Spec A §18#1 still unanswered); heavy migration (every model gains FKs) before any value ships |
| **O2** | Overload `Site` to mean "branch" and add company semantics later into the same table | Rejected — conflates physical site with legal entity; Spec A §5.1 explicitly warns against name-duplication shortcuts |
| **O3 (recommended)** | **Two-phase:** Phase 1 scopes = `GLOBAL / SITE / DEPARTMENT` over current models; Phase 2 adds `Company` as a real model **without redesigning scopes** | Accepted for design — ships deny-by-default in weeks; Phase 2 is additive (nullable `Site.company` FK + one new scope type) |

### 2.2 Spec A entity → current model mapping

| Spec A | Current code | Phase |
|---|---|---|
| Group | — (single group today) | later, if ever |
| Company | — (implicit "the company") | Phase 2 (additive) |
| Branch | `people.Site` | Phase 1 (scope type `SITE`) |
| Department | `people.Department` | Phase 1 (scope type `DEPARTMENT`) |
| Location/room | — (free-text remarks today) | optional later; not a scope type until it exists |

**Decision required (D-org):** confirm single-company vs multi-company. If multi-company is real,
Phase 2 starts immediately after Phase 1 enforcement — the scope table below already reserves the
pattern.

---

## 3. Role Model (action layer — unchanged roles, tightened reads)

Keep the four existing Django groups (`admin / technician / auditor / viewer` —
`apps/core/roles.py`, LDAP group mapping in `apps/accounts/rolesync.py`):

| Action class | admin | technician | auditor | viewer | unauthenticated |
|---|:--:|:--:|:--:|:--:|:--:|
| Scope administration (grant/revoke) | ✅ | ❌ | ❌ | ❌ | 401 |
| Create/edit assets, lifecycle commands | ✅ | ✅ (in scope) | ❌ | ❌ | 401 |
| Approve requests / decide write-offs | ✅ | ❌* | ❌ | ❌ | 401 |
| Read (list/detail/export/report) | ✅ in scope | ✅ in scope | ✅ in scope | ✅ in scope | 401 |
| Physical audit, labels | ✅ | ✅ in scope | ✅ read | ❌ | 401 |

\* current behavior: `decide_request` is admin-only (`services.py` §11); approval engine (gap §3.2)
will re-map this row.

**Key change:** the "reads: anything opens to any authenticated user" rule in `roles.py` and
`api/permissions.py` is **replaced** by "reads: anything in your scope" — the role decides the
*action*, the scope decides the *rows*.

**Superuser = break-glass.** `is_superuser` implies GLOBAL scope, but per Spec A §11.2 every
superuser login and every superuser mutation should emit an ActivityLog event so emergency use is
visible (alerting itself = gap workstream 11).

---

## 4. `UserAccessScope` Schema

### 4.1 Model (proposed — new file `apps/core/models.py` or `apps/accounts/models.py`)

```python
class UserAccessScope(models.Model):
    """Which records a user may act on (Spec A §5.2, §9.1). Deny by default:
    a user with no active rows has no access beyond §4.4 self-view."""

    class ScopeType(models.TextChoices):
        GLOBAL = "GLOBAL", "All records"          # full visibility (policy-approved)
        SITE = "SITE", "Site"                     # people.Site
        DEPARTMENT = "DEPARTMENT", "Department"   # people.Department

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="access_scopes"
    )
    scope_type = models.CharField(max_length=12, choices=ScopeType.choices)

    # Exactly one of these is set, matching scope_type (enforced by CheckConstraint).
    site = models.ForeignKey("people.Site", null=True, blank=True,
                             on_delete=models.CASCADE, related_name="user_scopes")
    department = models.ForeignKey("people.Department", null=True, blank=True,
                                   on_delete=models.CASCADE, related_name="user_scopes")

    valid_from = models.DateField(null=True, blank=True)   # NULL = open start
    valid_to = models.DateField(null=True, blank=True)     # NULL = open end
    reason = models.CharField(max_length=255)              # required: why granted
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                    related_name="scopes_granted")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=(scope_type == SITE and site IS NOT NULL and department IS NULL)
                      or (scope_type == DEPARTMENT and department IS NOT NULL and site IS NULL)
                      or (scope_type == GLOBAL and site IS NULL and department IS NULL),
                name="scope_typed_columns",
            ),
        ]
        indexes = [models.Index(fields=["user", "scope_type"])]
```

*(constraint shown as pseudocode; implemented with `Q()` objects in Django.)*

### 4.2 Design rationale

| Choice | Why |
|---|---|
| Typed nullable FKs + CHECK | Spec A §9.1 — avoids ambiguous polymorphic references; DB, not just app, validates |
| `GLOBAL` as an explicit type | Keeps "no rows = deny" semantics distinguishable from "has full access"; superuser backfill writes a GLOBAL row instead of a magic flag |
| `reason` + `created_by` NOT NULL | Spec A §5.3 — privileged scope changes carry reason + audit |
| Date window | Spec A §9.1 `valid_from/valid_to` — temporary grants (contractors, rotation) expire themselves |
| `CASCADE` on user | Removing the user removes scopes; scope history for audit lives in ActivityLog, not in orphan rows |
| Phase-2 Company | add `company` FK column + `ScopeType.COMPANY`; no redesign |

### 4.3 Effective-scope semantics

```
effective_scopes(user):
  if not user.is_authenticated        -> DENY
  if user.is_superuser                -> GLOBAL  (break-glass; audited)
  rows = user.access_scopes active in [today within valid_from..valid_to]
  if rows contains GLOBAL             -> GLOBAL
  else                                -> {sites} ∪ {departments}
```

- **Union semantics:** multiple rows add visibility; a user scoped to Site A *and* Department X
  sees the union.
- **Department scope** filters People and Requests by department; Assets are visible when their
  `site` is in scope **or** their current custodian is in the scoped department (decision D-scope:
  confirm asset visibility rule — recommendation = site-primary, department as person-data scope
  only, to keep asset queries index-friendly).
- **Fail closed:** any exception inside scope resolution → DENY + ActivityLog warning.

### 4.4 Employee self-view (the one carve-out)

Spec A §5.2 gives Employees "own requests and current/past assigned assets". Today **no link
exists between `auth.User` and `people.Person`** (`Person` has `ldap_uid`/`email` only — verified).
Required addition:

- `Person.user = OneToOneField(User, null=True, blank=True, on_delete=SET_NULL, related_name="person")`
- Resolution order at login/first access: `ldap_uid` ↔ LDAP username, else verified email.
- A user with **zero** scope rows but a linked Person gets exactly: own `Assignment` history,
  own `AssetRequest` rows, and read-only detail of assets currently assigned to them.
- A user with zero scopes and **no** linked Person gets nothing (404 everywhere) — this is
  deliberate deny-by-default and must be communicated in rollout notes.

**Implemented 2026-10-16:** `Person.user` added (`apps/people/models.py`, migration
`people.0003_person_user`); login auto-link in `apps/accounts/personlink.py`
(`ldap_uid` first, else a **unique** active `email` match — ambiguous matches are refused, and a
link failure never blocks a login). The carve-out lives in `apps/core/scopes.py` (`linked_person` /
`self_view_q` / `_self_view_allows`, applied inside `scope_queryset` and `check_scope` **only when
the scope set is empty**) and is surfaced at `/me/` (`assets.SelfView` →
`templates/assets/self_view.html`, "My assets" in the nav).

---

## 5. Deny-by-Default Enforcement Plan

### 5.1 Single source of truth — `apps/core/scopes.py` (new)

```python
def effective_scopes(user) -> ScopeSet            # §4.3, fail closed
def scope_queryset(user, qs, *, site_field="site", dept_field=None) -> qs   # GLOBAL -> qs unchanged
def user_in_site(user, site) -> bool
def user_in_department(user, department) -> bool
def require_scope(user, obj) -> None              # raises OutOfScope (404) / Forbidden (403)
```

Every layer below calls **only** these helpers — no per-view reimplementation.

### 5.2 Enforcement points (current code touchpoints)

| Layer | Rule | Status code policy |
|---|---|---|
| **List views** (`apps/assets`, `apps/people`, `apps/audit`, `apps/reports` index) | `scope_queryset()` applied before pagination | rows simply absent |
| **Detail views** (asset/person/transfer/…) | `require_scope(user, obj)` before render | **404** — out-of-scope looks identical to nonexistent (Spec A §10.1, no existence leak) |
| **Mutations** (check-out/in, receive, edit, delete) | object scope check **and** target-org fields validated against scope | 404 out-of-scope object; **403** in-scope-but-forbidden action (role) |
| **Create forms** | client-supplied `site_id`/`department_id` must be in scope — ignored/rejected otherwise | 403 (never silent re-map) |
| **API** (`apps/api`) | new `IsInScope(BasePermission)` default-deny for **all** methods incl. SAFE; `get_queryset()` = `scope_queryset()`; scanner token inherits token owner's scope | 401 unauthenticated, 403 authenticated-but-out-of-scope action, 404 out-of-scope object |
| **Exports/reports** (`apps/reports` views + exporters) | same `scope_queryset()` before aggregation/export | exported file contains only scoped rows (Spec A §14.2 #13) |
| **Django admin** | `get_queryset(request)` scoped on Asset/Site/Person/Assignment/Transfer/Request admin classes; add-links hidden outside scope; direct `/admin/.../{id}/change/` URL still checked | 404 |
| **Attachments** | `/api/v1/attachments/` — scope-checked list/upload/download through the owning record's scope (Spec A §6.13); files live in `PRIVATE_MEDIA_ROOT` with no URL | 404 |
| **Templates/nav** | optionally hide out-of-scope menu items | *cosmetic only — never the control* |

### 5.3 Audit

- `scope_grant` / `scope_revoke` ActivityLog events: actor, target user, scope, reason
  (reason required by model constraint).
- Cross-scope administrative actions (GLOBAL user touching another site) also logged —
  Spec B §9.4 "audit logs should record cross-scope administrative actions".
- Superuser mutations logged (break-glass visibility, Spec A §11.2 #5/#6).

### 5.4 Staged rollout (avoid locking everyone out)

| Stage | Change | Gate |
|---|---|---|
| **A — Record** | Ship `UserAccessScope` model + admin UI + grant existing users explicit scopes (admin→GLOBAL; technicians→their sites; **review list** printed for anyone still unscoped) | scope inventory signed off |
| **B — Shadow** | `SCOPE_ENFORCEMENT=False` flag: helpers run and log *"would deny"* events, UI unchanged | one week of deny-log review; zero false denials |
| **C — Enforce** | Flip flag for list/detail/API/exports for **non-superusers** | full suite green incl. new IDOR tests (§6) |
| **D — Admin + review** | Scope Django admin; enable break-glass ActivityLog alerts; remove legacy "reads open" code paths | IDOR list §6 all passing; sign-off |

Flag: `SCOPE_ENFORCEMENT_ENABLED` in settings (`base.py`), default **False**, forced True in tests
so regressions fail CI. Rollback = flag off (Stage C/D reversible; Stage A data is harmless).

---

## 6. IDOR / Scope-Bypass Test List

New file `tests/test_scopes.py` (top-level `tests/` package — `apps/core/tests.py` already exists
as a module). Fixtures: two sites (A, B), users per role per site, assets in each. **All tests run
with `SCOPE_ENFORCEMENT_ENABLED=True`.**

| # | Test | Actor → action | Expected | Spec ref |
|---|---|---|---|---|
| 1 | list isolation (HTML) | technician A → GET asset list | only site-A rows rendered | §5.3 |
| 2 | list isolation (API) | technician A token → GET `/api/v1/assets/` | only site-A rows | §14.2 #13 |
| 3 | detail by ID | technician A → GET site-B asset `{pk}` | **404** | §14.2 #1 |
| 4 | detail by ID (API) | technician A → GET `/api/v1/assets/{B-pk}/` | **404** | §14.2 #1 |
| 5 | mutation by ID | technician A → POST check-out on site-B asset | **404** | §14.2 #1 |
| 6 | destructive by ID | technician A → admin delete URL for site-B asset | **404** | §14.2 #1 |
| 7 | forged org field | technician A → create/edit asset with `site=B` in POST | **403**, row not created | §5.3 |
| 8 | export bypass | technician A → CSV export with `?site=B` / export all | only site-A rows in file | §14.2 #13 |
| 9 | report bypass | technician A → report endpoints (`reports/<slug>.csv`) | aggregates exclude site B | §14.2 #13 |
| 10 | scanner scope | scanner token (tech A) → `GET /api/v1/scan/{B-tag}/` | **404** | §5.3 |
| 11 | transfer scope | technician A → dispatch/receive transfer containing site-B assets | **404** | §5.3 |
| 12 | admin changelist | technician A → `/admin/assets/asset/` | only site-A assets | §5.3 |
| 13 | admin direct URL | technician A → `/admin/assets/asset/{B-pk}/change/` | **404** | §14.2 #1 |
| 14 | zero-scope user | authenticated user, no scope rows, no Person link | empty lists, detail **404** | deny-by-default |
| 15 | employee self-view | linked Person → GET own assignments/requests, then another user's asset detail | own rows only; detail **404** | §5.2 |
| 16 | expired scope | scope with `valid_to` yesterday → list/detail | denied (as zero-scope) | §9.1 |
| 17 | scope escalation | non-admin → `POST .../users/{self}/scopes` (or any scope-write path) | **403** (admin-only endpoint) | §5.3 |
| 18 | department scope | department user → people list | own department only | §5.2 |
| 19 | role × scope cross | viewer A (right scope, wrong role) → check-out | **403** (role gate, not scope) | §5.3 |
| 20 | audit of scope change | admin grants scope without reason / non-admin tries | 400 missing reason / 403; grant emits ActivityLog | §5.3 |
| 21 | concurrent check-out *(paired with gap workstream 7)* | two parallel `check_out` on one asset | exactly one active assignment (partial unique index) | §14.2 #5 |
| 22 | self-approval | requester approves own request | **403** (`SelfApprovalForbidden`) | §14.2 #3 |
| 23 | attachment guess | user B's token → download A's attachment by ID | **404** | §14.2 #9 |

**Rows 22 + 23 shipped 2026-10-16 (second drop).** Row 22 has both layers: the service raises
`SelfApprovalForbidden` (a subclass of `NotAuthorized`, the HTTP layer's 403) whenever
`actor == request.requester` on approve *or* reject, and the wire exposes it at
`POST /api/v1/requests/{id}/approve|reject/` (admin role, scoped request → 404, wrong state → 409).
Row 23 shipped with the **attachments module** (`apps/attachments`, gap §3.4): typed owner FKs +
DB CHECK `attachment_exactly_one_owner`, private storage (`PRIVATE_MEDIA_ROOT`, `base_url=None`
so Django itself refuses to build a URL), scope-checked list/upload/download at
`/api/v1/attachments/`, and authorization through the owning record's scope — assets/requests
follow their site, transfers follow either end (v1 union rule). The canary test is retired in
favour of the real row-23 assertions.

**Rows 17 + 20 shipped 2026-10-16 (third drop).** The scope-write path now exists, so both rows
are tested against the real endpoint instead of being held by unit tests:
`GET|POST /api/v1/users/{id}/scopes/` and `DELETE /api/v1/users/{id}/scopes/{scope_id}/`, both
`IsAdmin`-gated (row 17: technician POST/GET/DELETE → **403**, anonymous → **401**, before the
payload is read) and both routed through one service, `apps/core/scopeadmin.py`. Row 20 lives
there too: a missing/blank `reason` → **400** with no row written, the typed site/department
pairing and the `valid_from/valid_to` window are validated *before* save (so the DB CHECK
`scope_typed_columns` can never surface as a 500), and every successful grant or revoke emits a
`scope_grant` / `scope_revoke` ActivityLog event carrying actor, target user, scope and reason.
The Django admin path (`UserAccessScopeAdmin.save_model` / `delete_model` / `delete_queryset`)
calls the same audit, so no scope write escapes the log — the last bullet of gap §3.1
("audit + reason for privileged scope changes") is closed.

**Implementation status (2026-10-16, third drop):** rows 1–16, 17, 18, 19, 20, 21, 22, 23 — i.e.
**all 23 rows — are implemented and passing**; nothing is deferred. `tests/test_scopes.py` holds
38 tests (shadow + enforced, incl. Stage D admin rows, transfer dispatch/receive **and
create/edit** scope gates, the active-assignment concurrency
backstop — DB partial unique index `uniq_active_assignment_per_asset` + IntegrityError→
AssetAlreadyAssigned conversion in `check_out`, plus a real-thread race on Postgres — and the
§4.4 employee self-view with its login auto-link) plus 9 module tests in
`apps/attachments/tests.py`. Wired choke points: `check_scope` /
`scope_list` / `ScopeGuardMixin`
(`apps/core/scopes.py`) for views/API/exports, `attachment_scope_q` / `scope_attachments`
(`apps/attachments/scopes.py`) for files, plus `ScopedAdminMixin` (`apps/core/admin.py`)
for Django admin querysets — with a 404 (not the stock redirect) for out-of-scope change URLs
under enforcement. Feature tests that are not about scope grant their fixture users a GLOBAL
scope, so deny-by-default stays covered exclusively by `tests/test_scopes.py`.

**Stage C is LIVE on the server (2026-10-15):** `SCOPE_ENFORCEMENT_ENABLED=1` in `.env`,
gunicorn restarted; after the three 2026-10-16 drops (rows 15/22/23 + 17/20 +
`people.0003_person_user` + `attachments.0001_initial`) the full suite is **190 passed + 60
subtests** green with the flag on.
Scopes:
`admin`/`itadmin` GLOBAL (break-glass accounts); `ittech` SITE scopes for all three active sites
(yangon/mandalay/naypyitaw — technician baseline; revoke a row to narrow him). Shadow review:
`manage.py scope_shadow_report`. Live authenticated check of the carve-out (2026-10-16): a
temporary zero-scope employee saw `/me/` 200 with own rows only, own asset detail 200, foreign
detail 404 — then the account was removed.

**Acceptance:** the §6 table passes with `SCOPE_ENFORCEMENT_ENABLED=True` (Stage C gate) and the
existing suite (**190 passed + 60 subtests**, verified 2026-10-16 on `itasset-dev`, exit 0) stays
green — all 23 rows have an endpoint-level test, no row deferred. Rows 17/20 were additionally
replayed live through nginx (`http://192.168.100.142:80`, 20/20 expectations: 403 technician,
401 anonymous, 400 missing reason, 201 grant + audit, 204 revoke + audit, zero leftover rows).

---

## 7. Open Decisions

| # | Decision | Recommendation |
|---|---|---|
| D-org | Single company forever, or multi-company needed? (Spec A §18#1) | Confirm before Phase 2; Phase 1 ships either way |
| D-scope | Department scope: people-data only, or also asset visibility? | Site-primary; department = people/requests scope |
| D-backfill | Existing users' initial scopes | admins → GLOBAL with review; technicians → named sites; everyone else reviewed individually (Stage A report) |
| D-employee | Adopt `Person.user` OneToOne link? | Yes — required for employee self-view (Spec A §5.2) |
| D-flag | Enforcement flag name/location | `SCOPE_ENFORCEMENT_ENABLED` in `config/settings/base.py`, forced True in tests |
| D-transfer | Transfer visibility for the receiving site (v1 open question) | **Resolved 2026-10-16: keep the union** — either end sees the transfer and its cargo before receipt (list + attachment download); *edits* stay sender-side (`from_site` in scope), so a receiver reads with 200 but patches with 403 |

---

## 8. Implementation Sequence (fits gap report §5)

1. `apps/core/scopes.py` helpers + `UserAccessScope` model + migration + admin (Stage A).
2. Backfill report + scope admin UI with required `reason` (audit wiring).
3. List/detail/create views → API → exports/reports → Django admin (one PR per layer).
4. `Person.user` link + employee self-view.
5. Stage B shadow logging → review → Stage C flip → §6 test list green.
6. Update `GLOSSARY.md`/`DEVELOPMENT.md` §11 (role matrix) to describe role+scope semantics.

---

**End of Document**
