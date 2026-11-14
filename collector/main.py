
"""Network Observability Dashboard - Application entry point."""

import json
import logging
import os

from collector.routers.nokia import NokiaRouter
from collector.routers.huawei import HuaweiRouter


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)


ROUTERS = {
    "nokia": {
        "class": NokiaRouter,
        "host": "192.168.1.1",
        "username": "admin",
    },
    "huawei": {
        "class": HuaweiRouter,
        "host": "192.168.1.2",
        "username": "root",
    },
}


def collect_from_router(name, config):
    """Connect to a router and collect available telemetry."""

    password = os.getenv(f"{name.upper()}_PASSWORD")

    if not password:
        logger.error("%s: credentials unavailable", name)
        return None

    router = config["class"](
        host=config["host"],
        username=config["username"],
        password=password,
    )

    try:
        logger.info("Connecting to %s", name)

        router.connect()
        router.open_cli()

        logger.info("Collecting telemetry from %s", name)

        # Common telemetry collected from both routers.
        system_metrics = router.collect_system_metrics()
        ethernet_metrics = router.collect_ethernet_metrics()
        wifi_metrics = router.collect_wifi_clients()

        # Nokia-specific telemetry.
        network_metrics = (
            router.collect_network_interfaces()
            if name == "nokia"
            else None
        )

        hosts_metrics = (
            router.collect_hosts()
            if name == "nokia"
            else None
        )

        result = {
            "device": name,
            "system": system_metrics["metrics"],
            "ethernet": ethernet_metrics["interfaces"],
            "network_interfaces": (
                network_metrics["interfaces"]
                if network_metrics else None
            ),
            "hosts": (
                hosts_metrics["hosts"]
                if hosts_metrics else None
            ),
            "wifi_clients": wifi_metrics["clients"],
            "collected_at": system_metrics["collected_at"],
        }

        logger.info("Collection successful: %s", name)

        return result

    except Exception:
        logger.exception("Collection failed: %s", name)
        return None

    finally:
        router.close()


def main():
    """Run one collection cycle across all routers."""

    results = {}

    for name, config in ROUTERS.items():
        result = collect_from_router(name, config)

        if result is not None:
            results[name] = result

    print("\n========== TELEMETRY RESULTS ==========")

    print(
        json.dumps(
            results,
            indent=4,
        )
    )


if __name__ == "__main__":
    main()
