
"""Prometheus exporter for Nokia and Huawei router telemetry."""

import json
import logging
import math
import os
import tempfile
import threading

from pathlib import Path

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    start_http_server,
)

logger = logging.getLogger(__name__)


class RouterMetricsExporter:

    def __init__(
        self,
        state,
        host="0.0.0.0",
        port=9200,
        state_file=None,
    ):
        self.state = state
        self.host = host
        self.port = port

        self.registry = CollectorRegistry()
        self._lock = threading.RLock()

        self._started = False
        self._http_server = None
        self._http_thread = None

        # Process each successful collection only once.
        self._processed_samples = {}

        # Last raw router counter values.
        # Keys: (metric_name, router, interface, interface_type)
        self._previous_counters = {}

        # Accumulated Prometheus counter values.
        self._accumulated_counters = {}

        self._counter_state_dirty = False

        # Persistent state location.
        self.state_file = Path(
            state_file
            if state_file is not None
            else Path(__file__).resolve().parent.parent
            / "data"
            / "router-counter-state.json"
        )

        self.cpu = Gauge(
            "router_cpu_usage_percent",
            "Router CPU utilization percentage",
            ["router"],
            registry=self.registry,
        )

        self.memory = Gauge(
            "router_memory_usage_percent",
            "Router memory utilization percentage",
            ["router"],
            registry=self.registry,
        )

        self.interface_rx_bytes = Counter(
            "router_interface_receive_bytes_total",
            "Cumulative interface received bytes",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_tx_bytes = Counter(
            "router_interface_transmit_bytes_total",
            "Cumulative interface transmitted bytes",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_rx_packets = Counter(
            "router_interface_receive_packets_total",
            "Cumulative interface received packets",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_tx_packets = Counter(
            "router_interface_transmit_packets_total",
            "Cumulative interface transmitted packets",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_rx_errors = Counter(
            "router_interface_receive_errors_total",
            "Cumulative interface receive errors",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_tx_errors = Counter(
            "router_interface_transmit_errors_total",
            "Cumulative interface transmit errors",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_rx_dropped = Counter(
            "router_interface_receive_dropped_total",
            "Cumulative interface received packets dropped",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_tx_dropped = Counter(
            "router_interface_transmit_dropped_total",
            "Cumulative interface transmitted packets dropped",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.interface_up = Gauge(
            "router_interface_up",
            "Interface state: 1 up, 0 down",
            ["router", "interface", "interface_type"],
            registry=self.registry,
        )

        self.wifi_clients = Gauge(
            "router_wifi_clients",
            "Number of associated Wi-Fi clients",
            ["router"],
            registry=self.registry,
        )

        self.connected_hosts = Gauge(
            "router_connected_hosts",
            "Number of hosts reported by a router",
            ["router"],
            registry=self.registry,
        )
        self.mac_forwarding_entries = Gauge(
            "router_mac_forwarding_entries",
            "Number of MAC forwarding entries learned per physical LAN port",
            ["router", "interface"],
            registry=self.registry,
        )

        self.wifi_neighbor_aps = Gauge(
            "router_wifi_neighbor_aps",
            "Number of nearby access points detected",
            ["router", "band"],
            registry=self.registry,
        )

        self.wifi_neighbor_ap_info = Gauge(
            "router_wifi_neighbor_ap_info",
            "Nearby Wi-Fi access point details from the latest successful scan",
            [
                "router",
                "bssid",
                "ssid",
                "band",
                "channel",
                "bandwidth_mhz",
                "mimo",
                "wifi_mode",
                "security",
                "wmm",
            ],
            registry=self.registry,
        )

        self.wifi_neighbor_ap_signal = Gauge(
            "router_wifi_neighbor_ap_signal_dbm",
            "Nearby Wi-Fi access point signal strength in dBm",
            ["router", "bssid", "band"],
            registry=self.registry,
        )

        self.wifi_neighbor_ap_noise = Gauge(
            "router_wifi_neighbor_ap_noise_dbm",
            "Nearby Wi-Fi access point noise level in dBm",
            ["router", "bssid", "band"],
            registry=self.registry,
        )

        self.wifi_neighbor_ap_bitrate = Gauge(
            "router_wifi_neighbor_ap_max_bitrate_mbps",
            "Nearby Wi-Fi access point advertised maximum bitrate in Mbps",
            ["router", "bssid", "band"],
            registry=self.registry,
        )

        self.wifi_neighbor_scan_success = Gauge(
            "router_wifi_neighbor_scan_success",
            "Latest Huawei nearby Wi-Fi scan status: 1 success, 0 failure",
            ["router"],
            registry=self.registry,
        )

        self.wifi_neighbor_scan_last_success = Gauge(
            "router_wifi_neighbor_scan_last_success_timestamp_seconds",
            "Unix timestamp of the latest successful nearby Wi-Fi scan",
            ["router"],
            registry=self.registry,
        )

        # Track the exact label sets so a successful scan replaces the
        # previous snapshot without leaving stale APs in Prometheus.
        self._active_neighbor_ap_info = set()
        self._active_neighbor_ap_signal = set()
        self._active_neighbor_ap_noise = set()
        self._active_neighbor_ap_bitrate = set()
        self._active_neighbor_ap_counts = set()

        self.collection_success = Gauge(
            "router_collection_success",
            "Latest collection status: 1 success, 0 failure",
            ["router", "group"],
            registry=self.registry,
        )

        self.collection_age = Gauge(
            "router_collection_age_seconds",
            "Age of the latest successful collection",
            ["router", "group"],
            registry=self.registry,
        )

        self.collection_duration = Gauge(
            "router_collection_duration_seconds",
            "Duration of the latest successful collection",
            ["router", "group"],
            registry=self.registry,
        )

        self.collection_last_success = Gauge(
            "router_collection_last_success_timestamp_seconds",
            "Unix timestamp of the latest successful collection",
            ["router", "group"],
            registry=self.registry,
        )

        self.collection_errors = Gauge(
            "router_collection_failures",
            "Cumulative number of failed collection attempts",
            ["router", "group"],
            registry=self.registry,
        )

        # Map internal Prometheus counter names to metric objects.
        self._counter_metrics = {
            metric._name: metric
            for metric in (
                self.interface_rx_bytes,
                self.interface_tx_bytes,
                self.interface_rx_packets,
                self.interface_tx_packets,
                self.interface_rx_errors,
                self.interface_tx_errors,
                self.interface_rx_dropped,
                self.interface_tx_dropped,
            )
        }

        # Restore counters before serving Prometheus metrics.
        self._load_counter_state()

    @staticmethod
    def _number(value):
        if isinstance(value, bool):
            return None

        if isinstance(value, (int, float)):
            if math.isfinite(value) and value >= 0:
                return value

        return None

    @staticmethod
    def _interface_type(router, interface):
        if router == "nokia":
            return "wan" if interface == "ppp111" else "network_interface"

        if router == "huawei":
            return "physical_lan_port"

        return "unknown"

    def _load_counter_state(self):
        """Restore raw and accumulated counters from persistent storage."""

        if not self.state_file.exists():
            logger.info(
                "No previous router counter state found; "
                "initializing fresh counter state"
            )
            return

        try:
            with self.state_file.open("r", encoding="utf-8") as file:
                payload = json.load(file)

            if payload.get("version") != 1:
                raise ValueError("Unsupported counter state version")

            counters = payload.get("counters")

            if not isinstance(counters, dict):
                raise ValueError("Invalid counter state structure")

            restored = 0

            for encoded_key, values in counters.items():
                key_parts = json.loads(encoded_key)

                if (
                    not isinstance(key_parts, list)
                    or len(key_parts) != 4
                ):
                    logger.warning(
                        "Skipping invalid counter key: %s",
                        encoded_key,
                    )
                    continue

                metric_name = key_parts[0]
                labels = key_parts[1:]

                metric = self._counter_metrics.get(metric_name)

                if metric is None:
                    logger.warning(
                        "Skipping unknown counter metric: %s",
                        metric_name,
                    )
                    continue

                if not isinstance(values, dict):
                    continue

                previous = self._number(values.get("previous"))
                total = self._number(values.get("total"))

                if previous is None or total is None:
                    logger.warning(
                        "Skipping invalid counter values: %s",
                        encoded_key,
                    )
                    continue

                key = (metric_name, *labels)

                self._previous_counters[key] = previous
                self._accumulated_counters[key] = total

                # Restore the actual Prometheus Counter.
                if total > 0:
                    metric.labels(*labels).inc(total)

                restored += 1

            logger.info(
                "Restored %s persistent router counter series from %s",
                restored,
                self.state_file,
            )

        except Exception:
            logger.exception(
                "Unable to restore router counter state from %s",
                self.state_file,
            )

            self._previous_counters.clear()
            self._accumulated_counters.clear()

    def _save_counter_state(self):
        """Atomically persist router counter state to disk."""

        if not self._counter_state_dirty:
            return

        self.state_file.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        counters = {}

        for key, previous in self._previous_counters.items():
            encoded_key = json.dumps(
                list(key),
                separators=(",", ":"),
            )

            counters[encoded_key] = {
                "previous": previous,
                "total": self._accumulated_counters.get(key, 0),
            }

        payload = {
            "version": 1,
            "counters": counters,
        }

        temporary_path = None

        try:
            file_descriptor, temporary_path = tempfile.mkstemp(
                prefix=".router-counter-state-",
                suffix=".tmp",
                dir=self.state_file.parent,
            )

            os.fchmod(file_descriptor, 0o600)

            with os.fdopen(
                file_descriptor,
                "w",
                encoding="utf-8",
            ) as file:
                json.dump(
                    payload,
                    file,
                    separators=(",", ":"),
                    sort_keys=True,
                    allow_nan=False,
                )

                file.write("\n")
                file.flush()
                os.fsync(file.fileno())

            # Atomic replacement prevents partially written state files.
            os.replace(
                temporary_path,
                self.state_file,
            )

            temporary_path = None

            # Persist the directory entry as well.
            directory_fd = os.open(
                self.state_file.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )

            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)

            self._counter_state_dirty = False

            logger.debug(
                "Persisted %s router counter series",
                len(counters),
            )

        finally:
            if temporary_path is not None:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

    def _increment_counter(
        self,
        metric,
        metric_name,
        labels,
        value,
    ):
        """Convert raw router counters into persistent Prometheus increments."""

        value = self._number(value)

        if value is None:
            return

        key = (metric_name, *labels)

        previous = self._previous_counters.get(key)
        accumulated = self._accumulated_counters.get(key, 0)

        if previous is None:
            # First observation: establish initial cumulative value.
            increment = value

        elif value >= previous:
            increment = value - previous

        else:
            # Router counter reset or rollover.
            increment = value

        if increment > 0:
            metric.labels(*labels).inc(increment)
            accumulated += increment

        self._previous_counters[key] = value
        self._accumulated_counters[key] = accumulated

        self._counter_state_dirty = True

    def _export_interface(
        self,
        router,
        interface,
        counters,
        status,
    ):
        name = str(interface)

        interface_type = self._interface_type(
            router,
            name,
        )

        labels = (
            router,
            name,
            interface_type,
        )

        mappings = (
            (self.interface_rx_bytes, "rx_bytes"),
            (self.interface_tx_bytes, "tx_bytes"),
            (self.interface_rx_packets, "rx_packets"),
            (self.interface_tx_packets, "tx_packets"),
            (self.interface_rx_errors, "rx_errors"),
            (self.interface_tx_errors, "tx_errors"),
            (self.interface_rx_dropped, "rx_dropped"),
            (self.interface_tx_dropped, "tx_dropped"),
        )

        for metric, field in mappings:
            self._increment_counter(
                metric,
                metric._name,
                labels,
                counters.get(field),
            )

        if status in ("up", "down"):
            self.interface_up.labels(*labels).set(
                1 if status == "up" else 0
            )

    def _export_core(self, router, data):
        system = data.get("system") or {}

        cpu = self._number(
            system.get("cpu_usage_percent")
        )

        memory = self._number(
            system.get("memory_usage_percent")
        )

        if cpu is not None:
            self.cpu.labels(router).set(cpu)

        if memory is not None:
            self.memory.labels(router).set(memory)

        if router == "nokia":
            for item in data.get("network_interfaces") or []:
                interface = item.get("interface")

                if not interface:
                    continue

                counters = {
                    field: item.get(field)
                    for field in (
                        "rx_bytes",
                        "tx_bytes",
                        "rx_packets",
                        "tx_packets",
                        "rx_errors",
                        "tx_errors",
                        "rx_dropped",
                        "tx_dropped",
                    )
                }

                self._export_interface(
                    router,
                    interface,
                    counters,
                    item.get("status"),
                )

        elif router == "huawei":
            for item in data.get("ethernet") or []:
                port_id = item.get("port_id")

                if port_id is None:
                    continue

                counters = {
                    field: item.get(field)
                    for field in (
                        "rx_bytes",
                        "tx_bytes",
                        "rx_packets",
                        "tx_packets",
                    )
                }

                rx_errors = [
                    item.get(field)
                    for field in (
                        "rx_fifo_overrun",
                        "rx_fcs_errors",
                        "rx_alignment_errors",
                        "rx_over_max",
                        "rx_byte_errors",
                    )
                ]

                tx_errors = [
                    item.get(field)
                    for field in (
                        "tx_excess_collisions",
                        "tx_late_collisions",
                        "tx_single_collisions",
                        "tx_multiple_collisions",
                    )
                ]

                counters["rx_errors"] = (
                    sum(
                        value
                        for value in rx_errors
                        if value is not None
                    )
                    if any(
                        value is not None
                        for value in rx_errors
                    )
                    else None
                )

                counters["tx_errors"] = (
                    sum(
                        value
                        for value in tx_errors
                        if value is not None
                    )
                    if any(
                        value is not None
                        for value in tx_errors
                    )
                    else None
                )

                self._export_interface(
                    router,
                    f"LAN{port_id}",
                    counters,
                    None,
                )

    def _export_inventory(self, router, data):
        wifi = data.get("wifi_clients")

        if wifi is not None:
            self.wifi_clients.labels(router).set(
                len(wifi)
            )

        hosts = data.get("hosts")

        if hosts is not None:
            self.connected_hosts.labels(router).set(
                len(hosts)
            )

    def _export_extended(
        self,
        router,
        data,
        success_timestamp=None,
    ):
        """Export extended router telemetry."""

        if router != "huawei":
            return

        commands = data.get("commands") or {}

        # Export Huawei MAC forwarding-table entries independently
        # of the Wi-Fi neighbour scan.
        mac_table = commands.get("mac_forwarding_table") or {}

        if mac_table.get("status") == "success":
            from collector.parsers.huawei_parser import (
                parse_mac_forwarding_table,
            )

            output = mac_table.get("output") or ""
            entries = parse_mac_forwarding_table(output)

            # Initialize all physical ports so zero-entry ports
            # are represented explicitly.
            counts = {
                f"LAN{port_id}": 0
                for port_id in range(1, 5)
            }

            for entry in entries:
                interface = entry.get("learned_interface")

                if interface in counts:
                    counts[interface] += 1

            for interface, count in counts.items():
                self.mac_forwarding_entries.labels(
                    router,
                    interface,
                ).set(count)

        # A failed scan must preserve the last successful AP snapshot.
        scan = commands.get("wifi_neighbor_scan") or {}

        if scan.get("status") != "success":
            self.wifi_neighbor_scan_success.labels(router).set(0)
            return

        from collector.parsers.huawei_parser import parse_wifi_neighbor

        parsed = parse_wifi_neighbor(
            scan.get("output") or ""
        )

        access_points = parsed.get("access_points") or []

        # A successful scan replaces the previous AP snapshot.
        for labels in self._active_neighbor_ap_info:
            self.wifi_neighbor_ap_info.remove(*labels)

        for labels in self._active_neighbor_ap_signal:
            self.wifi_neighbor_ap_signal.remove(*labels)

        for labels in self._active_neighbor_ap_noise:
            self.wifi_neighbor_ap_noise.remove(*labels)

        for labels in self._active_neighbor_ap_bitrate:
            self.wifi_neighbor_ap_bitrate.remove(*labels)

        for labels in self._active_neighbor_ap_counts:
            self.wifi_neighbor_aps.remove(*labels)

        self._active_neighbor_ap_info.clear()
        self._active_neighbor_ap_signal.clear()
        self._active_neighbor_ap_noise.clear()
        self._active_neighbor_ap_bitrate.clear()
        self._active_neighbor_ap_counts.clear()

        band_counts = {}

        for ap in access_points:
            bssid = str(ap.get("bssid") or "").upper()
            band = str(ap.get("band") or "unknown")

            if not bssid:
                continue

            info_labels = (
                router,
                bssid,
                str(ap.get("ssid") or ""),
                band,
                str(ap.get("channel") if ap.get("channel") is not None else ""),
                str(
                    ap.get("bandwidth_mhz")
                    if ap.get("bandwidth_mhz") is not None
                    else ""
                ),
                str(ap.get("mimo") or ""),
                str(ap.get("wifi_mode") or ""),
                str(ap.get("security") or ""),
                str(ap.get("wmm") or ""),
            )

            numeric_labels = (router, bssid, band)

            self.wifi_neighbor_ap_info.labels(
                *info_labels
            ).set(1)

            self._active_neighbor_ap_info.add(info_labels)

            numeric_metrics = (
                (
                    "rssi_dbm",
                    self.wifi_neighbor_ap_signal,
                    self._active_neighbor_ap_signal,
                ),
                (
                    "noise_dbm",
                    self.wifi_neighbor_ap_noise,
                    self._active_neighbor_ap_noise,
                ),
                (
                    "max_bit_rate_mbps",
                    self.wifi_neighbor_ap_bitrate,
                    self._active_neighbor_ap_bitrate,
                ),
            )

            for field, metric, active_set in numeric_metrics:
                value = ap.get(field)

                if value is None:
                    continue

                metric.labels(*numeric_labels).set(float(value))
                active_set.add(numeric_labels)

            band_counts[band] = band_counts.get(band, 0) + 1

        # Publish explicit zero counts for both Wi-Fi bands.
        for band in ("2.4GHz", "5GHz"):
            labels = (router, band)
            self.wifi_neighbor_aps.labels(*labels).set(
                band_counts.get(band, 0)
            )
            self._active_neighbor_ap_counts.add(labels)

        self.wifi_neighbor_scan_success.labels(router).set(1)

        if success_timestamp is not None:
            self.wifi_neighbor_scan_last_success.labels(
                router
            ).set(float(success_timestamp))

    def refresh(self):
        """Export new successful samples and current health state."""

        snapshot = self.state.snapshot()

        with self._lock:
            for router, router_state in snapshot.items():
                groups = router_state.get("groups") or {}

                for group, group_state in groups.items():
                    current_success = (
                        group_state.get("status") == "success"
                    )

                    self.collection_success.labels(
                        router,
                        group,
                    ).set(
                        1 if current_success else 0
                    )

                    age = group_state.get("age_seconds")

                    if age is not None:
                        self.collection_age.labels(
                            router,
                            group,
                        ).set(age)

                    success_timestamp = group_state.get(
                        "success_timestamp"
                    )

                    if success_timestamp is not None:
                        self.collection_last_success.labels(
                            router,
                            group,
                        ).set(success_timestamp)

                    if current_success:
                        self.collection_duration.labels(
                            router,
                            group,
                        ).set(
                            group_state.get(
                                "duration_seconds",
                                0,
                            )
                        )

                    self.collection_errors.labels(
                        router,
                        group,
                    ).set(
                        group_state.get("failure_count", 0)
                    )

                    # Preserve last-known-good metric values on failure.
                    if not current_success:
                        continue

                    if success_timestamp is None:
                        continue

                    sample_key = (router, group)

                    if (
                        self._processed_samples.get(sample_key)
                        == success_timestamp
                    ):
                        continue

                    data = group_state.get("data") or {}

                    if group == "core":
                        self._export_core(router, data)

                    elif group == "inventory":
                        self._export_inventory(router, data)

                    elif group == "extended":
                        self._export_extended(
                            router,
                            data,
                            success_timestamp=success_timestamp,
                        )

                    self._processed_samples[sample_key] = (
                        success_timestamp
                    )

            # Save only when new router counter values were processed.
            self._save_counter_state()

    def start(self):
        """Start the Prometheus HTTP endpoint."""

        if self._started:
            raise RuntimeError("Exporter already started")

        self._http_server, self._http_thread = start_http_server(
            self.port,
            addr=self.host,
            registry=self.registry,
        )

        self._started = True

        logger.info(
            "Router metrics exporter listening on %s:%s",
            self.host,
            self.port,
        )

    def run_refresh_loop(self, stop_event, interval=5):
        """Refresh metrics independently of Prometheus scrapes."""

        while not stop_event.is_set():
            try:
                self.refresh()

            except Exception:
                logger.exception(
                    "Prometheus metric refresh failed"
                )

            stop_event.wait(interval)
