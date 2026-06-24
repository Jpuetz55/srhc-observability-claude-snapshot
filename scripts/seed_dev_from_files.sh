#!/usr/bin/env bash
set -euo pipefail
# Import repo dashboard JSON into the editable DEV Grafana org via API.

# Stop seeding with a consistent error message.
die() {
  echo "❌ $*" >&2
  exit 1
}

# Assert that a command needed for Grafana API seeding exists.
need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

# Seed DEV org dashboards into Grafana DB (no provisioning).
# Reads JSON from repo and imports via Grafana API.
#
# Requirements:
#   - env var GRAFANA_URL (default http://localhost:3000)
#   - token at /etc/{observability,onservability}/grafana_token_dev (or env GRAFANA_TOKEN)
#   - DEV_ORG_ID (default 2)
#   - dashboards live under ./grafana/dashboards-dev
#
# Notes:
#   - Grafana "foldersFromFilesStructure" is a provisioning feature.
#     Here we emulate it: folder name = first directory under dashboards-dev.
#   - Overwrites existing dashboards by UID.

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
DEV_ORG_ID="${DEV_ORG_ID:-2}"
DASH_ROOT="${DASH_ROOT:-./grafana/dashboards-dev}"
SEED_MODE="${SEED_MODE:-merge}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/scripts/lib/grafana_auth.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/grafana_auth.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/grafana_auth.sh"
fi
TOKEN_FILE="${TOKEN_FILE:-$OBS_DEV_TOKEN_FILE}"

need_cmd curl
need_cmd jq
need_cmd find

if [[ -z "${GRAFANA_TOKEN:-}" ]]; then
  GRAFANA_TOKEN="$(obs_read_token_file "$TOKEN_FILE" || true)"
fi
[[ -n "${GRAFANA_TOKEN:-}" ]] || die "Unable to read Grafana token from $TOKEN_FILE"

if [[ ! -d "${DASH_ROOT}" ]]; then
  die "DASH_ROOT not found: ${DASH_ROOT}"
fi

auth_hdr=(-H "Authorization: Bearer ${GRAFANA_TOKEN}")
org_hdr=(-H "X-Grafana-Org-Id: ${DEV_ORG_ID}")
json_hdr=(-H "Content-Type: application/json")

# Simple JSON API wrapper for requests where curl should fail non-2xx.
api() {
  local method="$1" path="$2"
  shift 2
  curl -fsS "${GRAFANA_URL}${path}" -X "${method}" "${auth_hdr[@]}" "${org_hdr[@]}" "${json_hdr[@]}" "$@"
}

# Variant used by delete helpers that need to treat 404 as success.
api_with_status() {
  local method="$1" path="$2"
  shift 2
  curl -sS -o /tmp/seed_dev_api_body.$$ -w "%{http_code}" "${GRAFANA_URL}${path}"     -X "${method}" "${auth_hdr[@]}" "${org_hdr[@]}" "${json_hdr[@]}" "$@"
}

# Delete an object idempotently during sync pruning.
api_delete_if_present() {
  local path="$1"
  local status
  status="$(api_with_status DELETE "$path")"
  if [[ "$status" == "404" ]]; then
    rm -f /tmp/seed_dev_api_body.$$
    return 0
  fi
  if [[ "$status" =~ ^2 ]]; then
    rm -f /tmp/seed_dev_api_body.$$
    return 0
  fi
  echo "WARN: DELETE ${path} returned HTTP ${status}" >&2
  if [[ -f /tmp/seed_dev_api_body.$$ ]]; then
    cat /tmp/seed_dev_api_body.$$ >&2 || true
    rm -f /tmp/seed_dev_api_body.$$
  fi
  return 1
}

# Remove DEV dashboards whose UIDs are no longer present in repo files.
sync_delete_unmanaged_dashboards() {
  local desired_uids_file="$1"
  local existing_json uid
  existing_json="$(api GET "/api/search?type=dash-db&limit=5000")"
  while IFS= read -r uid; do
    [[ -n "$uid" ]] || continue
    if ! grep -Fxq "$uid" "$desired_uids_file"; then
      echo "🧹 deleting unmanaged DEV dashboard uid=${uid}"
      api_delete_if_present "/api/dashboards/uid/${uid}" || true
    fi
  done < <(jq -r '.[] | .uid // empty' <<<"$existing_json")
}

