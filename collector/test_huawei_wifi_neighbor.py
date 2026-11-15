
"""Tests for Huawei nearby Wi-Fi access-point parsing."""

import unittest

from collector.parsers.huawei_parser import parse_wifi_neighbor


SAMPLE_OUTPUT = """display wifi neighbor
Scanning neighbors,it will take several seconds, please wait!

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


class HuaweiWifiNeighborParserTests(unittest.TestCase):

    def test_parses_scan_metadata(self):
        result = parse_wifi_neighbor(SAMPLE_OUTPUT)

        self.assertEqual(result["reported_ap_count"], 4)
        self.assertEqual(result["parsed_ap_count"], 4)
        self.assertEqual(
            result["current_working_channels"],
            {"2.4GHz": 9, "5GHz": 149},
        )

    def test_parses_both_frequency_bands(self):
        result = parse_wifi_neighbor(SAMPLE_OUTPUT)

        bands = [ap["band"] for ap in result["access_points"]]

        self.assertEqual(
            bands,
            ["2.4GHz", "2.4GHz", "2.4GHz", "5GHz"],
        )

    def test_preserves_hidden_ssid(self):
        result = parse_wifi_neighbor(SAMPLE_OUTPUT)

        hidden = result["access_points"][0]

        self.assertEqual(hidden["bssid"], "26:0B:88:41:C0:19")
        self.assertIsNone(hidden["ssid"])

    def test_preserves_ssid_and_signal_information(self):
        result = parse_wifi_neighbor(SAMPLE_OUTPUT)

        ap = result["access_points"][1]

        self.assertEqual(ap["ssid"], "Airtel_sant_6604")
        self.assertEqual(ap["channel"], 1)
        self.assertEqual(ap["bandwidth_mhz"], 20)
        self.assertEqual(ap["rssi_dbm"], -89)
        self.assertEqual(ap["noise_dbm"], -90)
        self.assertEqual(ap["max_bit_rate_mbps"], 144)

    def test_parses_ssid_containing_spaces(self):
        result = parse_wifi_neighbor(SAMPLE_OUTPUT)

        ap = result["access_points"][3]

        self.assertEqual(ap["ssid"], "JioFiber 5G")
        self.assertEqual(ap["band"], "5GHz")
        self.assertEqual(ap["channel"], 157)
        self.assertEqual(ap["bandwidth_mhz"], 80)
        self.assertEqual(ap["max_bit_rate_mbps"], 867)

    def test_empty_output_returns_empty_result(self):
        result = parse_wifi_neighbor("")

        self.assertEqual(result["reported_ap_count"], None)
        self.assertEqual(result["parsed_ap_count"], 0)
        self.assertEqual(result["access_points"], [])

    def test_missing_table_returns_metadata(self):
        output = """CurrentWorkingChannel:9(2.4G) 149(5G)
Neighbor ap number:0"""

        result = parse_wifi_neighbor(output)

        self.assertEqual(result["reported_ap_count"], 0)
        self.assertEqual(result["parsed_ap_count"], 0)
        self.assertEqual(result["access_points"], [])


if __name__ == "__main__":
    unittest.main()
