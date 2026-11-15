
"""Unit tests for Layer 2 normalization and counter processing."""
import unittest

from collector.layer2 import (
    CounterRateTracker,
    normalize_nokia,
    normalize_huawei,
)


class Layer2Tests(unittest.TestCase):

    def test_nokia_keeps_lan_stats_and_netdev_separate(self):
        device = {
            "ethernet": [{
                "interface_id": 2,
                "status": "down",
                "bytes_received": None,
                "bytes_sent": None,
            }],
            "network_interfaces": [{
                "interface": "eth2",
                "status": "down",
                "rx_bytes": 100,
                "tx_bytes": 200,
            }],
        }

        records = normalize_nokia(device)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["operational_status"], "down")
        self.assertIsNone(records[0]["counters"]["rx_bytes"])
        self.assertEqual(records[1]["interface_id"], "netdev_eth2")
        self.assertFalse(any(r["aggregate_eligible"] for r in records))

    def test_nokia_lan_stats_has_provisional_correlation(self):
        device = {
            "ethernet": [{
                "interface_id": 0,
                "status": "up",
                "bytes_received": 1000,
                "bytes_sent": 2000,
            }],
            "network_interfaces": [],
        }

        record = normalize_nokia(device)[0]
        correlation = record["correlation"]

        self.assertEqual(
            correlation["interface_id"], "netdev_eth0"
        )
        self.assertEqual(
            correlation["relationship"],
            "provisional_logical_correlation",
        )
        self.assertEqual(correlation["confidence"], "high_provisional")
        self.assertFalse(correlation["physical_socket_verified"])
        self.assertFalse(correlation["counter_sources_merged"])

    def test_nokia_all_lan_ids_have_expected_correlations(self):
        device = {
            "ethernet": [
                {"interface_id": i, "status": "up"}
                for i in range(4)
            ],
            "network_interfaces": [],
        }

        records = normalize_nokia(device)

        expected = [
            "netdev_eth0",
            "netdev_eth1",
            "netdev_eth2",
            "netdev_eth3",
        ]

        self.assertEqual(
            [r["correlation"]["interface_id"] for r in records],
            expected,
        )

    def test_nokia_unknown_lan_id_has_no_correlation(self):
        device = {
            "ethernet": [{
                "interface_id": 9,
                "status": "up",
            }],
            "network_interfaces": [],
        }

        record = normalize_nokia(device)[0]
        self.assertIsNone(record["correlation"])

    def test_nokia_correlation_does_not_merge_counters(self):
        device = {
            "ethernet": [{
                "interface_id": 0,
                "status": "up",
                "bytes_received": 1000,
                "bytes_sent": 2000,
            }],
            "network_interfaces": [{
                "interface": "eth0",
                "status": "up",
                "rx_bytes": 900,
                "tx_bytes": 1900,
            }],
        }

        records = normalize_nokia(device)

        lan_stats = next(
            r for r in records if r["counter_source"] == "lan_stats"
        )
        netdev = next(
            r for r in records
            if r["counter_source"] == "network_interface_all"
        )

        self.assertEqual(lan_stats["counters"]["rx_bytes"], 1000)
        self.assertEqual(netdev["counters"]["rx_bytes"], 900)
        self.assertNotEqual(
            lan_stats["interface_id"], netdev["interface_id"]
        )
        self.assertFalse(lan_stats["aggregate_eligible"])
        self.assertFalse(netdev["aggregate_eligible"])

    def test_huawei_physical_ports(self):
        device = {
            "ethernet": [{
                "port_id": 1,
                "rx_bytes": 100,
                "tx_bytes": 200,
                "rx_packets": 10,
                "tx_packets": 20,
            }]
        }

        record = normalize_huawei(device)[0]

        self.assertEqual(record["interface_name"], "LAN1")
        self.assertTrue(record["is_physical"])
        self.assertEqual(record["counters"]["rx_bytes"], 100)
        self.assertFalse(record["aggregate_eligible"])

    def test_huawei_enum_link_configuration(self):
        output = """get port config portid 1
Speed(0-10M, 1-100M, 2-1000M,3-10G,4-Auto) : 1
Duplex(0-Half, 1-Full)        : 1
Link(0-Down, 1-Up)            : 1
success!
SU_WAP>"""

        device = {
            "ethernet": [{
                "port_id": 1,
                "rx_bytes": 100,
                "tx_bytes": 200,
            }],
            "extended": {
                "commands": {
                    "port_1_link_configuration": {
                        "status": "success",
                        "output": output,
                    }
                }
            },
        }

        record = normalize_huawei(device)[0]

        self.assertEqual(record["operational_status"], "up")
        self.assertEqual(record["speed_mbps"], 100)
        self.assertEqual(record["duplex"], "full")

    def test_huawei_down_link_configuration(self):
        output = """Speed(0-10M, 1-100M, 2-1000M,3-10G,4-Auto) : 0
Duplex(0-Half, 1-Full) : 0
Link(0-Down, 1-Up) : 0"""

        device = {
            "ethernet": [{
                "port_id": 4,
                "rx_bytes": 0,
                "tx_bytes": 10,
            }],
            "extended": {
                "commands": {
                    "port_4_link_configuration": {
                        "status": "success",
                        "output": output,
                    }
                }
            },
        }

        record = normalize_huawei(device)[0]

        self.assertEqual(record["operational_status"], "down")
        self.assertIsNone(record["speed_mbps"])
        self.assertIsNone(record["duplex"])

    def test_rate_baseline_then_rate(self):
        tracker = CounterRateTracker()

        record = {
            "device_id": "nokia_primary",
            "interface_id": "wan",
            "operational_status": "up",
            "counters": {
                "rx_bytes": 1_000_000,
                "tx_bytes": 2_000_000,
            },
        }

        first = tracker.update(record, 100)
        self.assertIsNone(first["rates"]["rx_mbps"])

        record["counters"]["rx_bytes"] += 1_000_000
        record["counters"]["tx_bytes"] += 500_000

        second = tracker.update(record, 101)

        self.assertEqual(second["rates"]["rx_mbps"], 8.0)
        self.assertEqual(second["rates"]["tx_mbps"], 4.0)

    def test_reset_does_not_create_negative_rate(self):
        tracker = CounterRateTracker()

        record = {
            "device_id": "nokia_primary",
            "interface_id": "wan",
            "operational_status": "up",
            "counters": {"rx_bytes": 100, "tx_bytes": 100},
        }

        tracker.update(record, 100)
        record["counters"]["rx_bytes"] = 10

        result = tracker.update(record, 101)

        self.assertIsNone(result["rates"]["rx_mbps"])
        self.assertEqual(
            result["counter_states"]["rx_bytes"],
            "counter_reset_or_rollover",
        )

    def test_down_interface_has_no_rate(self):
        tracker = CounterRateTracker()

        record = {
            "device_id": "huawei_ap",
            "interface_id": "lan4",
            "operational_status": "down",
            "counters": {"rx_bytes": 0, "tx_bytes": 0},
        }

        result = tracker.update(record, 100)

        self.assertIsNone(result["rates"]["rx_mbps"])
        self.assertEqual(
            result["counter_states"]["rx_bytes"],
            "interface_down",
        )


if __name__ == "__main__":
    unittest.main()
