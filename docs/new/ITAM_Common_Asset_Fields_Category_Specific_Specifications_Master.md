# IT Asset Management System
# Common Asset Fields + Category-Specific Specification Fields
## Master Guide v1.0

**Document Type:** Functional and Technical Master Guide  
**Purpose:** Define a consistent, extensible way to record common asset information and category-specific technical specifications across a company group and its branches.  
**Audience:** Business owners, IT/Admin teams, system analysts, developers, QA, and implementation teams.

---

## 1. Purpose and Design Principles

The Asset Management System should use two layers of information:

1. **Common Asset Fields** — information required for nearly every asset, regardless of category.
2. **Category-Specific Specification Fields** — technical details that depend on the asset category, such as CPU/RAM for a laptop, port count for a switch, or engine capacity for a vehicle.

The system must not force every asset into one oversized form containing hundreds of irrelevant fields. Instead, the asset category determines which specification fields are displayed, validated, and required.

### 1.1 Core principles

- Every tracked asset has one unique Asset ID and, where applicable, a unique Asset Tag.
- Common fields are stored consistently across all categories.
- Category-specific fields are configurable through master data; developers should not hard-code every field into the application.
- Each specification definition includes a data type, unit, validation rules, and whether it is required.
- Unknown or not-yet-recorded values should be distinguishable from values such as `0`, `No`, or `Not Applicable`.
- Asset changes, assignments, movements, repairs, and status changes must be auditable.
- Company, branch, department, and custodian access must be enforced by server-side authorization, not just by hiding UI controls.
- Fields that change over time should have history where that history matters.
- Components that are independently tracked should be records of their own and linked to the parent asset where appropriate.

---

## 2. Information Model

### 2.1 High-level relationship

```text
Company Group
  └── Company
       └── Branch / Site
            └── Asset
                 ├── Common Asset Fields
                 ├── Category
                 │    └── Applicable Specification Definitions
                 │         └── Asset Specification Values
                 ├── Assignment History
                 ├── Location / Movement History
                 ├── Maintenance / Repair History
                 ├── Warranty / Purchase Records
                 ├── Attachments
                 └── Components (optional, independently tracked)
```

### 2.2 Recommended logical tables

| Table | Purpose |
|---|---|
| `companies` | Legal companies within the group |
| `branches` | Branches, offices, warehouses, and sites |
| `departments` | Department master data |
| `locations` | Rooms, floors, server rooms, stores, and other physical locations |
| `asset_categories` | Hierarchical asset categories |
| `assets` | Common information for each asset |
| `specification_definitions` | Reusable definitions for specification fields |
| `category_specifications` | Assigns specification definitions to categories and sets category-specific rules |
| `asset_specification_values` | Stores an asset's values for applicable specifications |
| `asset_components` | Independently tracked or replaceable components associated with an asset |
| `asset_assignments` | Assignment history to employees, departments, or teams |
| `asset_movements` | Transfer and location history |
| `asset_status_history` | Status change history |
| `asset_maintenance_records` | Preventive maintenance, repair, and service history |
| `asset_documents` | Invoices, warranty files, photos, handover forms, and other attachments |
| `vendors` | Supplier and service provider master data |
| `purchase_records` | Purchase order, invoice, cost, and acquisition details |
| `audit_logs` | Security-sensitive and business-critical activity logs |

---

## 3. Common Asset Fields

Common fields should appear for all relevant asset categories. Some fields may be optional depending on the asset type or business process, but their meaning must remain consistent.

### 3.1 Identity and classification

| Field | Type | Required | Example | Notes |
|---|---|---:|---|---|
| `asset_id` | UUID / internal ID | Yes | System-generated | Immutable primary identifier |
| `asset_tag` | String | Policy-based | `GF-IT-000123` | Unique within the agreed scope; use a unique constraint |
| `asset_name` | String | Yes | `Finance Laptop 01` | Human-readable name |
| `category_id` | FK | Yes | Laptop | Determines specification fields |
| `subcategory_id` | FK / optional | No | Business Laptop | Optional if hierarchical categories are used |
| `description` | Text | No | Used by Finance Department | Short description |
| `manufacturer` | String / master-data FK | Usually | Dell | Prefer normalized manufacturer master data if needed |
| `model` | String | Usually | Latitude 5440 | Model or product family |
| `serial_number` | String | If available | `ABC12345` | Uniqueness policy must allow blanks and manufacturer exceptions |
| `barcode_or_qr_code` | String / generated | Optional | Encoded asset URL/ID | Do not use this as the sole database identifier |
| `criticality` | Enum | Optional | Low / Medium / High / Critical | Used for support and replacement priority |

### 3.2 Ownership and organizational scope

| Field | Type | Required | Example | Notes |
|---|---|---:|---|---|
| `company_id` | FK | Yes | Great Foundation | Group-level ownership scope |
| `branch_id` | FK | Yes, where applicable | Yangon Office | Physical or operational branch |
| `department_id` | FK | Optional | Finance | Current responsible department |
| `owner_type` | Enum | Optional | Company / Employee / Department | Define ownership rules clearly |
| `owner_id` | FK or typed reference | Optional | Employee ID | Use a proper relational design where possible |
| `custodian_employee_id` | FK | Optional | Employee ID | Person currently responsible for the asset |
| `location_id` | FK | Optional | 3rd Floor / IT Room | Use a location master table |
| `cost_center` | String / FK | Optional | FIN-01 | Finance reporting code |

