# Wireless RF observability extension

This repo now includes an optional wireless RF extension for Cisco WLC / Catalyst 9800 evidence. It keeps the core Grafana/Mimir workflow intact while adding a path for AP neighbor-density, DFS/radar tracking, and AP traffic-distribution voice latency.

## Design goal

The controller should collect evidence only. The repo should own parsing, validation, metrics, dashboards, and promotion.

```text
Manual WLC CLI evidence
        |
        v
tools/wireless_rf parser
        |
        +-- CSV / JSON for ad hoc reports
        +-- SQLite for historical DFS counter deltas
        +-- Prometheus exposition (*.prom)
                 |
                 v
          Prometheus / Alloy / Mimir
                 |
                 v
          Grafana dashboard + Prometheus rules
```

## Why this fits the repo

The repo is still the source of truth for Grafana dashboards, Prometheus rules, and metric contracts. The wireless collector is a source-specific metric producer. It does not replace the platform dashboards; it adds a domain-specific telemetry feed that can be scraped into the same Mimir backend.

## Collection modes

### Raw WLC Evidence File

Use this when you want the simplest and safest first version.

1. Generate one raw text file from the WLC by an approved manual or offline process.
2. Run the parser locally.
3. Review CSV/JSON output.
4. Publish the Prometheus exposition file when the parser looks correct.

Catalyst Center device-command collection is retired. This repo keeps the
parser and publisher, but it does not submit WLC CLI commands through Catalyst
Center.

## Outputs

Default outputs are written under `data/wireless-rf/`:

```text
data/wireless-rf/
├── raw/
│   └── wlc_rf_raw.txt
├── out/
│   ├── wlc_rf_snapshot.csv
│   ├── wlc_rf_summary.json
│   └── wlc_rf.prom
└── wlc_rf.sqlite
```

## Metrics produced by the parser

The parser emits raw `*_cli` metrics, including:

- `wireless_ap_neighbor_count_cli`
- `wireless_ap_neighbor_rssi_mean_dbm_cli`
- `wireless_ap_neighbor_strongest_rssi_dbm_cli`
- `wireless_ap_neighbor_weakest_rssi_dbm_cli`
- `wireless_ap_neighbor_high_rssi_total_cli`
- `wireless_ap_current_channel_cli`
- `wireless_ap_channel_is_dfs_cli`
- `wireless_ap_dfs_cac_running_cli`
- `wireless_ap_dfs_radar_changes_total_cli`
- `wireless_ap_zero_wait_dfs_enabled_cli`
- `wireless_ap_ac_latency_avg_us_cli`
- `wireless_ap_ac_latency_active_clients_cli`
- `wireless_ap_ac_latency_packets_cli`

Prometheus recording rules normalize these into dashboard-facing metrics such as:

- `wireless_ap_neighbor_count`
- `wireless_ap_neighbor_count_mean_by_site`
- `wireless_ap_neighbor_count_stddev_by_site`
- `wireless_ap_channel_is_dfs`
- `wireless_ap_dfs_ap_on_dfs_ratio`
- `wireless_ap_dfs_radar_changes_24h`
- `wireless_ap_voice_latency_avg_ms`
- `wireless_ap_voice_latency_p95_ms_by_site`
- `wireless_ap_voice_latency_packet_weighted_mean_ms_by_site`
- `wireless_ap_voice_latency_mean_ms_by_site`
- `wireless_ap_voice_latency_stddev_ms_by_site`
- `wireless_ap_voice_latency_sem_ms_by_site`
- `wireless_ap_voice_latency_ci95_low_ms_by_site`
- `wireless_ap_voice_latency_ci95_high_ms_by_site`
- `wireless_ap_voice_latency_ranked_ms`
- `wireless_ap_voice_latency_very_high_packets`

Keep client RUN-state latency and AP voice access-category latency separate:

- client RUN-state latency comes from MDT client mobility history and is useful for roaming/onboarding validation
- AP voice access-category latency comes from WLC traffic-distribution CLI output and is useful for voice QoS and airtime latency monitoring

## Dashboards

The dashboards are stored in both DEV and PROD dashboard trees:

```text
grafana/dashboards-dev/Platform - Wireless RF/
grafana/dashboards-prod/Platform - Wireless RF/
```

AP RF MDT dashboard:

