#!/usr/bin/env bash
set -euo pipefail
# Canonical human-driven release workflow.
# Flow: DEV (Grafana API) -> repo -> PROD (files).
# This script MAY commit to Git.
# This script MUST NOT be used in CI.
# Print the manual release workflow and options.
usage() {
  cat <<'EOF'
Usage:
  ./scripts/release.sh -m "commit message" [--dry-run]

Behavior:
  - ./scripts/export_dev_db_to_repo.sh   (stages changes)
  - git commit -m "message"              (if changes exist)
  - ./scripts/promote_repo_to_prod.sh

Options:
  -m, --message "msg"  Required commit message
  --dry-run            Propagates to sub-scripts and prints actions only
EOF
}

# Return a wall-clock timestamp for release logs.
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
# Print a timestamped release log line.
log(){ echo "[$(ts)] $*"; }
# Stop the release with a consistent error message.
die(){ echo "❌ $*" >&2; exit 1; }

# Assert that a required file exists before release begins.
need_file() { [[ -f "$1" ]] || die "Missing required file: $1"; }
# Assert that a required command exists before release begins.
need_cmd() { command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

MSG=""
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -m|--message)
      [[ $# -ge 2 ]] || die "$1 requires a value"
      MSG="${2:-}"
      shift 2
      ;;
    --dry-run) DRY_RUN=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done

[[ -n "$MSG" ]] || { usage; die "Missing -m \"commit message\""; }

if [[ "$EUID" -eq 0 && "$DRY_RUN" != "1" ]]; then
  die "Do not run as root."
fi

# Always operate from repo root (so relative paths are stable)
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EXPORT_SCRIPT="./scripts/export_dev_db_to_repo.sh"
PROMOTE_SCRIPT="./scripts/promote_repo_to_prod.sh"
PATHS_LIB="./scripts/lib/paths.sh"

need_cmd git
need_cmd bash
need_file "$EXPORT_SCRIPT"
need_file "$PROMOTE_SCRIPT"
need_file "$PATHS_LIB"

args=()
if [[ "$DRY_RUN" == "1" ]]; then args+=(--dry-run); fi

log "Release: export -> commit -> promote"
log "Message: $MSG"
log "DRY_RUN : $DRY_RUN"

bash "$EXPORT_SCRIPT" "${args[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
  log "[dry-run] would run: git commit -m \"$MSG\" (if changes staged)"
else
  # Export stages dashboard changes; commit only when the staging area changed.
  if git diff --cached --quiet; then
    log "No staged changes. Nothing to commit."
  else
    git commit -m "$MSG"
    log "✅ Committed: $MSG"
  fi
fi

# Promotion is intentionally last so PROD only sees a committed repo state.
bash "$PROMOTE_SCRIPT" "${args[@]}"

if [[ "$DRY_RUN" == "1" ]]; then
  log "✅ [dry-run] Release simulation complete"
else
  log "✅ Release complete"
fi
