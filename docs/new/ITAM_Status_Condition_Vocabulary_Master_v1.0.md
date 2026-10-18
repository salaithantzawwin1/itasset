# IT Asset Management System
# Status & Condition Vocabulary — Unified Master List

**Version:** 1.0
**Date:** 2026-10-15
**Status:** Proposed for business-owner sign-off
**Purpose:** Reconcile the three conflicting status/condition vocabularies into one agreed list
and define the crosswalk for migration.

**Sources reconciled:**

| Source | Document | List |
|---|---|---|
| **A** | `IT_Asset_Management_Technical_Specification_v1.0.md` §7.1 | `DRAFT, IN_STOCK, AVAILABLE, RESERVED, ASSIGNED, IN_TRANSIT, UNDER_INSPECTION, IN_MAINTENANCE, MISSING, RETIRED, DISPOSED` |
| **B** | `ITAM_Common_Asset_Fields_Category_Specific_Specifications_Master.md` §3.3 | `Draft, Requested, Pending Approval, In Stock, In Service, In Repair, On Loan, Lost, Stolen, Retired, Disposed` |
| **C** | Current code (`apps/assets/models.py`) + `GLOSSARY.md` | `IN_STOCK, AVAILABLE, ASSIGNED, IN_REPAIR, IN_TRANSIT, RETIRED, DISPOSED` |

**Companion document:** `ITAM_Gap_Analysis_Report_v1.0.md`.

---

## 1. Reconciliation Principles

1. **Request states never appear in asset status.** Spec A §7.1 is explicit: *"Do not mix
   REQUESTED or APPROVED into asset status; those belong to the request/approval workflow."*
   Source B violates this (`Requested`, `Pending Approval`) — those map to `AssetRequest`, not
   `Asset.status`.
2. **Lifecycle status ≠ condition ≠ operational state.** Three separate concerns
   (Spec B §3.3 itself distinguishes them).
3. **Custody is modeled by `Assignment`, not by status.** "On Loan"/"In Service" collapse into
   `ASSIGNED` + assignment row (`due_at` already exists).
4. **Minimize code churn:** current Source-C tokens (verified against live code and tests) are the
   backbone; new tokens are added only where the specs add real workflow value.
5. One token = one meaning everywhere (models, API, reports, UI, i18n, seed data, tests).

---

## 2. Unified Asset Lifecycle Status (agreed target list)

| # | Token | Label | Max 12? | From | Notes |
|---|---|---|---|---|---|
| 1 | `DRAFT` | Draft | ✅ | A, B | Optional — imported/unapproved records. **Decision D1.** |
| 2 | `IN_STOCK` | In stock | ✅ | A, B, C | Received/tagged, not yet released. |
| 3 | `AVAILABLE` | Available | ✅ | A, C | Ready to assign. Spec B's "In Service" splits into 3/4. |
| 4 | `RESERVED` | Reserved | ✅ | A | Held for an approved request (Spec A §8.1 step 7). **Decision D2.** |
| 5 | `ASSIGNED` | Assigned | ✅ | A, C | Holder = active `Assignment` row. |
| 6 | `IN_TRANSIT` | In transit | ✅ | A, C | Site/company transfer in progress. |
| 7 | `UNDER_INSPECTION` | Under inspection | ❌ (17 ch) | A | Returned, pending inspection (Spec A §8.2). Needs `max_length` widen. **Decision D3.** |
| 8 | `IN_REPAIR` | In repair | ✅ | C | = A's `IN_MAINTENANCE`, B's "In Repair". **Decision D4** (keep vs rename). |
| 9 | `MISSING` | Missing | ✅ | A | = B's "Lost"/"Stolen" (+ cause). **Decision D5.** |
| 10 | `RETIRED` | Retired | ✅ | A, B, C | No longer in service; excluded from available stock. |
| 11 | `DISPOSED` | Disposed | ✅ | A, B, C | Terminal; sanitization evidence required. |

**Technical note:** `Asset.status` is `max_length=12`. `UNDER_INSPECTION` (17) and
`IN_MAINTENANCE` (15) do not fit — adopting either requires a schema migration to widen the field.
All other tokens fit today.

### 2.1 Excluded values → where they go instead