```text
Wireless AP RF MDT Observability
wireless-ap-rf-mdt-observability__wireless_ap_rf_mdt_observability.json
```

It includes:

- TX frame rate
- RX frame rate
- retry burden per 100 TX frames
- FCS error rate
- MDT noise floor
- radio stuck resets

Neighbor and DFS dashboard:

```text
Wireless RF Neighbor and DFS Observability
wireless-rf-neighbor-and-dfs__wireless_rf_observability.json
```

It includes:

- APs observed
- mean neighbor count
- APs currently on DFS channels
- radar changes over the last 24 hours
- neighbor-count trend by Site Tag
- DFS/radar event trend
- top APs by nearby AP count
- AP RF snapshot table

Vocera badge impact dashboard:

```text
Vocera Badge 802.11r Impact
vocera-badge-80211r-impact__vocera_badge_80211r_impact.json
```

It keeps RUN-state latency panels separate from AP voice access-category latency and includes:

- voice access-category latency over time in milliseconds
- site-level voice latency mean with 95% confidence interval
- very-high voice latency packet counts by site
- ranked AP voice latency, highest to lowest

## Prometheus / Mimir ingestion options

Choose one ingestion pattern:

1. Node exporter textfile collector reads `wlc_rf.prom`.
2. Telegraf reads the file and exposes it on the existing Telegraf Prometheus endpoint.
3. A tiny HTTP sidecar serves the generated `wlc_rf.prom` file and Prometheus/Alloy scrapes it.

For this repo, the recommended default is the node exporter textfile collector because the parser already writes valid Prometheus exposition text and the file can be dropped in without another service layer. See `docs/wireless-rf-textfile-ingestion.md` for the systemd service, timer, and validation commands.

## Systemd installation (node_exporter textfile path)

Install the parser-only service and timer:

```bash
sudo WIRELESS_RF_REPO_ROOT="$PWD" \
  WIRELESS_RF_INPUT="data/wireless-rf/raw/wlc_rf_raw.txt" \
  WIRELESS_RF_WLC="SRHC-WLC-40G-SEC" \
  WIRELESS_RF_BAND="5ghz" \
  WIRELESS_RF_PROM_OUT="data/wireless-rf/out/wlc_rf.prom" \
  TEXTFILE_COLLECTOR_DIR="/var/lib/node_exporter/textfile_collector" \
  bash ./scripts/install_wireless_rf_textfile.sh --start-now --enable
```

Or via Makefile:

```bash
make wireless-rf-install-textfile
```

Validate installation:

```bash
systemctl status wireless-rf-textfile.service --no-pager -l
systemctl list-timers wireless-rf-textfile.timer --no-pager
```

Important: `wireless-rf-textfile.service` **only parses an existing raw file** and publishes `wlc_rf.prom`. It does not collect fresh WLC output.

## Hourly collect + parse + publish

To collect fresh data every run, install the hourly workflow:

```bash
sudo bash ./scripts/install_wireless_rf_hourly.sh
```

Then edit `/etc/default/wireless-rf-hourly` with Catalyst Center credentials and WLC settings, and enable:

```bash
sudo systemctl start wireless-rf-hourly.service
sudo systemctl enable --now wireless-rf-hourly.timer
systemctl list-timers wireless-rf-hourly.timer --no-pager
```

`make deploy` installs the `wireless-rf-textfile` parser timer and the `wireless-rf-hourly` unit/timer by default when the installer scripts are present. It does not start the hourly timer automatically; edit `/etc/default/wireless-rf-hourly` first, then enable the timer.

## Commands

Parse an existing raw file:

```bash
make wireless-rf-parse INPUT=data/wireless-rf/raw/wlc_rf_raw.txt WLC=SRHC-WLC-40G-SEC
```

Run the optional Streamlit UI:

```bash
make wireless-rf-web
```

Stage manually collected WLC evidence and parse it locally. The repo does not
provide a Catalyst Center collection command.

## Current limitations

The parser is intentionally tolerant because Cisco CLI table formats vary by IOS-XE version and controller model. Treat the first run as parser validation. Check the CSV against a few raw AP blocks before relying on the metrics for alerting.

DFS event timing from CLI counters is inferred by comparing stored counter values across runs. For exact timestamps, ingest WLC syslog or MDT/YANG radar operational data later.
