#!/usr/bin/env bash
set -euo pipefail
# Install the Vocera iperf QoE service/timer that publishes node_exporter textfiles.

# Print install usage and textfile environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_vocera_iperf_qoe_textfile.sh [--enable] [--start-now]

Installs the Vocera iperf QoE node_exporter textfile service/timer.

Options:
  --enable     Enable and start vocera-iperf-qoe-textfile.timer.
  --start-now  Run vocera-iperf-qoe-textfile.service once after install.

Environment overrides:
  VOCERA_IPERF_QOE_CONFIG         default: config/vocera-iperf-qoe.example.yaml
  VOCERA_IPERF_QOE_INCOMING_ROOT  default: /var/lib/vocera-iperf-qoe/incoming
  VOCERA_IPERF_QOE_PROM_OUT       default: data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom
  VOCERA_IPERF_QOE_JSON_OUT       default: data/vocera-iperf-qoe/out/vocera_iperf_qoe_summary.json
  TEXTFILE_COLLECTOR_DIR          default: /var/lib/node_exporter/textfile_collector
  VOCERA_IPERF_QOE_REPO_ROOT      default: current repo root
EOF
}

# Exit with a consistent install error.
die(){ echo "ERROR: $*" >&2; exit 1; }
# Assert that a required command is available before touching systemd.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

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
  die "Run as root, for example: sudo bash ./scripts/install_vocera_iperf_qoe_textfile.sh"
fi

need_cmd install
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${VOCERA_IPERF_QOE_REPO_ROOT:-$DEFAULT_ROOT}"
[[ -f "$REPO_ROOT/systemd/vocera-iperf-qoe-textfile.service" ]] || die "Missing unit file under repo root: $REPO_ROOT"
[[ -f "$REPO_ROOT/systemd/vocera-iperf-qoe-textfile.timer" ]] || die "Missing timer file under repo root: $REPO_ROOT"

VOCERA_IPERF_QOE_CONFIG="${VOCERA_IPERF_QOE_CONFIG:-config/vocera-iperf-qoe.example.yaml}"
VOCERA_IPERF_QOE_INCOMING_ROOT="${VOCERA_IPERF_QOE_INCOMING_ROOT:-/var/lib/vocera-iperf-qoe/incoming}"
VOCERA_IPERF_QOE_PROM_OUT="${VOCERA_IPERF_QOE_PROM_OUT:-data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom}"
VOCERA_IPERF_QOE_JSON_OUT="${VOCERA_IPERF_QOE_JSON_OUT:-data/vocera-iperf-qoe/out/vocera_iperf_qoe_summary.json}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"

install -o root -g root -m 0644 "$REPO_ROOT/systemd/vocera-iperf-qoe-textfile.service" /etc/systemd/system/vocera-iperf-qoe-textfile.service
install -o root -g root -m 0644 "$REPO_ROOT/systemd/vocera-iperf-qoe-textfile.timer" /etc/systemd/system/vocera-iperf-qoe-textfile.timer

install -d -o root -g root -m 0755 /etc/systemd/system/vocera-iperf-qoe-textfile.service.d
cat >/etc/systemd/system/vocera-iperf-qoe-textfile.service.d/override.conf <<EOF
[Service]
WorkingDirectory=$REPO_ROOT
ProtectHome=false
ReadWritePaths=$REPO_ROOT/data $TEXTFILE_COLLECTOR_DIR
EOF

install -d -m 0755 "$TEXTFILE_COLLECTOR_DIR"

if [[ ! -f /etc/default/vocera-iperf-qoe-textfile ]]; then
  cat >/etc/default/vocera-iperf-qoe-textfile <<EOF
VOCERA_IPERF_QOE_CONFIG=$VOCERA_IPERF_QOE_CONFIG
VOCERA_IPERF_QOE_INCOMING_ROOT=$VOCERA_IPERF_QOE_INCOMING_ROOT
VOCERA_IPERF_QOE_PROM_OUT=$VOCERA_IPERF_QOE_PROM_OUT
VOCERA_IPERF_QOE_JSON_OUT=$VOCERA_IPERF_QOE_JSON_OUT
TEXTFILE_COLLECTOR_DIR=$TEXTFILE_COLLECTOR_DIR
EOF
else
  echo "Keeping existing /etc/default/vocera-iperf-qoe-textfile"
fi

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  systemctl start vocera-iperf-qoe-textfile.service
  systemctl status vocera-iperf-qoe-textfile.service --no-pager -l
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  systemctl enable --now vocera-iperf-qoe-textfile.timer
  systemctl list-timers vocera-iperf-qoe-textfile.timer --no-pager
fi

echo "Installed vocera-iperf-qoe-textfile.service and vocera-iperf-qoe-textfile.timer"
echo "Repo root override: $REPO_ROOT"
echo "Config file: /etc/default/vocera-iperf-qoe-textfile"