### 3.3 Lifecycle and operational status

Use separate fields for **asset lifecycle status** and **operational condition**. They represent different things.

| Field | Type | Required | Example | Meaning |
|---|---|---:|---|---|
| `lifecycle_status` | Enum | Yes | In Service | Business lifecycle state |
| `condition_status` | Enum | Optional | Good | Physical/functional condition |
| `operational_status` | Enum | Optional | Working | Current operational state |
| `acquisition_date` | Date | Optional | `2026-01-15` | Date acquired |
| `in_service_date` | Date | Optional | `2026-01-20` | Date put into service |
| `end_of_life_date` | Date | Optional | `2031-01-20` | Planned lifecycle date |
| `disposal_date` | Date | Optional | `2032-02-01` | Actual disposal date |
| `disposal_reason` | Enum / text | Conditional | Obsolete | Required when disposed, if policy requires |

**Suggested lifecycle statuses:** `Draft`, `Requested`, `Pending Approval`, `In Stock`, `In Service`, `In Repair`, `On Loan`, `Lost`, `Stolen`, `Retired`, `Disposed`.

**Suggested condition statuses:** `New`, `Excellent`, `Good`, `Fair`, `Poor`, `Damaged`, `Unserviceable`.

**Suggested operational statuses:** `Working`, `Partially Working`, `Not Working`, `Not Tested`, `Not Applicable`.

Do not treat the suggested lists as final without approval from the business owner. Status transitions should be controlled by workflow rules.

### 3.4 Purchase, financial, and warranty information

| Field | Type | Required | Example | Notes |
|---|---|---:|---|---|
| `vendor_id` | FK | Optional | Vendor master ID | Supplier |
| `purchase_order_number` | String | Optional | `PO-2026-0012` | Purchase reference |
| `invoice_number` | String | Optional | `INV-00231` | Invoice reference |
| `purchase_date` | Date | Optional | `2026-01-15` | Actual purchase date |
| `purchase_cost` | Decimal | Optional | `1250000.00` | Use decimal, not floating-point |
| `currency_code` | String / FK | Conditional | MMK | ISO-style currency code or approved currency master |
| `warranty_start_date` | Date | Optional | `2026-01-15` | Warranty coverage start |
| `warranty_end_date` | Date | Optional | `2029-01-14` | Validate end date is not earlier than start date |
| `warranty_provider` | String / FK | Optional | Manufacturer | Service provider |
| `support_contract_reference` | String | Optional | `SUP-2026-01` | Optional support agreement |
| `depreciation_class` | FK / enum | Optional | Computer Equipment | Coordinate with Finance |
| `capitalization_status` | Enum | Optional | Capitalized / Expense | Finance policy controlled |

**Important:** Purchase cost, depreciation, capitalization, and disposal values should follow the company's accounting policy. IT Asset Management should not silently replace or override the accounting system's official financial records.

### 3.5 Administration and audit metadata

| Field | Type | Required | Notes |
|---|---|---:|---|
| `created_at` | Timestamp | Yes | Server-generated |
| `created_by` | User ID | Yes | Authenticated actor |
| `updated_at` | Timestamp | Yes | Server-generated |
| `updated_by` | User ID | Yes | Authenticated actor |
| `record_version` | Integer | Recommended | Supports optimistic concurrency |
| `is_active` | Boolean | Recommended | Use carefully; do not use as a replacement for lifecycle status |
| `deleted_at` | Timestamp / nullable | Optional | Prefer soft deletion only when justified by retention policy |

Do not allow users to edit audit fields directly.

---

## 4. Category and Specification Master Data

### 4.1 Category master

Use a category hierarchy where appropriate.

Example:

```text
IT Equipment
  ├── End User Devices
  │    ├── Desktop PC
  │    ├── Laptop
  │    ├── Workstation
  │    ├── Tablet
  │    └── Mobile Phone
  ├── Server & Storage
  │    ├── Physical Server
  │    ├── NAS
  │    └── SAN
  ├── Network & Security
  │    ├── Router
  │    ├── Switch
  │    ├── Firewall
  │    └── Wireless Access Point
  ├── Peripherals
  │    ├── Monitor
  │    ├── Printer
  │    ├── Scanner
  │    ├── UPS
  │    └── Docking Station
  └── Software & Licenses
       ├── Software License
       └── Subscription
```

Other business categories such as furniture, air conditioners, vehicles, tools, and machinery can use the same framework. Do not force non-IT assets into IT-only categories.

### 4.2 Specification definition

Each specification field should be defined once and reused where suitable.

Recommended fields for `specification_definitions`:

| Field | Purpose |
|---|---|
| `specification_id` | Unique identifier |
| `field_key` | Stable machine key, e.g. `ram_capacity_gb` |
| `display_name` | Label shown to the user, e.g. `RAM Capacity` |
| `description` | Help text and meaning |
| `data_type` | String, integer, decimal, boolean, date, enum, URL, etc. |
| `unit` | GB, GHz, W, inches, ports, etc. |
| `option_set` | Approved choices for enum fields |
| `default_value` | Optional default |
| `validation_rules` | Min/max, format, regex, or other constraints |
| `is_sensitive` | Indicates whether extra permissions or masking are needed |
| `is_active` | Whether the definition can be used for new records |

