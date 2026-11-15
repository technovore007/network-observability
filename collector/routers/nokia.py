
"""Nokia G-2425G-A router interface."""

from datetime import datetime, timezone

from collector.routers.base import SSHRouter
from collector.parsers import nokia_parser


class NokiaRouter(SSHRouter):

    def __init__(self, host, username, password, timeout=10):
        super().__init__(
            host=host,
            username=username,
            password=password,
            prompt_pattern=r"user(?:\(show\))?[>#]",
            timeout=timeout,
        )

    def open_cli(self):
        """Initialize Nokia CLI in show mode."""
        self.open_shell()
        self.execute("enable")
        self.execute("show")

    def collect_system_metrics(self):
        """Collect and parse Nokia system telemetry."""
        collected_at = datetime.now(timezone.utc).isoformat()
        cpu_output = self.execute("cpu")
        memory_output = self.execute("mem")
        sysinfo_output = self.execute("sysinfo")

        return {
            "device": "nokia",
            "collected_at": collected_at,
            "metrics": {
                **nokia_parser.parse_cpu(cpu_output),
                **nokia_parser.parse_memory(memory_output),
                **nokia_parser.parse_sysinfo(sysinfo_output),
            },
        }

    def collect_ethernet_metrics(self):
        """Collect Nokia Ethernet interface statistics."""
        collected_at = datetime.now(timezone.utc).isoformat()
        output = self.execute("lan stats", timeout=30)

        return {
            "device": "nokia",
            "collected_at": collected_at,
            "interfaces": nokia_parser.parse_lan_stats(output),
        }

    def collect_network_interfaces(self):
        """Collect Nokia network interface statistics."""
        collected_at = datetime.now(timezone.utc).isoformat()
        output = self.execute("network interface all")

        return {
            "device": "nokia",
            "collected_at": collected_at,
            "interfaces": nokia_parser.parse_network_interfaces(output),
        }

    def collect_hosts(self):
        """Collect Nokia connected-host inventory."""
        collected_at = datetime.now(timezone.utc).isoformat()
        output = self.execute("lan ip hosts")

        return {
            "device": "nokia",
            "collected_at": collected_at,
            "hosts": nokia_parser.parse_hosts(output),
        }

    def collect_wifi_clients(self):
        """Collect Nokia associated Wi-Fi clients."""
        collected_at = datetime.now(timezone.utc).isoformat()
        output = self.execute("wifi client list")

        return {
            "device": "nokia",
            "collected_at": collected_at,
            "clients": nokia_parser.parse_wifi_clients(output),
        }

    def collect_extended_telemetry(self, include_neighbor_scan=False):
        """Collect additional Nokia metadata, WAN, DHCP and neighbour data.

        The `wlan` command performs a nearby-AP scan and writes scan data to
        router flash. It is opt-in so it is not accidentally run every cycle.
        """
        commands = [
            ("hardware_version", "hwversion"),
            ("software_version", "swversion"),
            ("build_information", "buildinfo"),
            ("wan_status", "wan all status"),
            ("wan_statistics", "wan all statistics"),
            ("wan_uptime", "wan all uptime"),
            ("dhcp_configuration", "lan ip dhcp"),
            ("arp_table", "arp"),
        ]

        if include_neighbor_scan:
            commands.append(("wifi_neighbor_scan", "wlan", 60))

        return {
            "device": "nokia",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "commands": self.collect_raw_commands(commands),
            "notes": {
                "primary_wan_interface": "ppp111",
                "wan_rx_direction": "download",
                "wan_tx_direction": "upload",
                "wifi_neighbor_scan_included": include_neighbor_scan,
                "wifi_neighbor_scan_warning": (
                    "The wlan scan writes results to flash; do not poll rapidly."
                ),
            },
        }
