#!/usr/bin/env bash
set -euo pipefail
# Parse local Vocera media ICAP pcaps and publish node_exporter textfile
# metrics. Captures are parsed only when their cached parser output is missing
# or stale; the newest capture snapshot is then published.

# Stop the textfile run with a concise operator-facing error.
die() { echo "ERROR: $*" >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${VOCERA_MEDIA_QOE_REPO_ROOT:-$DEFAULT_ROOT}"

RAW_DIR="${VOCERA_MEDIA_QOE_RAW_DIR:-/var/lib/vocera-media-qoe/raw}"
PCAP="${VOCERA_MEDIA_QOE_PCAP:-}"
CONFIG="${VOCERA_MEDIA_QOE_CONFIG:-config/vocera-media-qoe.yaml}"
PROM_OUT="${VOCERA_MEDIA_QOE_PROM_OUT:-data/vocera-media-qoe/out/vocera_media_qoe.prom}"
JSON_OUT="${VOCERA_MEDIA_QOE_JSON_OUT:-data/vocera-media-qoe/out/vocera_media_qoe_summary.json}"
PARSED_DIR="${VOCERA_MEDIA_QOE_PARSED_DIR:-$(dirname "$JSON_OUT")/captures}"
SQL_OUT="${VOCERA_MEDIA_QOE_SQL_OUT:-$(dirname "$JSON_OUT")/vocera_media_qoe_import.sql}"
ARCHIVE_DIR="${VOCERA_MEDIA_QOE_ARCHIVE_DIR-}"
DATABASE_URL="${VOCERA_MEDIA_QOE_DATABASE_URL:-}"
PSQL_BIN="${VOCERA_MEDIA_QOE_PSQL_BIN:-psql}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"
TEXTFILE_OUT="${VOCERA_MEDIA_QOE_TEXTFILE_OUT:-$TEXTFILE_COLLECTOR_DIR/vocera_media_qoe.prom}"

# Escape text so failures can still be emitted as valid JSON.
json_escape() {
  local text="$1"
  text="${text//\\/\\\\}"
  text="${text//\"/\\\"}"
  text="${text//$'\n'/\\n}"
  printf '%s' "$text"
}

# Publish minimal failure artifacts so node_exporter sees a fresh down sample.
write_failure_outputs() {
  local message="$1"
  local escaped
  escaped="$(json_escape "$message")"
  mkdir -p "$(dirname "$PROM_OUT")" "$(dirname "$JSON_OUT")" "$(dirname "$TEXTFILE_OUT")"
  cat >"$PROM_OUT" <<'EOF'
# HELP vocera_media_last_capture_timestamp_seconds Latest packet timestamp seen in the analyzed capture window.
# TYPE vocera_media_last_capture_timestamp_seconds gauge
vocera_media_last_capture_timestamp_seconds{capture_point="unknown",server="unknown",site="unknown"} 0
# HELP vocera_media_capture_parse_success 1 when the capture parsed successfully, otherwise 0.
# TYPE vocera_media_capture_parse_success gauge
vocera_media_capture_parse_success{capture_point="unknown",server="unknown",site="unknown"} 0
EOF
  cat >"$JSON_OUT" <<EOF
{
  "packets_read": 0,
  "udp_packets_seen": 0,
  "last_capture_timestamp_seconds": null,
  "parse_success": 0,
  "error": "$escaped",
  "streams": []
}
EOF
  install -D -m 0644 "$PROM_OUT" "$TEXTFILE_OUT"
}

cd "$REPO_ROOT" || die "repo root not found: $REPO_ROOT"

if [[ -n "$PCAP" && ! -r "$PCAP" ]]; then
  message="pcap is not readable: $PCAP"
  write_failure_outputs "$message"
  die "$message"
fi

if [[ ! -f "$CONFIG" ]]; then
  message="config file not found: $CONFIG"
  write_failure_outputs "$message"
  die "$message"
fi

mkdir -p "$(dirname "$PROM_OUT")" "$(dirname "$JSON_OUT")" "$(dirname "$TEXTFILE_OUT")"

args=(
  --raw-dir "$RAW_DIR"
  --config "$CONFIG"
  --prom-out "$PROM_OUT"
  --json-out "$JSON_OUT"
  --parsed-dir "$PARSED_DIR"
  --textfile-out "$TEXTFILE_OUT"
  --sql-out "$SQL_OUT"
  --psql-bin "$PSQL_BIN"
)
if [[ -n "$ARCHIVE_DIR" ]]; then
  args+=(--archive-dir "$ARCHIVE_DIR")
else
  args+=(--no-archive)
fi
if [[ -n "$PCAP" ]]; then
  args+=(--pcap "$PCAP")
fi
if [[ -n "$DATABASE_URL" ]]; then
  args+=(--postgres-url "$DATABASE_URL")
fi

set +e
PYTHONPATH=tools/vocera_media_qoe python3 -m vocera_media_qoe_batch "${args[@]}"
rc=$?
set -e

if [[ "$rc" -ne 0 ]]; then
  message="vocera media QoE batch publisher failed with exit code $rc"
  write_failure_outputs "$message"
  echo "$message"
  exit 0
fi

if command -v promtool >/dev/null 2>&1; then
  if ! promtool check metrics <"$PROM_OUT"; then
    echo "WARN: promtool reported metric lint issues for $PROM_OUT; publishing anyway" >&2
  fi
fi

echo "Published Vocera media QoE metrics to $TEXTFILE_OUT"