Recommended `category_specifications` fields:

| Field | Purpose |
|---|---|
| `category_id` | Category to which the field applies |
| `specification_id` | Reusable field definition |
| `is_required` | Required for this category |
| `is_unique_per_category` | Whether value uniqueness is enforced, if applicable |
| `display_order` | UI ordering |
| `section_name` | Example: Processor, Memory, Display, Network |
| `is_editable_after_creation` | Whether normal users may change it after creation |
| `effective_from` / `effective_to` | Optional configuration versioning |

Recommended `asset_specification_values` fields:

| Field | Purpose |
|---|---|
| `asset_id` | Asset whose value is being recorded |
| `specification_id` | Specification definition |
| `value_string` | String/enum/URL values |
| `value_number` | Numeric values |
| `value_boolean` | Boolean values |
| `value_date` | Date values |
| `value_json` | Only for carefully controlled complex values, if necessary |
| `recorded_at` | When the value was recorded |
| `recorded_by` | User who recorded the value |

**Implementation note:** A typed-value design can prevent invalid comparisons and make reporting easier. Alternatively, a validated JSONB specification object may be suitable for a smaller system, but it requires disciplined schema validation and reporting design. Do not store every value as an unvalidated string if the system needs reliable filtering and reporting.

### 4.3 Specification configuration rules

- Each `field_key` must be stable and unique.
- Display labels can change; field keys should not be casually renamed.
- A field may apply to multiple categories.
- Requiredness is set at the category-field mapping level, not globally, unless it is truly universal.
- Units must be explicit. `512` alone is ambiguous; `512 GB` is meaningful.
- Enumerated fields must use approved option values.
- The UI should show only active fields assigned to the selected category.
- If an asset's category changes, the system must validate the new category's required fields and preserve or explicitly map old values. Never silently delete specification data.
- Deactivating a field must not erase existing asset values or audit history.
- Changes to specification configuration should be audited and ideally versioned.

---

## 5. Category-Specific Specification Master Catalogue

The following is a starting catalogue. Business owners and IT should confirm which fields are required for their environment. A field marked “Recommended” is not automatically mandatory.

### 5.1 Desktop PC

| Field Key | Display Name | Type / Unit | Requirement | Validation / Notes |
|---|---|---|---|---|
| `cpu_manufacturer` | CPU Manufacturer | Enum/String | Recommended | Intel, AMD, Other |
| `cpu_model` | CPU Model | String | Recommended | Example: Intel Core i5-14500 |
| `cpu_cores` | CPU Cores | Integer | Optional | Must be greater than 0 |
| `ram_capacity_gb` | RAM Capacity | Decimal/GB | Recommended | Total installed RAM |
| `ram_type` | RAM Type | Enum | Optional | DDR3, DDR4, DDR5, Other |
| `ram_speed_mhz` | RAM Speed | Integer/MHz | Optional | Actual supported/recorded speed |
| `motherboard_model` | Motherboard Model | String | Optional | Manufacturer/model |
| `storage_1_type` | Primary Storage Type | Enum | Recommended | HDD, SATA SSD, NVMe SSD, Other |
| `storage_1_capacity_gb` | Primary Storage Capacity | Integer/GB | Recommended | Capacity in GB |
| `storage_2_type` | Secondary Storage Type | Enum | Optional | Same options |
| `storage_2_capacity_gb` | Secondary Storage Capacity | Integer/GB | Optional | Capacity in GB |
| `gpu_model` | Graphics Adapter | String | Optional | Integrated or dedicated |
| `gpu_memory_gb` | GPU Memory | Decimal/GB | Optional | Use only where relevant |
| `psu_wattage_w` | PSU Wattage | Integer/W | Optional | Power supply rating |
| `case_form_factor` | Case Form Factor | Enum/String | Optional | Tower, SFF, Mini PC, Other |
| `os_name` | Operating System | String/Enum | Recommended | Example: Windows 11 Pro |
| `os_version` | OS Version / Build | String | Optional | Record the observed version |
| `tpm_version` | TPM Version | Enum | Optional | None, 1.2, 2.0, Unknown |
| `monitor_count` | Number of Monitors | Integer | Optional | Use component records if individually tracked |
| `network_interface` | Network Interface | String | Optional | Example: 1GbE |
| `wifi_supported` | Wi-Fi Supported | Boolean | Optional | Yes/No |
| `bluetooth_supported` | Bluetooth Supported | Boolean | Optional | Yes/No |

### 5.2 Laptop

