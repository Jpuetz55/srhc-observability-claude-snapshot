# Wireless RF textfile ingestion

This is a **parser-and-publish** path for manually acquired WLC CLI evidence.
It does not log into a WLC, issue `show` commands, call Catalyst Center, or
create a capture. Stage a supported raw text export first, then parse it on the
collector:

```text
staged WLC CLI text -> wireless_rf parser -> wlc_rf.prom
  -> node_exporter textfile collector -> Prometheus -> selected Mimir series
```

For the current live WLC telemetry plane, see
[`wlc-mdt-telemetry.md`](wlc-mdt-telemetry.md). This textfile workflow is
investigation evidence, not a replacement for Telegraf MDT.

## Output paths

`make wireless-rf-parse` writes its default artifacts beneath
`data/wireless-rf/out/`:

```text
data/wireless-rf/out/wlc_rf_snapshot.csv
data/wireless-rf/out/wlc_rf_summary.json
data/wireless-rf/out/wlc_rf.prom
```

Override `RF_CSV_OUT`, `RF_JSON_OUT`, `RF_PROM_OUT`, and `RF_SQLITE_DB` only
when a site needs a different output location. Preserve the raw source file and
record its WLC/time context outside the generated exposition file.

## One-shot validation

```bash
make wireless-rf-parse \
  INPUT=data/wireless-rf/raw/wlc_rf_raw.txt \
  WLC=SRHC-WLC-40G-SEC

sudo install -D -m 0644 \
  data/wireless-rf/out/wlc_rf.prom \
  /var/lib/node_exporter/textfile_collector/wlc_rf.prom

curl -fsS http://127.0.0.1:9100/metrics \
  | grep -E 'wireless_ap_neighbor_count_cli|wireless_ap_ac_latency_avg_us_cli'

curl -fsSG 'http://127.0.0.1:9009/prometheus/api/v1/query' \
  --data-urlencode 'query=wireless_ap_voice_latency_avg_ms'
```

The first query proves node_exporter exposes raw `*_cli` samples. The second
queries the local, single-tenant Mimir endpoint; do **not** add an
`X-Scope-OrgID` header to this VM profile.

## Node exporter requirement

Node exporter must have its textfile collector enabled for the same directory:

```text
--collector.textfile.directory=/var/lib/node_exporter/textfile_collector
```

Prometheus only needs its existing node-exporter scrape target. Its remote-write
allowlist determines which resulting metrics are copied to Mimir.

## systemd timer

The repo provides a parser-only service and timer:

```text
systemd/wireless-rf-textfile.service
systemd/wireless-rf-textfile.timer
```

Install for the current checkout:

```bash
make wireless-rf-textfile-install
```

The installer creates `/etc/default/wireless-rf-textfile`. Typical values are:

```bash
WIRELESS_RF_INPUT=data/wireless-rf/raw/wlc_rf_raw.txt
WIRELESS_RF_WLC=SRHC-WLC-40G-SEC
WIRELESS_RF_BAND=5ghz
WIRELESS_RF_PROM_OUT=data/wireless-rf/out/wlc_rf.prom
TEXTFILE_COLLECTOR_DIR=/var/lib/node_exporter/textfile_collector
```

Run once before enabling recurrence:

```bash
sudo systemctl start wireless-rf-textfile.service
systemctl status wireless-rf-textfile.service
```

Enable only when a separate approved process reliably refreshes the staged raw
input:

```bash
sudo systemctl enable --now wireless-rf-textfile.timer
systemctl list-timers wireless-rf-textfile.timer
```

The optional hourly collector unit is not the canonical incident workflow and
must not be enabled just because it is installed. Current WLC incident capture
uses manual EPC plus WLC-to-collector SCP as described in
[`wireless/vocera-wlc-continuous-capture-runbook.md`](wireless/vocera-wlc-continuous-capture-runbook.md).
