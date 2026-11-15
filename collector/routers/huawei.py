"""Huawei EchoLife HG8145V5 router interface."""

from datetime import datetime, timezone

from collector.routers.base import SSHRouter
from collector.parsers import huawei_parser


class HuaweiRouter(SSHRouter):

    def __init__(self, host, username, password, timeout=10):
        super().__init__(
            host=host,
            username=username,
            password=password,
            prompt_pattern=r"(?:WAP|SU_WAP)>",
            timeout=timeout,
            legacy_rsa=True,
        )

    def open_cli(self):
        """Enter Huawei super-user CLI."""
        self.open_shell()
        self.execute("su")

    def collect_system_metrics(self):
        """Collect and parse Huawei system telemetry."""
        collected_at = datetime.now(timezone.utc).isoformat()
        sysinfo_output = self.execute("display sysinfo")
        memory_output = self.execute("display memory info")

        return {
            "device": "huawei",
            "collected_at": collected_at,
            "metrics": {
                **huawei_parser.parse_sysinfo(sysinfo_output),
                **huawei_parser.parse_memory(memory_output),
            },
        }

    def collect_ethernet_metrics(self):
        """Collect byte and packet statistics from Huawei Ethernet ports."""
        collected_at = datetime.now(timezone.utc).isoformat()
        interfaces = []

        for port_id in range(1, 5):
            output = self.execute(
                f"display portstatistics portnum {port_id}"
            )
            interfaces.append(
                huawei_parser.parse_port_statistics(output)
            )

        return {
            "device": "huawei",
            "collected_at": collected_at,
            "interfaces": interfaces,
        }

    def collect_wifi_clients(self):
        """Collect Huawei associated Wi-Fi stations."""
        output = self.execute("display wifi associate")

        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "clients": huawei_parser.parse_wifi_associate(output),
        }

    def collect_extended_telemetry(
        self,
        include_neighbor_scan=False,
        wifi_clients=None,
    ):
        """Collect Huawei device, port, neighbour and Wi-Fi diagnostics.

        Neighbour scans are opt-in to avoid repeatedly triggering radio scans.
        Per-station diagnostics are collected for currently associated MACs.
        """
        commands = [
            ("device_information", "display deviceInfo"),
            ("version_information", "display version"),
            ("cpu_hardware_information", "display cpu info"),
            ("interface_information", "display if"),
            ("mac_forwarding_table", "display macaddress"),
            ("lan_port_workmode", "display lanport workmode"),
            ("ip_neighbour_table", "display ip neigh"),
            ("wifi_radio_information", "display wifi radio"),
            ("wifi_configuration", "display wifi information"),
            ("wlan_station_information", "display wlan stainfo"),
        ]

        for port_id in range(1, 5):
            commands.append((
                f"port_{port_id}_link_configuration",
                f"get port config portid {port_id}",
            ))
            commands.append((
                f"port_{port_id}_packet_statistics",
                f"display port statistics portid {port_id}",
            ))

        if include_neighbor_scan:
            commands.append(("wifi_neighbor_scan", "display wifi neighbor", 60))

        results = self.collect_raw_commands(commands)

        # The station-specific command is useful only for currently associated
        # clients. MACs are taken from the parsed association table.
        for client in wifi_clients or []:
            mac = client.get("mac_address")
            if not mac:
                continue
            key = f"wifi_station_{mac.replace(':', '')}"
            results.update(self.collect_raw_commands([
                (key, f"display wlan stainfo mac {mac}")
            ]))

        return {
            "device": "huawei",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "commands": results,
            "notes": {
                "wifi_neighbor_scan_included": include_neighbor_scan,
                "wifi_neighbor_scan_warning": (
                    "The neighbour scan is opt-in; avoid rapid repeated scans."
                ),
                "ethernet_port_mapping": {
                    "1": "Nokia uplink and other learned LAN devices",
                    "2": "Bedroom TV",
                    "3": "CCTV camera",
                    "4": "No learned MAC observed in previous capture",
                },
            },
        }
