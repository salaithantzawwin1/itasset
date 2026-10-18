# Category Schema Design

**Version:** 1.0.0
**Last updated:** 2026-10-12
**Status:** Accepted

---

## 1. Problem Statement

Different asset categories have different spec fields:

| Category | Fields |
|---|---|
| Laptop / Desktop | CPU, RAM, storage, motherboard, GPU, PSU, OS |
| Monitor | Screen size, resolution, panel type, refresh rate, inputs |
| Server | Hostname, role, environment, rack position, RAID, mgmt IP |
| Printer | Type, color/mono, paper size, duplex, toner |
| Network | Port count, PoE, uplink, firmware, mgmt IP |

Common fields (asset_tag, serial_no, warranty, site, status) apply to every asset.

---

## 2. Design Options Considered

### A — Wide Table
All possible columns on Asset.
- Pros: Fast queries, simple ORM
- Cons: 50+ columns; every new category needs ALTER TABLE; many NULLs

### B — Pure JSONB
Everything in Asset.specs JSONB.
- Pros: Fully flexible
- Cons: JSONB filters cannot use B-tree indexes at scale

### C — EAV
Separate AssetAttribute table (asset_id, key, value).
- Pros: Very flexible
- Cons: Query joins explode; no type safety

### D — Hybrid ⭐ (Chosen)
Common columns + JSONB + promoted columns.
- Pros: Flexible + fast + validated
- Cons: Discipline required (promotion step)

---

## 3. Chosen Design — Hybrid Model

### Three-layer model

```
┌──────────────────────────────────────────┐
│ Layer 1: Common Fields (real columns)    │
│   asset_tag, serial_no, category, site,  │
│   warranty_end, status, condition        │
└──────────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────┐
│ Layer 2: Category Schema (declarative)   │
│   Category.field_schema = {              │
│     'fields': [                          │
│       {'key': 'cpu', 'type': 'string'}   │
│     ]                                    │
│   }                                      │
└──────────────────────────────────────────┘
                   ↓
┌──────────────────────────────────────────┐
│ Layer 3: Category Values (JSONB + cols)  │
│   Asset.specs = {'cpu': 'i7-13700'}      │
│   Asset.cpu   = 'i7-13700'  ← promoted   │
└──────────────────────────────────────────┘
```

---

## 4. Field Type Reference

| Type | Django form | JSON Schema |
|---|---|---|
| string | CharField | {"type": "string"} |
| text | TextField | {"type": "string"} |
| integer | IntegerField | {"type": "integer"} |
| decimal | DecimalField | {"type": "number"} |
| boolean | BooleanField | {"type": "boolean"} |
| choice | ChoiceField | {"enum": [...]} |
| multi-choice | MultipleChoiceField | {"type": "array"} |
| date | DateField | {"format": "date"} |
| ip | GenericIPAddressField | {"format": "ipv4"} |

---

## 5. Promoted Columns Policy

Promote a field if:
1. Used in ≥ 1 report
2. Used in list filters
3. Used in sorting
4. Appears in > 5% of queries

### Current promoted columns

| Column | Type | Used by |
|---|---|---|
| cpu | CharField(100) | Laptop/Desktop reports |
| ram_gb | IntegerField | Laptop/Desktop reports |
| os_family | CharField(20) | OS inventory |
| screen_size_in | DecimalField | Monitor reports |
| resolution | CharField(20) | Monitor reports |

---

## 6. Default Category Schemas

### Laptop / Desktop (IT-HW-LAP / IT-HW-DSK)

```json
{
  "version": 1,
  "fields": [
    {"key": "device_type", "label": "Device Type", "type": "choice",
     "choices": ["laptop", "desktop", "all-in-one", "mini-PC"],
     "required": true, "filterable": true},
    {"key": "hostname", "label": "Hostname", "type": "string",
     "required": true, "max_length": 63},
    {"key": "cpu", "label": "CPU", "type": "string",
     "required": true, "filterable": true, "searchable": true},
    {"key": "ram_gb", "label": "RAM (GB)", "type": "integer",
     "required": true, "filterable": true, "min": 1, "max": 1024},
    {"key": "storage", "label": "Storage", "type": "string", "required": true},
    {"key": "motherboard", "label": "Motherboard", "type": "string"},
    {"key": "gpu", "label": "GPU", "type": "string"},
    {"key": "psu_watt", "label": "PSU (W)", "type": "integer"},
    {"key": "os_family", "label": "OS Family", "type": "choice",
     "choices": ["WIN10", "WIN11", "MACOS", "LINUX", "OTHER"],
     "required": true, "filterable": true},
    {"key": "encrypted", "label": "Encrypted", "type": "boolean", "required": true}
  ]
}
```

