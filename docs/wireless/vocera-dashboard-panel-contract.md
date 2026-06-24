# Vocera Dashboard Panel Contract

This document is the accuracy contract for the Vocera Badge 802.11r dashboard.
It separates client/RUN-state telemetry, client-side detail telemetry, AP voice
access-category latency, and RF context so a rendered panel is not mistaken for
a validated measurement.

Badge-to-badge and badge-to-server media latency/jitter require packet-stream
measurements. See `docs/wireless/vocera-media-latency-jitter-methodology.md`
for the source-of-truth methodology.

Run the live panel audit with:

```bash
make vocera-dashboard-audit
```

Run raw WLC CLI to Prometheus textfile verification with:

```bash
make wireless-rf-verify-parse
```

## Source Types

- MDT/client telemetry: Cisco wireless client telemetry and recording rules
  derived from client state, FT state, retry, RSSI, SNR, and current AP labels.
- Client detail raw: Catalyst Center badge client detail metrics ending in
  `_cc`. These are client-side/detail-derived values, not AP voice AC latency.
- WLC CLI/AP voice AC: `show wireless stats ap name <AP>
  traffic-distribution slot <slot> latency access-category voice last-received`
  parsed into `wireless_ap_ac_latency_*_cli` and normalized by recording rules.
  Cisco defines this as AP-to-client successful transmission time by access
  category; it is not badge-to-badge or badge-to-server media latency.
- RF context: AP RF, channel, DFS, utilization, neighbor, and noise metrics used
  to explain possible causes after an AP voice AC outlier is found.

## Executive Summary

### Panel: Client RUN-State Latency p95

Meaning:
  Time for the client to reach RUN state. Not RTP latency. Not AP-to-client
  voice access-category latency.

Source:
  MDT / wireless client mobility history.

Metric:
  `wireless_badge_client_run_state_latency_p95_us / 1000`

Unit:
  Milliseconds.

Validation:
  Query Mimir for the panel expression and compare against raw client mobility
  history `run_latency` telemetry. Confirm every microsecond metric is divided
  by `1000` before display.

### Panel: Median Client Tx Retry % 5m

Meaning:
  Median per-client retry percentage over the latest 5-minute counter window
  across selected badge clients. It indicates typical RF/client transmit
  health but does not prove roaming interruption or voice RTP loss by itself.
  It is calculated as client retry attempts divided by client packets plus
  retry attempts.

Source:
  MDT/client traffic counters: Cisco `data-retries` and `pkts-rx`.

Metric:
  `quantile(0.5, wireless_badge_client_tx_retry_pct{...})`

Unit:
  Percent.

Validation:
  Compare with per-client `wireless_badge_client_tx_retry_pct` values, which
  use the same 5-minute counter window, and use RSSI/SNR plus AP voice latency
  panels for context.

### Panel: Median AP Voice Packet-Weighted Mean

Meaning:
  Median of AP-level packet-weighted mean voice access-category latency from
  the latest 90 minutes. Each AP-level value weights radio/client-generation
  latency by voice packet count.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Raw Metrics:
  `wireless_ap_ac_latency_avg_us_cli`,
  `wireless_ap_ac_latency_packets_cli`

Normalized Metric:
  `wireless_ap_voice_latency_packet_weighted_mean_ms_median_by_site`

Unit:
  Milliseconds.

Validation:
  Query `quantile(0.5, last_over_time(wireless_ap_voice_latency_packet_weighted_mean_ms_median_by_site[90m]))`.
  Confirm raw latency is microseconds and dashboard output is milliseconds.

### Panel: Badge Clients Still Not Using FT

Meaning:
  Table of badge client MACs currently classified as non-FT.

Source:
  MDT/client telemetry.

Metric:
  `wireless_badge_client_ft_state{ft_state="non_ft"}`

Unit:
  Client identity rows.

Validation:
  Confirm each listed client has a matching non-FT key-management source label.

### Panel: Client RUN-State Latency p95 Over Time

Meaning:
  Time series of client RUN-state p95. This is onboarding/client-state timing.

Source:
  MDT / wireless client mobility history.

Metric:
  `wireless_badge_client_run_state_latency_p95_us / 1000`

Unit:
  Milliseconds.

Validation:
  Ensure the title does not claim roam duration, RTP latency, or AP voice AC
  latency.

### Panel: Top 20 Badges by RUN-State / Onboarding Latency - Normal

Meaning:
  Highest individual badge client RUN-state latency observations at or below
  the configured normal/outlier split threshold.

Source:
  MDT / wireless client mobility history.

Metric:
  `topk(20, (wireless_badge_client_run_state_latency_us / 1000) <= $run_latency_outlier_ms)`

Unit:
  Milliseconds.

