
"""Parsers for Nokia G-2425G-A CLI output."""

import re


def parse_cpu(output: str) -> dict:
    match = re.search(
        r"Current CPU Usage:\s*(\d+)\s*%",
        output,
        re.IGNORECASE,
    )

    return {
        "cpu_usage_percent": int(match.group(1)) if match else None
    }


def parse_memory(output: str) -> dict:
    total = re.search(r"MemTotal:\s*(\d+)", output)
    free = re.search(r"MemFree:\s*(\d+)", output)

    total_value = int(total.group(1)) if total else None
    free_value = int(free.group(1)) if free else None

    used_value = (
        total_value - free_value
        if total_value is not None and free_value is not None
        else None
    )

    usage_percent = (
        round(used_value / total_value * 100, 2)
        if total_value and used_value is not None
        else None
    )

    return {
        "memory_total_raw": total_value,
        "memory_free_raw": free_value,
        "memory_used_raw": used_value,
        "memory_usage_percent": usage_percent,
    }


def parse_sysinfo(output: str) -> dict:
    uptime = re.search(
        r"System Uptime:\s*(.+)",
        output,
    )

    mac = re.search(
        r"MACAddress\s*=\s*(\S+)",
        output,
    )

    product = re.search(
        r"ProductClass:\s*\[(.*?)\]",
        output,
    )

    return {
        "uptime": uptime.group(1).strip() if uptime else None,
        "mac_address": mac.group(1) if mac else None,
        "product_class": product.group(1) if product else None,
    }


def parse_lan_stats(output: str) -> list[dict]:
    """Parse Nokia Ethernet interface statistics."""

    interfaces = []

    blocks = re.split(
        r"Ethernet Interface\s*-\s*(\d+)\s*Statistics:",
        output,
        flags=re.IGNORECASE,
    )

    for index in range(1, len(blocks), 2):
        interface_id = int(blocks[index])
        block = blocks[index + 1]

        status_match = re.search(
            r"Status\s*=\s*(up|down)",
            block,
            re.IGNORECASE,
        )

        status = (
            status_match.group(1).lower()
            if status_match else None
        )

        interface = {
            "interface_id": interface_id,
            "status": status,
        }

        # A down interface has no valid traffic sample.
        if status != "up":
            for field in [
                "bytes_sent",
                "bytes_received",
                "packets_sent",
                "packets_received",
                "errors_sent",
                "errors_received",
                "discard_packets_sent",
                "discard_packets_received",
                "unicast_packets_sent",
                "unicast_packets_received",
                "multicast_packets_sent",
                "multicast_packets_received",
                "broadcast_packets_sent",
                "broadcast_packets_received",
            ]:
                interface[field] = None

            interfaces.append(interface)
            continue

        counters = re.findall(
            r"^\s*(\w+)\s*:\s*(\d+)\s*,?\s*$",
            block,
            re.MULTILINE,
        )

        raw_counters = {
            key.lower(): int(value)
            for key, value in counters
        }

        field_mapping = {
            "bytes_sent": "bytessent",
            "bytes_received": "bytesreceived",
            "packets_sent": "packetssent",
            "packets_received": "packetsreceived",
            "errors_sent": "errorssent",
            "errors_received": "errorsreceived",
            "discard_packets_sent": "discardpacketssent",
            "discard_packets_received": "discardpacketsreceived",
            "unicast_packets_sent": "unicastpacketssent",
            "unicast_packets_received": "unicastpacketsreceived",
            "multicast_packets_sent": "multicastpacketssent",
            "multicast_packets_received": "multicastpacketsreceived",
            "broadcast_packets_sent": "broadcastpacketssent",
            "broadcast_packets_received": "broadcastpacketsreceived",
        }

        for normalized, raw_name in field_mapping.items():
            interface[normalized] = raw_counters.get(raw_name)

        interfaces.append(interface)

    return interfaces


