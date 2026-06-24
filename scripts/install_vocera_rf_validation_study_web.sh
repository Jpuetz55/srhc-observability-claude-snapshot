#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  sudo bash scripts/install_vocera_rf_validation_study_web.sh [--enable] [--start-now] [--skip-frontend-build] [--build-frontend] [--install-python-deps]

Installs the collector-hosted study workflow web UI systemd unit.

Defaults:
  - copies the systemd unit
  - does NOT build the React/Vite/Tailwind frontend as root
  - expects `make study-web-frontend-build` to have already been run as the repo user
  - leaves Python dependency installation to the operator unless --install-python-deps is supplied

Examples:
  make study-web-frontend-build
  sudo bash scripts/install_vocera_rf_validation_study_web.sh --install-python-deps --skip-frontend-build --enable --start-now
  sudo bash scripts/install_vocera_rf_validation_study_web.sh --build-frontend --enable --start-now  # legacy/manual only
USAGE
}

enable=0
start_now=0
skip_frontend_build=1
install_python_deps=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable)
      enable=1
      ;;
    --start-now)
      start_now=1
      ;;
    --skip-frontend-build)
      skip_frontend_build=1
      ;;
    --build-frontend)
      skip_frontend_build=0
      ;;
    --install-python-deps)
      install_python_deps=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
  echo "Run as root, for example: sudo bash scripts/install_vocera_rf_validation_study_web.sh" >&2
  exit 1
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unit_src="$repo_root/systemd/vocera-rf-validation-study-web.service"
unit_dst="/etc/systemd/system/vocera-rf-validation-study-web.service"
requirements="$repo_root/tools/study_web/requirements.txt"
frontend_dir="$repo_root/web/study-ui"
static_dir="$repo_root/tools/study_web/static"
venv_dir="${STUDY_WEB_VENV_DIR:-$repo_root/.venv-study-web}"

if [[ "$install_python_deps" == "1" ]]; then
  echo "Installing Python dependencies into $venv_dir"
  python3 -m venv "$venv_dir"
  "$venv_dir/bin/python" -m pip install --upgrade pip
  "$venv_dir/bin/python" -m pip install -r "$requirements"
else
  echo "Skipping Python dependency installation. Use --install-python-deps if fastapi/uvicorn are not already installed."
fi

if [[ "$skip_frontend_build" != "1" ]]; then
  if command -v npm >/dev/null 2>&1; then
    echo "Building React/Vite/Tailwind frontend"
    pushd "$frontend_dir" >/dev/null
    if [[ -f package-lock.json ]]; then
      npm ci
    else
      npm install
    fi
    npm run build
    popd >/dev/null
    rm -rf "$static_dir"
    mkdir -p "$static_dir"
    cp -a "$frontend_dir/dist/." "$static_dir/"
  else
    echo "WARNING: npm was not found; leaving existing static UI assets in place." >&2
  fi
else
  echo "Skipping frontend build. Run 'make study-web-frontend-build' as the repo user before installing/restarting."
  if [[ ! -f "$static_dir/index.html" ]]; then
    echo "WARNING: $static_dir/index.html does not exist; the web UI may not serve current frontend assets." >&2
  fi
fi

install -m 0644 "$unit_src" "$unit_dst"
systemctl daemon-reload

if [[ "$enable" == "1" ]]; then
  systemctl enable vocera-rf-validation-study-web.service
fi

if [[ "$start_now" == "1" ]]; then
  systemctl restart vocera-rf-validation-study-web.service
fi

systemctl status vocera-rf-validation-study-web.service --no-pager || true
echo
echo "Web UI: http://$(hostname -I | awk '{print $1}'):8097/"
echo "API health: http://$(hostname -I | awk '{print $1}'):8097/api/health"
