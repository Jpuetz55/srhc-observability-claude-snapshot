# Retained WLC CLI RF evidence parser

This module parses manually collected Catalyst 9800/WLC RF and
traffic-distribution CLI output into CSV, JSON, SQLite history, and Prometheus
textfile metrics. It is useful for offline RF review and controlled evidence
normalization.

> **Current status:** available parser/tooling, not a current provisioned
> Grafana dashboard workflow. The tested dashboard inventory contains only
> **WLC Control Plane** and **Vocera Iperf QoE**.

## Collection boundary

Collect raw WLC evidence through an approved manual/offline process, stage it
outside Git, and parse it locally. Catalyst Center device-command collection
and Command Runner execution are retired/unavailable in this repository.

```text
manual WLC CLI evidence -> wireless_rf parser -> CSV / JSON / SQLite / .prom
                                           -> optional node_exporter textfile
```

The parser does not alter WLC configuration. It also does not replace WLC MDT:
AP/client/live control-plane telemetry and manually captured RF CLI evidence
are complementary sources with different freshness and semantics.

## Inputs and output

Typical raw input includes AP tag/channel/RF information, RF logging, per-AP
auto-RF detail, and optional traffic-distribution voice-latency sections. See
`tools/wireless_rf/README.md` for the exact expected fragments.

```bash
make wireless-rf-parse \
  INPUT=data/wireless-rf/raw/wlc_rf_raw.txt \
  WLC=SRHC-WLC-40G-SEC \
  BAND=5ghz
```

Default generated outputs:

```text
data/wireless-rf/out/wlc_rf_snapshot.csv
data/wireless-rf/out/wlc_rf_summary.json
data/wireless-rf/out/wlc_rf.prom
data/wireless-rf/wlc_rf.sqlite
```

## Optional node-exporter publication

To make the normalized snapshot scrapeable by Prometheus, install the
parser-only service/timer after staging an existing raw file:

```bash
make wireless-rf-textfile-install
```

The service parses an existing `WIRELESS_RF_INPUT` and atomically installs the
result into the node-exporter textfile directory. It does not collect fresh WLC
CLI output and it does not need Catalyst Center credentials.

Use these checks before relying on a metric:

```bash
make wireless-rf-verify-parse INPUT=data/wireless-rf/raw/wlc_rf_raw.txt WLC=SRHC-WLC-40G-SEC
make wireless-rf-status
```

## Interpretation boundary

Keep AP traffic-distribution voice access-category latency distinct from WLC
MDT client RUN-state latency. They use different source data and should not be
combined or renamed as end-to-end voice latency.
