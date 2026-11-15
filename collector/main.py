
"""Network Observability Dashboard - Application entry point."""

import argparse
import json
import logging
import os

from collector.routers.nokia import NokiaRouter
from collector.routers.huawei import HuaweiRouter
from collector.layer2 import build_layer2


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


def collect_from_router(
    name,
    config,
    include_huawei_neighbor_scan=False,
):
    """Collect all implemented telemetry from one router."""

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

        logger.info("Collecting core telemetry from %s", name)
        system_metrics = router.collect_system_metrics()
        ethernet_metrics = router.collect_ethernet_metrics()
        wifi_metrics = router.collect_wifi_clients()

        # Nokia-only inventories and interface telemetry.
        network_metrics = None
        hosts_metrics = None

        if name == "nokia":
            network_metrics = router.collect_network_interfaces()
            hosts_metrics = router.collect_hosts()

        logger.info("Collecting extended telemetry from %s", name)

        if name == "huawei":
            extended_metrics = router.collect_extended_telemetry(
                include_neighbor_scan=include_huawei_neighbor_scan,
                wifi_clients=wifi_metrics["clients"],
            )
        else:
            # Nokia's nearby-AP scan remains disabled.
            extended_metrics = router.collect_extended_telemetry(
                include_neighbor_scan=False,
            )

        optional_failures = [
            key
            for key, value in extended_metrics["commands"].items()
            if value["status"] != "success"
        ]

        result = {
            "device": name,
            "system": system_metrics["metrics"],
            "ethernet": ethernet_metrics["interfaces"],
            "network_interfaces": (
                network_metrics["interfaces"] if network_metrics else None
            ),
            "hosts": hosts_metrics["hosts"] if hosts_metrics else None,
            "wifi_clients": wifi_metrics["clients"],
            "extended": extended_metrics,
            "collected_at": system_metrics["collected_at"],
            "collection_status": (
                "partial" if optional_failures else "success"
            ),
            "optional_collection_failures": optional_failures,
        }

        logger.info("Collection successful: %s", name)
        return result

    except Exception:
        logger.exception("Core collection failed: %s", name)
        return None

    finally:
        router.close()


def main():
    """Run one collection cycle across all configured routers."""

    parser = argparse.ArgumentParser(
        description="Collect telemetry from Nokia and Huawei routers."
    )

    parser.add_argument(
        "--include-huawei-neighbor-scan",
        action="store_true",
        help=(
            "Run Huawei's nearby Wi-Fi scan using "
            "'display wifi neighbor'. This scan is opt-in; "
            "avoid running it during frequent collection cycles."
        ),
    )

    args = parser.parse_args()

    results = {}

    for name, config in ROUTERS.items():
        result = collect_from_router(
            name,
            config,
            include_huawei_neighbor_scan=(
                args.include_huawei_neighbor_scan
            ),
        )

        if result is not None:
            results[name] = result

    collected_device_count = len(results)

    if results:
        results["_layer2"] = build_layer2(results)

    print("\n========== TELEMETRY RESULTS ==========")
    print(json.dumps(results, indent=4))

    if collected_device_count != len(ROUTERS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