# Remove empty DEV folders that are no longer represented by repo folders.
sync_delete_unmanaged_folders() {
  local desired_folders_file="$1"
  local existing_json title uid
  existing_json="$(api GET "/api/folders")"
  while IFS=$'	' read -r title uid; do
    [[ -n "$uid" ]] || continue
    [[ "$title" == "General" ]] && continue
    if ! grep -Fxq "$title" "$desired_folders_file"; then
      echo "🧹 deleting unmanaged DEV folder title=${title} uid=${uid}"
      api_delete_if_present "/api/folders/${uid}" || true
    fi
  done < <(jq -r '.[] | [(.title // ""), (.uid // "")] | @tsv' <<<"$existing_json")
}
# Create folder if missing; echo folderUid for dashboard import payloads.
ensure_folder() {
  local folder_title="$1"
  local uid

  # Lookup by title because repo folder names map to Grafana folder titles.
  uid="$(api GET "/api/folders" | jq -r --arg t "$folder_title" '.[] | select(.title==$t) | .uid' | head -n1 || true)"
  if [[ -n "${uid}" && "${uid}" != "null" ]]; then
    echo "${uid}"
    return 0
  fi

  # Create the folder only when the title lookup misses.
  uid="$(api POST "/api/folders" -d "$(jq -nc --arg t "$folder_title" '{title:$t}')" | jq -r '.uid')"
  echo "${uid}"
}

# Import dashboard JSON into a resolved folder UID.
import_dashboard() {
  local file="$1"
  local folder_uid="$2"

  # Strip volatile fields that cause conflicts (id, version)
  # Preserve dashboard.uid as the stable identity.
  local payload
  payload="$(jq -c --arg folderUid "$folder_uid" '
    {
      dashboard: (. | del(.id, .version)),
      folderUid: $folderUid,
      overwrite: true,
      message: "seed_dev_from_repo"
    }' "$file")"

  api POST "/api/dashboards/db" -d "$payload" >/dev/null
}

echo "🔄 Seeding DEV org ${DEV_ORG_ID} from ${DASH_ROOT}"
echo "   Grafana: ${GRAFANA_URL}"
echo "   Seed mode: ${SEED_MODE}"

# Find committed dashboard files before any API writes.
mapfile -t files < <(find "${DASH_ROOT}" -type f -name "*.json" | sort)
if (( ${#files[@]} == 0 )); then
  die "No dashboard JSON files found under ${DASH_ROOT}"
fi

ok=0
fail=0

desired_uids_file="$(mktemp)"
desired_folders_file="$(mktemp)"
trap 'rm -f "$desired_uids_file" "$desired_folders_file" /tmp/seed_dev_api_body.$$' EXIT

# Build desired-state allowlists from repo files. Sync mode uses these to prune
# stale DEV API objects after resolving the current file tree.
for f in "${files[@]}"; do
  dash_uid="$(jq -r '.uid // empty' "$f" || true)"
  [[ -n "$dash_uid" ]] && printf '%s
' "$dash_uid" >> "$desired_uids_file"
  rel="${f#${DASH_ROOT}/}"
  folder="${rel%%/*}"
  if [[ "${folder}" == "${rel}" ]]; then
    folder="General"
  fi
  printf '%s
' "$folder" >> "$desired_folders_file"
done
sort -u -o "$desired_uids_file" "$desired_uids_file"
sort -u -o "$desired_folders_file" "$desired_folders_file"

if [[ "$SEED_MODE" == "sync" ]]; then
  echo "🧹 Sync mode enabled: pruning unmanaged dashboards and folders in DEV org ${DEV_ORG_ID}"
  sync_delete_unmanaged_dashboards "$desired_uids_file"
  sync_delete_unmanaged_folders "$desired_folders_file"
fi

for f in "${files[@]}"; do
  # Folder title = first directory under dashboards-dev.
  rel="${f#${DASH_ROOT}/}"
  folder="${rel%%/*}"
  if [[ "${folder}" == "${rel}" ]]; then
    folder="General"
  fi

  folder_uid="$(ensure_folder "${folder}")"

  # Sanity: must have a uid
  dash_uid="$(jq -r '.uid // empty' "$f" || true)"
  dash_title="$(jq -r '.title // empty' "$f" || true)"

  if [[ -z "${dash_uid}" ]]; then
    echo "❌ SKIP (no dashboard uid): ${f}"
    ((fail++)) || true
    continue
  fi

  if import_dashboard "$f" "$folder_uid"; then
    echo "✅ ${folder} :: ${dash_title} (uid=${dash_uid})"
    ((ok++)) || true
  else
    echo "❌ FAIL importing: ${f}"
    ((fail++)) || true
  fi
done

echo
echo "Done. Imported ok=${ok}, failed=${fail}"
if (( fail > 0 )); then
  exit 2
fi
