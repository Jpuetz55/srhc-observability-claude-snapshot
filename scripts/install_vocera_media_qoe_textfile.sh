#!/usr/bin/env bash
set -euo pipefail
# Install the Vocera media PCAP QoE service/timer that publishes node_exporter
# textfile metrics from offline captures.

# Print install usage and textfile/parser environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_vocera_media_qoe_textfile.sh [--enable] [--start-now]

Installs the Vocera media PCAP QoE node_exporter textfile service/timer.

Options:
  --enable     Enable and start vocera-media-qoe-textfile.timer.
  --start-now  Run vocera-media-qoe-textfile.service once after install.

Environment overrides:
  VOCERA_MEDIA_QOE_RAW_DIR       default: /var/lib/vocera-media-qoe/raw
  VOCERA_MEDIA_QOE_PCAP          optional exact pcap path; otherwise raw dir is scanned
  VOCERA_MEDIA_QOE_CONFIG        default: config/vocera-media-qoe.yaml
  VOCERA_MEDIA_QOE_PROM_OUT      default: data/vocera-media-qoe/out/vocera_media_qoe.prom
  VOCERA_MEDIA_QOE_JSON_OUT      default: data/vocera-media-qoe/out/vocera_media_qoe_summary.json
  VOCERA_MEDIA_QOE_PARSED_DIR    default: data/vocera-media-qoe/out/captures
  VOCERA_MEDIA_QOE_SQL_OUT       default: data/vocera-media-qoe/out/vocera_media_qoe_import.sql
  VOCERA_MEDIA_QOE_ARCHIVE_DIR   optional archive output directory; blank disables archives
  VOCERA_MEDIA_QOE_DATABASE_URL  optional PostgreSQL URL for capture-time history
  VOCERA_MEDIA_QOE_PSQL_BIN      default: psql
  VOCERA_MEDIA_QOE_RAW_OWNER     default: sudo caller, then appsadmin
  VOCERA_MEDIA_QOE_RAW_GROUP     default: RAW_OWNER's primary group
  TEXTFILE_COLLECTOR_DIR         default: /var/lib/node_exporter/textfile_collector
  VOCERA_MEDIA_QOE_REPO_ROOT     default: current repo root
EOF
}

# Exit with a consistent install error.
die(){ echo "ERROR: $*" >&2; exit 1; }
# Assert that a required command is available before touching systemd.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
# Add a key to the EnvironmentFile only when the operator has not set it.
ensure_env_key(){
  local file="$1"
  local key="$2"
  local value="$3"
  if ! grep -q "^${key}=" "$file"; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

ENABLE_TIMER=0
START_NOW=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable)
      ENABLE_TIMER=1
      ;;
    --start-now)
      START_NOW=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  die "Run as root, for example: sudo bash ./scripts/install_vocera_media_qoe_textfile.sh"
fi

need_cmd install
need_cmd chown
need_cmd chmod
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${VOCERA_MEDIA_QOE_REPO_ROOT:-$DEFAULT_ROOT}"
[[ -f "$REPO_ROOT/systemd/vocera-media-qoe-textfile.service" ]] || die "Missing unit file under repo root: $REPO_ROOT"
[[ -f "$REPO_ROOT/systemd/vocera-media-qoe-textfile.timer" ]] || die "Missing timer file under repo root: $REPO_ROOT"
[[ -f "$REPO_ROOT/scripts/run_vocera_media_qoe_textfile.sh" ]] || die "Missing publisher script under repo root: $REPO_ROOT"

VOCERA_MEDIA_QOE_RAW_DIR="${VOCERA_MEDIA_QOE_RAW_DIR:-/var/lib/vocera-media-qoe/raw}"
VOCERA_MEDIA_QOE_PCAP="${VOCERA_MEDIA_QOE_PCAP:-}"
VOCERA_MEDIA_QOE_CONFIG="${VOCERA_MEDIA_QOE_CONFIG:-config/vocera-media-qoe.yaml}"
VOCERA_MEDIA_QOE_PROM_OUT="${VOCERA_MEDIA_QOE_PROM_OUT:-data/vocera-media-qoe/out/vocera_media_qoe.prom}"
VOCERA_MEDIA_QOE_JSON_OUT="${VOCERA_MEDIA_QOE_JSON_OUT:-data/vocera-media-qoe/out/vocera_media_qoe_summary.json}"
VOCERA_MEDIA_QOE_PARSED_DIR="${VOCERA_MEDIA_QOE_PARSED_DIR:-data/vocera-media-qoe/out/captures}"
VOCERA_MEDIA_QOE_SQL_OUT="${VOCERA_MEDIA_QOE_SQL_OUT:-data/vocera-media-qoe/out/vocera_media_qoe_import.sql}"
VOCERA_MEDIA_QOE_ARCHIVE_DIR="${VOCERA_MEDIA_QOE_ARCHIVE_DIR-}"
VOCERA_MEDIA_QOE_DATABASE_URL="${VOCERA_MEDIA_QOE_DATABASE_URL:-}"
VOCERA_MEDIA_QOE_PSQL_BIN="${VOCERA_MEDIA_QOE_PSQL_BIN:-psql}"
VOCERA_MEDIA_QOE_RAW_OWNER="${VOCERA_MEDIA_QOE_RAW_OWNER:-${SUDO_USER:-appsadmin}}"
VOCERA_MEDIA_QOE_RAW_GROUP="${VOCERA_MEDIA_QOE_RAW_GROUP:-$(id -gn "$VOCERA_MEDIA_QOE_RAW_OWNER" 2>/dev/null || printf '%s' "$VOCERA_MEDIA_QOE_RAW_OWNER")}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"