| Field Key | Display Name | Type / Unit | Requirement | Validation / Notes |
|---|---|---|---|---|
| `cpu_manufacturer` | CPU Manufacturer | Enum/String | Recommended | Intel, AMD, Apple, Other |
| `cpu_model` | CPU Model | String | Recommended | Example: Intel Core Ultra 5 |
| `cpu_cores` | CPU Cores | Integer | Optional | Greater than 0 |
| `ram_capacity_gb` | RAM Capacity | Decimal/GB | Recommended | Installed RAM |
| `ram_type` | RAM Type | Enum | Optional | DDR4, DDR5, LPDDR, Other |
| `ram_upgradeable` | RAM Upgradeable | Boolean | Optional | Yes/No/Unknown if using enum |
| `storage_1_type` | Primary Storage Type | Enum | Recommended | HDD, SATA SSD, NVMe SSD, Other |
| `storage_1_capacity_gb` | Primary Storage Capacity | Integer/GB | Recommended | Capacity in GB |
| `gpu_model` | Graphics Adapter | String | Optional | Integrated/dedicated |
| `screen_size_in` | Screen Size | Decimal/inches | Recommended | Positive numeric value |
| `screen_resolution` | Screen Resolution | String | Optional | Example: 1920x1080 |
| `touchscreen` | Touchscreen | Boolean | Optional | Yes/No |
| `battery_health_pct` | Battery Health | Integer/% | Optional | 0–100; date of measurement recommended |
| `battery_cycle_count` | Battery Cycle Count | Integer/count | Optional | May not be available on all devices |
| `battery_condition` | Battery Condition | Enum | Recommended | Good, Fair, Poor, Replace, Unknown |
| `adapter_wattage_w` | Charger Wattage | Integer/W | Optional | Example: 65 W |
| `adapter_model` | Charger Model | String | Optional | Record separately if tracked |
| `wifi_standard` | Wi-Fi Standard | String/Enum | Optional | Example: Wi-Fi 6 |
| `bluetooth_version` | Bluetooth Version | String | Optional | If known |
| `os_name` | Operating System | String/Enum | Recommended | Example: Windows 11 Pro |
| `os_version` | OS Version / Build | String | Optional | Observed version |
| `device_encryption` | Disk Encryption | Enum | Optional | Enabled, Disabled, Unknown |
| `bios_version` | BIOS/UEFI Version | String | Optional | Useful for support and security |

**Laptop note:** Battery health and cycle count are time-dependent. If battery condition history matters, store measurements in a separate `asset_inspections` or `asset_specification_history` table instead of overwriting the previous measurement.

### 5.3 Workstation

Use the Desktop PC field set plus optional high-performance fields:

- CPU model, core/thread count
- RAM capacity and type
- GPU model, GPU memory
- Number and capacity of storage devices
- PSU wattage
- Operating system and version
- Specialized card or accelerator details
- Cooling configuration, if required by support policy

Do not duplicate the whole field catalogue. Reuse common definitions and add workstation-only fields where needed.

### 5.4 Physical Server

| Field Key | Display Name | Type / Unit | Requirement | Notes |
|---|---|---|---|---|
| `server_role` | Server Role | Enum/String | Recommended | Virtualization, Database, File, Application, Backup, Other |
| `chassis_form_factor` | Chassis Form Factor | Enum/String | Recommended | Rack, Tower, Blade, Other |
| `cpu_model` | CPU Model | String | Recommended | Record each CPU if detailed inventory is required |
| `cpu_socket_count` | CPU Socket Count | Integer | Optional | Physical sockets |
| `cpu_installed_count` | Installed CPU Count | Integer | Recommended | Installed processors |
| `ram_capacity_gb` | Total RAM | Decimal/GB | Recommended | Total installed memory |
| `ram_type` | RAM Type | Enum/String | Optional | DDR4, DDR5, Other |
| `drive_bay_count` | Drive Bay Count | Integer | Optional | Total bays |
| `raid_controller_model` | RAID Controller | String | Optional | Controller model |
| `raid_configuration` | RAID Configuration | String | Optional | Example: RAID 1; use a structured model if detailed disk reporting is needed |
| `storage_raw_capacity_tb` | Raw Storage Capacity | Decimal/TB | Optional | Physical capacity before RAID/formatting |
| `storage_usable_capacity_tb` | Usable Storage Capacity | Decimal/TB | Optional | Capacity available after RAID/configuration |
| `nic_count` | NIC Port Count | Integer | Optional | Physical or logical count must be clear |
| `nic_speed` | NIC Speed | String | Optional | Example: 1GbE, 10GbE |
| `psu_redundancy` | Redundant PSU | Boolean | Optional | Yes/No |
| `idrac_ilo_version` | Out-of-band Management | String | Optional | iDRAC, iLO, IPMI version |
| `firmware_baseline` | Firmware Baseline | String | Optional | Can be linked to configuration management |
| `hypervisor` | Hypervisor | String | Optional | Example: VMware ESXi |
| `os_name` | Operating System | String | Recommended | Host OS or hypervisor |
| `os_version` | OS / Hypervisor Version | String | Recommended | Include build when relevant |
| `rack_location` | Rack Location | String / FK | Optional | Prefer location master where practical |
| `rack_unit` | Rack Unit | String/Integer | Optional | Example: U12 |

**Server note:** Detailed CPU, DIMM, drive, NIC, PSU, and RAID layouts are often better represented as component records when each part must be tracked, replaced, or audited independently.

### 5.5 Virtual Machine

A VM is a logical asset and should be distinguished from a physical host.

Suggested fields:

- `hypervisor_platform`
- `vm_name`
- `vm_uuid`
- `host_asset_id` (relationship to physical host, if managed here)
- `vCPU_count`
- `memory_assigned_gb`
- `provisioned_storage_gb`
- `guest_os`
- `guest_os_version`
- `environment` (Production, Test, Development, DR)
- `ip_address` (use a related network interface table if multiple IPs are expected)
- `backup_policy`
- `service_owner`
- `application_service`

