# Wireless RF report tool

This optional tool turns Cisco Catalyst 9800 / WLC RF evidence into outputs that fit this Grafana/Mimir repo:

- CSV for Excel review
- JSON summary for reports
- SQLite history for DFS/radar counter deltas
- Prometheus exposition for Grafana/Mimir dashboards
- optional Streamlit UI for upload-and-review workflows

The WLC should only collect raw evidence. Parsing, statistics, DFS deltas, and UI stay off-box where they are easier to test and maintain.

## Inputs

The parser expects one raw text file that includes:

```text
show ap tag summary
show ap dot11 5ghz summary
show ap dot11 5ghz channel
show ap dot11 5ghz logging
show logging | include DFS|RADAR|Radar|radar|CAC|DCA|RRM|channel
show ap name <AP_NAME> auto-rf dot11 5ghz
show wireless stats ap name <AP_NAME> traffic-distribution slot <SLOT> latency access-category voice last-received
```

The most important sections are:

- `show ap tag summary`, used to map APs to Site Tag / Policy Tag / RF Tag
- each AP's `Nearby APs` section, used for neighbor-density statistics
- each AP's `Radar Information` section, especially `Channel changes due to radar`
- each AP traffic-distribution latency section, used for AP-level voice access-category latency metrics

## Parse a raw file

```bash
PYTHONPATH=tools/wireless_rf \
python3 -m wireless_rf.cli parse data/wireless-rf/raw/wlc_rf_raw.txt \
  --wlc SRHC-WLC-40G-SEC \
  --site-tag-regex '^ST_SALIN_SRHC' \
  --band 5ghz \
  --csv-out data/wireless-rf/out/wlc_rf_snapshot.csv \
  --json-out data/wireless-rf/out/wlc_rf_summary.json \
  --prom-out data/wireless-rf/out/wlc_rf.prom
```

## Collection Boundary

Catalyst Center device-command collection is intentionally unavailable in this
repo. Stage raw WLC evidence through an approved manual/offline process, then
parse the raw output with the `parse` command.

The traffic-distribution latency parser still expects CLI evidence when those
sections are present. Keep AP traffic-distribution latency separate from MDT
client RUN-state latency.

## Optional Streamlit UI

```bash
cd tools/wireless_rf
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-web.txt
PYTHONPATH=. streamlit run streamlit_app.py
```

## Prometheus exposition

The Make target writes `data/wireless-rf/out/wlc_rf.prom`. You can ingest this with one of these patterns:

1. Node exporter textfile collector.
2. Telegraf `inputs.file` + Prometheus output.
3. A lightweight static file HTTP sidecar scraped by Prometheus or Grafana Alloy.

The repo includes recording rules under `prometheus/rules/wireless/` and dashboards under `grafana/dashboards-*` that expect the raw `*_cli` metrics produced by this tool. The standalone VM path should use node exporter textfile ingestion; see `docs/wireless-rf-textfile-ingestion.md`.

## Badge client 802.11r workflow

Copy `config/badge-client-observability.example.yaml` to `config/badge-client-observability.yaml`, then point it at a local badge inventory with `VOCERA_BADGE_MACS` or `VOCERA_BADGE_MACS_FILE`. Do not commit real badge MAC lists.

Collect explicit badge client detail from Catalyst Center:

```bash
make wireless-badge-collect
```

Parse the collected JSON into CSV, JSON, SQLite, and Prometheus exposition:

```bash
make wireless-badge-parse
```

The badge parser writes `data/wireless-rf/exports/badge_client.prom`. The dashboard `Vocera Badge 802.11r Impact - Latency, Retries, and Roaming` expects the raw badge metrics plus the recording rules in `prometheus/rules/wireless/badge-client-80211r.rules.yml`.

The badge path intentionally uses Catalyst Center client-detail telemetry for RSSI, SNR, retry percentage, latency, roaming, onboarding, AKM, and FT state. It does not collect WLC packet counter deltas; those views remain in Catalyst Center.
