
"""Scheduled, serialized telemetry collection for Nokia and Huawei routers."""

import logging
import os
import threading
import time

from collector.routers.nokia import NokiaRouter
from collector.routers.huawei import HuaweiRouter
from collector.state import TelemetryState


logger = logging.getLogger(__name__)


ROUTERS = {
    "nokia": {
        "class": NokiaRouter,
        "host": "192.168.1.1",
        "username": "admin",
        "intervals": {
            "core": 30,
            "inventory": 120,
            "extended": 900,
        },
    },
    "huawei": {
        "class": HuaweiRouter,
        "host": "192.168.1.2",
        "username": "root",
        "intervals": {
            "core": 60,
            "inventory": 120,
            "extended": 900,
        },
    },
}


class RouterWorker(threading.Thread):
    """One serialized SSH collection worker for a single router."""

    def __init__(self, name, config, state, stop_event):
        super().__init__(name=f"collector-{name}", daemon=True)

        self.router_name = name
        self.config = config
        self.state = state
        self.stop_event = stop_event

        self.next_due = {
            group: 0.0
            for group in config["intervals"]
        }

    def _create_router(self):
        password = os.getenv(
            f"{self.router_name.upper()}_PASSWORD"
        )

        if not password:
            raise RuntimeError(
                f"{self.router_name.upper()}_PASSWORD is unavailable"
            )

        return self.config["class"](
            host=self.config["host"],
            username=self.config["username"],
            password=password,
        )

    def _collect_group(self, router, group):
        """Execute one collection group using existing router methods."""

        if self.router_name == "nokia":
            if group == "core":
                system = router.collect_system_metrics()
                ethernet = router.collect_ethernet_metrics()
                interfaces = router.collect_network_interfaces()

                return {
                    "system": system["metrics"],
                    "ethernet": ethernet["interfaces"],
                    "network_interfaces": interfaces["interfaces"],
                }

            if group == "inventory":
                hosts = router.collect_hosts()
                wifi = router.collect_wifi_clients()

                return {
                    "hosts": hosts["hosts"],
                    "wifi_clients": wifi["clients"],
                }

            if group == "extended":
                return router.collect_extended_telemetry(
                    include_neighbor_scan=False,
                )

        if self.router_name == "huawei":
            if group == "core":
                system = router.collect_system_metrics()
                ethernet = router.collect_ethernet_metrics()

                return {
                    "system": system["metrics"],
                    "ethernet": ethernet["interfaces"],
                }

            if group == "inventory":
                wifi = router.collect_wifi_clients()

                return {
                    "wifi_clients": wifi["clients"],
                }

            if group == "extended":
                inventory = self.state.get_group(
                    "huawei",
                    "inventory",
                )

                wifi_clients = (
                    inventory["data"].get("wifi_clients", [])
                    if inventory and inventory.get("data")
                    else []
                )

                return router.collect_extended_telemetry(
                    include_neighbor_scan=True,
                    wifi_clients=wifi_clients,
                )

        raise ValueError(
            f"Unsupported group {group!r} for {self.router_name}"
        )

    def _schedule_retry(self, group):
        self.next_due[group] = (
            time.monotonic() + self.config["intervals"][group]
        )

    def _run_due_groups(self):
        now = time.monotonic()

        due_groups = [
            group
            for group, due_at in self.next_due.items()
            if now >= due_at
        ]

        if not due_groups:
            return

        router = None
        current_group = None

        try:
            logger.info(
                "[%s] Connecting; due groups: %s",
                self.router_name,
                ", ".join(due_groups),
            )

            router = self._create_router()
            router.connect()
            router.open_cli()

            for index, group in enumerate(due_groups):
                if self.stop_event.is_set():
                    break

                current_group = group
                started = time.monotonic()

                try:
                    data = self._collect_group(router, group)
                    duration = time.monotonic() - started

                    self.state.update_group(
                        self.router_name,
                        group,
                        data,
                        duration_seconds=duration,
                        collected_at=time.time(),
                    )

                    logger.info(
                        "[%s] %s collection succeeded in %.2fs",
                        self.router_name,
                        group,
                        duration,
                    )

                    self._schedule_retry(group)

                except Exception as exc:
                    duration = time.monotonic() - started

                    self.state.record_failure(
                        self.router_name,
                        group,
                        f"{type(exc).__name__}: {exc}",
                        duration_seconds=duration,
                    )

                    self._schedule_retry(group)

                    logger.exception(
                        "[%s] %s collection failed",
                        self.router_name,
                        group,
                    )

                    # A failed CLI operation may leave the interactive
                    # shell out of sync. Do not issue further commands
                    # on this session. Retry remaining groups next cycle.
                    for remaining in due_groups[index + 1:]:
                        self.state.record_failure(
                            self.router_name,
                            remaining,
                            "Skipped because the preceding collection failed",
                        )
                        self._schedule_retry(remaining)

                    break

        except Exception as exc:
            logger.exception(
                "[%s] Router connection/session failed",
                self.router_name,
            )

            for group in due_groups:
                if group == current_group:
                    continue

                self.state.record_failure(
                    self.router_name,
                    group,
                    f"{type(exc).__name__}: {exc}",
                )
                self._schedule_retry(group)

            if current_group is not None:
                # If the group was already rescheduled after its own
                # collection error, do not overwrite its failure state.
                current_state = self.state.get_group(
                    self.router_name,
                    current_group,
                )

                if current_state is None or current_state.get("status") != "error":
                    self.state.record_failure(
                        self.router_name,
                        current_group,
                        f"{type(exc).__name__}: {exc}",
                    )
                    self._schedule_retry(current_group)

        finally:
            if router is not None:
                try:
                    router.close()
                except Exception:
                    logger.exception(
                        "[%s] Error while closing SSH session",
                        self.router_name,
                    )

    def run(self):
        logger.info("[%s] Worker started", self.router_name)

        while not self.stop_event.is_set():
            self._run_due_groups()
            self.stop_event.wait(1.0)

        logger.info("[%s] Worker stopped", self.router_name)


class RouterScheduler:
    """Manage independent router workers and shared telemetry state."""

    def __init__(self, state=None):
        self.state = state or TelemetryState()
        self.stop_event = threading.Event()

        self.workers = [
            RouterWorker(
                name=name,
                config=config,
                state=self.state,
                stop_event=self.stop_event,
            )
            for name, config in ROUTERS.items()
        ]

    def start(self):
        logger.info("Starting router telemetry scheduler")

        for worker in self.workers:
            worker.start()

    def stop(self, timeout=15):
        logger.info("Stopping router telemetry scheduler")
        self.stop_event.set()

        deadline = time.monotonic() + timeout

        for worker in self.workers:
            if worker.ident is None:
                continue

            remaining = max(0, deadline - time.monotonic())
            worker.join(timeout=remaining)

            if worker.is_alive():
                logger.warning(
                    "[%s] Worker did not stop within the shutdown timeout",
                    worker.router_name,
                )

    def is_alive(self):
        return any(worker.is_alive() for worker in self.workers)
