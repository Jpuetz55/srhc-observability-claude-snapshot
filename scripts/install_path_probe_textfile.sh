#!/usr/bin/env bash
set -euo pipefail
# Install the path probe service/timer that publishes RTT/loss/delay-variation textfiles.

# Print command usage and supported environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_path_probe_textfile.sh [--enable] [--start-now]

Installs the wireless path probe node_exporter textfile service/timer.

Options:
  --enable     Enable and start wireless-path-probe.timer.
  --start-now  Run wireless-path-probe.service once after install.

Environment overrides:
  PATH_PROBE_CONFIG            default: config/path-probe.yaml
  PATH_PROBE_PROM_OUT          default: data/path-probe/out/path_probe.prom
  PATH_PROBE_JSON_OUT          default: data/path-probe/out/path_probe_summary.json
  PATH_PROBE_JOB               optional job name from config
  TEXTFILE_COLLECTOR_DIR       default: /var/lib/node_exporter/textfile_collector
  PATH_PROBE_REPO_ROOT         default: current repo root
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
  die "Run as root, for example: sudo bash ./scripts/install_path_probe_textfile.sh"
fi

need_cmd install
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${PATH_PROBE_REPO_ROOT:-$DEFAULT_ROOT}"
[[ -f "$REPO_ROOT/systemd/wireless-path-probe.service" ]] || die "Missing unit file under repo root: $REPO_ROOT"
[[ -f "$REPO_ROOT/systemd/wireless-path-probe.timer" ]] || die "Missing timer file under repo root: $REPO_ROOT"

PATH_PROBE_CONFIG="${PATH_PROBE_CONFIG:-config/path-probe.yaml}"
PATH_PROBE_PROM_OUT="${PATH_PROBE_PROM_OUT:-data/path-probe/out/path_probe.prom}"
PATH_PROBE_JSON_OUT="${PATH_PROBE_JSON_OUT:-data/path-probe/out/path_probe_summary.json}"
PATH_PROBE_JOB="${PATH_PROBE_JOB:-}"
TEXTFILE_COLLECTOR_DIR="${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"

install -o root -g root -m 0644 "$REPO_ROOT/systemd/wireless-path-probe.service" /etc/systemd/system/wireless-path-probe.service
install -o root -g root -m 0644 "$REPO_ROOT/systemd/wireless-path-probe.timer" /etc/systemd/system/wireless-path-probe.timer

install -d -o root -g root -m 0755 /etc/systemd/system/wireless-path-probe.service.d
# Keep host-specific repo/textfile paths outside the committed unit.
cat >/etc/systemd/system/wireless-path-probe.service.d/override.conf <<EOF
[Service]
WorkingDirectory=$REPO_ROOT
ReadWritePaths=$REPO_ROOT/data $TEXTFILE_COLLECTOR_DIR
EOF

install -d -o root -g root -m 0755 "$(dirname "$TEXTFILE_COLLECTOR_DIR")"
install -d -m 0755 "$TEXTFILE_COLLECTOR_DIR"

if [[ ! -f /etc/default/wireless-path-probe ]]; then
  # Seed defaults once; real target addresses belong in the site config file.
  cat >/etc/default/wireless-path-probe <<EOF
PATH_PROBE_CONFIG=$PATH_PROBE_CONFIG
PATH_PROBE_PROM_OUT=$PATH_PROBE_PROM_OUT
PATH_PROBE_JSON_OUT=$PATH_PROBE_JSON_OUT
PATH_PROBE_JOB=$PATH_PROBE_JOB
TEXTFILE_COLLECTOR_DIR=$TEXTFILE_COLLECTOR_DIR
EOF
else
  echo "Keeping existing /etc/default/wireless-path-probe"
fi

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  # Optional one-shot run validates the configured targets immediately.
  systemctl start wireless-path-probe.service
  systemctl status wireless-path-probe.service --no-pager -l
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  # Enable only after config/path-probe.yaml has real site targets.
  systemctl enable --now wireless-path-probe.timer
  systemctl list-timers wireless-path-probe.timer --no-pager
fi

echo "Installed wireless-path-probe.service and wireless-path-probe.timer"
echo "Repo root override: $REPO_ROOT"
echo "Config file: /etc/default/wireless-path-probe"
