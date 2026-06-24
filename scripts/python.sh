#!/usr/bin/env bash
set -euo pipefail
# Invoke the repository-selected Python interpreter from scripts/lib/python.sh.

# Stop the wrapper when the shared Python helper is missing.
die() {
  echo "❌ $*" >&2
  exit 1
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/scripts/lib/python.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/python.sh"
else
  die "Missing required file: scripts/lib/python.sh"
fi

python_cmd "$@"
