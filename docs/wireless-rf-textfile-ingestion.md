# Wireless RF textfile ingestion

The standalone VM ingestion path is:

```text
raw WLC evidence -> wireless_rf parser -> wlc_rf.prom -> node_exporter textfile collector -> Prometheus -> Mimir
```

The parser emits valid Prometheus exposition text, so the preferred standalone path is to publish `wlc_rf.prom` into node exporter's textfile collector directory. This keeps the wireless parser out of the scrape path and avoids a custom HTTP service.

## Output paths

The `make wireless-rf-parse` target writes the RF parser outputs under `data/wireless-rf/out/` by default:

```text
data/wireless-rf/out/wlc_rf_snapshot.csv
data/wireless-rf/out/wlc_rf_summary.json
data/wireless-rf/out/wlc_rf.prom
```

Override these with `RF_CSV_OUT`, `RF_JSON_OUT`, `RF_PROM_OUT`, and `RF_SQLITE_DB` when a VM needs different paths.

## One-shot validation

Run this before enabling the timer:

```bash
make wireless-rf-parse INPUT=data/wireless-rf/raw/wlc_rf_raw.txt WLC=SRHC-WLC-40G-SEC

sudo install -D -m 0644 \
  data/wireless-rf/out/wlc_rf.prom \
  /var/lib/node_exporter/textfile_collector/wlc_rf.prom

curl -s http://127.0.0.1:9100/metrics | grep -E 'wireless_ap_neighbor_count_cli|wireless_ap_ac_latency_avg_us_cli'

curl -sG http://127.0.0.1:9009/prometheus/api/v1/query \
  -H 'X-Scope-OrgID: observability' \
  --data-urlencode 'query=wireless_ap_voice_latency_avg_ms'
```

The first `curl` proves node exporter is exposing the raw `*_cli` series. Query `wireless_ap_neighbor_count` when validating neighbor/DFS data, and query `wireless_ap_voice_latency_avg_ms` when validating traffic-distribution voice latency. The Mimir query proves Prometheus has scraped and remote-written the normalized recording rule output.

## Node exporter requirement

Node exporter must be started with the textfile collector enabled and pointed at the same directory used by the service:

```text
--collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

Prometheus only needs to scrape node exporter. A minimal scrape job looks like:

```yaml
scrape_configs:
  - job_name: node
    static_configs:
      - targets:
          - 127.0.0.1:9100
```

Keep the existing Prometheus remote-write path to Mimir; no separate scrape job is required for `wlc_rf.prom`.

## systemd timer

The repo includes:

```text
systemd/wireless-rf-textfile.service
systemd/wireless-rf-textfile.timer
```

`make deploy` promotes dashboards, Prometheus config, Prometheus rules, and installs the wireless RF systemd units when the installer scripts are present. The parser-only textfile timer is enabled by default. The hourly collector unit/timer is installed, but the hourly timer is not enabled until `/etc/default/wireless-rf-hourly` has Catalyst Center credentials and WLC settings.

Install the units for the current checkout path:

```bash
make wireless-rf-textfile-install
```

The installer copies the units, writes a systemd override for the current repo root, creates the node exporter textfile directory, and creates `/etc/default/wireless-rf-textfile` if it does not already exist.

Edit `/etc/default/wireless-rf-textfile` for site-specific values:

```bash
WIRELESS_RF_INPUT=data/wireless-rf/raw/wlc_rf_raw.txt
WIRELESS_RF_WLC=SRHC-WLC-40G-SEC
WIRELESS_RF_BAND=5ghz
WIRELESS_RF_PROM_OUT=data/wireless-rf/out/wlc_rf.prom
TEXTFILE_COLLECTOR_DIR=/var/lib/node_exporter/textfile_collector
```

Start and inspect a single run:

```bash
sudo systemctl start wireless-rf-textfile.service
systemctl status wireless-rf-textfile.service
```

Enable recurring refresh:

```bash
sudo systemctl enable --now wireless-rf-textfile.timer
systemctl list-timers wireless-rf-textfile.timer
```

You can also install and enable in one command:

```bash
sudo bash ./scripts/install_wireless_rf_textfile.sh --start-now --enable
```

The textfile timer only parses and publishes the latest raw file. Stage WLC raw
evidence through an approved manual/offline process before enabling the hourly
parser.
