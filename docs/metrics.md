# Verify Cisco MDT Metrics in Prometheus and Mimir TSDB

This document explains how to verify which Cisco Model Driven Telemetry (MDT) metrics are being scraped from Telegraf, which metrics exist in the local Prometheus TSDB, and which metrics are being remote-written into the standalone local Mimir instance.

## Applies to

This procedure applies to the **standalone VM deployment** of `grafana-mimir-observability`, not the Kubernetes deployment.

Expected standalone VM layout:

- Telegraf Prometheus endpoint: `127.0.0.1:9273`
- Prometheus API: `127.0.0.1:9090`
- Mimir API: `127.0.0.1:9009`
- Mimir query path: `http://127.0.0.1:9009/prometheus`
- Mimir remote-write path: `http://127.0.0.1:9009/api/v1/push`
- Mimir multitenancy: disabled

For the live WLC dial-out telemetry architecture and expected control-plane
subscriptions, read [`wlc-mdt-telemetry.md`](wlc-mdt-telemetry.md). The metric
queries below are diagnostic interfaces; their existence does not imply every
metric has a provisioned Grafana panel.

Because Mimir multitenancy is disabled in this standalone VM profile, do **not** use the Kubernetes tenant header:

```bash
-H 'X-Scope-OrgID: observability'
```

That header belongs to the Kubernetes / Mimir gateway layout, not the local VM layout.

## Important architecture note

There are two different TSDB views on this VM:

1. **Prometheus local TSDB**
   - Prometheus scrapes Telegraf.
   - This is where the raw Cisco MDT metrics from Telegraf appear first.
   - Raw metric names often look like:
     - `Cisco_IOS_XE_wireless_client_oper:...`
     - `Cisco_IOS_XE_wireless_access_point_oper:...`
     - `Cisco_IOS_XE_aaa_oper:...`
     - `Cisco_IOS_XE_interfaces_oper:...`

2. **Mimir TSDB**
   - Prometheus remote-writes into Mimir.
   - The repo intentionally filters what gets remote-written.
   - High-cardinality raw Cisco operational trees are generally kept in local Prometheus and are not all sent to Mimir.
   - Mimir should primarily contain allowlisted metrics and recording-rule outputs such as `wireless_*`, `platform_*`, `process_*`, `up`, `scrape_*`, `go_*`, `prometheus_*`, `mimir_*`, and related metrics.

In other words: seeing a raw `Cisco_IOS_XE_*` metric in Prometheus does **not** automatically mean that same raw metric is stored in Mimir.

## Quick health checks

Run these from the `grafana-mimir-observability` VM.

### 1. Confirm Mimir is alive

```bash
curl -fsS 'http://127.0.0.1:9009/ready' && echo
```

Expected output:

```text
ready
```

### 2. Confirm Prometheus is scraping Telegraf

```bash
curl -fsS -G 'http://127.0.0.1:9090/api/v1/query' \
  --data-urlencode 'query=up{job="telegraf"}' \
| jq
```

Expected result should include:

```json
"job": "telegraf"
```

And the value should be `1`:

```json
"value": [
  <timestamp>,
  "1"
]
```

If the value is `0` or the result is empty, Prometheus is not successfully scraping Telegraf.

## List raw Cisco MDT metrics in Prometheus local TSDB

This is usually the first command to run when asking: **What MDT metrics are being collected from the WLC through Telegraf?**

```bash
END=$(date +%s)
START=$((END - 86400))

curl -fsS -G 'http://127.0.0.1:9090/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={job="telegraf",__name__=~"Cisco_IOS_XE_.*"}' \
| jq -r '.data[].__name__' \
| sort -u
```

This checks the last 24 hours of Prometheus local TSDB for raw Cisco IOS XE MDT metrics scraped from the Telegraf job.

## List all Telegraf metrics in Prometheus local TSDB

Use this when you want everything Prometheus is scraping from Telegraf, including host, Telegraf internal, and Cisco MDT metrics.

```bash
curl -fsS -G 'http://127.0.0.1:9090/api/v1/label/__name__/values' \
  --data-urlencode 'match[]={job="telegraf"}' \
| jq -r '.data[]' \
| sort
```

## List likely wireless / MDT metrics in Prometheus local TSDB

This keeps the output focused on Cisco IOS XE and wireless telemetry.

```bash
curl -fsS -G 'http://127.0.0.1:9090/api/v1/label/__name__/values' \
  --data-urlencode 'match[]={job="telegraf"}' \
| jq -r '.data[]' \
| grep -Ei '^(Cisco_IOS_XE_|wireless_|platform_|process_)' \
| sort
```

## List metrics stored in Mimir

Use this to see what metric names exist in Mimir.

```bash
curl -fsS -G 'http://127.0.0.1:9009/prometheus/api/v1/label/__name__/values' \
| jq -r '.data[]' \
| sort
```

If this works, it lists metric names currently visible through Mimir’s Prometheus-compatible query API.

## List wireless and platform metrics stored in Mimir

Recording-rule outputs may not keep `job="telegraf"`, so do **not** filter only on `job="telegraf"` when checking Mimir for dashboard-ready metrics.

```bash
END=$(date +%s)
START=$((END - 86400))

curl -fsS -G 'http://127.0.0.1:9009/prometheus/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={__name__=~"wireless_.*|platform_.*|process_.*|up|scrape_.*"}' \
| jq -r '.data[].__name__' \
| sort -u
```

This is usually the better command for answering: **What dashboard-ready metrics are being saved into Mimir?**

