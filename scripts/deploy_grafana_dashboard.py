
#!/usr/bin/env python3
"""Deploy the Home Infrastructure Overview dashboard."""

import base64
import getpass
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

GRAFANA_URL = "http://localhost:3000"
PROMETHEUS_URL = "http://localhost:9090"

PROMETHEUS_UID = "ag4dyiy9ndt6oe"
DASHBOARD_UID = "home-infra-overview"
DASHBOARD_TITLE = "Home Infrastructure Overview"


def grafana_api(path, username, password, method="GET", payload=None):
    token = base64.b64encode(
        f"{username}:{password}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {token}",
        "Accept": "application/json",
    }

    data = None

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode()

    request = urllib.request.Request(
        GRAFANA_URL + path,
        data=data,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode()
            return json.loads(body) if body else {}

    except urllib.error.HTTPError as exc:
        raise RuntimeError(
            f"Grafana API HTTP {exc.code}: "
            f"{exc.read().decode(errors='replace')}"
        ) from exc


def validate_promql(expression):
    url = PROMETHEUS_URL + "/api/v1/query?" + urllib.parse.urlencode(
        {"query": expression}
    )

    with urllib.request.urlopen(url, timeout=15) as response:
        result = json.load(response)

    if result.get("status") != "success":
        raise RuntimeError(f"Invalid PromQL: {expression}")

    return len(result["data"]["result"])


def target(expression, legend="{{router}}", instant=False,
           ref_id="A", fmt="time_series"):
    return {
        "refId": ref_id,
        "expr": expression,
        "legendFormat": legend,
        "instant": instant,
        "range": not instant,
        "format": fmt,
    }


def panel(
    panel_id,
    title,
    targets,
    viz="timeseries",
    unit="short",
    x=0,
    y=0,
    w=12,
    h=8,
):
    return {
        "id": panel_id,
        "title": title,
        "type": viz,
        "datasource": {
            "type": "prometheus",
            "uid": PROMETHEUS_UID,
        },
        "gridPos": {
            "x": x,
            "y": y,
            "w": w,
            "h": h,
        },
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "decimals": 1,
                "color": {"mode": "palette-classic"},
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 70},
                        {"color": "red", "value": 90},
                    ],
                },
            },
            "overrides": [],
        },
        "options": {},
    }


