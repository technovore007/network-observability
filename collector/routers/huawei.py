
"""Huawei EchoLife HG8145V5 router interface."""

from datetime import datetime, timezone

from collector.routers.base import SSHRouter
from collector.parsers import huawei_parser
from collector.parsers.huawei_parser import parse_wifi_associate

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
        """Collect statistics from Huawei Ethernet ports 1-4."""

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
        output = self.execute("display wifi associate")

        return {
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "clients": parse_wifi_associate(output),
        }