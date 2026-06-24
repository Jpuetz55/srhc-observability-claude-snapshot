#!/usr/bin/env bash
set -euo pipefail
# Install the scheduled WLC RF parse+publish pipeline for node_exporter.

# Print install usage and scheduled-collection environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_wireless_rf_hourly.sh [--enable] [--start-now]

Installs the wireless RF hourly parse+publish service/timer.

Options:
  --enable     Enable and start wireless-rf-hourly.timer.
  --start-now  Run wireless-rf-hourly.service once after install.

Environment overrides:
  WIRELESS_RF_REPO_ROOT         default: current repo root
  WIRELESS_RF_WLC               default: unknown
  WIRELESS_RF_BAND              default: 5ghz
  WIRELESS_RF_INPUT             default: data/wireless-rf/raw/wlc_rf_raw.txt
  WIRELESS_RF_PROM_OUT          default: data/wireless-rf/out/wlc_rf.prom
  TEXTFILE_COLLECTOR_DIR        default: /var/lib/node_exporter/textfile_collector
  SITE_TAG_REGEX                optional site-tag parse filter
  AP_NAME_REGEX                 optional AP-name parse filter
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
  die "Run as root, for example: sudo bash ./scripts/install_wireless_rf_hourly.sh"
fi

need_cmd chmod
need_cmd install
need_cmd systemctl

repo_root="${WIRELESS_RF_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

install -d -o root -g root -m 0755 /usr/local/sbin
# The runtime wrapper composes existing make targets so scheduled and manual
# parsing use the same code paths.
cat >/usr/local/sbin/wireless-rf-hourly.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /etc/default/wireless-rf-hourly
cd "${repo_root}"
mkdir -p data/wireless-rf/raw data/wireless-rf/out "\${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"
make wireless-rf-parse \\
  INPUT="\${WIRELESS_RF_INPUT:-data/wireless-rf/raw/wlc_rf_raw.txt}" \\
  WLC="\${WIRELESS_RF_WLC:-unknown}" \\
  BAND="\${WIRELESS_RF_BAND:-5ghz}" \\
  SITE_TAG_REGEX="\${SITE_TAG_REGEX:-}" \\
  AP_NAME_REGEX="\${AP_NAME_REGEX:-}" \\
  RF_PROM_OUT="\${WIRELESS_RF_PROM_OUT:-data/wireless-rf/out/wlc_rf.prom}"
install -D -m 0644 "\${WIRELESS_RF_PROM_OUT:-data/wireless-rf/out/wlc_rf.prom}" "\${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}/wlc_rf.prom"
EOF
chmod 0755 /usr/local/sbin/wireless-rf-hourly.sh

if [[ ! -f /etc/default/wireless-rf-hourly ]]; then
  # Do not overwrite credentials or collection scope during reinstall.
  cat >/etc/default/wireless-rf-hourly <<'EOF'
WIRELESS_RF_WLC=unknown
WIRELESS_RF_BAND=5ghz
WIRELESS_RF_INPUT=data/wireless-rf/raw/wlc_rf_raw.txt
WIRELESS_RF_PROM_OUT=data/wireless-rf/out/wlc_rf.prom
TEXTFILE_COLLECTOR_DIR=/var/lib/node_exporter/textfile_collector
SITE_TAG_REGEX=
AP_NAME_REGEX=
EOF
  chmod 0600 /etc/default/wireless-rf-hourly
else
  echo "Keeping existing /etc/default/wireless-rf-hourly"
fi

cat >/etc/systemd/system/wireless-rf-hourly.service <<'EOF'
[Unit]
Description=Parse and publish WLC RF metrics hourly
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/default/wireless-rf-hourly
ExecStart=/usr/local/sbin/wireless-rf-hourly.sh
NoNewPrivileges=true
PrivateTmp=true
EOF

cat >/etc/systemd/system/wireless-rf-hourly.timer <<'EOF'
[Unit]
Description=Run WLC RF parser hourly

[Timer]
OnBootSec=5min
OnCalendar=hourly
AccuracySec=1min
Persistent=true
Unit=wireless-rf-hourly.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  # Optional one-shot run verifies parse/publish after install.
  systemctl start wireless-rf-hourly.service
  systemctl status wireless-rf-hourly.service --no-pager -l
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  systemctl enable --now wireless-rf-hourly.timer
  systemctl list-timers wireless-rf-hourly.timer --no-pager
fi

echo "Installed wireless-rf-hourly.service and wireless-rf-hourly.timer"
echo "Config file: /etc/default/wireless-rf-hourly"
echo "Next: edit /etc/default/wireless-rf-hourly before starting the service if credentials are not already set."