def build_dashboard():
    panels = []

    # ROUTER HEALTH

    panels.append(panel(
        1, "Router CPU Utilization",
        [target("router_cpu_usage_percent", "{{router}}", True)],
        "stat", "percent", 0, 0, 6, 5
    ))

    panels.append(panel(
        2, "Router Memory Utilization",
        [target("router_memory_usage_percent", "{{router}}", True)],
        "stat", "percent", 6, 0, 6, 5
    ))

    panels.append(panel(
        3, "Connected LAN Hosts",
        [target("router_connected_hosts", "{{router}}", True)],
        "stat", "short", 12, 0, 6, 5
    ))

    panels.append(panel(
        4, "Associated Wi-Fi Clients",
        [target("router_wifi_clients", "{{router}}", True)],
        "stat", "short", 18, 0, 6, 5
    ))

    panels.append(panel(
        5, "Router CPU History",
        [target("router_cpu_usage_percent")],
        "timeseries", "percent", 0, 5, 12, 8
    ))

    panels.append(panel(
        6, "Router Memory History",
        [target("router_memory_usage_percent")],
        "timeseries", "percent", 12, 5, 12, 8
    ))

    panels.append(panel(
        7, "Huawei Learned MAC Entries by LAN Port",
        [target(
            'router_mac_forwarding_entries{router="huawei"}',
            "{{interface}}", True
        )],
        "bargauge", "short", 0, 13, 12, 8
    ))

    panels.append(panel(
        8, "Router Collection Health",
        [target(
            "router_collection_success",
            "{{router}} / {{group}}",
            True
        )],
        "stat", "short", 12, 13, 12, 8
    ))

    # HOME SERVER

    panels.append(panel(
        9, "Home Server CPU Utilization",
        [target(
            '100 * (1 - avg by(instance) '
            '(rate(node_cpu_seconds_total{mode="idle"}[5m])))',
            "{{instance}}"
        )],
        "timeseries", "percent", 0, 21, 12, 8
    ))

    panels.append(panel(
        10, "Home Server Memory Utilization",
        [target(
            '100 * (1 - node_memory_MemAvailable_bytes '
            '/ node_memory_MemTotal_bytes)',
            "{{instance}}", True
        )],
        "gauge", "percent", 12, 21, 6, 8
    ))

    panels.append(panel(
        11, "Root Filesystem Utilization",
        [target(
            '100 * (1 - '
            'node_filesystem_avail_bytes{mountpoint="/",fstype="ext4"} '
            '/ '
            'node_filesystem_size_bytes{mountpoint="/",fstype="ext4"})',
            "Root filesystem", True
        )],
        "gauge", "percent", 18, 21, 6, 8
    ))

    panels.append(panel(
        12, "CCTV Storage Utilization",
        [target(
            '100 * (1 - '
            'node_filesystem_avail_bytes{mountpoint="/storage/cctv"} '
            '/ '
            'node_filesystem_size_bytes{mountpoint="/storage/cctv"})',
            "CCTV storage", True
        )],
        "gauge", "percent", 0, 29, 8, 8
    ))

    # NETWORK: DISTINCT QUERY REF IDS

    panels.append(panel(
        13, "Home Server Network Throughput",
        [
            target(
                'rate(node_network_receive_bytes_total'
                '{device="enp14s0"}[5m])',
                "Receive",
                ref_id="A"
            ),
            target(
                'rate(node_network_transmit_bytes_total'
                '{device="enp14s0"}[5m])',
                "Transmit",
                ref_id="B"
            ),
        ],
        "timeseries", "Bps", 8, 29, 16, 8
    ))

    # DOCKER: ACTUAL CONTAINER NAME LABELS

    panels.append(panel(
        14, "Docker Container Memory Usage",
        [target(
            'topk(10, '
            'container_memory_working_set_bytes'
            '{job="cadvisor",name!=""})',
            "{{name}}", True
        )],
        "bargauge", "bytes", 0, 37, 12, 9
    ))

    panels.append(panel(
        15, "Docker Container CPU Usage",
        [target(
            'topk(10, '
            'rate(container_cpu_usage_seconds_total'
            '{job="cadvisor",name!="",cpu="total"}[5m]) * 100)',
            "{{name}}"
        )],
        "timeseries", "percent", 12, 37, 12, 9
    ))

    # TAILSCALE

    panels.append(panel(
        16, "Tailscale Inbound Traffic by Path",
        [target(
            'sum by(path) '
            '(rate(tailscaled_inbound_bytes_total[5m])) * 8',
            "{{path}}"
        )],
        "timeseries", "bps", 0, 46, 12, 8
    ))

    panels.append(panel(
        17, "Tailscale Outbound Traffic by Path",
        [target(
            'sum by(path) '
            '(rate(tailscaled_outbound_bytes_total[5m])) * 8',
            "{{path}}"
        )],
        "timeseries", "bps", 12, 46, 12, 8
    ))

    # DEVICE INVENTORY
    #
    # Nokia host inventory is the primary record.
    # Wi-Fi labels are joined onto matching MAC addresses.
    # Huawei-only MAC observations are included as fallback.

    hosts = 'router_device_info{source="nokia_hosts"}'
    wifi = 'router_device_info{source="nokia_wifi"}'
    huawei = 'router_device_info{source="huawei_mac_table"}'

    inventory_query = (
        f'(({hosts} * on(mac_address) '
        f'group_left(ssid,frequency_band) {wifi}) '
        f'or on(mac_address) {hosts}) '
        f'or on(mac_address) '
        f'({huawei} unless on(mac_address) {hosts})'
    )

    inventory = panel(
        18,
        "Discovered Network Devices",
        [target(inventory_query, "", True, "A", "table")],
        "table", "short", 0, 54, 24, 12
    )

    inventory["transformations"] = [
        {
            "id": "organize",
            "options": {
                "excludeByName": {
                    "Time": True,
                    "__name__": True,
                    "environment": True,
                    "instance": True,
                    "job": True,
                    "hostname": True,
                    "Value": True,
                },
                "indexByName": {
                    "friendly_name": 0,
                    "ip_address": 1,
                    "mac_address": 2,
                    "connection_type": 3,
                    "router": 4,
                    "ssid": 5,
                    "frequency_band": 6,
                    "source": 7,
                },
                "renameByName": {
                    "friendly_name": "Device",
                    "ip_address": "IP Address",
                    "mac_address": "MAC Address",
                    "connection_type": "Connection",
                    "router": "Router",
                    "ssid": "SSID",
                    "frequency_band": "Wi-Fi Band",
                    "source": "Discovery Source",
                },
            },
        }
    ]

    inventory["options"] = {
        "showHeader": True,
        "cellHeight": "sm",
    }

    inventory["fieldConfig"]["defaults"]["custom"] = {
        "align": "left",
        "cellOptions": {"type": "auto"},
        "inspect": False,
    }

    inventory["fieldConfig"]["overrides"] = [
        {
            "matcher": {
                "id": "byName",
                "options": "Device",
            },
            "properties": [
                {"id": "custom.width", "value": 190}
            ],
        },
        {
            "matcher": {
                "id": "byName",
                "options": "IP Address",
            },
            "properties": [
                {"id": "custom.width", "value": 130}
            ],
        },
        {
            "matcher": {
                "id": "byName",
                "options": "MAC Address",
            },
            "properties": [
                {"id": "custom.width", "value": 175}
            ],
        },
    ]

    panels.append(inventory)

    return {
        "id": None,
        "uid": DASHBOARD_UID,
        "title": DASHBOARD_TITLE,
        "description": (
            "Home infrastructure landing dashboard. "
            "Detailed network, Wi-Fi, device, server, Docker, "
            "CCTV and Tailscale dashboards are maintained separately."
        ),
        "tags": [
            "homelab",
            "network",
            "infrastructure",
            "observability",
        ],
        "timezone": "browser",
        "schemaVersion": 41,
        "version": 0,
        "refresh": "15s",
        "time": {
            "from": "now-1h",
            "to": "now",
        },
        "editable": True,
        "graphTooltip": 1,
        "panels": panels,
    }