def parse_network_interfaces(output: str) -> list[dict]:
    """Parse Linux-style network interface statistics from Nokia."""

    interface_blocks = re.split(
        r"(?m)^(\S+)\s+Link encap:",
        output,
    )

    interfaces = []

    for index in range(1, len(interface_blocks), 2):
        name = interface_blocks[index]
        block = interface_blocks[index + 1]

        def extract(pattern):
            match = re.search(pattern, block, re.IGNORECASE)
            return int(match.group(1)) if match else None

        rx = re.search(
            r"RX packets:(\d+)\s+errors:(\d+)\s+"
            r"dropped:(\d+)\s+overruns:(\d+)\s+frame:(\d+)",
            block,
            re.IGNORECASE,
        )

        tx = re.search(
            r"TX packets:(\d+)\s+errors:(\d+)\s+"
            r"dropped:(\d+)\s+overruns:(\d+)\s+carrier:(\d+)",
            block,
            re.IGNORECASE,
        )

        ipv4 = re.search(
            r"inet addr:(\S+)",
            block,
            re.IGNORECASE,
        )

        ipv6 = re.findall(r"inet6 addr:\s*(\S+)", block, re.IGNORECASE)

        flags = re.search(
            r"^\s*(.*?)\s+MTU:(\d+)",
            block,
            re.MULTILINE,
        )

        interfaces.append({
            "interface": name,
            "status": (
                "up" if flags and "UP" in flags.group(1).split()
                else "down" if flags else None
            ),
            "ipv4_address": ipv4.group(1) if ipv4 else None,
            "ipv6_addresses": ipv6 if ipv6 else [],
            "mtu": int(flags.group(2)) if flags else None,

            "rx_packets": int(rx.group(1)) if rx else None,
            "rx_errors": int(rx.group(2)) if rx else None,
            "rx_dropped": int(rx.group(3)) if rx else None,
            "rx_overruns": int(rx.group(4)) if rx else None,

            "tx_packets": int(tx.group(1)) if tx else None,
            "tx_errors": int(tx.group(2)) if tx else None,
            "tx_dropped": int(tx.group(3)) if tx else None,
            "tx_overruns": int(tx.group(4)) if tx else None,

            "rx_bytes": extract(r"RX bytes:(\d+)"),
            "tx_bytes": extract(r"TX bytes:(\d+)"),
        })

    return interfaces


def parse_hosts(output: str) -> list[dict]:
    """Parse Nokia DHCP and connected-host inventory."""

    hosts = []

    for line in output.splitlines():
        line = line.strip()

        # Skip the CLI header and empty lines.
        if not line or line.startswith("Status"):
            continue

        columns = re.split(r"\s+", line, maxsplit=5)

        # Expected columns:
        # Status, Connection Type, Allocation,
        # IPv4 Address, Hardware Address, HostName
        if len(columns) != 6:
            continue

        status, connection_type, allocation, ip, mac, hostname = columns

        # Ignore lines that do not resemble host records.
        if not re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", ip):
            continue

        if not re.fullmatch(r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}", mac):
            continue

        hosts.append({
            "status": status.lower(),
            "connection_type": connection_type,
            "allocation": allocation.lower(),
            "ipv4_address": ip,
            "mac_address": mac.lower(),
            "hostname": hostname,
        })

    return hosts


def parse_wifi_clients(output: str) -> list[dict]:
    """Parse Nokia associated Wi-Fi clients across frequency bands."""

    clients = []
    current_band = None
    current_ssid = None

    for line in output.splitlines():
        line = line.strip()

        if not line:
            continue

        band_match = re.search(
            r"OperatingFrequencyBand\s*=\s*(.+)",
            line,
            re.IGNORECASE,
        )

        if band_match:
            current_band = band_match.group(1).strip()
            continue

        ssid_match = re.search(
            r"SSID\s*=\s*(.+)",
            line,
            re.IGNORECASE,
        )

        if ssid_match:
            current_ssid = ssid_match.group(1).strip()
            continue

        # Skip table headers and separators.
        if line.startswith("DeviceName") or line.startswith("---"):
            continue

        # Expected columns: DeviceName, MACAddress, Status
        match = re.match(
            r"(\S+)\s+"
            r"([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\s+"
            r"(\S+)",
            line,
        )

        if not match:
            continue

        device_name, mac_address, status = match.groups()

        clients.append({
            "device_name": device_name,
            "mac_address": mac_address.lower(),
            "status": status.lower(),
            "frequency_band": current_band,
            "ssid": current_ssid,
        })

    return clients
