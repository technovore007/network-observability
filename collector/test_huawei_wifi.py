
from pprint import pprint

from collector.parsers.huawei_parser import parse_wifi_associate

sample = """
Mac               SSID                             Time   TxRate  RxRate  Mode  Antennas PowerSave DualBand  BF  11K 11V
############################################################## 2.4GHz ##############################################################
Number of associated STAs on 2.4GHz band: 1

8A:1B:43:DE:81:EA HomeNet                          201813 72M     1M      11bgn 1*1      on        -         -
##############################################################  5GHz  ##############################################################
Number of associated STAs on 5GHz band: 1

94:65:2D:08:53:C7 HomeNet                          5604   234M    325M    11ac  1*1      off       -         0   1   1

success!
"""

clients = parse_wifi_associate(sample)

pprint(clients)

assert len(clients) == 2
assert clients[0]["mac_address"] == "8a:1b:43:de:81:ea"
assert clients[0]["frequency_band"] == "2.4GHz"
assert clients[0]["tx_rate"] == "72M"
assert clients[1]["frequency_band"] == "5GHz"
assert clients[1]["rx_rate"] == "325M"

print(f"\nPASS: Parsed {len(clients)} Huawei Wi-Fi clients.")