Avoid storing a VM as if it were a physical server. The physical host and VM have different lifecycle, ownership, and capacity relationships.

### 5.6 Monitor

- `screen_size_in`
- `panel_type` (IPS, TN, VA, OLED, Other)
- `native_resolution`
- `refresh_rate_hz`
- `video_inputs` (HDMI, DisplayPort, USB-C, VGA, Other)
- `curved_display` (Boolean)
- `built_in_speakers` (Boolean)
- `power_consumption_w` (optional)
- `stand_model` (optional)

If a monitor has its own Asset Tag and lifecycle, create a separate asset record and link it to the assigned PC/laptop through an assignment or component relationship.

### 5.7 Printer / Scanner / Multifunction Printer

- `device_type` (Printer, Scanner, MFP)
- `print_technology` (Laser, Inkjet, Thermal, Other)
- `color_capability` (Monochrome, Color)
- `print_speed_ppm`
- `max_paper_size`
- `duplex_supported`
- `network_capability`
- `ip_address` (prefer network interface records for multiple interfaces)
- `mac_address`
- `meter_count` (time-dependent; record meter history if needed)
- `consumable_type`
- `driver_or_firmware_version`

### 5.8 Network Switch

- `switch_type` (Managed, Unmanaged, Layer 2, Layer 3)
- `port_count`
- `port_speed_profile`
- `sfp_port_count`
- `poe_supported`
- `poe_budget_w`
- `switching_capacity_gbps`
- `forwarding_rate_mpps`
- `stacking_supported`
- `management_ip`
- `mac_address`
- `firmware_version`
- `rack_unit`
- `support_end_date`

### 5.9 Router

- `wan_interface_types`
- `lan_port_count`
- `wan_port_count`
- `max_throughput_mbps`
- `vpn_capability`
- `vpn_tunnel_capacity` (if known)
- `routing_protocols`
- `management_ip`
- `firmware_version`
- `power_supply_redundancy`
- `support_end_date`

### 5.10 Firewall / Security Appliance

- `firewall_model`
- `throughput_firewall_gbps`
- `throughput_threat_protection_gbps`
- `interface_count`
- `interface_speed_profile`
- `vpn_throughput_mbps`
- `vpn_tunnel_capacity`
- `ha_capability`
- `ha_role`
- `management_ip`
- `firmware_version`
- `license_expiry_date`
- `subscription_status`
- `support_end_date`

**Security note:** Do not store administrator passwords, private keys, API secrets, VPN pre-shared keys, or other credentials in asset specification fields. Use an approved secrets-management solution with access controls and audit logs.

### 5.11 Wireless Access Point

- `wifi_standard`
- `supported_bands`
- `spatial_streams`
- `max_data_rate_mbps`
- `ethernet_port_count`
- `poe_standard`
- `management_ip`
- `mac_address`
- `controller_or_cloud_managed`
- `firmware_version`
- `mounting_type`

### 5.12 NAS / Storage Appliance

- `storage_type`
- `drive_bay_count`
- `installed_drive_count`
- `installed_raw_capacity_tb`
- `usable_capacity_tb`
- `raid_or_storage_pool_configuration`
- `network_port_count`
- `network_speed_profile`
- `iscsi_supported`
- `snapshot_supported`
- `replication_supported`
- `firmware_version`
- `backup_role`

Detailed disk serial numbers, disk health, RAID membership, and storage-pool details should use related component/storage tables if the organization needs operational monitoring.

### 5.13 UPS

- `capacity_va`
- `capacity_w`
- `topology` (Standby, Line Interactive, Online)
- `input_voltage_v`
- `output_voltage_v`
- `battery_count`
- `battery_type`
- `battery_install_date`
- `battery_replacement_due_date`
- `management_card`
- `management_ip`
- `runtime_estimate_minutes`

Battery replacement dates and battery test results are time-dependent and should be recorded in maintenance/inspection history.

### 5.14 Mobile Phone / Tablet

- `operating_system`
- `os_version`
- `storage_capacity_gb`
- `ram_capacity_gb`
- `screen_size_in`
- `imei_1` / `imei_2` (mobile devices only; restrict access if policy requires)
- `serial_number`
- `sim_number_or_identifier` (only if necessary and appropriately protected)
- `mobile_device_management_status`
- `encryption_status`
- `battery_health_pct`
- `charger_type`
- `warranty_end_date`

Personal data and mobile identifiers should be accessible only to authorized roles and retained according to policy.

### 5.15 Software License / Subscription

Software licenses are not physical equipment. They may share lifecycle and ownership concepts but should have a dedicated license model or a distinct asset subtype.

- `software_product_name`
- `publisher`
- `license_type` (Per User, Per Device, Subscription, Perpetual, Other)
- `license_metric`
- `license_quantity_purchased`
- `license_quantity_assigned`
- `license_key_reference` (reference to a secure vault; do not expose keys to all users)
- `subscription_start_date`
- `subscription_end_date`
- `renewal_date`
- `auto_renewal`
- `contract_reference`
- `license_owner_department`

Do not store full license keys in a general-purpose specification table unless a documented security review approves the design.

