#!/usr/bin/env bash
set -euo pipefail
# Install the parser-only service/timer that republishes an existing raw WLC
# evidence file into node_exporter textfile format.

# Print install usage and host-specific environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_wireless_rf_textfile.sh [--enable] [--start-now]

Installs the wireless RF node exporter textfile parser service/timer.

Options:
  --enable     Enable and start wireless-rf-textfile.timer.
  --start-now  Run wireless-rf-textfile.service once after install.

Environment overrides:
  WIRELESS_RF_INPUT             default: data/wireless-rf/raw/wlc_rf_raw.txt
  WIRELESS_RF_WLC               default: unknown
  WIRELESS_RF_BAND              default: 5ghz
  WIRELESS_RF_PROM_OUT          default: data/wireless-rf/out/wlc_rf.prom
  TEXTFILE_COLLECTOR_DIR        default: /var/lib/node_exporter/textfile_collector
  WIRELESS_RF_REPO_ROOT         default: current repo root
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
  die "Run as root, for example: sudo bash ./scripts/install_wireless_rf_textfile.sh"
fi

need_cmd install
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${WIRELESS_RF_REPO_ROOT:-$DEFAULT_ROOT}"
[[ -f "$REPO_ROOT/systemd/wireless-rf-textfile.service" ]] || die "Missing unit file under repo root: $REPO_ROOT"
[[ -f "$REPO_ROOT/systemd/wireless-rf-textfile.timer" ]] || die "Missing timer file under repo root: $REPO_ROOT"

WIRELESS_RF_INPUT="${WIRELESS_RF_INPUT:-data/wireless-rf/raw/wlc_rf_raw.txt}"
WIRELESS_RF_WLC="${WIRELESS_RF_WLC:-unknown}"
WIRELESS_RF_BAND="${WIRELESS_RF_BAND:-5ghz}"
WIRELESS_RF_PROM_OUT="${WIRELESS_RF_PROM_OUT:-data/wireless-rf/out/wlc_rf.prom}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"

install -o root -g root -m 0644 "$REPO_ROOT/systemd/wireless-rf-textfile.service" /etc/systemd/system/wireless-rf-textfile.service
install -o root -g root -m 0644 "$REPO_ROOT/systemd/wireless-rf-textfile.timer" /etc/systemd/system/wireless-rf-textfile.timer

install -d -o root -g root -m 0755 /etc/systemd/system/wireless-rf-textfile.service.d
# Keep host-specific paths in an override instead of templating committed units.
cat >/etc/systemd/system/wireless-rf-textfile.service.d/override.conf <<EOF
[Service]
WorkingDirectory=$REPO_ROOT
ReadWritePaths=$REPO_ROOT/data $TEXTFILE_COLLECTOR_DIR
EOF

install -d -o root -g root -m 0755 "$(dirname "$TEXTFILE_COLLECTOR_DIR")"
install -d -m 0755 "$TEXTFILE_COLLECTOR_DIR"

if [[ ! -f /etc/default/wireless-rf-textfile ]]; then
  # Seed defaults once; keep operator edits on reinstall.
  cat >/etc/default/wireless-rf-textfile <<EOF
WIRELESS_RF_INPUT=$WIRELESS_RF_INPUT
WIRELESS_RF_WLC=$WIRELESS_RF_WLC
WIRELESS_RF_BAND=$WIRELESS_RF_BAND
WIRELESS_RF_PROM_OUT=$WIRELESS_RF_PROM_OUT
TEXTFILE_COLLECTOR_DIR=$TEXTFILE_COLLECTOR_DIR
EOF
else
  echo "Keeping existing /etc/default/wireless-rf-textfile"
fi

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  # Optional one-shot run validates parsing and publishing immediately.
  systemctl start wireless-rf-textfile.service
  systemctl status wireless-rf-textfile.service --no-pager -l
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  # Timer enablement is opt-in to avoid unexpected textfile writes.
  systemctl enable --now wireless-rf-textfile.timer
  systemctl list-timers wireless-rf-textfile.timer --no-pager
fi

echo "Installed wireless-rf-textfile.service and wireless-rf-textfile.timer"
echo "Repo root override: $REPO_ROOT"
echo "Config file: /etc/default/wireless-rf-textfile"