| Source value | Rationale | Maps to |
|---|---|---|
| B: `Requested` | Request state, not asset state (principle 1) | `AssetRequest.status` ≈ `SUBMITTED` |
| B: `Pending Approval` | " | `AssetRequest.status` ≈ `PENDING_APPROVAL` |
| B: `In Service` | Ambiguous — hides custody | Split: `AVAILABLE` or `ASSIGNED` (by active assignment) |
| B: `On Loan` | Custody, not lifecycle | `ASSIGNED` + `Assignment.due_at` |
| B: `Lost` / `Stolen` | Investigation outcome, not distinct state | `MISSING` + cause (`WriteOff.Cause` has `THEFT`; `DisposalRecord.Method.NOT_APPLICABLE` = stolen) |
| A: `REQUESTED`, `APPROVED` | Explicitly prohibited by Spec A §7.1 | `AssetRequest.status` |

---

## 3. Condition (physical/functional) — unified

**Agreed list = current five (Source C). No code change.**

| Token | Label | A | B |
|---|---|---|---|
| `NEW` | New | — | `New`, `Excellent` (D6) |
| `GOOD` | Good | condition | `Good` |
| `FAIR` | Fair | condition | `Fair` |
| `POOR` | Poor | condition | `Poor` |
| `DAMAGED` | Damaged | condition | `Damaged`, `Unserviceable` (D7) |

Used by: `Asset.condition`, `Assignment.condition_out`, `Assignment.condition_in`
(`max_length=12` — all fit).

### 3.1 Operational status (Spec B only)

`Working / Partially Working / Not Working / Not Tested / Not Applicable` — **recommendation: do
not add a third top-level enum.** Record as a category specification field or inspection result
(Spec B §4 model) where a category needs it. **Decision D8.**

---

## 4. Crosswalk tables (migration)

### 4.1 Source A → unified

| A | Unified |
|---|---|
| `DRAFT` | `DRAFT` (if D1 = yes) else not adopted |
| `IN_STOCK` | `IN_STOCK` |
| `AVAILABLE` | `AVAILABLE` |
| `RESERVED` | `RESERVED` (if D2 = yes) |
| `ASSIGNED` | `ASSIGNED` |
| `IN_TRANSIT` | `IN_TRANSIT` |
| `UNDER_INSPECTION` | `UNDER_INSPECTION` (if D3 = yes) |
| `IN_MAINTENANCE` | `IN_REPAIR` (D4) |
| `MISSING` | `MISSING` (if D5 = yes) |
| `RETIRED` | `RETIRED` |
| `DISPOSED` | `DISPOSED` |

### 4.2 Source B → unified

| B | Unified | Action |
|---|---|---|
| `Draft` | `DRAFT` | per D1 |
| `Requested` | — | `AssetRequest` |
| `Pending Approval` | — | `AssetRequest` |
| `In Stock` | `IN_STOCK` | identity |
| `In Service` | `AVAILABLE` or `ASSIGNED` | split by active assignment |
| `In Repair` | `IN_REPAIR` | identity |
| `On Loan` | `ASSIGNED` | assignment carries `due_at` |
| `Lost` | `MISSING` | per D5 |
| `Stolen` | `MISSING` | + cause theft |
| `Retired` | `RETIRED` | identity |
| `Disposed` | `DISPOSED` | identity |

### 4.3 Source C (current code) → unified

All seven tokens keep their exact values — **no data migration for existing rows** beyond adding
new-choice rows (1, 4, 7, 9) when adopted.

---

## 5. Allowed Transitions (target state machine)

Legend: **(C)** = current behavior verified in `apps/assets/services.py`; **(N)** = new with adoption.

```
(DRAFT) ──────────────▶ IN_STOCK                      (C: import creates IN_STOCK)
IN_STOCK ─────────────▶ AVAILABLE                     (C: receive & tag)
AVAILABLE ─(reserve)──▶ RESERVED ─(assign)──▶ ASSIGNED   (N, per D2)
AVAILABLE ────────────▶ ASSIGNED                     (C: check-out)
RESERVED ─(cancel)────▶ AVAILABLE                    (N)
ASSIGNED ─(handover)──▶ ASSIGNED                     (C)
ASSIGNED ─(return ok)─▶ AVAILABLE                    (C)
ASSIGNED ─(return bad)▶ IN_REPAIR                    (C: condition DAMAGED)
ASSIGNED ─(dispatch)──▶ IN_TRANSIT                   (C)
IN_TRANSIT ─(receive)─▶ AVAILABLE / IN_STOCK / IN_REPAIR (C: arrival; damaged → IN_REPAIR)
ASSIGNED/AVAILABLE ──▶ UNDER_INSPECTION ─▶ AVAILABLE / IN_REPAIR   (N, per D3)
IN_REPAIR ─(repaired)─▶ AVAILABLE                    (C)
IN_REPAIR ─(write-off)▶ RETIRED                      (C: admin decision)
any non-terminal ─────▶ MISSING                      (N, per D5)
MISSING ─(found)──────▶ AVAILABLE / RETIRED          (N)
RETIRED ─(sanitize)───▶ DISPOSED                     (C: DisposalRecord required)
DISPOSED = terminal                                   (C)
```

