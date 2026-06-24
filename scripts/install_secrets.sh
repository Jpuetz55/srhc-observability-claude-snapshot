#!/usr/bin/env bash
# Thin wrapper around scripts/install_secrets.py, matching the convention of
# the other install_*.sh scripts in this repo.
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
  echo "Run as root: sudo bash scripts/install_secrets.sh" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/install_secrets.py" "$@"
