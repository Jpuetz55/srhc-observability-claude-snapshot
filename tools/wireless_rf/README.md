# Wireless RF report tool

`tools/wireless_rf/` is a retained, source-specific parser for manually
collected Cisco Catalyst 9800/WLC RF evidence. It produces:

- CSV for review;
- JSON summary;
- SQLite counter history for repeated snapshots;
- Prometheus exposition for optional node-exporter textfile ingestion; and
- an optional Streamlit review UI.

It is not a WLC controller, a Catalyst Center Command Runner client, or the
current provisioned Grafana dashboard workflow.

## Collection boundary

The WLC collects raw text evidence through an approved manual/offline process.
Parsing, statistics, and visualization stay off-box. The repository does not
submit CLI through Catalyst Center and it does not SSH to the WLC.

Useful raw sections include:

```text
show ap tag summary
show ap dot11 5ghz summary
show ap dot11 5ghz channel
show ap dot11 5ghz logging
show logging | include DFS|RADAR|Radar|radar|CAC|DCA|RRM|channel
show ap name <AP_NAME> auto-rf dot11 5ghz
show wireless stats ap name <AP_NAME> traffic-distribution slot <SLOT> latency access-category voice last-received
```

## Parse a staged raw file

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

Review the CSV against a small number of original AP blocks before using a new
CLI format in reporting. Cisco table formatting varies by IOS-XE release and
controller model.

## Optional publication

The standalone collectors-VM path uses node-exporter textfile ingestion:

```bash
make wireless-rf-textfile-install
```

This service only parses a pre-existing raw file. It does not collect hourly
output, create a Catalyst Center job, or discover controller credentials.

## Dashboard status

The parser may emit metrics matched by retained recording rules, but the
current tested dashboard inventory does not provision RF/DFS/badge dashboards.
Adding such a dashboard requires deliberate source, inventory, contract, and
documentation updates.

## Optional Streamlit review UI

```bash
cd tools/wireless_rf
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-web.txt
PYTHONPATH=. streamlit run streamlit_app.py
```