## Check whether raw Cisco MDT metrics are being remote-written to Mimir

The current repo is designed to avoid remote-writing most high-cardinality raw Cisco operational trees into Mimir. This command verifies whether any raw Cisco IOS XE metrics made it into Mimir anyway.

```bash
END=$(date +%s)
START=$((END - 86400))

curl -fsS -G 'http://127.0.0.1:9009/prometheus/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={__name__=~"Cisco_IOS_XE_.*"}' \
| jq -r '.data[].__name__' \
| sort -u
```

Expected result in the current standalone VM design may be empty. That does not necessarily mean telemetry is broken. It usually means the raw Cisco MDT metrics are present in Prometheus local TSDB but are being filtered before remote-write to Mimir.

## Save metric lists to files

This is useful when comparing before and after changes.

```bash
mkdir -p /tmp/mdt-metric-check
END=$(date +%s)
START=$((END - 86400))

# Raw Cisco MDT metrics in Prometheus local TSDB
curl -fsS -G 'http://127.0.0.1:9090/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={job="telegraf",__name__=~"Cisco_IOS_XE_.*"}' \
| jq -r '.data[].__name__' \
| sort -u \
| tee /tmp/mdt-metric-check/prometheus-raw-cisco-mdt-metrics.txt

# Dashboard-ready metrics in Mimir
curl -fsS -G 'http://127.0.0.1:9009/prometheus/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={__name__=~"wireless_.*|platform_.*|process_.*|up|scrape_.*"}' \
| jq -r '.data[].__name__' \
| sort -u \
| tee /tmp/mdt-metric-check/mimir-dashboard-ready-metrics.txt
```

## Troubleshooting common errors

### `curl: no URL specified!`

Example bad command:

```bash
curl -X 127.0.0.1:metrics/
```

Problems:

- `-X` sets the HTTP method. It does not specify the URL.
- `127.0.0.1:metrics/` is not a valid URL.
- The port must be numeric.
- The URL should include `http://`.

Use a valid URL instead, for example:

```bash
curl -fsS 'http://127.0.0.1:9273/metrics' | head
```

### `jq: Cannot iterate over null`

This means the command expected `.data[]`, but the API response did not contain a normal `data` array. The response was probably an error object.

Re-run without the final `jq -r '.data[]'` filter so you can see the real API error:

```bash
curl -sS -G 'http://127.0.0.1:9009/prometheus/api/v1/label/__name__/values' \
  --data-urlencode 'match[]={job="telegraf"}' \
| jq
```

### `curl: (22) The requested URL returned error: 422`

A `422` means the API understood the request but rejected the query parameters.

For Mimir, prefer the `/series` endpoint with an explicit time range when filtering by matchers:

```bash
END=$(date +%s)
START=$((END - 86400))

curl -sS -G 'http://127.0.0.1:9009/prometheus/api/v1/series' \
  --data-urlencode "start=$START" \
  --data-urlencode "end=$END" \
  --data-urlencode 'match[]={__name__=~"wireless_.*|platform_.*|process_.*|up|scrape_.*"}' \
| jq
```

### Empty Mimir result but Prometheus has raw Cisco metrics

This is expected if the metrics are raw `Cisco_IOS_XE_*` metrics.

Prometheus remote-write is intentionally filtered so the local Mimir VM does not store every high-cardinality Cisco operational tree. In the current repo, the remote-write allowlist keeps metrics matching prefixes like:

```text
ALERTS.*
up
wireless_.*
platform_.*
kube_.*
mimir_.*
cortex_.*
prometheus_.*
process_.*
go_.*
scrape_.*
```

That means raw metrics such as this may exist in Prometheus but not Mimir:

```text
Cisco_IOS_XE_wireless_client_oper:client_oper_data_traffic_stats_most_recent_rssi
```

The preferred long-term approach is to create recording rules that convert raw Cisco MDT metrics into normalized dashboard metrics such as:

```text
wireless_client_rssi_dbm
wireless_client_snr_db
wireless_client_retry_pct
wireless_ap_neighbor_count
platform_target_up_ratio
```

Then allow those normalized `wireless_*` or `platform_*` metrics to be remote-written into Mimir.

## Recommended workflow

Use this order when troubleshooting telemetry storage:

1. Confirm Mimir is alive.
2. Confirm Prometheus is scraping Telegraf.
3. Confirm raw Cisco MDT metrics exist in Prometheus local TSDB.
4. Confirm dashboard-ready normalized metrics exist in Mimir.
5. If a needed raw Cisco metric is missing from Mimir, do not immediately remote-write the raw tree. First decide whether it should become a recording rule with a normalized `wireless_*` or `platform_*` name.

## One-command summary

For raw Cisco MDT metrics currently scraped from Telegraf into Prometheus local TSDB:

```bash
END=$(date +%s); START=$((END - 86400)); curl -fsS -G 'http://127.0.0.1:9090/api/v1/series' --data-urlencode "start=$START" --data-urlencode "end=$END" --data-urlencode 'match[]={job="telegraf",__name__=~"Cisco_IOS_XE_.*"}' | jq -r '.data[].__name__' | sort -u
```

For dashboard-ready metrics currently visible in Mimir:

```bash
END=$(date +%s); START=$((END - 86400)); curl -fsS -G 'http://127.0.0.1:9009/prometheus/api/v1/series' --data-urlencode "start=$START" --data-urlencode "end=$END" --data-urlencode 'match[]={__name__=~"wireless_.*|platform_.*|process_.*|up|scrape_.*"}' | jq -r '.data[].__name__' | sort -u
```
