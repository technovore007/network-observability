"""Layer 2 normalization, classification and counter-rate processing.

Raw collector output is preserved. Normalized records distinguish observations
from aggregate-eligible counters. Provisional interface correlations are
metadata only and never merge independent counter sources.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

from collector.parsers.huawei_parser import (
    parse_interface_information,
    parse_mac_forwarding_table,
    parse_wifi_neighbor,
)

NOKIA_LAN_CORRELATIONS = {
    0: {
        "interface_id": "netdev_eth0",
        "relationship": "provisional_logical_correlation",
        "confidence": "high_provisional",
        "evidence": "repeated_close_byte_counter_correlation",
    },
    1: {
        "interface_id": "netdev_eth1",
        "relationship": "provisional_logical_correlation",
        "confidence": "high_provisional",
        "evidence": "repeated_link_state_correlation",
    },
    2: {
        "interface_id": "netdev_eth2",
        "relationship": "provisional_logical_correlation",
        "confidence": "high_provisional",
        "evidence": "repeated_link_state_correlation",
    },
    3: {
        "interface_id": "netdev_eth3",
        "relationship": "provisional_logical_correlation",
        "confidence": "high_provisional",
        "evidence": "repeated_close_byte_counter_correlation",
    },
}


def _status(value):
    if value is None:
        return "unknown"
    value = str(value).strip().lower()
    return value if value in {"up", "down"} else "unknown"


def _counter(value):
    return value if isinstance(value, int) and value >= 0 else None


def _record(device_id, interface_id, name, kind, role, source,
            raw_status=None, physical=False, parent=None, counters=None,
            aggregate_eligible=False, classification_confidence="provisional",
            **extra):
    return {
        "device_id": device_id,
        "interface_id": str(interface_id),
        "interface_name": name,
        "interface_type": kind,
        "interface_role": role,
        "is_physical": physical,
        "parent_interface": parent,
        "operational_status": _status(raw_status),
        "speed_mbps": extra.pop("speed_mbps", None),
        "duplex": extra.pop("duplex", None),
        "counters": {
            key: _counter((counters or {}).get(key))
            for key in (
                "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
                "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"
            )
        },
        "counter_source": source,
        "aggregate_eligible": aggregate_eligible,
        "classification_confidence": classification_confidence,
        **extra,
    }


def normalize_nokia(device):
    records = []

    # Preserve native LAN statistics and attach correlation metadata only.
    for item in device.get("ethernet") or []:
        iid = item.get("interface_id")

        correlation = NOKIA_LAN_CORRELATIONS.get(iid)
        correlation_metadata = None

        if correlation:
            correlation_metadata = {
                **correlation,
                "physical_socket_verified": False,
                "counter_sources_merged": False,
            }

        records.append(_record(
            "nokia_primary", f"lan_stats_{iid}", f"LAN interface {iid}",
            "ethernet", "lan", "lan_stats",
            item.get("status"), physical=True,
            counters={
                "rx_bytes": item.get("bytes_received"),
                "tx_bytes": item.get("bytes_sent"),
                "rx_packets": item.get("packets_received"),
                "tx_packets": item.get("packets_sent"),
                "rx_errors": item.get("errors_received"),
                "tx_errors": item.get("errors_sent"),
                "rx_dropped": item.get("discard_packets_received"),
                "tx_dropped": item.get("discard_packets_sent"),
            },
            aggregate_eligible=False,
            classification_confidence=(
                "source-confirmed; physical socket unknown"
            ),
            source_interface_id=iid,
            correlation=correlation_metadata,
        ))

    # Linux-style interface counters remain independent observations.
    for item in device.get("network_interfaces") or []:
        name = item.get("interface")
        if not name:
            continue

        if name == "ppp111":
            kind, role = "wan", "internet"
        elif name == "br0":
            kind, role = "bridge", "lan"
        elif name in {"eth0", "eth1", "eth2", "eth3"}:
            kind, role = "ethernet", "lan_candidate"
        elif name.startswith(("ra", "rai")):
            kind, role = "wifi", "wireless"
        elif name == "lo":
            kind, role = "loopback", "internal"
        elif name.startswith(("gpon", "pon")):
            kind, role = "gpon", "access"
        else:
            kind, role = "virtual", "internal_or_unknown"

        records.append(_record(
            "nokia_primary", f"netdev_{name}", name, kind, role,
            "network_interface_all", item.get("status"),
            physical=(name in {"eth0", "eth1", "eth2", "eth3"}),
            counters={k: item.get(k) for k in (
                "rx_bytes", "tx_bytes", "rx_packets", "tx_packets",
                "rx_errors", "tx_errors", "rx_dropped", "tx_dropped"
            )},
            aggregate_eligible=False,
            classification_confidence=(
                "name-based candidate; not a verified socket mapping"
                if name in {"eth0", "eth1", "eth2", "eth3"}
                else "observed interface; role inferred from name"
            ),
            ipv4_address=item.get("ipv4_address"),
            ipv6_addresses=item.get("ipv6_addresses", []),
            mtu=item.get("mtu"),
        ))

    return records


def _huawei_link_config(device, port_id):
    """Parse Huawei's enum-based get port config output."""
    commands = (device.get("extended") or {}).get("commands") or {}
    item = commands.get(f"port_{port_id}_link_configuration") or {}
    output = item.get("output") or ""

    def enum_value(field):
        match = re.search(
            rf"^\s*{field}\s*\([^\n]*?\)\s*:\s*(\d+)\s*$",
            output,
            re.I | re.M,
        )
        return int(match.group(1)) if match else None

    speed_codes = {0: 10, 1: 100, 2: 1000, 3: 10000}
    speed_code = enum_value("Speed")
    duplex_code = enum_value("Duplex")
    link_code = enum_value("Link")

    status = {0: "down", 1: "up"}.get(link_code)
    speed = speed_codes.get(speed_code) if status == "up" else None
    duplex = (
        {0: "half", 1: "full"}.get(duplex_code)
        if status == "up" else None
    )

    return speed, duplex, status