### 5.16 Other Physical Assets

For furniture, air conditioners, vehicles, tools, or machinery, reuse common fields and create category-specific fields based on actual business requirements.

Examples:
- **Air conditioner:** capacity BTU, type, refrigerant, power rating, installation location, installation date.
- **Vehicle:** registration number, VIN/chassis number, engine number, engine capacity, fuel type, odometer reading.
- **Furniture:** material, dimensions, color, condition.
- **Machinery:** manufacturer, model, serial, rated capacity, voltage, maintenance interval, safety inspection date.

Do not add speculative fields to every category. Confirm the data with the responsible department.

---

## 6. Components and Accessories

A component should become a separate record when one or more of these apply:

- It has its own Asset Tag or serial number.
- It can be moved independently between assets.
- It is covered by a separate warranty.
- It is replaced or repaired independently.
- The organization needs its own stock, assignment, or audit history.

Examples: monitor, docking station, external SSD, server disk, RAM module, UPS battery, network transceiver.

### 6.1 Recommended relationship

```text
Asset (Desktop PC)
  ├── Component (Monitor, separately tracked)
  ├── Component (Docking Station, separately tracked)
  └── Component (Keyboard, consumable/non-tracked)
```

Use a component classification to distinguish:
- `Independently Tracked`
- `Attached Component`
- `Consumable`
- `Accessory / Non-Tracked`

Avoid recording a monitor's serial number only in a free-text field on the PC if the monitor must later be transferred to another employee or PC.

---

## 7. Field Types and Validation Standards

| Data type | Example | Rule |
|---|---|---|
| String | Model name | Length limit; trim leading/trailing spaces |
| Integer | Port count | Whole number; minimum/maximum where relevant |
| Decimal | Screen size | Precision and range defined |
| Boolean | Touchscreen | True/False; use Unknown when necessary if data is not known |
| Enum | RAM type | Must match approved option set |
| Date | Purchase date | Valid date; check related-date rules |
| URL | Manufacturer support page | Validate URL format and permitted schemes |
| IP address | Management IP | Validate IPv4/IPv6 format; consider a separate network interface model |
| MAC address | `00:11:22:33:44:55` | Normalize format and validate |
| JSON | Complex structure | Use only when schema validation and reporting needs are understood |

### 7.1 Unknown, not applicable, and not recorded

Do not confuse these states:

- **Unknown:** The field applies, but the value has not been confirmed.
- **Not Applicable:** The field does not apply to this asset.
- **Not Recorded:** No value has been entered yet.
- **Known value:** A confirmed value exists.

The implementation can represent these states using null plus an explicit value-status field, or through another consistent model. The UI must communicate them clearly.

### 7.2 Units and normalization

- Store numeric values in a consistent base unit and display friendly units in the UI.
- Use explicit field units such as `GB`, `TB`, `GHz`, `MHz`, `W`, `VA`, `Mbps`, `Gbps`, `inches`, and `%`.
- Do not store `16 GB` as a numeric value. Store numeric `16` with unit `GB`.
- Decide whether storage is represented using manufacturer decimal units or binary units for capacity reporting and document that decision.
- Normalize manufacturer, category, branch, department, and status values when they are used for reporting or controlled workflows.

---

## 8. Form and User Experience Rules

### 8.1 Asset creation flow

1. User selects company and branch within their authorized scope.
2. User selects an asset category.
3. System loads the common asset form.
4. System loads only the specification fields mapped to the selected category.
5. User enters available information.
6. System validates required fields and field-specific rules.
7. User saves a draft or submits for approval, depending on the asset-creation policy.
8. System generates or assigns an Asset Tag according to the configured rule.
9. System records the actor, timestamp, and change audit.

### 8.2 Changing category

If the category changes after specifications have been entered:

1. Warn the user that the category change affects applicable specification fields.
2. Show which existing values remain applicable, which will become inactive, and which new fields are required.
3. Preserve previous values in history or retain them against the asset without presenting them as current category values.
4. Validate the destination category's required fields.
5. Record the category change in the audit log.

Do not silently delete old specification values.

### 8.3 Editing specifications

- Only authorized roles may edit technical fields.
- For sensitive or operationally important changes, require a reason.
- Use change history for fields such as serial number, CPU/RAM, IP address, firmware, battery health, and warranty dates where traceability matters.
- Show the last-updated date and editor where useful.
- Avoid overwriting measured values without retaining history if the value changes over time.

### 8.4 Search and reporting

Users should be able to search and filter by:
- Asset Tag, serial number, name, manufacturer, model
- Company, branch, department, custodian, location
- Category, lifecycle status, condition, criticality
- Warranty expiration, acquisition date, and end-of-life date
- Category-specific values such as RAM capacity, storage capacity, CPU model, switch port count, or firmware version

Only fields configured for filtering/reporting should be indexed or promoted into optimized reporting structures. Avoid indexing every arbitrary value without considering database size and query patterns.

---

## 9. Database Design Guidance

### 9.1 Recommended pattern

Use normalized relational tables for common fields and configuration tables for dynamic specifications.

