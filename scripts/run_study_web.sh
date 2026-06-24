#!/usr/bin/env bash
set -euo pipefail

repo_root="${STUDY_WEB_REPO_ROOT:-/home/appsadmin/grafana-mimir-observability}"
venv_python="${STUDY_WEB_VENV_DIR:-$repo_root/.venv-study-web}/bin/python"
if [[ -x "$venv_python" ]]; then
  python_bin="$venv_python"
else
  python_bin="/usr/bin/python3"
fi

exec "$python_bin" -m uvicorn study_web.main:app \
  --host "${VOCERA_RF_STUDY_WEB_HOST:-0.0.0.0}" \
  --port "${VOCERA_RF_STUDY_WEB_PORT:-8097}"
