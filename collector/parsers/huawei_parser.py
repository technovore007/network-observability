
"""Parsers for Huawei EchoLife HG8145V5 CLI output."""

import re


def parse_sysinfo(output: str) -> dict:

    cpu = re.search(
        r"CpuUsed\s*=\s*(\d+)\s*Percent",
        output,
        re.IGNORECASE,
    )

    memory = re.search(
        r"MemUsed\s*=\s*(\d+)\s*Percent",
        output,
        re.IGNORECASE,
    )

    clock = re.search(
        r"CurTime\s*=\s*(.+)",
        output,
        re.IGNORECASE,
    )

    return {
        "cpu_usage_percent": int(cpu.group(1)) if cpu else None,
        "memory_usage_percent": int(memory.group(1)) if memory else None,
        "router_clock_raw": clock.group(1).strip() if clock else None,
    }


def parse_memory(output: str) -> dict:

    match = re.search(
        r"Mem:\s*(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)",
        output,
    )

    if not match:
        return {
            "memory_total_raw": None,
            "memory_used_raw": None,
            "memory_free_raw": None,
            "memory_shared_raw": None,
            "memory_buffers_raw": None,
        }

    total, used, free, shared, buffers = map(
        int,
        match.groups(),
    )

    return {
        "memory_total_raw": total,
        "memory_used_raw": used,
        "memory_free_raw": free,
        "memory_shared_raw": shared,
        "memory_buffers_raw": buffers,
    }


def parse_port_statistics(output: str) -> dict:
    """Parse Huawei Ethernet port statistics."""

    port_match = re.search(
        r"Ethernet portid\s*=\s*(\d+)",
        output,
        re.IGNORECASE,
    )

    if not port_match:
        raise ValueError("Unable to identify Huawei Ethernet port")

    port_id = int(port_match.group(1))

    raw_counters = {
        key.lower(): int(value)
        for key, value in re.findall(
            r"^\s*([a-zA-Z0-9_]+)\s*:\s*(\d+)\s*$",
            output,
            re.MULTILINE,
        )
    }

    return {
        "port_id": port_id,

        "rx_packets": raw_counters.get("rx"),
        "tx_packets": raw_counters.get("tx"),

        "rx_bytes": raw_counters.get("rx_byte_ok"),
        "tx_bytes": raw_counters.get("tx_byte_ok"),

        "rx_unicast_packets": raw_counters.get("rx_uc"),
        "tx_unicast_packets": raw_counters.get("tx_uc"),

        "rx_multicast_packets": raw_counters.get("rx_mc"),
        "tx_multicast_packets": raw_counters.get("tx_mc"),

        "rx_broadcast_packets": raw_counters.get("rx_bc"),
        "tx_broadcast_packets": raw_counters.get("tx_bc"),

        "rx_fifo_overrun": raw_counters.get("rx_fifo_overrun"),
        "rx_fcs_errors": raw_counters.get("rx_fcs_err"),
        "rx_alignment_errors": raw_counters.get("rx_align_err"),
        "rx_over_max": raw_counters.get("rx_over_max"),
        "rx_byte_errors": raw_counters.get("rx_byte_err"),

        "tx_excess_collisions": raw_counters.get("tx_excess_col"),
        "tx_late_collisions": raw_counters.get("tx_late_col"),
        "tx_single_collisions": raw_counters.get("tx_single_col"),
        "tx_multiple_collisions": raw_counters.get("tx_multi_col"),
    }


def parse_wifi_associate(output: str) -> list[dict]:
    """Parse Huawei Wi-Fi associated station information."""

    clients = []

    current_band = None

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        band_match = re.search(
            r"(\d+(?:\.\d+)?GHz)",
            line,
            re.IGNORECASE,
        )

        if "#" in line and band_match:
            current_band = band_match.group(1)
            continue

        # Skip summary and table header lines.
        if (
            line.startswith("Number of associated")
            or line.startswith("Mac ")
            or set(line) == {"#"}
            or line.lower() == "success!"
        ):
            continue

        match = re.match(
            r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}|-"
            r"[0-9a-fA-F]{2}){5})\s+"
            r"(\S+)\s+"
            r"(\d+)\s+"
            r"(\S+)\s+"
            r"(\S+)\s+"
            r"(\S+)\s+"
            r"(\S+)\s+"
            r"(\S+)\s+"
            r"(\S+)"
            r"(?:\s+(\S+))?"
            r"(?:\s+(\S+))?"
            r"(?:\s+(\S+))?",
            line,
        )

        if not match:
            continue

        (
            mac,
            ssid,
            association_time,
            tx_rate,
            rx_rate,
            mode,
            antennas,
            power_save,
            dual_band,
            beamforming,
            support_11k,
            support_11v,
        ) = match.groups()

        clients.append({
            "mac_address": mac.lower(),
            "ssid": ssid,
            "frequency_band": current_band,
            "association_time_raw": int(association_time),
            "tx_rate": tx_rate,
            "rx_rate": rx_rate,
            "mode": mode,
            "antennas": antennas,
            "power_save": power_save,
            "dual_band": dual_band,
            "beamforming": beamforming,
            "support_11k": support_11k,
            "support_11v": support_11v,
        })

    return clients
