# Layer 2 normalization package

This package is intended to be copied into the existing project as the
`collector/` package. It preserves the existing Layer 1 router collection and
adds a normalized `_layer2` section to the JSON output.

## What it adds

- Canonical interface records for Nokia and Huawei observations.
- Explicit interface type and role classification.
- Nokia `lan stats` and `network interface all` kept as separate observations.
- Huawei LAN1–LAN4 represented as confirmed physical port IDs.
- Counter fields preserve missing values as `null`; down interfaces do not get
  synthetic zero counters.
- In-memory RX/TX Mbps delta calculator with baseline, reset/rollover,
  unavailable, down and invalid-interval states.
- Unit tests for normalization and counter-rate behavior.

## Important interpretation safeguards

- Nokia `eth0`–`eth3` are candidates, not verified physical socket labels.
- Nokia `lan stats` IDs are retained as `lan_stats_N`. The observed `eth2`
  versus `lan_stats_2` status discrepancy means the two sources are not joined
  or summed.
- Huawei LAN1 is the uplink to the Nokia and carries other learned LAN devices.
  Never add Huawei LAN1 counters to Nokia WAN counters.
- No cross-interface totals are calculated. `aggregate_eligible` is false
  until source overlap and topology are verified.
- Negotiated Wi-Fi rates are not throughput counters.
- Rate tracker state is in-memory only. A later storage/exporter layer should
  persist counter baselines if rates must survive process restarts.

## Apply

Copy the contents of this `collector/` directory over the existing project's
`collector/` directory, preserving `config/routers.env` outside it.

Run existing collector as before:

```bash
python -m collector.main
```

Optional nearby AP scan (use sparingly):

```bash
python -m collector.main --include-neighbor-scans
```

The output now includes `_layer2` alongside the raw per-router observations.

Run focused Layer 2 tests:

```bash
python -m unittest collector.test_layer2 -v
```

Run parser tests:

```bash
python -m unittest collector.test_nokia_hosts collector.test_nokia_wifi collector.test_huawei_wifi -v
```

The SSH/integration scripts are live-device diagnostics, not offline unit
tests; run them only when router credentials and network access are available.
