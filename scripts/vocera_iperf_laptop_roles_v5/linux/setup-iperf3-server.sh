#!/usr/bin/env bash
# Install iperf3 and create a systemd service that listens on the server VM.
# This script is intended for first-time setup of the synthetic QoE endpoint.
set -euo pipefail

PORT="${PORT:-5201}"

if command -v dnf >/dev/null 2>&1; then
  dnf install -y iperf3
elif command -v yum >/dev/null 2>&1; then
  yum install -y iperf3
elif command -v apt-get >/dev/null 2>&1; then
  apt-get update
  apt-get install -y iperf3
else
  echo "No supported package manager found. Install iperf3 manually." >&2
  exit 1
fi

if command -v firewall-cmd >/dev/null 2>&1; then
  firewall-cmd --add-port="${PORT}/tcp" --permanent || true
  firewall-cmd --add-port="${PORT}/udp" --permanent || true
  firewall-cmd --reload || true
fi

cat >/etc/systemd/system/iperf3-${PORT}.service <<EOF
[Unit]
Description=iperf3 server on port ${PORT}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/iperf3 -s -p ${PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now "iperf3-${PORT}.service"
systemctl status --no-pager "iperf3-${PORT}.service" || true