```text
assets
  asset_id PK
  asset_tag
  asset_name
  category_id FK
  company_id FK
  branch_id FK
  department_id FK NULL
  location_id FK NULL
  custodian_employee_id FK NULL
  lifecycle_status
  condition_status
  operational_status
  manufacturer_id FK NULL
  model
  serial_number
  acquisition_date
  purchase_cost
  currency_code
  warranty_start_date
  warranty_end_date
  created_at
  created_by
  updated_at
  updated_by

specification_definitions
  specification_id PK
  field_key UNIQUE
  display_name
  data_type
  unit NULL
  option_set JSONB NULL
  validation_rules JSONB NULL
  is_active

category_specifications
  category_id FK
  specification_id FK
  is_required
  display_order
  section_name
  validation_override JSONB NULL
  PRIMARY KEY (category_id, specification_id)

asset_specification_values
  asset_id FK
  specification_id FK
  value_string NULL
  value_number NULL
  value_boolean NULL
  value_date NULL
  value_json JSONB NULL
  value_status
  updated_at
  updated_by
  UNIQUE (asset_id, specification_id)
```

This is a logical design, not a complete production migration script. Exact SQL types, constraints, indexes, foreign keys, and Prisma models should be confirmed during implementation.

### 9.2 Typed values versus JSONB

**Option A — Typed values in a relational table**
- Stronger control over value types.
- Easier to query numeric/date fields consistently.
- Suitable when reporting on specifications is important.
- Requires validation that only the correct value column is populated for each data type.

**Option B — One JSONB specification document per asset**
- Flexible and can simplify storage of variable fields.
- Requires schema validation in the application.
- Reporting, constraints, and cross-category comparisons can become harder.
- Use only if the team understands the reporting and migration trade-offs.

**Recommendation:** For a company-wide IT Asset Management System with filtering and reporting requirements, use normalized specification definitions and validated typed values, or a carefully designed hybrid. Do not allow arbitrary unvalidated key/value pairs.

### 9.3 Indexes and uniqueness

Consider indexes for:
- `asset_tag`
- `serial_number` where applicable
- `company_id`, `branch_id`, `category_id`
- `lifecycle_status`
- `custodian_employee_id`
- `warranty_end_date`
- Frequently queried specification fields

Serial numbers can be duplicated, blank, reused, or incorrectly entered in the real world. Define a practical uniqueness policy rather than applying an unconditional unique constraint without business review.

### 9.4 Tenant and organizational scoping

If multiple companies and branches share the same application:
- Every asset must belong to an authorized company scope.
- Branch and department relationships must be validated server-side.
- API queries must not return records from another company just because a user changes an ID in the request.
- Reporting exports must apply the same access rules as the UI.
- Audit logs should record cross-scope administrative actions.

---

## 10. API and Application Behavior

Illustrative endpoints (final routes may vary):

| Method | Endpoint | Purpose |
|---|---|---|
| `GET` | `/api/asset-categories` | List categories available to the user |
| `GET` | `/api/asset-categories/{id}/specifications` | Return active fields for a category |
| `POST` | `/api/assets` | Create an asset with common fields and specification values |
| `GET` | `/api/assets/{id}` | Retrieve asset details and current specifications |
| `PATCH` | `/api/assets/{id}` | Update permitted common fields |
| `PATCH` | `/api/assets/{id}/specifications` | Update specification values |
| `GET` | `/api/assets/{id}/history` | Retrieve authorized audit/lifecycle history |
| `POST` | `/api/assets/{id}/components` | Link or register a component |
| `GET` | `/api/reports/assets` | Filtered asset report |

### 10.1 Example request (illustrative)

```json
{
  "assetName": "Finance Laptop 01",
  "assetTag": "GF-IT-000123",
  "categoryId": "laptop-category-id",
  "companyId": "company-id",
  "branchId": "branch-id",
  "lifecycleStatus": "In Service",
  "specifications": {
    "cpu_model": "Intel Core i5-1345U",
    "ram_capacity_gb": 16,
    "ram_type": "DDR5",
    "storage_1_type": "NVMe SSD",
    "storage_1_capacity_gb": 512,
    "screen_size_in": 14,
    "battery_condition": "Good",
    "os_name": "Windows 11 Pro"
  }
}
```

The server must validate that:
- The category exists and is active.
- The user can create assets in the requested company/branch.
- Each submitted specification is permitted for that category.
- Values match each field's data type and validation rules.
- Required fields are present when the workflow requires them.
- The asset tag does not violate the configured uniqueness policy.

Never trust validation performed only by the browser.

---

## 11. Roles and Permissions

Suggested role matrix; adapt it to the actual organization:

| Action | System Admin | IT Asset Manager | Branch IT | Department Manager | Employee / Custodian | Auditor |
|---|---:|---:|---:|---:|---:|---:|
| Configure categories and specification fields | Yes | Limited/Yes by delegation | No | No | No | Read-only |
| Create asset | Yes | Yes | Authorized branch only | No/Request only | No | No |
| Edit common asset fields | Yes | Yes | Authorized branch only | Limited | No | No |
| Edit technical specifications | Yes | Yes | Authorized branch only | No | No | Read-only |
| Assign / transfer asset | Yes | Yes | Authorized branch only | Approval where required | Acknowledge receipt | Read-only |
| Dispose asset | Yes | Approval/workflow | Request only | Approval as policy | No | Read-only |
| View all company/branch data | Policy-based | Authorized scope | Own branch scope | Own department scope | Own assigned assets | Authorized audit scope |
| Export reports | Restricted | Authorized scope | Limited | Limited | Own assets only | Authorized scope |