Validation:
  Compare an outlier client with raw mobility-history `run_latency` telemetry.
  Confirm `run_latency_outlier_ms` is high enough to preserve normal-scale
  readability while excluding pathological values.

### Panel: Top 20 Badges by RUN-State / Onboarding Latency - Outliers

Meaning:
  Highest individual badge client RUN-state latency observations above the
  configured outlier threshold.

Source:
  MDT / wireless client mobility history.

Metric:
  `topk(20, (wireless_badge_client_run_state_latency_us / 1000) > $run_latency_outlier_ms)`

Unit:
  Milliseconds.

Validation:
  Compare each listed client with raw mobility-history `run_latency` telemetry
  before using it as evidence of a client-state/onboarding issue.

## AP -> Client Voice Access-Category Latency

### Panel: Current Median AP Voice Packet-Weighted Mean

Meaning:
  Latest median AP-level packet-weighted mean voice access-category latency by
  site and band from the last 90 minutes.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `last_over_time(wireless_ap_voice_latency_packet_weighted_mean_ms_median_by_site[90m])`

Unit:
  Milliseconds.

Validation:
  Query Mimir for the exact panel expression and verify the underlying raw AP
  voice packet and latency values with `scripts/verify_wireless_rf_cli_parse.py`.

### Panel: Current AP -> Client Voice AC Packet-Weighted Mean

Meaning:
  Latest packet-weighted mean AP voice access-category latency by site and band
  from the last 90 minutes.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `last_over_time(wireless_ap_voice_latency_packet_weighted_mean_ms_by_site[90m])`

Unit:
  Milliseconds.

Validation:
  Recalculate from `avg_latency_us * packets / packets` using raw CLI metrics
  and confirm the recording rule converts microseconds to milliseconds first.

### Panel: Top APs by Packet-Weighted Voice Mean - Normal

Meaning:
  APs with the highest packet-weighted mean voice access-category latency at
  or below the configured normal/outlier split threshold, limited to APs that
  currently have at least one Vocera badge client.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `topk(20, (wireless_ap_voice_latency_packet_weighted_mean_ms_by_ap{...} <= $voice_mean_outlier_ms) and on (wlc, ap_name) (sum by (wlc, ap_name) (wireless_badge_client_current_ap_info{...}) > 0))`

Unit:
  Milliseconds.

Validation:
  Select one AP and compare raw CLI `Average Latency (usec)` and voice packet
  buckets against `wlc_rf.prom`. Confirm `voice_mean_outlier_ms` is high enough
  to preserve normal-scale readability while excluding pathological values.
  Confirm the AP also appears in `wireless_badge_client_current_ap_info`.

### Panel: Top APs by Packet-Weighted Voice Mean - Outliers

Meaning:
  APs with packet-weighted mean voice access-category latency above the
  configured outlier threshold.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `topk(20, wireless_ap_voice_latency_packet_weighted_mean_ms_by_ap{...} > $voice_mean_outlier_ms)`

Unit:
  Milliseconds.

Validation:
  Select one AP and compare raw CLI `Average Latency (usec)` and voice packet
  buckets against `wlc_rf.prom` before treating it as an AP voice AC outlier.

### Panel: Top APs by Very-High Voice Packets

Meaning:
  APs with the highest number of packets in the WLC very-high voice latency
  bucket.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `wireless_ap_voice_latency_very_high_packets`

Unit:
  Packet count.

Validation:
  Compare with the CLI `Very high` row for the selected AP/slot/generation.

### Panel: AP Voice Packet-Weighted Mean - Low Tail p05

Meaning:
  Low-tail p05 AP-level packet-weighted mean voice access-category latency by
  site and band.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `clamp_min(wireless_ap_voice_latency_packet_weighted_mean_ms_p05_by_site, 0)`

Unit:
  Milliseconds.

Validation:
  Confirm the panel uses packet-weighted mean recording rules, not raw AP
  latency p95 or unweighted mean/CI rules.

### Panel: AP Voice Packet-Weighted Mean - Typical / Median

Meaning:
  Median AP-level packet-weighted mean voice access-category latency by site
  and band.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `wireless_ap_voice_latency_packet_weighted_mean_ms_median_by_site`

Unit:
  Milliseconds.

Validation:
  Confirm the panel uses packet-weighted mean recording rules, not raw AP
  latency p95 or unweighted mean/CI rules.

### Panel: AP Voice Packet-Weighted Mean - High Tail p95

Meaning:
  High-tail p95 AP-level packet-weighted mean voice access-category latency by
  site and band.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence.

Metric:
  `wireless_ap_voice_latency_packet_weighted_mean_ms_p95_by_site`

Unit:
  Milliseconds.

