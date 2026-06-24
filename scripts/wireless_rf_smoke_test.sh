#!/usr/bin/env bash
set -euo pipefail
# Scoped smoke test for parse -> textfile -> queries from an existing raw file.

PROM_URL="${PROM_URL:-http://127.0.0.1:9090}"
MIMIR_URL="${MIMIR_URL:-http://127.0.0.1:9009/prometheus}"
MIMIR_ORG_ID="${MIMIR_ORG_ID:-observability}"
NODE_EXPORTER_URL="${NODE_EXPORTER_URL:-http://127.0.0.1:9100}"
WIRELESS_RF_INPUT="${WIRELESS_RF_INPUT:-data/wireless-rf/raw/wlc_rf_raw.txt}"
WIRELESS_RF_WLC="${WIRELESS_RF_WLC:-${WLC:-unknown}}"
WIRELESS_RF_BAND="${WIRELESS_RF_BAND:-${BAND:-5ghz}}"
WIRELESS_RF_PROM_OUT="${WIRELESS_RF_PROM_OUT:-data/wireless-rf/out/wlc_rf.prom}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"
SITE_TAG_REGEX="${SITE_TAG_REGEX:-}"
AP_NAME_REGEX="${AP_NAME_REGEX:-}"
ACCESS_CATEGORY="${ACCESS_CATEGORY:-voice}"
RF_VERIFY_AP="${RF_VERIFY_AP:-}"
RF_VERIFY_SLOT="${RF_VERIFY_SLOT:-}"
RF_VERIFY_CLIENT_GENERATION="${RF_VERIFY_CLIENT_GENERATION:-}"
ALLOW_WIDE_SCOPE="${ALLOW_WIDE_SCOPE:-0}"

# Fail the smoke test with a concise message.
fail() {
  echo "FAIL: $*" >&2
  exit 1
}

# Mark one smoke-test stage as passed.
pass_step() {
  echo "PASS: $*"
}

# Query count(<expr>) from Prometheus or a Mimir-compatible API.
query_count() {
  local base_url="$1"
  local query="$2"
  shift 2
  local value
  value="$(
    curl -fsS -G "$base_url/api/v1/query" "$@" --data-urlencode "query=count($query)" \
      | jq -r '.data.result[0].value[1] // "0"'
  )" || return 1
  printf '%s\n' "$value"
}

# Require a query count to be greater than zero.
require_positive_count() {
  local name="$1"
  local value="$2"
  awk -v value="$value" 'BEGIN { exit !(value > 0) }' || fail "$name count is not positive: $value"
  pass_step "$name count=$value"
}

if [[ ! -f "$WIRELESS_RF_INPUT" ]]; then
  fail "Raw WLC RF input file does not exist: $WIRELESS_RF_INPUT"
fi

if [[ "$ALLOW_WIDE_SCOPE" != "1" && -z "$SITE_TAG_REGEX" && -z "$AP_NAME_REGEX" ]]; then
  # Parsing/publishing a broad raw file can still affect dashboards, so require
  # explicit scope unless the operator deliberately opts into a wide run.
  fail "Set SITE_TAG_REGEX or AP_NAME_REGEX for a scoped smoke test, or ALLOW_WIDE_SCOPE=1 explicitly."
fi

make wireless-rf-parse \
  INPUT="$WIRELESS_RF_INPUT" \
  WLC="$WIRELESS_RF_WLC" \
  BAND="$WIRELESS_RF_BAND" \
  SITE_TAG_REGEX="$SITE_TAG_REGEX" \
  AP_NAME_REGEX="$AP_NAME_REGEX" \
  RF_PROM_OUT="$WIRELESS_RF_PROM_OUT"
pass_step "parse completed"

make wireless-rf-verify-parse \
  INPUT="$WIRELESS_RF_INPUT" \
  RF_PROM_OUT="$WIRELESS_RF_PROM_OUT" \
  BAND="$WIRELESS_RF_BAND" \
  RF_VERIFY_WLC="$WIRELESS_RF_WLC" \
  RF_VERIFY_AP="$RF_VERIFY_AP" \
  RF_VERIFY_SLOT="$RF_VERIFY_SLOT" \
  RF_VERIFY_ACCESS_CATEGORY="$ACCESS_CATEGORY" \
  RF_VERIFY_CLIENT_GENERATION="$RF_VERIFY_CLIENT_GENERATION"
pass_step "raw CLI to Prometheus parse verification completed"

mkdir -p "$TEXTFILE_COLLECTOR_DIR" 2>/dev/null || true
if [[ -w "$TEXTFILE_COLLECTOR_DIR" ]]; then
  install -D -m 0644 "$WIRELESS_RF_PROM_OUT" "$TEXTFILE_COLLECTOR_DIR/wlc_rf.prom"
else
  sudo install -D -m 0644 "$WIRELESS_RF_PROM_OUT" "$TEXTFILE_COLLECTOR_DIR/wlc_rf.prom"
fi
pass_step "textfile published"

node_count="$(
  curl -fsS "$NODE_EXPORTER_URL/metrics" \
    | awk '/^wireless_ap_ac_latency_avg_us_cli\{/ { count++ } END { print count + 0 }'
)" || fail "node_exporter raw metric query failed"
require_positive_count "node_exporter wireless_ap_ac_latency_avg_us_cli" "$node_count"

prom_raw_count="$(query_count "$PROM_URL" 'wireless_ap_ac_latency_avg_us_cli')" \
  || fail "Prometheus raw metric query failed"
require_positive_count "Prometheus wireless_ap_ac_latency_avg_us_cli" "$prom_raw_count"

prom_rule_count="$(query_count "$PROM_URL" 'wireless_ap_voice_latency_ranked_ms')" \
  || fail "Prometheus recording rule query failed"
require_positive_count "Prometheus wireless_ap_voice_latency_ranked_ms" "$prom_rule_count"

mimir_rule_count="$(query_count "$MIMIR_URL" 'wireless_ap_voice_latency_ranked_ms' -H "X-Scope-OrgID: $MIMIR_ORG_ID")" \
  || fail "Mimir recording rule query failed"
require_positive_count "Mimir wireless_ap_voice_latency_ranked_ms" "$mimir_rule_count"

echo "PASS: wireless RF smoke test completed"