Use least privilege. Access scope and actions should be evaluated on the server for every request.

---

## 12. Audit and History Requirements

The system should record:
- Asset creation and deletion/retirement actions
- Changes to common fields
- Changes to specification values
- Category changes and specification configuration changes
- Assignment, return, transfer, and custody acknowledgement
- Maintenance and repair updates
- Status changes and approvals
- Data imports and bulk updates
- Report exports where audit policy requires it
- Administrative actions and permission changes

Each audit event should include at least:
- Actor user ID
- Timestamp from the server
- Entity type and ID
- Action type
- Before/after values or a safe change summary
- Reason/comment where required
- Request/correlation ID where available

Do not place passwords, tokens, private keys, or other secrets in audit logs.

---

## 13. Data Migration and Bulk Import

### 13.1 Suggested import columns

A starter import template should include:
- Asset Tag
- Asset Name
- Category
- Company
- Branch
- Department
- Location
- Custodian Employee ID
- Manufacturer
- Model
- Serial Number
- Lifecycle Status
- Condition
- Acquisition Date
- Purchase Cost
- Currency
- Warranty End Date
- Category-specific specification columns

### 13.2 Import rules

1. Provide a template generated from the selected category or a template containing one worksheet per category.
2. Validate categories, companies, branches, departments, employees, dates, numbers, and enums before import.
3. Produce a preview with row-level errors.
4. Do not partially import a file silently.
5. Use an import batch ID and retain a summary of created, updated, skipped, and rejected rows.
6. Define whether import can update existing assets; never overwrite existing records based only on a weak name match.
7. Preserve source identifiers and migration references when importing from an existing Django system.
8. Require approval for bulk changes that affect ownership, branch, status, or financial values.

---

## 14. Acceptance Criteria

The solution is acceptable when the following conditions are met:

1. A user can create an asset with common fields and category-specific specifications.
2. Selecting `Laptop` shows laptop fields, not switch or server fields.
3. Selecting `Network Switch` shows network-specific fields.
4. Requiredness and validation are controlled by category configuration.
5. A field can be reused across multiple categories without duplicating its definition unnecessarily.
6. Invalid data types, enum values, and out-of-range values are rejected by the server.
7. Changing an asset category does not silently delete existing specification data.
8. Assets are scoped by company and branch according to permissions.
9. Asset specifications can be searched and reported where configured.
10. Changes to asset data and specification configuration are auditable.
11. Independently tracked components can be linked to an asset and later moved or reassigned according to policy.
12. Import errors are presented clearly and do not cause silent data loss.
13. The UI distinguishes Unknown, Not Applicable, and Not Recorded where the business requires it.
14. Existing data can be migrated with a reconciliation report.

---

## 15. Implementation Phases

### Phase 1 — Requirements confirmation
- Confirm company/branch hierarchy and user roles.
- Confirm asset categories and subcategories.
- Confirm common fields and category-specific field catalogue.
- Identify required fields, reporting needs, and unique identifiers.
- Decide which components need independent tracking.

### Phase 2 — Master data and schema
- Build company, branch, department, location, category, and specification masters.
- Implement field types, units, option sets, and validation rules.
- Implement server-side category-based validation.
- Implement audit history.

### Phase 3 — Asset management workflow
- Create, edit, view, assign, transfer, return, maintain, retire, and dispose assets.
- Add attachments and component relationships.
- Add role-based and company/branch-scoped access.

### Phase 4 — Search, reporting, and import
- Implement search and filters.
- Build standard reports.
- Create category-based import templates and validation preview.
- Validate performance for realistic asset counts.

### Phase 5 — Testing and rollout
- Unit and integration testing.
- Permission and cross-branch security testing.
- Migration reconciliation.
- User acceptance testing.
- Backup/restore and rollback rehearsal.
- Pilot with one branch before group-wide deployment.

---

## 16. Decisions Required Before Development

The business owner and IT team should explicitly approve these decisions:

- [ ] Final category and subcategory list
- [ ] Required common fields
- [ ] Required fields for each category
- [ ] Asset Tag format and uniqueness scope
- [ ] Serial-number duplicate policy
- [ ] Whether software licenses are managed in the same module or a dedicated license module
- [ ] Which components require independent Asset Tags
- [ ] Whether asset specifications need field-level history or only current values
- [ ] Which specification fields must support reports and advanced search
- [ ] Purchase cost, depreciation, and disposal accounting ownership
- [ ] Lifecycle statuses and allowed status transitions
- [ ] Company/branch visibility and approval rules
- [ ] Import/update rules for existing Django data
- [ ] Data retention and attachment access rules

---

## 17. Final Recommendation

Implement the system around **Common Asset Fields + configurable Category-Specific Specification Fields**.

Use normalized common asset data for identity, company/branch, lifecycle, ownership, purchase, and warranty information. Use specification definitions and category mappings to control which technical fields appear for each category. Use typed, validated values or a carefully designed hybrid model. Track independently replaceable or assignable components as separate records.

Before development begins, approve the category catalogue, required fields, validation rules, and access matrix. This prevents developers from inventing field meanings during implementation and reduces costly schema changes later.
