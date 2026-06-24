#!/usr/bin/env bash
set -euo pipefail
# Compatibility wrapper: older workflows call this name, while the exporter
# implementation lives in export_dashboards.sh.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/export_dashboards.sh" "$@"
