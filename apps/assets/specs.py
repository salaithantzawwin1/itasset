"""Category-specific specification catalogue + engine (ADR-0004 hybrid model).

Storage contract (docs/category-schema-design.md, docs/itasset-docs/docs/adr/0004):
- ``Category.schema`` — declarative field definitions:
      {"version": 1, "fields": [{"key", "label", "type", "unit", "choices",
        "required", "level", "min", "max", "max_length", "sensitive", "help"}, ...]}
- ``Asset.attrs`` — JSON values keyed by field key. JSON-native types only:
  str / int / float / bool / ISO-date string (YYYY-MM-DD) / list[str].

The catalogue below is §5 of
docs/new/ITAM_Common_Asset_Fields_Category_Specific_Specifications_Master.md
(16 category groups). Per that document's preface ("a field marked
Recommended is not automatically mandatory") every catalogue field ships
``required=False`` with its requirement level recorded in ``level`` —
requiredness stays a per-category configuration the business owner flips on,
and the engine enforces it whenever a schema sets ``required=True``.

Engine entry points:
- ``validate_specs(category, raw)``      → cleaned dict, or ValidationError
- ``merge_preserved(old, cleaned, cat)`` → old-category values survive a
                                            category change (§8.2: never
                                            silently delete spec data)
- ``build_spec_form_fields(category)``   → dynamic Django form fields
- ``format_spec_value(field, value)``    → display string for detail views
- ``validate_schema_dict(schema)``       → Category.clean() structure check
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import json

from django import forms
from django.core.exceptions import ValidationError

SPEC_TYPES = {
    "string",
    "text",
    "integer",
    "decimal",
    "boolean",
    "choice",
    "multi-choice",
    "date",
    "ip",
}

SPEC_FIELD_PREFIX = "spec__"


def _f(key, label, type, *, unit=None, choices=None, level="optional", help=None, **extra):
    """Field-definition helper — omit empty keys so schemas stay readable."""
    d = {"key": key, "label": label, "type": type, "required": False, "level": level}
    if unit:
        d["unit"] = unit
    if choices:
        d["choices"] = list(choices)
    if help:
        d["help"] = help
    d.update(extra)
    return d


# ---------------------------------------------------------------------------
# §5 catalogue — code → (name, schema). Codes extend the existing taxonomy
# (IT-HW-* hardware, new IT-NET-*/IT-STG-*/IT-SW-* groups).
# ---------------------------------------------------------------------------


def _desktop_fields():
    """§5.1 Desktop PC — shared with Workstation (§5.3 says reuse, don't duplicate)."""
    return [
        _f(
            "cpu_manufacturer",
            "CPU Manufacturer",
            "choice",
            choices=["Intel", "AMD", "Other"],
            level="recommended",
        ),
        _f(
            "cpu_model", "CPU Model", "string", help="e.g. Intel Core i5-14500", level="recommended"
        ),
        _f("cpu_cores", "CPU Cores", "integer", min=1),
        _f("ram_capacity_gb", "RAM Capacity", "decimal", unit="GB", min=0.25, level="recommended"),
        _f("ram_type", "RAM Type", "choice", choices=["DDR3", "DDR4", "DDR5", "Other"]),
        _f("ram_speed_mhz", "RAM Speed", "integer", unit="MHz", min=1),
        _f("motherboard_model", "Motherboard Model", "string"),
        _f(
            "storage_1_type",
            "Primary Storage Type",
            "choice",
            choices=["HDD", "SATA SSD", "NVMe SSD", "Other"],
            level="recommended",
        ),
        _f(
            "storage_1_capacity_gb",
            "Primary Storage Capacity",
            "integer",
            unit="GB",
            min=1,
            level="recommended",
        ),
        _f(
            "storage_2_type",
            "Secondary Storage Type",
            "choice",
            choices=["HDD", "SATA SSD", "NVMe SSD", "Other"],
        ),
        _f("storage_2_capacity_gb", "Secondary Storage Capacity", "integer", unit="GB", min=1),
        _f("gpu_model", "Graphics Adapter", "string", help="Integrated or dedicated"),
        _f("gpu_memory_gb", "GPU Memory", "decimal", unit="GB", min=0),
        _f("psu_wattage_w", "PSU Wattage", "integer", unit="W", min=1),
        _f(
            "case_form_factor",
            "Case Form Factor",
            "choice",
            choices=["Tower", "SFF", "Mini PC", "Other"],
        ),
        _f(
            "os_name", "Operating System", "string", help="e.g. Windows 11 Pro", level="recommended"
        ),
        _f("os_version", "OS Version / Build", "string"),
        _f("tpm_version", "TPM Version", "choice", choices=["None", "1.2", "2.0", "Unknown"]),
        _f("monitor_count", "Number of Monitors", "integer", min=0),
        _f("network_interface", "Network Interface", "string", help="e.g. 1GbE"),
        _f("wifi_supported", "Wi-Fi Supported", "boolean"),
        _f("bluetooth_supported", "Bluetooth Supported", "boolean"),
    ]


CATALOGUE = {
    "IT-HW-DSK": {
        "name": "Desktop / Workstation",
        "schema": {"version": 1, "fields": _desktop_fields()},
    },
    "IT-HW-LAP": {
        "name": "Laptop",
        "schema": {
            "version": 1,
            "fields": [
                _f(
                    "cpu_manufacturer",
                    "CPU Manufacturer",
                    "choice",
                    choices=["Intel", "AMD", "Apple", "Other"],
                    level="recommended",
                ),
                _f(
                    "cpu_model",
                    "CPU Model",
                    "string",
                    help="e.g. Intel Core Ultra 5",
                    level="recommended",
                ),
                _f("cpu_cores", "CPU Cores", "integer", min=1),
                _f(
                    "ram_capacity_gb",
                    "RAM Capacity",
                    "decimal",
                    unit="GB",
                    min=0.5,
                    level="recommended",
                ),
                _f("ram_type", "RAM Type", "choice", choices=["DDR4", "DDR5", "LPDDR", "Other"]),
                _f("ram_upgradeable", "RAM Upgradeable", "boolean"),
                _f(
                    "storage_1_type",
                    "Primary Storage Type",
                    "choice",
                    choices=["HDD", "SATA SSD", "NVMe SSD", "Other"],
                    level="recommended",
                ),
                _f(
                    "storage_1_capacity_gb",
                    "Primary Storage Capacity",
                    "integer",
                    unit="GB",
                    min=1,
                    level="recommended",
                ),
                _f("gpu_model", "Graphics Adapter", "string"),
                _f(
                    "screen_size_in",
                    "Screen Size",
                    "decimal",
                    unit="inches",
                    min=4,
                    max=30,
                    level="recommended",
                ),
                _f("screen_resolution", "Screen Resolution", "string", help="e.g. 1920x1080"),
                _f("touchscreen", "Touchscreen", "boolean"),
                _f("battery_health_pct", "Battery Health", "integer", unit="%", min=0, max=100),
                _f("battery_cycle_count", "Battery Cycle Count", "integer", min=0),
                _f(
                    "battery_condition",
                    "Battery Condition",
                    "choice",
                    choices=["Good", "Fair", "Poor", "Replace", "Unknown"],
                    level="recommended",
                ),
                _f("adapter_wattage_w", "Charger Wattage", "integer", unit="W", min=1),
                _f("adapter_model", "Charger Model", "string"),
                _f("wifi_standard", "Wi-Fi Standard", "string", help="e.g. Wi-Fi 6"),
                _f("bluetooth_version", "Bluetooth Version", "string"),
                _f("os_name", "Operating System", "string", level="recommended"),
                _f("os_version", "OS Version / Build", "string"),
                _f(
                    "device_encryption",
                    "Disk Encryption",
                    "choice",
                    choices=["Enabled", "Disabled", "Unknown"],
                ),
                _f(
                    "bios_version",
                    "BIOS/UEFI Version",
                    "string",
                    help="Useful for support and security",
                ),
            ],
        },
    },
    "IT-HW-WKS": {
        "name": "Workstation",
        # §5.3: desktop field set + workstation-only extras (no duplication).
        "schema": {
            "version": 1,
            "fields": _desktop_fields()
            + [
                _f("cpu_threads", "CPU Threads", "integer", min=1),
                _f("specialized_card", "Specialized Card / Accelerator", "string"),
                _f("cooling_config", "Cooling Configuration", "string"),
            ],
        },
    },
    "IT-HW-SRV": {
        "name": "Physical Server",
        "schema": {
            "version": 1,
            "fields": [
                _f(
                    "server_role",
                    "Server Role",
                    "choice",
                    choices=[
                        "Virtualization",
                        "Database",
                        "File",
                        "Application",
                        "Backup",
                        "Other",
                    ],
                    level="recommended",
                ),
                _f(
                    "chassis_form_factor",
                    "Chassis Form Factor",
                    "choice",
                    choices=["Rack", "Tower", "Blade", "Other"],
                    level="recommended",
                ),
                _f("cpu_model", "CPU Model", "string", level="recommended"),
                _f("cpu_socket_count", "CPU Socket Count", "integer", min=0),
                _f(
                    "cpu_installed_count",
                    "Installed CPU Count",
                    "integer",
                    min=0,
                    level="recommended",
                ),
                _f(
                    "ram_capacity_gb",
                    "Total RAM",
                    "decimal",
                    unit="GB",
                    min=0.5,
                    level="recommended",
                ),
                _f("ram_type", "RAM Type", "choice", choices=["DDR4", "DDR5", "Other"]),
                _f("drive_bay_count", "Drive Bay Count", "integer", min=0),
                _f("raid_controller_model", "RAID Controller", "string"),
                _f("raid_configuration", "RAID Configuration", "string", help="e.g. RAID 1"),
                _f("storage_raw_capacity_tb", "Raw Storage Capacity", "decimal", unit="TB", min=0),
                _f(
                    "storage_usable_capacity_tb",
                    "Usable Storage Capacity",
                    "decimal",
                    unit="TB",
                    min=0,
                ),
                _f("nic_count", "NIC Port Count", "integer", min=0),
                _f("nic_speed", "NIC Speed", "string", help="e.g. 1GbE, 10GbE"),
                _f("psu_redundancy", "Redundant PSU", "boolean"),
                _f(
                    "idrac_ilo_version",
                    "Out-of-band Management",
                    "string",
                    help="iDRAC, iLO, IPMI version",
                ),
                _f("firmware_baseline", "Firmware Baseline", "string"),
                _f("hypervisor", "Hypervisor", "string", help="e.g. VMware ESXi"),
                _f(
                    "os_name",
                    "Operating System",
                    "string",
                    help="Host OS or hypervisor",
                    level="recommended",
                ),
                _f("os_version", "OS / Hypervisor Version", "string", level="recommended"),
                _f("rack_location", "Rack Location", "string"),
                _f("rack_unit", "Rack Unit", "string", help="e.g. U12"),
            ],
        },
    },
    "IT-HW-VM": {
        "name": "Virtual Machine",
        "schema": {
            "version": 1,
            "fields": [
                _f("hypervisor_platform", "Hypervisor Platform", "string"),
                _f("vm_name", "VM Name", "string"),
                _f("vm_uuid", "VM UUID", "string"),
                _f(
                    "host_asset_tag",
                    "Host Asset Tag",
                    "string",
                    help="Asset tag of the physical host",
                ),
                _f("vcpu_count", "vCPU Count", "integer", min=1),
                _f("memory_assigned_gb", "Memory Assigned", "decimal", unit="GB", min=0.25),
                _f("provisioned_storage_gb", "Provisioned Storage", "decimal", unit="GB", min=0),
                _f("guest_os", "Guest OS", "string"),
                _f("guest_os_version", "Guest OS Version", "string"),
                _f(
                    "environment",
                    "Environment",
                    "choice",
                    choices=["Production", "Test", "Development", "DR"],
                ),
                _f("ip_address", "IP Address", "ip"),
                _f("backup_policy", "Backup Policy", "string"),
                _f("service_owner", "Service Owner", "string"),
                _f("application_service", "Application / Service", "string"),
            ],
        },
    },
    "IT-HW-MON": {
        "name": "Monitor",
        "schema": {
            "version": 1,
            "fields": [
                _f(
                    "screen_size_in",
                    "Screen Size",
                    "decimal",
                    unit="inches",
                    min=5,
                    max=200,
                    level="recommended",
                ),
                _f(
                    "panel_type",
                    "Panel Type",
                    "choice",
                    choices=["IPS", "TN", "VA", "OLED", "Other"],
                ),
                _f(
                    "native_resolution",
                    "Native Resolution",
                    "string",
                    help="e.g. 1920x1080",
                    level="recommended",
                ),
                _f("refresh_rate_hz", "Refresh Rate", "integer", unit="Hz", min=1),
                _f(
                    "video_inputs",
                    "Video Inputs",
                    "multi-choice",
                    choices=["HDMI", "DisplayPort", "USB-C", "VGA", "Other"],
                ),
                _f("curved_display", "Curved Display", "boolean"),
                _f("built_in_speakers", "Built-in Speakers", "boolean"),
                _f("power_consumption_w", "Power Consumption", "integer", unit="W", min=1),
                _f("stand_model", "Stand Model", "string"),
            ],
        },
    },
    "IT-HW-PRN": {
        "name": "Printer / Scanner / MFP",
        "schema": {
            "version": 1,
            "fields": [
                _f("device_type", "Device Type", "choice", choices=["Printer", "Scanner", "MFP"]),
                _f(
                    "print_technology",
                    "Print Technology",
                    "choice",
                    choices=["Laser", "Inkjet", "Thermal", "Other"],
                ),
                _f(
                    "color_capability",
                    "Color Capability",
                    "choice",
                    choices=["Monochrome", "Color"],
                ),
                _f("print_speed_ppm", "Print Speed", "integer", unit="ppm", min=1),
                _f("max_paper_size", "Max Paper Size", "string", help="e.g. A4, A3, Legal"),
                _f("duplex_supported", "Duplex Supported", "boolean"),
                _f("network_capability", "Network Capability", "boolean"),
                _f("ip_address", "IP Address", "ip"),
                _f("mac_address", "MAC Address", "string", help="e.g. 00:11:22:33:44:55"),
                _f("meter_count", "Meter Count", "integer", min=0),
                _f("consumable_type", "Consumable Type", "string", help="e.g. toner model"),
                _f("driver_or_firmware_version", "Driver / Firmware Version", "string"),
            ],
        },
    },
    "IT-NET-SW": {
        "name": "Network Switch",
        "schema": {
            "version": 1,
            "fields": [
                _f(
                    "switch_type",
                    "Switch Type",
                    "choice",
                    choices=["Managed", "Unmanaged", "Layer 2", "Layer 3"],
                ),
                _f("port_count", "Port Count", "integer", min=1),
                _f("port_speed_profile", "Port Speed Profile", "string", help="e.g. 1G/10G"),
                _f("sfp_port_count", "SFP Port Count", "integer", min=0),
                _f("poe_supported", "PoE Supported", "boolean"),
                _f("poe_budget_w", "PoE Budget", "integer", unit="W", min=0),
                _f("switching_capacity_gbps", "Switching Capacity", "decimal", unit="Gbps", min=0),
                _f("forwarding_rate_mpps", "Forwarding Rate", "decimal", unit="Mpps", min=0),
                _f("stacking_supported", "Stacking Supported", "boolean"),
                _f("management_ip", "Management IP", "ip"),
                _f("mac_address", "MAC Address", "string"),
                _f("firmware_version", "Firmware Version", "string"),
                _f("rack_unit", "Rack Unit", "string", help="e.g. U12"),
                _f("support_end_date", "Support End Date", "date"),
            ],
        },
    },
    "IT-NET-RT": {
        "name": "Router",
        "schema": {
            "version": 1,
            "fields": [
                _f("wan_interface_types", "WAN Interface Types", "string"),
                _f("lan_port_count", "LAN Port Count", "integer", min=0),
                _f("wan_port_count", "WAN Port Count", "integer", min=0),
                _f("max_throughput_mbps", "Max Throughput", "integer", unit="Mbps", min=0),
                _f("vpn_capability", "VPN Capability", "boolean"),
                _f("vpn_tunnel_capacity", "VPN Tunnel Capacity", "integer", min=0),
                _f("routing_protocols", "Routing Protocols", "string"),
                _f("management_ip", "Management IP", "ip"),
                _f("firmware_version", "Firmware Version", "string"),
                _f("power_supply_redundancy", "Power Supply Redundancy", "boolean"),
                _f("support_end_date", "Support End Date", "date"),
            ],
        },
    },
    "IT-NET-FW": {
        "name": "Firewall / Security Appliance",
        # §5.10 security note: never store credentials/secrets in spec fields.
        "schema": {
            "version": 1,
            "fields": [
                _f("firewall_model", "Firewall Model", "string"),
                _f(
                    "throughput_firewall_gbps", "Firewall Throughput", "decimal", unit="Gbps", min=0
                ),
                _f(
                    "throughput_threat_protection_gbps",
                    "Threat Protection Throughput",
                    "decimal",
                    unit="Gbps",
                    min=0,
                ),
                _f("interface_count", "Interface Count", "integer", min=0),
                _f("interface_speed_profile", "Interface Speed Profile", "string"),
                _f("vpn_throughput_mbps", "VPN Throughput", "integer", unit="Mbps", min=0),
                _f("vpn_tunnel_capacity", "VPN Tunnel Capacity", "integer", min=0),
                _f("ha_capability", "HA Capability", "boolean"),
                _f("ha_role", "HA Role", "string", help="e.g. Active, Passive, Standalone"),
                _f("management_ip", "Management IP", "ip"),
                _f("firmware_version", "Firmware Version", "string"),
                _f("license_expiry_date", "License Expiry Date", "date"),
                _f("subscription_status", "Subscription Status", "string"),
                _f("support_end_date", "Support End Date", "date"),
            ],
        },
    },
    "IT-NET-AP": {
        "name": "Wireless Access Point",
        "schema": {
            "version": 1,
            "fields": [
                _f("wifi_standard", "Wi-Fi Standard", "string", help="e.g. Wi-Fi 6 (802.11ax)"),
                _f(
                    "supported_bands",
                    "Supported Bands",
                    "multi-choice",
                    choices=["2.4GHz", "5GHz", "6GHz"],
                ),
                _f("spatial_streams", "Spatial Streams", "integer", min=1),
                _f("max_data_rate_mbps", "Max Data Rate", "integer", unit="Mbps", min=0),
                _f("ethernet_port_count", "Ethernet Port Count", "integer", min=0),
                _f("poe_standard", "PoE Standard", "string", help="e.g. 802.3af/at/bt"),
                _f("management_ip", "Management IP", "ip"),
                _f("mac_address", "MAC Address", "string"),
                _f("controller_or_cloud_managed", "Controller / Cloud Managed", "string"),
                _f("firmware_version", "Firmware Version", "string"),
                _f(
                    "mounting_type",
                    "Mounting Type",
                    "choice",
                    choices=["Ceiling", "Wall", "Desktop", "Other"],
                ),
            ],
        },
    },
    "IT-STG-NAS": {
        "name": "NAS / Storage Appliance",
        "schema": {
            "version": 1,
            "fields": [
                _f("storage_type", "Storage Type", "string", help="e.g. NAS, SAN"),
                _f("drive_bay_count", "Drive Bay Count", "integer", min=0),
                _f("installed_drive_count", "Installed Drive Count", "integer", min=0),
                _f(
                    "installed_raw_capacity_tb",
                    "Installed Raw Capacity",
                    "decimal",
                    unit="TB",
                    min=0,
                ),
                _f("usable_capacity_tb", "Usable Capacity", "decimal", unit="TB", min=0),
                _f(
                    "raid_or_storage_pool_configuration",
                    "RAID / Storage Pool Configuration",
                    "string",
                ),
                _f("network_port_count", "Network Port Count", "integer", min=0),
                _f("network_speed_profile", "Network Speed Profile", "string"),
                _f("iscsi_supported", "iSCSI Supported", "boolean"),
                _f("snapshot_supported", "Snapshot Supported", "boolean"),
                _f("replication_supported", "Replication Supported", "boolean"),
                _f("firmware_version", "Firmware Version", "string"),
                _f("backup_role", "Backup Role", "string"),
            ],
        },
    },
    "IT-HW-UPS": {
        "name": "UPS",
        "schema": {
            "version": 1,
            "fields": [
                _f("capacity_va", "Capacity", "integer", unit="VA", min=1),
                _f("capacity_w", "Capacity", "integer", unit="W", min=1),
                _f(
                    "topology",
                    "Topology",
                    "choice",
                    choices=["Standby", "Line Interactive", "Online"],
                ),
                _f("input_voltage_v", "Input Voltage", "integer", unit="V", min=0),
                _f("output_voltage_v", "Output Voltage", "integer", unit="V", min=0),
                _f("battery_count", "Battery Count", "integer", min=0),
                _f("battery_type", "Battery Type", "string"),
                _f("battery_install_date", "Battery Install Date", "date"),
                _f("battery_replacement_due_date", "Battery Replacement Due", "date"),
                _f("management_card", "Management Card", "string"),
                _f("management_ip", "Management IP", "ip"),
                _f(
                    "runtime_estimate_minutes", "Runtime Estimate", "integer", unit="minutes", min=0
                ),
            ],
        },
    },
    "IT-HW-MOB": {
        "name": "Mobile Phone / Tablet",
        # Warranty, serial, storage/RAM overlap common columns — kept only where
        # they are device-specific (§7.2: don't duplicate a common field).
        "schema": {
            "version": 1,
            "fields": [
                _f("operating_system", "Operating System", "string"),
                _f("os_version", "OS Version", "string"),
                _f("screen_size_in", "Screen Size", "decimal", unit="inches", min=3, max=30),
                _f("imei_1", "IMEI 1", "string", sensitive=True, help="Restrict access per policy"),
                _f("imei_2", "IMEI 2", "string", sensitive=True),
                _f(
                    "sim_identifier",
                    "SIM Identifier",
                    "string",
                    sensitive=True,
                    help="Only if necessary and protected",
                ),
                _f(
                    "mdm_status",
                    "MDM Status",
                    "choice",
                    choices=["Enrolled", "Not enrolled", "Unknown"],
                ),
                _f(
                    "encryption_status",
                    "Encryption Status",
                    "choice",
                    choices=["Enabled", "Disabled", "Unknown"],
                ),
                _f("battery_health_pct", "Battery Health", "integer", unit="%", min=0, max=100),
                _f("charger_type", "Charger Type", "string"),
            ],
        },
    },
    "IT-SW-LIC": {
        "name": "Software License / Subscription",
        # §5.15: licenses are not physical equipment — keep a vault *reference*
        # only; never store license keys here.
        "schema": {
            "version": 1,
            "fields": [
                _f("software_product_name", "Software Product", "string"),
                _f("publisher", "Publisher", "string"),
                _f(
                    "license_type",
                    "License Type",
                    "choice",
                    choices=["Per User", "Per Device", "Subscription", "Perpetual", "Other"],
                ),
                _f("license_metric", "License Metric", "string"),
                _f("license_quantity_purchased", "Quantity Purchased", "integer", min=0),
                _f("license_quantity_assigned", "Quantity Assigned", "integer", min=0),
                _f(
                    "license_key_reference",
                    "License Key Reference",
                    "string",
                    help="Vault reference only — never the key itself",
                ),
                _f("subscription_start_date", "Subscription Start", "date"),
                _f("subscription_end_date", "Subscription End", "date"),
                _f("renewal_date", "Renewal Date", "date"),
                _f("auto_renewal", "Auto Renewal", "boolean"),
                _f("contract_reference", "Contract Reference", "string"),
                _f("license_owner_department", "Owner Department", "string"),
            ],
        },
    },
    "IT-OTHER": {
        "name": "Other Physical Asset",
        # §5.16: confirm real fields with the responsible department — ship the
        # common columns only rather than speculative fields.
        "schema": {"version": 1, "fields": []},
    },
}


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def spec_schema(category) -> dict:
    """Defensive accessor — legacy/junk schema values degrade to 'no fields'."""
    schema = getattr(category, "schema", None)
    if not isinstance(schema, dict):
        return {"version": 1, "fields": []}
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return {"version": 1, "fields": []}
    return {
        "version": schema.get("version", 1),
        "fields": [f for f in fields if isinstance(f, dict)],
    }


def spec_fields(category) -> list[dict]:
    return spec_schema(category)["fields"]


def validate_schema_dict(schema) -> None:
    """Structural check for a Category.schema value (used by Category.clean)."""
    if schema in (None, ""):
        return
    if not isinstance(schema, dict):
        raise ValidationError(
            {"schema": 'Schema must be a JSON object like {"version": 1, "fields": [...]}'}
        )
    fields = schema.get("fields", [])
    if not isinstance(fields, list):
        raise ValidationError({"schema": 'Schema "fields" must be a list.'})
    seen: set[str] = set()
    for i, f in enumerate(fields):
        if not isinstance(f, dict):
            raise ValidationError({"schema": f"Field #{i + 1} must be an object."})
        key = f.get("key")
        if not key or not isinstance(key, str):
            raise ValidationError({"schema": f'Field #{i + 1} is missing a stable "key".'})
        if key in seen:
            raise ValidationError({"schema": f"Duplicate field key: {key!r}."})
        seen.add(key)
        if not f.get("label"):
            raise ValidationError({"schema": f'Field {key!r} needs a display "label".'})
        ftype = f.get("type")
        if ftype not in SPEC_TYPES:
            raise ValidationError(
                {
                    "schema": (
                        f"Field {key!r} has unknown type {ftype!r} (allowed: {sorted(SPEC_TYPES)})."
                    )
                }
            )
        if ftype in ("choice", "multi-choice") and not f.get("choices"):
            raise ValidationError(
                {"schema": f'Choice field {key!r} needs a non-empty "choices" list.'}
            )


def _is_empty(value) -> bool:
    """§7.1 \"not recorded\": None, blank string and empty list all mean absent."""
    return value is None or value == "" or value == [] or value == ()


def _coerce(fdef: dict, value):
    """Coerce one submitted value to its canonical JSON-native type.

    Accepts both raw strings (API/CSV/POST) and already-typed Python values
    (form cleaned_data). Raises ValueError with a human message on bad input.
    """
    ftype = fdef["type"]

    if ftype in ("string", "text"):
        return str(value).strip()

    if ftype == "integer":
        if isinstance(value, bool):
            raise ValueError("must be a whole number")
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        try:
            return int(value)
        except (TypeError, ValueError):
            raise ValueError("must be a whole number") from None

    if ftype == "decimal":
        if isinstance(value, bool):
            raise ValueError("must be a number")
        if isinstance(value, str):
            value = value.replace(",", "").strip()
        try:
            return float(value)
        except (TypeError, ValueError):
            raise ValueError("must be a number") from None

    if ftype == "boolean":
        if isinstance(value, bool):
            return value
        text = str(value).strip().lower()
        if text in ("true", "1", "yes", "y", "on"):
            return True
        if text in ("false", "0", "no", "n", "off"):
            return False
        raise ValueError("must be Yes or No (leave blank for Unknown)")

    if ftype == "choice":
        text = str(value).strip()
        for opt in fdef.get("choices", []):
            if text == opt or text.lower() == str(opt).lower():
                return opt  # canonical spelling from the option set
        raise ValueError(f"must be one of: {', '.join(fdef.get('choices', []))}")

    if ftype == "multi-choice":
        items = value if isinstance(value, (list, tuple)) else str(value).split(",")
        out = []
        lowered = {str(o).lower(): o for o in fdef.get("choices", [])}
        for item in items:
            text = str(item).strip()
            if not text:
                continue
            hit = lowered.get(text.lower())
            if hit is None:
                raise ValueError(f"must be from: {', '.join(fdef.get('choices', []))}")
            out.append(hit)
        return out

    if ftype == "date":
        if isinstance(value, _dt.datetime):
            return value.date().isoformat()
        if isinstance(value, _dt.date):
            return value.isoformat()
        try:
            return _dt.date.fromisoformat(str(value).strip()).isoformat()
        except ValueError:
            raise ValueError("must be a date in YYYY-MM-DD format") from None

    if ftype == "ip":
        text = str(value).strip()
        try:
            return str(ipaddress.ip_address(text))
        except ValueError:
            raise ValueError("must be a valid IPv4 or IPv6 address") from None

    raise ValueError(f"unsupported field type {ftype!r}")


def validate_specs(category, raw: dict | None) -> dict:
    """Validate/coerce a submitted spec dict against the category schema.

    Rules (master doc §4.3/§7/§8, ADR-0004):
    - unknown keys are rejected (no silent typos in JSONB);
    - values are coerced to canonical JSON-native types;
    - ``required`` fields (schema-driven) must be present and non-empty;
    - min/max/max_length and choice option sets are enforced;
    - blank values are dropped (\"not recorded\" — §7.1).

    Returns the cleaned dict (JSON-serialisable). Raises
    ``django.core.exceptions.ValidationError`` (message_dict keyed by field)
    on any problem.
    """
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ValidationError({"specs": "Specifications must be a JSON object of key/value pairs."})

    fields = {f["key"]: f for f in spec_fields(category)}
    cleaned: dict = {}
    errors: dict[str, list[str]] = {}

    unknown = [k for k in raw if k not in fields]
    if unknown:
        errors["_unknown"] = [f"Unknown specification field(s): {', '.join(sorted(unknown))}."]

    for key, fdef in fields.items():
        value = raw.get(key)
        if _is_empty(value):
            if fdef.get("required"):
                errors[key] = [f"{fdef['label']} is required."]
            continue
        try:
            value = _coerce(fdef, value)
        except ValueError as exc:
            errors[key] = [f"{fdef['label']}: {exc}."]
            continue
        if fdef["type"] in ("integer", "decimal") and not isinstance(value, bool):
            lo, hi = fdef.get("min"), fdef.get("max")
            if lo is not None and value < lo:
                errors[key] = [f"{fdef['label']}: must be at least {lo}."]
                continue
            if hi is not None and value > hi:
                errors[key] = [f"{fdef['label']}: must be at most {hi}."]
                continue
        if fdef["type"] in ("string", "text"):
            max_len = fdef.get("max_length")
            if max_len and len(value) > max_len:
                errors[key] = [f"{fdef['label']}: at most {max_len} characters."]
                continue
        cleaned[key] = value

    if errors:
        raise ValidationError(errors)
    return cleaned


def merge_preserved(old_attrs: dict | None, cleaned: dict, category) -> dict:
    """Combine stored attrs with freshly validated ones — §8.2/§4.3.

    Keys of the *new* category come from ``cleaned``; keys that are not part
    of the new category's schema (values recorded under a previous category,
    or a field later removed from the schema) are preserved verbatim —
    specification data is never silently deleted.
    """
    new_keys = {f["key"] for f in spec_fields(category)}
    kept = {k: v for k, v in (old_attrs or {}).items() if k not in new_keys}
    kept.update(cleaned)
    return kept


def spec_form_initial(category, attrs: dict | None) -> dict:
    """Initial form data for the dynamic spec fields of one asset."""
    attrs = attrs or {}
    return {f"{SPEC_FIELD_PREFIX}{f['key']}": attrs.get(f["key"]) for f in spec_fields(category)}


def build_spec_form_fields(category) -> dict[str, forms.Field]:
    """Dynamic Django form fields for one category (AssetForm + admin form).

    Widgets are typed for good UX; semantic rules (required, min/max,
    option sets, unknown keys) are enforced once by ``validate_specs`` in the
    form's clean — a single source of truth shared with API and import.
    """
    out: dict[str, forms.Field] = {}
    for fdef in spec_fields(category):
        key = fdef["key"]
        label = fdef["label"]
        help_text = fdef.get("help", "")
        if fdef.get("unit"):
            help_text = f"({fdef['unit']})" + (f" {help_text}" if help_text else "")
        common = dict(label=label, required=False, help_text=help_text)
        ftype = fdef["type"]
        if ftype == "text":
            fld = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), **common)
        elif ftype == "string":
            fld = forms.CharField(max_length=fdef.get("max_length", 255), **common)
        elif ftype == "integer":
            fld = forms.IntegerField(**common)
        elif ftype == "decimal":
            fld = forms.DecimalField(max_digits=10, decimal_places=3, **common)
        elif ftype == "boolean":
            # NullBooleanSelect renders/round-trips True/False/None correctly
            # (a plain Select would render False as blank and lose it on save)
            fld = forms.NullBooleanField(**common)
        elif ftype == "choice":
            choices = [("", "—")] + [(c, c) for c in fdef.get("choices", [])]
            fld = forms.ChoiceField(choices=choices, **common)
        elif ftype == "multi-choice":
            fld = forms.MultipleChoiceField(
                choices=[(c, c) for c in fdef.get("choices", [])],
                widget=forms.CheckboxSelectMultiple,
                **common,
            )
        elif ftype == "date":
            fld = forms.DateField(input_formats=["%Y-%m-%d"], **common)
        elif ftype == "ip":
            fld = forms.GenericIPAddressField(protocol="both", **common)
        else:  # pragma: no cover — validate_schema_dict blocks unknown types
            continue
        out[f"{SPEC_FIELD_PREFIX}{key}"] = fld
    return out


def format_spec_value(fdef: dict, value) -> str:
    """Human display for one stored spec value (detail page, exports)."""
    ftype = fdef["type"]
    if ftype == "boolean":
        # tri-state: an explicit unknown reads as Unknown, not "not recorded"
        text = "Yes" if value is True else "No" if value is False else "Unknown"
    elif _is_empty(value):
        return "—"
    elif ftype == "multi-choice":
        text = ", ".join(str(v) for v in value)
    elif ftype == "decimal":
        text = f"{float(value):g}"
    else:
        text = str(value)
    unit = fdef.get("unit")
    return f"{text} {unit}" if unit and ftype in ("integer", "decimal") else text


def spec_rows(category, attrs: dict | None) -> list[tuple[str, str]]:
    """(label, display value) pairs for every recorded spec value, in schema order."""
    attrs = attrs or {}
    rows = []
    for fdef in spec_fields(category):
        value = attrs.get(fdef["key"])
        if _is_empty(value):
            continue
        rows.append((fdef["label"], format_spec_value(fdef, value)))
    return rows


def schema_as_json(schema) -> str:
    """Pretty JSON for admin textareas."""
    return json.dumps(schema or {}, indent=2, ensure_ascii=False)