def normalize_huawei(device):
    records = []

    # Physical LAN port counters: these remain the authoritative physical
    # port observations and are not merged with display-if logical records.
    for item in device.get("ethernet") or []:
        port_id = item.get("port_id")
        if port_id is None:
            continue

        speed, duplex, link_status = _huawei_link_config(device, port_id)

        counters = {
            "rx_bytes": item.get("rx_bytes"),
            "tx_bytes": item.get("tx_bytes"),
            "rx_packets": item.get("rx_packets"),
            "tx_packets": item.get("tx_packets"),
            "rx_errors": sum(v or 0 for v in (
                item.get("rx_fifo_overrun"), item.get("rx_fcs_errors"),
                item.get("rx_alignment_errors"), item.get("rx_over_max"),
                item.get("rx_byte_errors")
            )) if any(item.get(k) is not None for k in (
                "rx_fifo_overrun", "rx_fcs_errors", "rx_alignment_errors",
                "rx_over_max", "rx_byte_errors"
            )) else None,
            "tx_errors": sum(v or 0 for v in (
                item.get("tx_excess_collisions"), item.get("tx_late_collisions"),
                item.get("tx_single_collisions"), item.get("tx_multiple_collisions")
            )) if any(item.get(k) is not None for k in (
                "tx_excess_collisions", "tx_late_collisions",
                "tx_single_collisions", "tx_multiple_collisions"
            )) else None,
        }

        records.append(_record(
            "huawei_ap", f"lan{port_id}", f"LAN{port_id}",
            "ethernet", "lan", "display_portstatistics_portnum",
            link_status, physical=True,
            counters=counters, aggregate_eligible=False,
            classification_confidence="physical port ID confirmed",
            speed_mbps=speed, duplex=duplex, source_port_id=port_id,
            topology_note=(
                "Nokia uplink and other learned LAN devices"
                if port_id == 1 else None
            ),
        ))

    # Logical interfaces from display if. This command reports interface
    # configuration/status, not physical-port traffic counters.
    commands = (device.get("extended") or {}).get("commands") or {}
    interface_command = commands.get("interface_information") or {}
    command_status = str(interface_command.get("status") or "").lower()

    if command_status == "success":
        logical_interfaces = parse_interface_information(
            interface_command.get("output") or ""
        )

        for item in logical_interfaces:
            name = item.get("interface")
            if not name:
                continue

            if name == "br0":
                kind, role = "bridge", "lan"
            elif name in {"lan0", "lan1", "lan2", "lan3"}:
                kind, role = "ethernet", "lan"
            else:
                kind, role = "unknown", "unknown"

            records.append(_record(
                "huawei_ap",
                f"logical_{name}",
                name,
                kind,
                role,
                "display_if",
                raw_status=None,
                physical=False,
                counters={},
                aggregate_eligible=False,
                classification_confidence=(
                    "CLI-reported logical interface; "
                    "physical port mapping unverified"
                ),
                netdev_if_index=item.get("netdev_if_index"),
                raw_interface_type=item.get("raw_interface_type"),
                mac_address=item.get("mac_address"),
                physical_status=item.get("physical_status"),
                protocol_status=item.get("protocol_status"),
                ipv4_address=item.get("ipv4_address"),
                ipv4_netmask=item.get("ipv4_netmask"),
                service_vlan=item.get("service_vlan"),
                service_priority=item.get("service_priority"),
                customer_vlan=item.get("customer_vlan"),
                customer_priority=item.get("customer_priority"),
                physical_port_index=item.get("physical_port_index"),
                multicast_vlan=item.get("multicast_vlan"),
                priority_policy=item.get("priority_policy"),
                default_priority=item.get("default_priority"),
            ))
    return records


