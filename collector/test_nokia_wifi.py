
from pprint import pprint

from collector.parsers.nokia_parser import parse_wifi_clients

sample = """
SupportedFrequencyBands = 2.4GHz
OperatingFrequencyBand  = 2.4GHz
SSID = HomeNet
DeviceName          MACAddress              Status
-----------------------------------------------------

SupportedFrequencyBands = 5GHz
OperatingFrequencyBand  = 5GHz
SSID = HomeNet
DeviceName          MACAddress              Status
-----------------------------------------------------
SAMSUNG-Galaxy-M31  8a:1b:43:de:81:ea       Connected
OnePlus-12          aa:bc:2d:d4:e4:23       Connected
unknown             94:65:2d:08:53:c7       Connected
unknown             2a:1f:a3:8b:e8:58       Connected
"""

clients = parse_wifi_clients(sample)

pprint(clients)

assert len(clients) == 4
assert all(c["frequency_band"] == "5GHz" for c in clients)
assert all(c["status"] == "connected" for c in clients)

print(f"\nPASS: Parsed {len(clients)} Wi-Fi clients.")
