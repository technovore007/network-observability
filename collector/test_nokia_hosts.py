from pprint import pprint

from collector.parsers.nokia_parser import parse_hosts

sample = """
Status  Connection Type Allocation  IPv4 Address    Hardware Address  HostName
Active  Ethernet        DHCP        192.168.1.7     c8:7e:a1:c5:64:b4 Unknown_c8:7e:a1:c5:64:b4
Active  Ethernet        Static      192.168.1.43    9c:a3:a9:82:f5:40 Unknown_9c:a3:a9:82:f5:40
Active  Ethernet        DHCP        192.168.1.14    8a:1b:43:de:81:ea SAMSUNG-Galaxy-M31
Active  802.11ac        DHCP        192.168.1.15    aa:bc:2d:d4:e4:23 OnePlus-12
"""

hosts = parse_hosts(sample)

pprint(hosts)

assert len(hosts) == 4
assert hosts[0]["mac_address"] == "c8:7e:a1:c5:64:b4"
assert hosts[1]["allocation"] == "static"
assert hosts[2]["hostname"] == "SAMSUNG-Galaxy-M31"

print(f"\nPASS: Parsed {len(hosts)} hosts successfully.")
