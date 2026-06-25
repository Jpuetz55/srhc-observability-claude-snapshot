# WLC MDT telemetry: WLC → Telegraf → Prometheus → Mimir

This is the primary live telemetry path for the WLC Control Plane dashboard.
It is separate from manual CLI evidence, PCAP capture, Catalyst Center, and
Study Workflow uploads.

## Data path

```text
Catalyst 9800 WLC
  -- gRPC dial-out, mTLS --> Telegraf Prometheus endpoint (127.0.0.1:9273)
  -- syslog (separate log path) --> log collector

Telegraf :9273 + node_exporter :9100
  -- Prometheus scrape --> recording rules
  -- remote_write allowlist --> local Mimir :9009

Grafana :3000
  -- PromQL --> Mimir :9009/prometheus
```

Prometheus scrapes Telegraf every 10 seconds with a 9-second timeout. It also
scrapes node_exporter and Mimir. Raw WLC operational metrics remain in local
Prometheus for diagnostics and rule evaluation; the `remote_write` allowlist
keeps the intended normalized `wireless_*` surface in Mimir.

## Current repo-required control-plane telemetry

The current tracked dashboard uses normalized metrics from these WLC MDT
sources:

| WLC subscription purpose | Repo rule file | Normalized metrics |
| --- | --- | --- |
| CPU one-minute utilization | `prometheus/rules/wireless/wlc-control-plane.rules.yml` | `wireless_wlc_cpu_one_minute_pct` |
| IOS-XE control processes | `prometheus/rules/wireless/wlc-control-plane.rules.yml` | `wireless_wlc_control_process_cpu_average_pct`, `wireless_wlc_control_process_memory_used_pct`, `wireless_wlc_control_process_load_average`, `wireless_wlc_control_process_health` |

In the current WLC setup these are the control-plane subscriptions typically
identified as **280** (CPU) and **290** (control processes). Other controller
subscriptions can exist for other tools; their presence or absence is not a
reason to change this repo's rule/dashboard contract without reviewing the
metric mapping first.

## Verify without changing configuration

Start at the WLC:

```text
show telemetry connection all
show telemetry ietf subscription 280 receiver
show telemetry ietf subscription 290 receiver
show telemetry receiver name GRAFANA
```

A healthy receiver shows an active connection and a connected/transport-ready
subscription. The WLC initiates the dial-out connection; do not assume that a
collector-originated TCP test proves the mTLS telemetry channel is working.

On the collectors VM:

```bash
curl -fsS http://127.0.0.1:9273/metrics | grep -Ei 'cpu|control|ios.*xe' | head
curl -fsS 'http://127.0.0.1:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.labels.job == "telegraf")'
curl -fsSG http://127.0.0.1:9090/api/v1/query \
  --data-urlencode 'query=up{job="telegraf"}'
curl -fsSG http://127.0.0.1:9009/prometheus/api/v1/query \
  --data-urlencode 'query=wireless_wlc_cpu_one_minute_pct'
```

Check rules and targets after a repo deploy:

```bash
systemctl status prometheus --no-pager -l
curl -fsS http://127.0.0.1:9090/api/v1/rules | jq '.data.groups[] | select(.name == "wireless-wlc-control-plane")'
make mimir-health
```

## Failure isolation order

1. **WLC transport:** check telemetry connection and subscription receiver state.
2. **mTLS/profile association:** inspect the configured WLC gRPC profile and
   trustpoints before editing any profile; receiver state alone does not prove a
   certificate mismatch.
3. **Telegraf exporter:** confirm port `9273` is reachable locally and includes
   recent WLC metric families.
4. **Prometheus:** confirm target health, then raw input metric names.
5. **Recording rules:** check the `wireless-wlc-control-plane` group and its
   inputs in local Prometheus.
6. **Mimir/Grafana:** only after the normalized metric exists locally, check
   remote write/query and Grafana datasource status.

## Configuration boundary

WLC telemetry subscriptions, receiver profiles, trustpoints, and certificates
are network-device configuration. This repository consumes the resulting
metrics; it does not contain a deployment mechanism that should alter those
WLC settings. Record configuration changes in the network change process and
then verify the data path above.
