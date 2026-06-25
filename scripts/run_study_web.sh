#!/usr/bin/env bash
set -euo pipefail

# Resolve the checkout from this wrapper when systemd does not explicitly set it.
# This prevents a copied service unit from silently launching an older checkout.
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
default_repo_root="$(cd "$script_dir/.." && pwd)"
repo_root="${STUDY_WEB_REPO_ROOT:-$default_repo_root}"
venv_python="${STUDY_WEB_VENV_DIR:-$repo_root/.venv-study-web}/bin/python"
if [[ -x "$venv_python" ]]; then
  python_bin="$venv_python"
else
  python_bin="/usr/bin/python3"
fi

exec "$python_bin" -m uvicorn study_web.main:app \
  --host "${VOCERA_RF_STUDY_WEB_HOST:-0.0.0.0}" \
  --port "${VOCERA_RF_STUDY_WEB_PORT:-8097}"
