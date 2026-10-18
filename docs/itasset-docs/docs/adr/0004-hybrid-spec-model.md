# ADR 0004 — Hybrid Spec Model for Category-Specific Fields

**Date:** 2026-10-12
**Status:** Accepted
**Deciders:** IT Infrastructure Team

## Context

Different asset categories have fundamentally different technical specifications:

- Laptop / Desktop: CPU, RAM, storage, motherboard, GPU, OS
- Monitor: screen size, resolution, panel type, refresh rate, inputs
- Server: hostname, role, environment, rack position, mgmt IP
- Printer: type, color, paper size, duplex, toner
- Network: port count, PoE, uplink, firmware

Common fields (asset_tag, serial_no, warranty, site, status) apply to all assets.
Category-specific fields vary.

We need a storage design that is:
1. Flexible — new categories without code changes
2. Fast — filterable at 100k rows (< 100 ms)
3. Maintainable — schema changes don't lose data

## Decision

Adopt a Hybrid Model with three layers:

1. Common Fields — real columns on Asset
2. Category Schema — declarative JSON in Category.field_schema
3. Category Values — JSONB in Asset.specs + promoted columns for hot fields

Promotion rule: any field used in ≥ 1 report, list filter, or > 5% of queries becomes
a real indexed column.

## Options Considered

### Option A — Wide Table
All possible columns on Asset.
Rejected: table becomes 50+ columns; every new category needs ALTER TABLE.

### Option B — Pure JSONB
Everything in Asset.specs JSONB.
Rejected: JSONB filters cannot use B-tree indexes at scale.

### Option C — EAV
Separate AssetAttribute table.
Rejected: query joins explode; no type safety.

### Option D — Hybrid (Chosen)
Common columns + JSONB + promoted columns.

## Consequences

### Positive
- New categories added without code changes
- Filters on promoted fields run in < 20 ms at 100k rows
- Validation declarative (JSON Schema from category schema)
- Field removal soft — data preserved
- Same schema drives admin form, API, CSV import, frontend

### Negative
- Discipline required — decide when to promote a field
- Two places to look for a value (column vs JSONB)
- Column budget: ≤ 12 promoted columns

### Neutral
- Category schema changes auditable via schema_history
- Field rename requires alias support

## Implementation

See docs/category-schema-design.md.

Key files:
- apps/assets/models.py — Category, Asset
- apps/assets/services.py — validate_specs, save_asset_with_specs
- apps/assets/constants.py — PromotedSpecs.PROMOTED_KEYS
- apps/assets/admin.py — DynamicSpecsForm

## References

- docs/category-schema-design.md
- DEVELOPMENT.md §2
- Prior art: Snipe-IT, Lansweeper, ServiceNow CMDB

---

**End of Document**