Invalid transitions keep returning typed errors (HTTP 409 semantics — see gap report §3.5).

---

## 6. Request Status (secondary reconciliation)

| Unified target | Current code | A §7.2 | B §3.3 |
|---|---|---|---|
| `SUBMITTED` | `PENDING` | `SUBMITTED` | `Requested` |
| `IN_REVIEW` | — (add with approval engine) | `IN_REVIEW` | — |
| `PENDING_APPROVAL` | `PENDING` | `PENDING_APPROVAL` | `Pending Approval` |
| `APPROVED` | `APPROVED` | `APPROVED` | — |
| `REJECTED` | `REJECTED` | `REJECTED` | — |
| `PROCURED` | `PROCURED` (keep — receiving stage) | — | — |
| `FULFILLED` | `FULFILLED` | `FULFILLED` | — |
| `CLOSED` | — (optional; ≈ FULFILLED) | `CLOSED` | — |
| `CANCELLED` | `CANCELLED` | `CANCELLED` | — |
| `DRAFT` | — (only if request drafting allowed) | `DRAFT` | — |

**Minimal-churn recommendation:** keep the current six; add `IN_REVIEW` only when the approval
engine (gap report §3.2) lands. Map A/B drafts and closed states per the table when needed.

## 7. Transfer Status (secondary)

| Unified | Current code | Spec A §8.3 |
|---|---|---|
| `PENDING` | `PENDING` (pending dispatch) | request + approval |
| `IN_TRANSIT` | `IN_TRANSIT` | dispatch (location updates only at receipt) |
| `RECEIVED` | `RECEIVED` | receipt (single transaction) |
| `EXCEPTION` | `EXCEPTION` | discrepancy → review, never silent complete |

No change required; if the approval engine adds an explicit approve step, insert `APPROVED`
between `PENDING` and `IN_TRANSIT` (Decision D9).

---

## 8. Where These Values Appear in Code (change impact)

Any token change touches: `apps/assets/models.py` (Status/Condition choices + `max_length`),
`apps/assets/services.py` (state machine), `apps/api/serializers.py`
(`status_display`), `apps/assets/admin.py` (admin forms), `apps/reports/queries.py` (filters), `apps/assets/management/commands/seed_demo.py`,
templates (status badges), `apps/dashboard/i18n.py` (EN/MM labels), tests
(`test_services.py`, `test_lifecycle.py`, `test_crud_views.py`, API tests), plus documentation:
`GLOSSARY.md`, `DEVELOPMENT.md` §3, `docs/category-schema-design.md`.
A `choices=` change also generates an `AlterField` migration (values are app-level, but keep
migrations in sync per repo policy).

---

## 9. Open Decisions (business-owner sign-off)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| D1 | Adopt `DRAFT` asset state? | Yes / No (imports start `IN_STOCK`) | Yes, for migrated/unapproved records only |
| D2 | Adopt `RESERVED`? | Yes / No | Yes, once approval→fulfilment flow needs holds |
| D3 | Adopt `UNDER_INSPECTION`? (widen field) | Yes / No (damaged returns → `IN_REPAIR` directly, current behavior) | Yes — Spec A §8.2 acceptance test #8 depends on it |
| D4 | `IN_REPAIR` vs rename `IN_MAINTENANCE` | Keep `IN_REPAIR` / rename | **Keep `IN_REPAIR`** — covers repair+preventive; rename touches models, services, tests, reports, i18n, seed, DB for zero behavior gain |
| D5 | Adopt `MISSING`? | Yes / No (retire directly) | Yes — Spec A §6.12/§14.2 audit discrepancies need it |
| D6 | `Excellent` condition value | Add / map to `NEW` | Map to `NEW` (avoid synonym drift) |
| D7 | `Unserviceable` condition value | Add / map to `DAMAGED` | Map to `DAMAGED` |
| D8 | Operational status enum | Top-level column / spec field / none | Spec field per category |
| D9 | `APPROVED` step in transfer states | With approval engine / later | With approval engine |

**Sign-off:**

| Role | Name | Date |
|---|---|---|
| Business owner | | |
| IT lead | | |
| Auditor (review) | | |

---

**End of Document**
