#!/usr/bin/env bash
set -euo pipefail
# Thin mode dispatcher shared by Makefile validate/plan/deploy targets.

# Print supported pipeline modes.
usage() {
  cat <<'EOF'
Usage:
  ./scripts/pipeline.sh <validate|plan|deploy> [extra args]

Modes:
  validate   Run repo checks only.
  plan       Run preflight, then dry-run promote.
  deploy     Run preflight, then promote.
EOF
}

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
MODE="${1:-}"
shift || true

case "$MODE" in
  validate)
    # Validation is read-only.
    exec bash ./scripts/preflight.sh
    ;;
  plan)
    # Plan uses the full preflight path, then promotes in dry-run mode.
    bash ./scripts/preflight.sh
    exec bash ./scripts/promote_repo_to_prod.sh --dry-run "$@"
    ;;
  deploy)
    # Deploy only runs after preflight succeeds.
    bash ./scripts/preflight.sh
    exec bash ./scripts/promote_repo_to_prod.sh "$@"
    ;;
  -h|--help|help|"")
    usage
    exit 0
    ;;
  *)
    usage
    echo "❌ Unknown mode: $MODE" >&2
    exit 1
    ;;
esac