install -o root -g root -m 0644 "$REPO_ROOT/systemd/vocera-media-qoe-textfile.service" /etc/systemd/system/vocera-media-qoe-textfile.service
install -o root -g root -m 0644 "$REPO_ROOT/systemd/vocera-media-qoe-textfile.timer" /etc/systemd/system/vocera-media-qoe-textfile.timer

install -d -o root -g root -m 0755 /etc/systemd/system/vocera-media-qoe-textfile.service.d
cat >/etc/systemd/system/vocera-media-qoe-textfile.service.d/override.conf <<EOF
[Service]
WorkingDirectory=$REPO_ROOT
ProtectHome=false
ReadWritePaths=
ReadWritePaths=$REPO_ROOT/data $VOCERA_MEDIA_QOE_RAW_DIR $TEXTFILE_COLLECTOR_DIR
EOF

install -d -o "$VOCERA_MEDIA_QOE_RAW_OWNER" -g "$VOCERA_MEDIA_QOE_RAW_GROUP" -m 2775 "$VOCERA_MEDIA_QOE_RAW_DIR"
chown "$VOCERA_MEDIA_QOE_RAW_OWNER:$VOCERA_MEDIA_QOE_RAW_GROUP" "$VOCERA_MEDIA_QOE_RAW_DIR"
chmod 2775 "$VOCERA_MEDIA_QOE_RAW_DIR"
find "$VOCERA_MEDIA_QOE_RAW_DIR" -mindepth 1 -type d -exec chown "$VOCERA_MEDIA_QOE_RAW_OWNER:$VOCERA_MEDIA_QOE_RAW_GROUP" {} + -exec chmod 2775 {} +
find "$VOCERA_MEDIA_QOE_RAW_DIR" -maxdepth 1 -type f -exec chown "$VOCERA_MEDIA_QOE_RAW_OWNER:$VOCERA_MEDIA_QOE_RAW_GROUP" {} + -exec chmod 0664 {} +
install -d -o root -g root -m 0755 "$(dirname "$TEXTFILE_COLLECTOR_DIR")"
install -d -m 0755 "$TEXTFILE_COLLECTOR_DIR"

DEFAULT_FILE=/etc/default/vocera-media-qoe-textfile

if [[ ! -f "$DEFAULT_FILE" ]]; then
  cat >"$DEFAULT_FILE" <<EOF
VOCERA_MEDIA_QOE_RAW_DIR=$VOCERA_MEDIA_QOE_RAW_DIR
VOCERA_MEDIA_QOE_PCAP=$VOCERA_MEDIA_QOE_PCAP
VOCERA_MEDIA_QOE_CONFIG=$VOCERA_MEDIA_QOE_CONFIG
VOCERA_MEDIA_QOE_PROM_OUT=$VOCERA_MEDIA_QOE_PROM_OUT
VOCERA_MEDIA_QOE_JSON_OUT=$VOCERA_MEDIA_QOE_JSON_OUT
VOCERA_MEDIA_QOE_PARSED_DIR=$VOCERA_MEDIA_QOE_PARSED_DIR
VOCERA_MEDIA_QOE_SQL_OUT=$VOCERA_MEDIA_QOE_SQL_OUT
VOCERA_MEDIA_QOE_ARCHIVE_DIR=$VOCERA_MEDIA_QOE_ARCHIVE_DIR
VOCERA_MEDIA_QOE_DATABASE_URL=$VOCERA_MEDIA_QOE_DATABASE_URL
VOCERA_MEDIA_QOE_PSQL_BIN=$VOCERA_MEDIA_QOE_PSQL_BIN
TEXTFILE_COLLECTOR_DIR=$TEXTFILE_COLLECTOR_DIR
EOF
else
  echo "Keeping existing $DEFAULT_FILE"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_PARSED_DIR "$VOCERA_MEDIA_QOE_PARSED_DIR"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_SQL_OUT "$VOCERA_MEDIA_QOE_SQL_OUT"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_ARCHIVE_DIR "$VOCERA_MEDIA_QOE_ARCHIVE_DIR"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_DATABASE_URL "$VOCERA_MEDIA_QOE_DATABASE_URL"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_PSQL_BIN "$VOCERA_MEDIA_QOE_PSQL_BIN"
fi

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  systemctl start vocera-media-qoe-textfile.service
  systemctl status vocera-media-qoe-textfile.service --no-pager -l || true
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  systemctl enable --now vocera-media-qoe-textfile.timer
  systemctl list-timers vocera-media-qoe-textfile.timer --no-pager
fi

echo "Installed vocera-media-qoe-textfile.service and vocera-media-qoe-textfile.timer"
echo "Repo root override: $REPO_ROOT"
echo "Raw pcap directory: $VOCERA_MEDIA_QOE_RAW_DIR"
echo "Raw pcap owner/group: $VOCERA_MEDIA_QOE_RAW_OWNER:$VOCERA_MEDIA_QOE_RAW_GROUP"
echo "Config file: /etc/default/vocera-media-qoe-textfile"
