#!/usr/bin/env bash
# Prepare the collector-side ingest directories used by laptop SCP uploads.
# The Prometheus textfile publisher reads from this tree later.
set -euo pipefail

BASE="${BASE:-/var/lib/vocera-iperf-qoe}"
USER_NAME="${USER_NAME:-appsadmin}"
GROUP_NAME="${GROUP_NAME:-appsadmin}"

mkdir -p "${BASE}/incoming" "${BASE}/processed" "${BASE}/logs"

chown -R "${USER_NAME}:${GROUP_NAME}" "${BASE}"

chmod 0750 "${BASE}"
chmod 0770 "${BASE}/incoming" "${BASE}/processed" "${BASE}/logs"

echo "Created collector ingest directories:"
ls -ld "${BASE}" "${BASE}/incoming" "${BASE}/processed" "${BASE}/logs"
