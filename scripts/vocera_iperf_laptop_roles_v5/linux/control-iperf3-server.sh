#!/usr/bin/env bash
# Start, stop, or inspect the Linux iperf3 service used as the stable server
# endpoint for the Vocera laptop synthetic QoE tests.
set -euo pipefail

ACTION="${1:-status}"
SERVICE="${SERVICE:-iperf3-5201.service}"

case "${ACTION}" in
  start)
    systemctl start "${SERVICE}"
    systemctl status --no-pager "${SERVICE}" || true
    ;;
  stop)
    systemctl stop "${SERVICE}"
    systemctl status --no-pager "${SERVICE}" || true
    ;;
  restart)
    systemctl restart "${SERVICE}"
    systemctl status --no-pager "${SERVICE}" || true
    ;;
  status)
    systemctl status --no-pager "${SERVICE}" || true
    ss -lntup | grep 5201 || true
    ;;
  enable)
    systemctl enable --now "${SERVICE}"
    systemctl status --no-pager "${SERVICE}" || true
    ;;
  disable)
    systemctl disable --now "${SERVICE}"
    systemctl status --no-pager "${SERVICE}" || true
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|enable|disable}" >&2
    exit 2
    ;;
esac
