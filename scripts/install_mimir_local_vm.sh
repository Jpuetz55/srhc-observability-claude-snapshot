#!/usr/bin/env bash
set -euo pipefail
# Install the pinned local Mimir single-binary service used by Prometheus
# remote_write and the Grafana datasource in this repo.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MIMIR_BIN="${MIMIR_BIN:-/usr/local/bin/mimir}"
MIMIR_VERSION="${MIMIR_VERSION:-3.0.6}"
MIMIR_ASSET="${MIMIR_ASSET:-mimir-linux-amd64}"
MIMIR_DOWNLOAD_URL="${MIMIR_DOWNLOAD_URL:-https://github.com/grafana/mimir/releases/download/mimir-${MIMIR_VERSION}/${MIMIR_ASSET}}"
MIMIR_SHA256="${MIMIR_SHA256:-def3f89b5619683396ed62b27a0af7528028ac7e91743c6240bbfb61ea039734}"
MIMIR_DATA_DIR="${MIMIR_DATA_DIR:-/var/lib/prometheus/mimir}"

# Exit with a consistent install error.
die(){ echo "❌ $*" >&2; exit 1; }
# Assert that a required command is available before installing Mimir.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

if [[ "$EUID" -ne 0 ]]; then
  die "Run as root, for example: sudo bash ./scripts/install_mimir_local_vm.sh"
fi

need_cmd install
need_cmd sha256sum
need_cmd systemctl

getent passwd prometheus >/dev/null || die "Missing prometheus user; install/start Prometheus first"

install -d -o prometheus -g prometheus -m 0750 "$MIMIR_DATA_DIR" /var/log/mimir
install -d -o root -g root -m 0755 /etc/mimir

# Verify both existing and downloaded binaries against the selected checksum.
verify_mimir_binary() {
  local path="$1"
  printf '%s  %s\n' "$MIMIR_SHA256" "$path" | sha256sum -c - >/dev/null
}

if [[ -x "$MIMIR_BIN" ]]; then
  verify_mimir_binary "$MIMIR_BIN" || die "$MIMIR_BIN exists but does not match MIMIR_VERSION=$MIMIR_VERSION and MIMIR_SHA256. Remove it or set matching MIMIR_VERSION, MIMIR_ASSET, MIMIR_DOWNLOAD_URL, and MIMIR_SHA256 overrides."
else
  need_cmd curl
  tmp="$(mktemp)"
  trap 'rm -f "$tmp"' EXIT
  curl -fL "$MIMIR_DOWNLOAD_URL" -o "$tmp"
  verify_mimir_binary "$tmp" || die "Downloaded Mimir binary checksum did not match MIMIR_SHA256"
  install -o root -g root -m 0755 "$tmp" "$MIMIR_BIN"
fi

install -o root -g root -m 0644 "$ROOT/mimir/mimir-local.yaml" /etc/mimir/mimir.yaml
install -o root -g root -m 0644 "$ROOT/mimir/systemd/mimir.service" /etc/systemd/system/mimir.service

# Wait for readiness after daemon-reload/start so callers can immediately query
# the local Mimir endpoint when the script exits.
systemctl daemon-reload
systemctl reset-failed mimir 2>/dev/null || true
systemctl enable --now mimir
systemctl is-active --quiet mimir

if command -v curl >/dev/null 2>&1; then
  for _ in {1..30}; do
    if curl -fsS http://127.0.0.1:9009/ready >/dev/null 2>&1; then
      break
    fi
    sleep 1
  done
  curl -fsS http://127.0.0.1:9009/ready >/dev/null
fi

echo "✅ Mimir local VM service is active"
echo "   Ready endpoint: http://127.0.0.1:9009/ready"