def normalize_huawei_forwarding(device):
    """Normalize Huawei MAC forwarding-table observations separately."""

    commands = (device.get("extended") or {}).get("commands") or {}
    mac_command = commands.get("mac_forwarding_table") or {}

    if str(mac_command.get("status") or "").lower() != "success":
        return []

    forwarding_entries = parse_mac_forwarding_table(
        mac_command.get("output") or ""
    )

    records = []

    for entry in forwarding_entries:
        records.append(_record(
            "huawei_ap",
            f"mac_{entry['vlan_id']}_{entry['mac_address']}_{entry['index']}",
            entry["mac_address"],
            "mac_forwarding_entry",
            "layer2_forwarding",
            "display_macaddress",
            raw_status=None,
            physical=False,
            counters={},
            aggregate_eligible=False,
            classification_confidence=(
                "CLI-reported MAC-to-port association"
            ),
            mac_address=entry["mac_address"],
            vlan_id=entry["vlan_id"],
            learned_port_id=entry["port_id"],
            learned_interface=entry["learned_interface"],
            forwarding_entry_index=entry["index"],
            entry_type=entry["entry_type"],
        ))

    return records

def normalize_huawei_wifi_neighbours(device):
    """Normalize nearby Wi-Fi access points detected by the Huawei AP."""

    extended = device.get("extended") or {}
    commands = extended.get("commands") or {}
    scan_command = commands.get("wifi_neighbor_scan") or {}

    status = str(scan_command.get("status") or "").lower()

    result = {
        "collection_status": (
            "success" if status == "success"
            else "failed" if scan_command
            else "not_collected"
        ),
        "collected_at": extended.get("collected_at"),
        "scan_metadata": {
            "reported_ap_count": None,
            "parsed_ap_count": 0,
            "current_working_channels": {
                "2.4GHz": None,
                "5GHz": None,
            },
        },
        "access_points": [],
    }

    if status != "success":
        return result

    parsed = parse_wifi_neighbor(scan_command.get("output") or "")

    result["scan_metadata"] = {
        "reported_ap_count": parsed["reported_ap_count"],
        "parsed_ap_count": parsed["parsed_ap_count"],
        "current_working_channels": parsed["current_working_channels"],
    }

    result["access_points"] = parsed["access_points"]

    return result

def normalize_device(device_id, device):
    if device_id == "nokia":
        return normalize_nokia(device)
    if device_id == "huawei":
        return normalize_huawei(device)
    raise ValueError(f"Unsupported device_id: {device_id}")


class CounterRateTracker:
    """Calculate rates from successive cumulative samples."""

    def __init__(self):
        self.previous = {}

    def update(self, record, timestamp=None):
        timestamp = timestamp or datetime.now(timezone.utc).timestamp()
        key = (record["device_id"], record["interface_id"])
        counters = record.get("counters") or {}
        previous = self.previous.get(key)

        rates = {}
        states = {}

        for field in ("rx_bytes", "tx_bytes"):
            current = counters.get(field)
            rate_field = field.replace("_bytes", "_mbps")

            if current is None:
                rates[rate_field] = None
                states[field] = "unavailable"
                continue

            if record.get("operational_status") != "up":
                rates[rate_field] = None
                states[field] = "interface_down"
                continue

            if previous is None:
                rates[rate_field] = None
                states[field] = "baseline"
                continue

            old_value = previous.get(field)
            old_time = previous.get("timestamp")
            elapsed = timestamp - old_time if old_time is not None else 0

            if old_value is None:
                rates[rate_field] = None
                states[field] = "unavailable"
            elif current < old_value:
                rates[rate_field] = None
                states[field] = "counter_reset_or_rollover"
            elif elapsed <= 0:
                rates[rate_field] = None
                states[field] = "invalid_interval"
            else:
                rates[rate_field] = round(
                    (current - old_value) * 8 / elapsed / 1_000_000, 6
                )
                states[field] = "valid"

        self.previous[key] = {
            "timestamp": timestamp,
            "rx_bytes": counters.get("rx_bytes"),
            "tx_bytes": counters.get("tx_bytes"),
        }

        return {"rates": rates, "counter_states": states}


def build_layer2(devices):
    """Build normalized Layer 2 observations."""

    normalized = {}
    forwarding_tables = {}
    wifi_neighbours = {}

    for device_id, device in devices.items():
        normalized[device_id] = normalize_device(device_id, device)

        if device_id == "huawei":
            forwarding_tables["huawei"] = (
                normalize_huawei_forwarding(device)
            )

            wifi_neighbours["huawei"] = (
                normalize_huawei_wifi_neighbours(device)
            )

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "devices": normalized,
        "forwarding_tables": forwarding_tables,
        "wifi_neighbours": wifi_neighbours,
        "aggregation_policy": {
            "default": "no cross-interface aggregation",
            "nokia": (
                "lan stats and network_interface_all remain separate; "
                "provisional logical correlations are metadata only; "
                "physical socket mapping is unverified"
            ),
            "huawei": (
                "physical LAN port counters and display-if logical "
                "interfaces remain separate; MAC forwarding observations "
                "are stored independently; nearby Wi-Fi access points "
                "are stored independently; LAN1 includes the Nokia uplink "
                "and must not be added to Nokia WAN totals"
            ),
        },
    }
