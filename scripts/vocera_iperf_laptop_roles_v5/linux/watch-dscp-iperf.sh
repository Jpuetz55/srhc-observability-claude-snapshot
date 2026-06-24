#!/usr/bin/env bash
# Watch iperf UDP traffic with tcpdump so DSCP/TOS marking can be verified
# during laptop probe setup or troubleshooting.
set -euo pipefail

PORT="${PORT:-5201}"
IFACE="${IFACE:-any}"

echo "Watching UDP DSCP/TOS for iperf traffic on ${IFACE}, UDP port ${PORT}"
echo "Look for: tos 0xb8"
exec tcpdump -i "${IFACE}" -nn -vvv "udp port ${PORT}"
