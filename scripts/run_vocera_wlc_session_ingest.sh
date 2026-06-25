#!/usr/bin/env bash
# Thin trigger for the WLC capture-session SCP ingest.
#
# Study Web owns the ingest pipeline: it validates a completed SCP upload under
# <session>/incoming/, finalizes it as a service-owned artifact under
# <session>/pcaps/, registers it as a wlc_epc capture, and runs the existing
# parser -- all in-process so it reuses the same parser executor and capture
# registration the generic raw-file path uses. This script only asks the local
# Study Web service to run one ingest-scan pass on a timer, so an exported EPC is
# imported without any operator action. It stores no WLC or SCP secrets and never
# SSHes anywhere.
set -euo pipefail

host="${STUDY_WEB_INGEST_HOST:-127.0.0.1}"
port="${STUDY_WEB_INGEST_PORT:-${VOCERA_RF_STUDY_WEB_PORT:-8097}}"
timeout="${STUDY_WEB_INGEST_TIMEOUT:-600}"
lock_file="${STUDY_WEB_WLC_INGEST_LOCK_FILE:-/run/vocera-media-qoe/wlc-session-ingest.lock}"
raw_root="${VOCERA_MEDIA_QOE_RAW_DIR:-/var/lib/vocera-media-qoe/raw}"
session_root="${STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT:-${raw_root}/wlc-sessions}"
min_free_bytes="${STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES:-536870912}"
url="http://${host}:${port}/api/media-qoe/wlc/sessions/ingest-scan"
health_url="http://${host}:${port}/api/health"

json_error() {
  local reason="$1" detail="$2"
  printf '{"event":"wlc_ingest_scan_failed","reason":"%s","detail":"%s"}\n' "$reason" "$detail"
}

lock_dir="$(dirname "${lock_file}")"
if [[ ! -d "${lock_dir}" ]]; then
  mkdir -p "${lock_dir}"
fi

exec 9>"${lock_file}"
if ! flock -n 9; then
  printf '{"event":"wlc_ingest_scan_skipped","reason":"already_running"}\n'
  exit 0
fi

if ! curl -fsS -m 10 "${health_url}" >/dev/null; then
  json_error "study_web_unhealthy" "local Study Web health endpoint did not respond"
  exit 1
fi

if [[ ! -d "${raw_root}" ]]; then
  json_error "raw_root_missing" "${raw_root}"
  exit 1
fi

if [[ ! -d "${session_root}" ]]; then
  json_error "session_root_missing" "${session_root}"
  exit 1
fi

if ! [[ "${min_free_bytes}" =~ ^[0-9]+$ ]]; then
  json_error "invalid_min_free_bytes" "${min_free_bytes}"
  exit 1
fi

free_kb="$(df -Pk "${session_root}" | awk 'NR == 2 {print $4}')"
free_bytes=$((free_kb * 1024))
if (( free_bytes < min_free_bytes )); then
  json_error "disk_space_insufficient" "free_bytes=${free_bytes};required_bytes=${min_free_bytes}"
  exit 1
fi

curl -fsS -m "${timeout}" -X POST -H 'content-type: application/json' -d '{}' "${url}"
printf '\n'
