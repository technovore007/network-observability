
"""Bridge router telemetry, persistent device identities and Prometheus."""

import logging

from prometheus_client import Gauge

from collector.device_registry import DeviceRegistry
from collector.exporter import RouterMetricsExporter

logger = logging.getLogger(__name__)


class DeviceInventoryExporter:
    """Normalize router observations and expose device inventory metrics."""

    def __init__(self, registry, prometheus_registry):
        self.registry = registry

        self.device_info = Gauge(
            "router_device_info",
            "Discovered network device and its latest known attributes",
            [
                "mac_address",
                "friendly_name",
                "router",
                "source",
                "ip_address",
                "hostname",
                "vendor",
                "connection_type",
                "interface",
                "ssid",
                "frequency_band",
            ],
            registry=prometheus_registry,
        )

        self._active_series = set()

    @staticmethod
    def _clean(value):
        return "" if value is None else str(value).strip()

    def _observe(self, mac, source, fields):
        if not mac:
            return

        try:
            self.registry.observe(mac, source, fields)
        except (ValueError, OSError):
            logger.exception(
                "Could not register device observation from %s",
                source,
            )

    def _observe_nokia(self, data):
        for host in data.get("hosts") or []:
            self._observe(
                host.get("mac_address"),
                "nokia_hosts",
                {
                    "ip_address": host.get("ipv4_address"),
                    "hostname": host.get("hostname"),
                    "connection_type": host.get("connection_type"),
                    "status": host.get("status"),
                    "router": "nokia",
                },
            )

        for client in data.get("wifi_clients") or []:
            self._observe(
                client.get("mac_address"),
                "nokia_wifi",
                {
                    "hostname": client.get("device_name"),
                    "connection_type": "wifi",
                    "router": "nokia",
                    "access_point": "nokia",
                    "ssid": client.get("ssid"),
                    "frequency_band": client.get("frequency_band"),
                    "status": client.get("status"),
                },
            )

    def _observe_huawei(self, data):
        for client in data.get("wifi_clients") or []:
            self._observe(
                client.get("mac_address"),
                "huawei_wifi",
                {
                    "connection_type": "wifi",
                    "router": "huawei",
                    "access_point": "huawei",
                    "ssid": client.get("ssid"),
                    "frequency_band": client.get("frequency_band"),
                },
            )

    def _observe_huawei_mac_table(self, data):
        if data.get("status") != "success":
            return

        from collector.parsers.huawei_parser import (
            parse_mac_forwarding_table,
        )

        entries = parse_mac_forwarding_table(
            data.get("output") or ""
        )

        for entry in entries:
            self._observe(
                entry.get("mac_address"),
                "huawei_mac_table",
                {
                    "router": "huawei",
                    "interface": entry.get("learned_interface"),
                    "vlan_id": entry.get("vlan_id"),
                },
            )

    def _publish(self):
        current_series = set()

        for device in self.registry.list_devices():
            mac = device["mac_address"]
            metadata = device.get("metadata") or {}
            observations = device.get("observations") or {}

            for source, observation in observations.items():
                fields = observation.get("fields") or {}

                labels = {
                    "mac_address": mac,
                    "friendly_name": self._clean(
                        metadata.get("name")
                        or device.get("hostname")
                        or device.get("device_name")
                        or mac
                    ),
                    "router": self._clean(fields.get("router")),
                    "source": source,
                    "ip_address": self._clean(
                        fields.get("ip_address")
                    ),
                    "hostname": self._clean(
                        fields.get("hostname")
                        or fields.get("device_name")
                    ),
                    "vendor": self._clean(fields.get("vendor")),
                    "connection_type": self._clean(
                        fields.get("connection_type")
                    ),
                    "interface": self._clean(
                        fields.get("interface")
                    ),
                    "ssid": self._clean(fields.get("ssid")),
                    "frequency_band": self._clean(
                        fields.get("frequency_band")
                    ),
                }

                identity = tuple(labels.values())
                current_series.add(identity)
                self.device_info.labels(**labels).set(1)

        for identity in self._active_series - current_series:
            self.device_info.remove(*identity)

        self._active_series = current_series

    def refresh(self, snapshot, processed_samples):
        """Process only new successful router collection samples."""

        for router in ("nokia", "huawei"):
            group = (
                snapshot.get(router, {})
                .get("groups", {})
                .get("inventory", {})
            )

            if group.get("status") != "success":
                continue

            timestamp = group.get("success_timestamp")
            sample_key = (router, "inventory")

            if timestamp is None:
                continue

            if processed_samples.get(sample_key) == timestamp:
                continue

            data = group.get("data") or {}

            if router == "nokia":
                self._observe_nokia(data)
            else:
                self._observe_huawei(data)

            processed_samples[sample_key] = timestamp

        extended = (
            snapshot.get("huawei", {})
            .get("groups", {})
            .get("extended", {})
        )

        if extended.get("status") == "success":
            timestamp = extended.get("success_timestamp")
            sample_key = ("huawei", "extended")

            if (
                timestamp is not None
                and processed_samples.get(sample_key) != timestamp
            ):
                commands = (
                    extended.get("data") or {}
                ).get("commands") or {}

                self._observe_huawei_mac_table(
                    commands.get("mac_forwarding_table") or {}
                )

                processed_samples[sample_key] = timestamp

        self._publish()


class IntegratedRouterMetricsExporter(RouterMetricsExporter):
    """Existing router exporter extended with persistent device inventory."""

    def __init__(self, state, **kwargs):
        super().__init__(state=state, **kwargs)

        self.device_registry = DeviceRegistry()

        self.device_inventory = DeviceInventoryExporter(
            registry=self.device_registry,
            prometheus_registry=self.registry,
        )

        self._device_processed_samples = {}

    def refresh(self):
        super().refresh()

        self.device_inventory.refresh(
            self.state.snapshot(),
            self._device_processed_samples,
        )
