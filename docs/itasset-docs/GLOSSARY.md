# Glossary

Terms used throughout the IT Asset Manager project.

## Core Terms

| Term | Definition |
|---|---|
| asset_tag | System-generated, permanent, unique ID. Format {category-code}-{seq}. Never reused. |
| serial_no | Manufacturer serial. Indexed but not unique. Normalized (trim + uppercase). |
| Assignment | Links an Asset to a Person for a period (out_at … in_at). Append-only. |
| AssetRequest | Pre-asset record for new asset requests. |
| Transfer | Moves assets between sites. Sets IN_TRANSIT on dispatch. |
| RepairTicket | Damage/repair case. Tracks fault, vendor, RMA no., cost. |
| DisposalRecord | Sanitization + disposal evidence. Required before DISPOSED. |
| ActivityLog | Append-only audit trail. Retained 24 months. |
| LicenseKey | A seat of a SoftwareLicense assigned to an Asset. |
| Contract | Support/warranty/subscription/lease agreement. |
| specs | JSONB column holding category-specific field values. |

## Acronyms

| Acronym | Meaning |
|---|---|
| RMA | Return Merchandise Authorization |
| SAM | Software Asset Management |
| ITIL | IT Infrastructure Library |
| MDM | Mobile Device Management |
| RPO | Recovery Point Objective |
| RTO | Recovery Time Objective |
| CAL | Client Access License |
| PO | Purchase Order |
| SLA | Service Level Agreement |
| DR | Disaster Recovery |
| LDAP | Lightweight Directory Access Protocol |
| AD | Active Directory |
| i18n | Internationalization |
| l10n | Localization |
| EOL | End of Life |
| YTD | Year to Date |
| DRF | Django REST Framework |
| ADR | Architecture Decision Record |
| CSP | Content Security Policy |
| JSONB | PostgreSQL binary JSON type |

## Status Values

| Status | Meaning |
|---|---|
| IN_STOCK | Received, tagged, not yet available |
| AVAILABLE | Ready to assign |
| ASSIGNED | Currently held by a person |
| IN_REPAIR | Under repair |
| IN_TRANSIT | Being moved between sites |
| RETIRED | No longer in service |
| DISPOSED | Terminal; sanitization complete |

## Condition Values

| Condition | Meaning |
|---|---|
| NEW | Unopened / brand new |
| GOOD | Working, no issues |
| FAIR | Working, cosmetic wear |
| POOR | Working, significant wear |
| DAMAGED | Not working |

---

**End of Document**