def main():
    print("Home Infrastructure Overview - Corrected Deployment")
    print("=" * 58)

    username = input("Grafana username: ").strip()
    password = getpass.getpass("Grafana password: ")

    print("\nChecking authentication...")
    user = grafana_api("/api/user", username, password)
    print("Authenticated:", user.get("login", username))

    print("\nChecking datasource...")
    datasources = grafana_api(
        "/api/datasources", username, password
    )

    if not any(
        item.get("uid") == PROMETHEUS_UID
        and item.get("type") == "prometheus"
        for item in datasources
    ):
        raise RuntimeError("Prometheus datasource not found.")

    print("Prometheus datasource verified.")

    dashboard = build_dashboard()

    print("\nValidating PromQL expressions...")
    for item in dashboard["panels"]:
        for query in item["targets"]:
            count = validate_promql(query["expr"])
            print(
                f"OK: {item['title']} "
                f"({count} returned series)"
            )

    existing = grafana_api(
        f"/api/dashboards/uid/{DASHBOARD_UID}",
        username,
        password,
    )

    dashboard["version"] = (
        existing.get("dashboard", {}).get("version", 0)
    )

    print("\nDashboard panels:", len(dashboard["panels"]))
    print("Existing dashboard version:", dashboard["version"])

    if input("\nUpdate existing dashboard? [y/N]: ").strip().lower() != "y":
        print("Cancelled.")
        return

    result = grafana_api(
        "/api/dashboards/db",
        username,
        password,
        method="POST",
        payload={
            "dashboard": dashboard,
            "folderId": 0,
            "overwrite": True,
            "message": "Fix network throughput and device inventory",
        },
    )

    print("\nDashboard updated successfully.")
    print("Status:", result.get("status"))
    print("URL:", GRAFANA_URL + result.get("url", ""))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("\nDEPLOYMENT FAILED:", exc, file=sys.stderr)
        sys.exit(1)