Validation:
  Confirm the panel uses packet-weighted mean recording rules, not raw AP
  latency p95 or unweighted mean/CI rules.

### Panel: AP Packet-Weighted Voice RF Drilldown

Meaning:
  Troubleshooting table that joins AP packet-weighted voice latency outliers
  with AP RF context.

Source:
  WLC CLI/AP voice AC traffic-distribution evidence plus AP RF/MDT context.

Metrics:
  `wireless_ap_voice_latency_packet_weighted_mean_ms_by_ap`,
  `wireless_ap_voice_latency_active_clients`,
  `wireless_ap_voice_latency_very_high_packets`,
  `wireless_ap_channel_utilization_pct`,
  `wireless_ap_receive_utilization_pct`,
  `wireless_ap_transmit_utilization_pct`,
  `wireless_ap_radio_noise_floor_dbm`,
  `wireless_ap_neighbor_count`,
  `wireless_ap_current_channel`,
  `wireless_ap_channel_is_dfs`

Unit:
  Mixed table columns.

Validation:
  Verify AP joins use AP identity labels and that RF fields are context columns,
  not alternate definitions of voice latency.

## Retry / RF Context

### Panel: Client Tx Retry % 5m - Low Tail p05

Meaning:
  Low-tail p05 per-client retry percentage across filtered badge clients over
  the latest 5-minute counter window.

Source:
  MDT/client traffic counters: Cisco `data-retries` and `pkts-rx`.

Metric:
  `wireless_badge_client_tx_retry_pct_p05`

Unit:
  Percent.

Validation:
  Compare with individual badge retry percentages from the same 5-minute
  window and use AP/RF panels for causality.

### Panel: Client Tx Retry % 5m - Median

Meaning:
  Median per-client retry percentage across filtered badge clients over the
  latest 5-minute counter window.

Source:
  MDT/client traffic counters: Cisco `data-retries` and `pkts-rx`.

Metric:
  `wireless_badge_client_tx_retry_pct_median`

Unit:
  Percent.

Validation:
  Compare with individual badge retry percentages from the same 5-minute
  window and use AP/RF panels for causality.

### Panel: Client Tx Retry % 5m - High Tail p95

Meaning:
  High-tail p95 per-client retry percentage across filtered badge clients over
  the latest 5-minute counter window.

Source:
  MDT/client traffic counters: Cisco `data-retries` and `pkts-rx`.

Metric:
  `wireless_badge_client_tx_retry_pct_p95`

Unit:
  Percent.

Validation:
  Compare with individual badge retry percentages from the same 5-minute
  window and use AP/RF panels for causality.

### Panel: Top 20 Badges by Median Tx Retry % - Selected Window

Meaning:
  Badge clients with the highest median 5-minute retry percentage over the
  selected retry window. The selected window is a generated PromQL range
  selector plus `@` timestamp, using a current-day default and three-hour
  historical windows.

Source:
  MDT/client traffic counters: Cisco `data-retries` and `pkts-rx`.

Metric:
  `topk(20, quantile_over_time(0.5, wireless_badge_client_tx_retry_pct{...}${retry_window_selector:raw}))`

Unit:
  Percent.

Validation:
  Check outliers against current AP and AP voice latency context. Regenerate
  the dropdown with `scripts/update_vocera_retry_window_variable.py` so the
  current-day option rolls forward.

### Panel: Badge Count by AP

Meaning:
  Count of filtered badge clients by current AP, using a seven-day lookback to
  avoid no-data instant panels when client/AP state is sparse.

Source:
  MDT/client current AP telemetry.

Metric:
  `topk(25, sum by (ap_name) (last_over_time(wireless_badge_client_current_ap_info[7d])))`

Unit:
  Count.

Validation:
  Do not apply `site_tag` or `band` dashboard filters to this panel; the
  fleet current-AP rule emits normalized MDT labels for those fields that do
  not match Catalyst Center snapshot labels used elsewhere on the dashboard.

## Raw CLI Parser Mapping

For AP voice access-category latency, verify this exact mapping:

```text
CLI row:
  Active Client Count    0 0 0 1
  Average Latency (usec) 0 0 0 1015027
  Very high              0 0 0 1

Prometheus textfile:
  client_generation="non_wifi6" active_clients = 1
  client_generation="non_wifi6" avg_us = 1015027
  client_generation="non_wifi6" latency_level="very_high" packets = 1
```

The verifier command is:

```bash
PYTHONPATH=tools/wireless_rf python3 scripts/verify_wireless_rf_cli_parse.py \
  --input data/wireless-rf/raw/wlc_rf_raw.txt \
  --prom data/wireless-rf/out/wlc_rf.prom \
  --ap SF1-BOILERROOM \
  --slot 1 \
  --access-category voice \
  --client-generation non_wifi6
```