### Monitor (IT-HW-MON)

```json
{
  "version": 1,
  "fields": [
    {"key": "screen_size_in", "label": "Screen Size (inch)",
     "type": "decimal", "required": true, "filterable": true,
     "min": 10, "max": 100},
    {"key": "resolution", "label": "Resolution", "type": "choice",
     "choices": ["1080p", "1440p", "4K", "5K"],
     "required": true, "filterable": true},
    {"key": "panel_type", "label": "Panel Type", "type": "choice",
     "choices": ["IPS", "VA", "TN", "OLED"]},
    {"key": "refresh_rate_hz", "label": "Refresh Rate (Hz)", "type": "integer"},
    {"key": "inputs", "label": "Inputs", "type": "multi-choice",
     "choices": ["HDMI", "DP", "USB-C", "VGA"]},
    {"key": "hdr", "label": "HDR", "type": "boolean"}
  ]
}
```

### Server (IT-HW-SRV)

```json
{
  "version": 1,
  "fields": [
    {"key": "hostname", "label": "Hostname", "type": "string", "required": true},
    {"key": "server_role", "label": "Role", "type": "choice",
     "choices": ["DC", "DNS", "DHCP", "DB", "APP", "FILE", "BACKUP", "OTHER"],
     "required": true, "filterable": true},
    {"key": "environment", "label": "Env", "type": "choice",
     "choices": ["prod", "staging", "dev"], "required": true},
    {"key": "cpu", "label": "CPU", "type": "string", "required": true},
    {"key": "ram_gb", "label": "RAM (GB)", "type": "integer", "required": true},
    {"key": "storage", "label": "Storage", "type": "string", "required": true},
    {"key": "mgmt_ip", "label": "Mgmt IP", "type": "ip"}
  ]
}
```

### Printer (IT-HW-PRN)

```json
{
  "version": 1,
  "fields": [
    {"key": "printer_type", "label": "Type", "type": "choice",
     "choices": ["laser", "inkjet", "thermal", "dot-matrix"], "required": true},
    {"key": "color", "label": "Color", "type": "boolean", "required": true},
    {"key": "paper_size", "label": "Paper Size", "type": "multi-choice",
     "choices": ["A4", "A3", "Letter", "Legal"], "required": true},
    {"key": "duplex", "label": "Duplex", "type": "boolean"},
    {"key": "network", "label": "Network", "type": "boolean"},
    {"key": "toner_model", "label": "Toner Model", "type": "string"}
  ]
}
```

---

## 7. Validation Pipeline

```python
import jsonschema


def validate_specs(category, specs):
    fields = category.get_fields()
    properties = {}
    required = []
    for f in fields:
        if f.get("hidden"):
            continue
        properties[f["key"]] = _field_to_json_schema(f)
        if f.get("required"):
            required.append(f["key"])
    schema = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    jsonschema.validate(instance=specs, schema=schema)
    return _normalize_specs(specs, fields)
```

---

## 8. Anti-Patterns

| Anti-pattern | Why it hurts |
|---|---|
| JSONB without promoted columns | Slow queries at scale |
| Wide columns for everything | Table bloat |
| EAV tables | Query joins explode |
| Every field required | Import friction |
| Delete a field from schema | Data becomes invisible |
| Hard-code category names | Defeats the design |
| Allow unknown keys in specs | Silent typos |
| Category logic in Asset.save() | Bypasses service layer |

---

## 9. References

- PostgreSQL JSONB — https://www.postgresql.org/docs/16/datatype-json.html
- JSON Schema — https://json-schema.org/
- Django JSONField — https://docs.djangoproject.com/en/5.1/ref/models/fields/#jsonfield
- Snipe-IT (prior art) — https://snipe-it.readme.io/

---

**End of Document**