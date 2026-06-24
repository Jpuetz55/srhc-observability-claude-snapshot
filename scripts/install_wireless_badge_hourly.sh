#!/usr/bin/env bash
set -euo pipefail
# Install the scheduled badge client-detail collection pipeline and publish the
# resulting Prometheus textfile for node_exporter.

# Print install usage and badge-collection environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_wireless_badge_hourly.sh [--enable] [--start-now]

Installs the Vocera badge collect+parse+publish service/timer.

The service shells out to:
  make wireless-badge-collect BADGE_CONFIG=...
  make wireless-badge-parse   BADGE_CONFIG=... BADGE_INPUT=...
and then installs the resulting badge_client.prom into the
node_exporter textfile_collector directory so Prometheus scrapes it.

Options:
  --enable     Enable and start wireless-badge-hourly.timer.
  --start-now  Run wireless-badge-hourly.service once after install.

Environment overrides (read from /etc/default/wireless-badge-hourly):
  WIRELESS_BADGE_REPO_ROOT     default: current repo root
  BADGE_CONFIG                 default: config/badge-client-observability.yaml
  BADGE_INPUT                  default: data/wireless-rf/raw/badge_client_raw.json
  BADGE_PROM_OUT               default: data/wireless-rf/exports/badge_client.prom
  TEXTFILE_COLLECTOR_DIR       default: /var/lib/node_exporter/textfile_collector
  DNAC_BASE_URL                Catalyst Center base URL (e.g. https://dnac.example.com)
  DNAC_USERNAME                Catalyst Center username
  DNAC_PASSWORD                Catalyst Center password
  VOCERA_BADGE_MACS            comma/space-separated badge MAC list
  VOCERA_BADGE_MACS_FILE       path to a file containing badge MACs (one per line, csv, or json)
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
    --enable)    ENABLE_TIMER=1 ;;
    --start-now) START_NOW=1 ;;
    -h|--help)   usage; exit 0 ;;
    *)           usage; die "Unknown argument: $1" ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  die "Run as root, for example: sudo bash ./scripts/install_wireless_badge_hourly.sh"
fi

need_cmd chmod
need_cmd install
need_cmd systemctl

repo_root="${WIRELESS_BADGE_REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"

install -d -o root -g root -m 0755 /usr/local/sbin
# The installed wrapper reads /etc/default at runtime so credentials and output
# paths can change without reinstalling the unit.
cat >/usr/local/sbin/wireless-badge-hourly.sh <<EOF
#!/usr/bin/env bash
set -euo pipefail
source /etc/default/wireless-badge-hourly
cd "${repo_root}"
mkdir -p data/wireless-rf/raw data/wireless-rf/exports "\${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}"
make wireless-badge-collect \\
  BADGE_CONFIG="\${BADGE_CONFIG:-config/badge-client-observability.yaml}"
make wireless-badge-parse \\
  BADGE_CONFIG="\${BADGE_CONFIG:-config/badge-client-observability.yaml}" \\
  BADGE_INPUT="\${BADGE_INPUT:-data/wireless-rf/raw/badge_client_raw.json}"
install -D -m 0644 \\
  "\${BADGE_PROM_OUT:-data/wireless-rf/exports/badge_client.prom}" \\
  "\${TEXTFILE_COLLECTOR_DIR:-/var/lib/node_exporter/textfile_collector}/badge_client.prom"
EOF
chmod 0755 /usr/local/sbin/wireless-badge-hourly.sh

if [[ ! -f /etc/default/wireless-badge-hourly ]]; then
  # Seed a root-owned defaults file without overwriting operator credentials.
  cat >/etc/default/wireless-badge-hourly <<'EOF'
DNAC_BASE_URL=
DNAC_USERNAME=
DNAC_PASSWORD=
PROMETHEUS_URL=http://localhost:9090
VOCERA_BADGE_MACS=
VOCERA_BADGE_MACS_FILE=
BADGE_CONFIG=config/badge-client-observability.yaml
BADGE_INPUT=data/wireless-rf/raw/badge_client_raw.json
BADGE_PROM_OUT=data/wireless-rf/exports/badge_client.prom
TEXTFILE_COLLECTOR_DIR=/var/lib/node_exporter/textfile_collector
EOF
  chmod 0600 /etc/default/wireless-badge-hourly
else
  echo "Keeping existing /etc/default/wireless-badge-hourly"
fi

cat >/etc/systemd/system/wireless-badge-hourly.service <<'EOF'
[Unit]
Description=Collect and publish Vocera badge client metrics from Catalyst Center
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
EnvironmentFile=/etc/default/wireless-badge-hourly
ExecStart=/usr/local/sbin/wireless-badge-hourly.sh
NoNewPrivileges=true
PrivateTmp=true
EOF

cat >/etc/systemd/system/wireless-badge-hourly.timer <<'EOF'
[Unit]
Description=Run Vocera badge client collection every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Persistent=true
Unit=wireless-badge-hourly.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  # Optional one-shot run validates the installed wrapper and environment file.
  systemctl start wireless-badge-hourly.service
  systemctl status wireless-badge-hourly.service --no-pager -l
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  # Timer enablement is opt-in so installers do not unexpectedly collect live
  # Catalyst Center data.
  systemctl enable --now wireless-badge-hourly.timer
  systemctl list-timers wireless-badge-hourly.timer --no-pager
fi

echo "Installed wireless-badge-hourly.service and wireless-badge-hourly.timer"
echo "Config file: /etc/default/wireless-badge-hourly"
echo "Next: edit /etc/default/wireless-badge-hourly to set DNAC_* and VOCERA_BADGE_MACS before starting the service."
