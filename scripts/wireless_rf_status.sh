#!/usr/bin/env bash
set -euo pipefail
# Read-only diagnostics for the wireless RF service, textfile, and query path.

PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
MIMIR_URL="${MIMIR_URL:-http://127.0.0.1:9009/prometheus}"
MIMIR_ORG_ID="${MIMIR_ORG_ID:-observability}"
NODE_EXPORTER_URL="${NODE_EXPORTER_URL:-http://127.0.0.1:9100}"
WIRELESS_RF_INPUT="${WIRELESS_RF_INPUT:-data/wireless-rf/raw/wlc_rf_raw.txt}"
WIRELESS_RF_PROM_OUT="${WIRELESS_RF_PROM_OUT:-data/wireless-rf/out/wlc_rf.prom}"

# Print a readable section heading in the status report.
section() {
  printf '\n== %s ==\n' "$*"
}

# Show mtime/size when an expected local artifact exists.
show_mtime() {
  local path="$1"
  if [[ -e "$path" ]]; then
    stat -c '%n mtime=%y size=%s bytes' "$path"
  else
    echo "$path missing"
  fi
}

# Count raw node_exporter textfile samples without requiring promtool.
metric_count_from_text() {
  local metric="$1"
  awk -v metric="$metric" '
    index($0, metric "{") == 1 { count++ }
    END { print count + 0 }
  '
}

# Return count(query) or query_failed for Prometheus/Mimir-compatible APIs.
query_prometheus() {
  local base_url="$1"
  local query="$2"
  shift 2
  curl -fsS -G "$base_url/api/v1/query" "$@" --data-urlencode "query=count($query)" \
    | jq -r '.data.result[0].value[1] // "0"' 2>/dev/null || echo "query_failed"
}

section "wireless-rf-hourly.timer"
systemctl status wireless-rf-hourly.timer --no-pager -l || true

section "wireless-rf-hourly.service"
systemctl status wireless-rf-hourly.service --no-pager -l || true

section "wireless-rf-hourly.service journal"
journalctl -u wireless-rf-hourly.service -n 50 --no-pager || true

section "wireless RF files"
show_mtime "$WIRELESS_RF_INPUT"
show_mtime "$WIRELESS_RF_PROM_OUT"

section "node_exporter raw latency metric count"
curl -fsS "$NODE_EXPORTER_URL/metrics" \
  | metric_count_from_text wireless_ap_ac_latency_avg_us_cli \
  || echo "node_exporter_query_failed"

section "Prometheus ranked latency count"
query_prometheus "$PROM_URL" 'wireless_ap_voice_latency_ranked_ms'

section "Mimir ranked latency count"
query_prometheus "$MIMIR_URL" 'wireless_ap_voice_latency_ranked_ms' -H "X-Scope-OrgID: $MIMIR_ORG_ID"
