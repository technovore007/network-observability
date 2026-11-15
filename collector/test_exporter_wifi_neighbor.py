"""Tests for Huawei nearby AP Prometheus metrics."""

import tempfile
import unittest
from pathlib import Path

from collector.exporter import RouterMetricsExporter
from collector.state import TelemetryState


SAMPLE_OUTPUT = """display wifi neighbor
CurrentWorkingChannel:9(2.4G) 149(5G)

Neighbor ap number:4
------------------------------------------------------------------------------------------------------------------------------------------------------------------
Mac                SSID                               Channel  BandWidth  MIMO     RSSI     Mode        Security                     WMM      Noise    MaxBitRate
------------------------------------------------------------------------------------------------------------------------------------------------------------------
##############################################################################2.4GHz##############################################################################
------------------------------------------------------------------------------------------------------------------------------------------------------------------
26:0B:88:41:C0:19                                     1        20M        2X2      -63      11b/g/n     WPA2-PSK-AES                 off      -90      144
30:BD:13:28:8D:06  Airtel_sant_6604                   1        20M        2X2      -89      11b/g/n     WPA2-PSK-AES                 off      -90      144
24:0B:88:61:C0:19  HomeNet                            1        20M        2X2      -63      11b/g/n     WPA2-PSK-AES                 off      -90      144
###############################################################################5GHz###############################################################################
------------------------------------------------------------------------------------------------------------------------------------------------------------------
A8:DA:0C:A7:41:62  JioFiber 5G                        157      80M        2X2      -71      11a/n/ac    WPA2-PSK-AES                 off      -90      867

success!
SU_WAP>"""


def make_scan(output, status="success"):
    return {
        "commands": {
            "wifi_neighbor_scan": {
                "status": status,
                "output": output,
            }
        }
    }


class HuaweiNeighborExporterTests(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.exporter = RouterMetricsExporter(
            state=TelemetryState(),
            port=0,
            state_file=Path(self.temp_dir.name) / "counter-state.json",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def value(self, metric_name, labels):
        return self.exporter.registry.get_sample_value(
            metric_name,
            labels,
        )

    def test_exports_ap_information_and_numeric_metrics(self):
        self.exporter._export_extended(
            "huawei",
            make_scan(SAMPLE_OUTPUT),
            success_timestamp=1234567890,
        )

        self.assertEqual(
            self.value(
                "router_wifi_neighbor_ap_signal_dbm",
                {
                    "router": "huawei",
                    "bssid": "30:BD:13:28:8D:06",
                    "band": "2.4GHz",
                },
            ),
            -89,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_ap_noise_dbm",
                {
                    "router": "huawei",
                    "bssid": "A8:DA:0C:A7:41:62",
                    "band": "5GHz",
                },
            ),
            -90,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_ap_max_bitrate_mbps",
                {
                    "router": "huawei",
                    "bssid": "A8:DA:0C:A7:41:62",
                    "band": "5GHz",
                },
            ),
            867,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_scan_last_success_timestamp_seconds",
                {"router": "huawei"},
            ),
            1234567890,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_aps",
                {"router": "huawei", "band": "2.4GHz"},
            ),
            3,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_aps",
                {"router": "huawei", "band": "5GHz"},
            ),
            1,
        )

    def test_failed_scan_preserves_last_successful_ap_snapshot(self):
        self.exporter._export_extended(
            "huawei",
            make_scan(SAMPLE_OUTPUT),
            success_timestamp=100,
        )

        self.exporter._export_extended(
            "huawei",
            make_scan("", status="failed"),
            success_timestamp=200,
        )

        self.assertEqual(
            self.value(
                "router_wifi_neighbor_ap_signal_dbm",
                {
                    "router": "huawei",
                    "bssid": "30:BD:13:28:8D:06",
                    "band": "2.4GHz",
                },
            ),
            -89,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_scan_success",
                {"router": "huawei"},
            ),
            0,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_scan_last_success_timestamp_seconds",
                {"router": "huawei"},
            ),
            100,
        )

    def test_successful_empty_scan_removes_old_aps_and_sets_zero_counts(self):
        self.exporter._export_extended(
            "huawei",
            make_scan(SAMPLE_OUTPUT),
            success_timestamp=100,
        )

        empty_output = """CurrentWorkingChannel:9(2.4G) 149(5G)
Neighbor ap number:0"""

        self.exporter._export_extended(
            "huawei",
            make_scan(empty_output),
            success_timestamp=200,
        )

        self.assertIsNone(
            self.value(
                "router_wifi_neighbor_ap_signal_dbm",
                {
                    "router": "huawei",
                    "bssid": "30:BD:13:28:8D:06",
                    "band": "2.4GHz",
                },
            )
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_aps",
                {"router": "huawei", "band": "2.4GHz"},
            ),
            0,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_aps",
                {"router": "huawei", "band": "5GHz"},
            ),
            0,
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_scan_success",
                {"router": "huawei"},
            ),
            1,
        )

    def test_new_successful_scan_replaces_old_ap_set(self):
        self.exporter._export_extended(
            "huawei",
            make_scan(SAMPLE_OUTPUT),
            success_timestamp=100,
        )

        reduced_output = """CurrentWorkingChannel:9(2.4G) 149(5G)
Neighbor ap number:1
------------------------------------------------------------------------------------------------------------------------------------------------------------------
Mac                SSID                               Channel  BandWidth  MIMO     RSSI     Mode        Security                     WMM      Noise    MaxBitRate
------------------------------------------------------------------------------------------------------------------------------------------------------------------
##############################################################################2.4GHz##############################################################################
------------------------------------------------------------------------------------------------------------------------------------------------------------------
24:0B:88:61:C0:19  HomeNet                            1        20M        2X2      -63      11b/g/n     WPA2-PSK-AES                 off      -90      144
"""
        self.exporter._export_extended(
            "huawei",
            make_scan(reduced_output),
            success_timestamp=200,
        )

        self.assertIsNone(
            self.value(
                "router_wifi_neighbor_ap_signal_dbm",
                {
                    "router": "huawei",
                    "bssid": "30:BD:13:28:8D:06",
                    "band": "2.4GHz",
                },
            )
        )
        self.assertEqual(
            self.value(
                "router_wifi_neighbor_ap_signal_dbm",
                {
                    "router": "huawei",
                    "bssid": "24:0B:88:61:C0:19",
                    "band": "2.4GHz",
                },
            ),
            -63,
        )

    def test_non_huawei_router_is_ignored(self):
        self.exporter._export_extended(
            "nokia",
            make_scan(SAMPLE_OUTPUT),
            success_timestamp=100,
        )

        self.assertIsNone(
            self.value(
                "router_wifi_neighbor_scan_success",
                {"router": "huawei"},
            )
        )

    def test_refresh_passes_collection_success_timestamp(self):
        self.exporter.state.update_group(
            "huawei",
            "extended",
            make_scan(SAMPLE_OUTPUT),
            collected_at=987654321,
        )

        self.exporter.refresh()

        self.assertEqual(
            self.value(
                "router_wifi_neighbor_scan_last_success_timestamp_seconds",
                {"router": "huawei"},
            ),
            987654321,
        )


if __name__ == "__main__":
    unittest.main()
