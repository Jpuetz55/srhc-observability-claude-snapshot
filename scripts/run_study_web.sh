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
  # Mirror the installer preference when a venv is absent. Do not silently
  # select a collector's legacy Python 3.9 default for Python 3.10+ source.
  python_bin="${STUDY_WEB_PYTHON_BIN:-}"
  if [[ -z "$python_bin" ]]; then
    for candidate in /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10 /usr/bin/python3; do
      if [[ -x "$candidate" ]]; then
        python_bin="$candidate"
        break
      fi
    done
  fi
fi

if ! "$python_bin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)'; then
  echo "ERROR: Study Web requires Python 3.10 or newer; selected $python_bin reports $($python_bin --version 2>&1)." >&2
  exit 1
fi

exec "$python_bin" -m uvicorn study_web.main:app \
  --host "${VOCERA_RF_STUDY_WEB_HOST:-0.0.0.0}" \
  --port "${VOCERA_RF_STUDY_WEB_PORT:-8097}"
