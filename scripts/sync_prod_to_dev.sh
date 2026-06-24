#!/usr/bin/env bash
set -euo pipefail
# Mirror repo PROD dashboards into the editable DEV Grafana org.

# Print sync workflow usage and dry-run behavior.
usage() {
  cat <<'EOF'
Usage:
  ./scripts/sync_prod_to_dev.sh [--dry-run]

Behavior:
  - Mirror repo grafana/dashboards-prod -> grafana/dashboards-dev
  - Validate dashboard JSON/contracts
  - Reseed the editable DEV Grafana org from files
  - In sync mode, prune unmanaged DEV dashboards/folders through the Grafana API

Notes:
  - This is the canonical PROD baseline -> DEV org reseed workflow.
  - It avoids Grafana DB surgery on the DEV org by deleting stale objects via API.
EOF
}

# Return a wall-clock timestamp for sync logs.
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
# Print a timestamped sync log line.
log(){ echo "[$(ts)] $*"; }
# Stop the sync with a consistent error message.
die(){ echo "❌ $*" >&2; exit 1; }
# Assert that a required command exists.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

DRY_RUN=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "Unknown arg: $1" ;;
  esac
done

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
need_cmd rsync
need_cmd bash

log "Syncing repo PROD dashboards -> DEV dashboards mirror"
if [[ "$DRY_RUN" == "1" ]]; then
  # rsync -n shows file-level changes without mutating the DEV tree.
  rsync -an --delete grafana/dashboards-prod/ grafana/dashboards-dev/
  log "[dry-run] would validate dashboards"
  log "[dry-run] would reseed DEV org from files with SEED_MODE=sync"
  exit 0
fi

rsync -a --delete grafana/dashboards-prod/ grafana/dashboards-dev/
python3 ./scripts/check_dashboards.py
# SEED_MODE=sync prunes unmanaged DEV dashboards/folders so DEV matches repo.
SEED_MODE=sync GRAFANA_URL="${DEV_GRAFANA_URL:-${GRAFANA_URL:-http://127.0.0.1:3000}}" DEV_ORG_ID="${DEV_ORG_ID:-2}" bash ./scripts/seed_dev_from_files.sh
log "✅ PROD baseline synced into DEV org"
