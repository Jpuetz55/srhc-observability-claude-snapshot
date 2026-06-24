#!/usr/bin/env bash
set -euo pipefail
# Export editable DEV Grafana dashboards into repo JSON files for review,
# validation, and eventual promotion to the provisioned PROD dashboard tree.

# Stop export with a consistent error message.
die() {
  echo "❌ $*" >&2
  exit 1
}

# Assert that a command required by the exporter exists.
need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing command: $1"
  fi
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -f "$REPO_ROOT/scripts/lib/paths.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/paths.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/paths.sh"
fi
if [[ -f "$REPO_ROOT/scripts/lib/python.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/python.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/python.sh"
fi
if [[ -f "$REPO_ROOT/scripts/lib/grafana_auth.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/grafana_auth.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/grafana_auth.sh"
fi
OUT_DIR="${OUT_DIR:-$OBS_REPO_DASH_DEV_DIR}"

need_cmd curl
need_cmd find
python_check

# Defaults target the local DEV Grafana org; release scripts can override these
# without changing exporter behavior.
: "${GRAFANA_DEV_URL:=http://127.0.0.1:3000}"
: "${GRAFANA_DEV_ORG_ID:=}"
: "${GRAFANA_DEV_TOKEN_FILE:=$OBS_DEV_TOKEN_FILE}"
: "${GRAFANA_PROD_TOKEN_FILE:=$OBS_PROD_TOKEN_FILE}"
: "${GRAFANA_HTTP_CONNECT_TIMEOUT:=3}"
: "${GRAFANA_HTTP_TIMEOUT:=15}"
: "${GRAFANA_HTTP_RETRIES:=2}"
: "${GRAFANA_HTTP_RETRY_DELAY:=1}"
: "${GRAFANA_DEV_ALLOW_ANON:=0}"
: "${EXPORT_KEEP_BACKUP:=1}"
: "${EXPORT_STAGING_PARENT:=}"
: "${EXPORT_FAIL_ON_COUNT_DROP:=0}"

if [[ "$GRAFANA_DEV_ALLOW_ANON" == "1" && ! -r "$GRAFANA_DEV_TOKEN_FILE" ]]; then
  echo "WARN: DEV token file not readable; proceeding without auth header (GRAFANA_DEV_ALLOW_ANON=1)" >&2
  GRAFANA_DEV_TOKEN=""
else
  if ! GRAFANA_DEV_TOKEN="$(obs_read_token_file "$GRAFANA_DEV_TOKEN_FILE")"; then
    if [[ "$GRAFANA_DEV_ALLOW_ANON" == "1" ]]; then
      echo "WARN: DEV token not found; proceeding without auth header (GRAFANA_DEV_ALLOW_ANON=1)" >&2
      GRAFANA_DEV_TOKEN=""
    else
      die "Unable to read DEV token. Expected file: $GRAFANA_DEV_TOKEN_FILE"
    fi
  fi
fi

if [[ -n "${GRAFANA_DEV_TOKEN:-}" ]]; then
  # Normalize token in case it was pasted with CR/LF.
  GRAFANA_DEV_TOKEN="$(printf "%s" "$GRAFANA_DEV_TOKEN" | tr -d '\r\n')"
fi

if [[ -z "${GRAFANA_TOKEN:-}" ]] && [[ -f "$GRAFANA_PROD_TOKEN_FILE" ]]; then
  # Read PROD token for consistency across scripts (not used by this exporter).
  GRAFANA_TOKEN="$(obs_read_token_file "$GRAFANA_PROD_TOKEN_FILE" || true)"
fi

# Safety: never rm -rf something weird
if [[ -z "$OUT_DIR" || "$OUT_DIR" == "/" ]]; then
  die "Refusing to use OUT_DIR='$OUT_DIR'"
fi

echo "[*] Exporting dashboards from DEV: $GRAFANA_DEV_URL -> $OUT_DIR"
echo "[*] Using DEV token file: $GRAFANA_DEV_TOKEN_FILE"

# Validate API responses before later JSON processing so auth/proxy failures
# surface with the response body instead of a downstream parse error.
json_validate_or_die() {
  local label="$1"
  local payload="$2"

  if ! python_cmd -c 'import sys,json; json.loads(sys.stdin.read())' <<<"$payload" >/dev/null 2>&1; then
    echo "---- Response (first 3000 chars) ----" >&2
    echo "${payload:0:3000}" >&2
    echo "------------------------------------" >&2
    die "Grafana API returned invalid JSON for: $label"
  fi
}

# Fetch one Grafana API path with optional org scoping and bounded retries.
grafana_api_get_or_die() {
  local path="$1"
  local use_org_header="${2:-1}"
  local url="${GRAFANA_DEV_URL}${path}"
  local payload status body err_msg
  local -a org_hdr=()
  local -a auth_hdr=()
  local max_attempts attempt

  if [[ -n "${GRAFANA_DEV_TOKEN:-}" ]]; then
    auth_hdr=(-H "Authorization: Bearer $GRAFANA_DEV_TOKEN")
  fi

  if [[ "$use_org_header" == "1" && -n "$GRAFANA_DEV_ORG_ID" ]]; then
    org_hdr=(-H "X-Grafana-Org-Id: $GRAFANA_DEV_ORG_ID")
  fi

  max_attempts=$((GRAFANA_HTTP_RETRIES + 1))
  attempt=1

  while (( attempt <= max_attempts )); do
    if payload="$(
      curl -sS \
        --connect-timeout "$GRAFANA_HTTP_CONNECT_TIMEOUT" \
        --max-time "$GRAFANA_HTTP_TIMEOUT" \
        "${auth_hdr[@]}" \
        "${org_hdr[@]}" \
        -w $'\n%{http_code}' \
        "$url"
    )"; then
      status="${payload##*$'\n'}"
      body="${payload%$'\n'*}"

      if [[ ! "$status" =~ ^[0-9]{3}$ ]]; then
        if (( attempt < max_attempts )); then
          echo "WARN: Invalid HTTP status for $path on attempt $attempt/$max_attempts; retrying..." >&2
          sleep "$GRAFANA_HTTP_RETRY_DELAY"
          attempt=$((attempt + 1))
          continue
        fi
        echo "---- Response (first 3000 chars) ----" >&2
        echo "${body:0:3000}" >&2
        echo "------------------------------------" >&2
        die "Unexpected HTTP status from Grafana for $path: $status"
      fi

      if (( status >= 200 && status < 300 )); then
        printf "%s" "$body"
        return 0
      fi

      # Retry transient server/rate-limit failures.
      if (( (status == 429 || status >= 500) && attempt < max_attempts )); then
        echo "WARN: Grafana API $path returned HTTP $status on attempt $attempt/$max_attempts; retrying..." >&2
        sleep "$GRAFANA_HTTP_RETRY_DELAY"
        attempt=$((attempt + 1))
        continue
      fi

      err_msg="$(
        python_cmd -c '
import json,sys
raw=sys.stdin.read()
try:
    obj=json.loads(raw)
except Exception:
    print(raw[:3000])
    sys.exit(0)
if isinstance(obj, dict):
    print(obj.get("message") or obj.get("error") or str(obj))
else:
    print(str(obj))
' <<<"$body"
      )"
      if [[ "$status" == "401" && "$path" == "/api/search?type=dash-db&limit=5000" && "${AUTH_CHECK_OK:-0}" == "1" ]]; then
        echo "   Token is valid for /api/user, but lacks access to search dashboards in this org." >&2
        echo "   Check Grafana service account role/scope (need dashboard read/search in org ${GRAFANA_DEV_ORG_ID:-unknown})." >&2
        die "Grafana API error for $path (HTTP $status): $err_msg"
      fi
      die "Grafana API error for $path (HTTP $status): $err_msg"
    fi

    if (( attempt < max_attempts )); then
      echo "WARN: curl failed for $path on attempt $attempt/$max_attempts; retrying..." >&2
      sleep "$GRAFANA_HTTP_RETRY_DELAY"
      attempt=$((attempt + 1))
      continue
    fi
    die "curl failed for $path after $max_attempts attempt(s)."
  done

  die "Unexpected internal error while fetching $path"
}

# Service-account tokens may be bound to one org. Prefer that org id when the
# API reports it, avoiding stale caller overrides.
extract_org_id() {
  python_cmd -c '
import json,sys
try:
    obj=json.loads(sys.stdin.read())
except Exception:
    print("")
    raise SystemExit(0)
if isinstance(obj, dict):
    v = obj.get("orgId")
    if isinstance(v, int) or (isinstance(v, str) and v.strip()):
        print(str(v))
        raise SystemExit(0)
print("")
'
}

# Convert stdin to a filesystem slug used for stable dashboard filenames.
slugify() {
  python_cmd -c '
import re,sys
s=sys.stdin.read().strip()
s=re.sub(r"[^A-Za-z0-9]+","-",s).strip("-").lower()
print(s if s else "item")
'
}

# Convert stdin to a safe folder dir name while preserving readable spaces.
safe_folder_name() {
  python_cmd -c '
import re,sys
s=sys.stdin.read().strip() or "General"
s=s.replace("/", "-")
s=re.sub(r"[^\w .-]+", "_", s)
s=s.strip() or "General"
print(s)
'
}

# ----------------------------
# Fetch dashboard list (uid + folder + title)
# ----------------------------
# Auth preflight: validate token and discover org id if unset.
AUTH_CHECK_OK=0
if [[ -n "${GRAFANA_DEV_TOKEN:-}" ]]; then
  user_json="$(grafana_api_get_or_die "/api/user" 0)"
  AUTH_CHECK_OK=1
  token_org_id="$(extract_org_id <<<"$user_json")"
  if [[ -n "$token_org_id" ]]; then
    if [[ -n "$GRAFANA_DEV_ORG_ID" && "$GRAFANA_DEV_ORG_ID" != "$token_org_id" ]]; then
      echo "WARN: DEV org override ($GRAFANA_DEV_ORG_ID) mismatches token org ($token_org_id); using token org." >&2
    fi
    GRAFANA_DEV_ORG_ID="$token_org_id"
  fi
fi
if [[ -n "$GRAFANA_DEV_ORG_ID" ]]; then
  echo "[*] Using DEV org header: $GRAFANA_DEV_ORG_ID"
elif [[ -n "${GRAFANA_DEV_TOKEN:-}" ]]; then
  echo "[*] Using token-bound org (org id not discovered)"
else
  echo "[*] Using anonymous org (no token; org header not set)"
fi

search_json="$(
  grafana_api_get_or_die "/api/search?type=dash-db&limit=5000"
)"
json_validate_or_die "/api/search" "$search_json"

dash_list="$(
  python_cmd -c '
import json,sys
data=json.load(sys.stdin)
if not isinstance(data, list):
    if isinstance(data, dict):
        msg = data.get("message") or data.get("error") or str(data)
    else:
        msg = repr(data)
    print(
        f"❌ /api/search returned {type(data).__name__}, expected array. {msg}",
        file=sys.stderr,
    )
    sys.exit(2)
for idx, d in enumerate(data):
    if not isinstance(d, dict):
        print(
            f"❌ /api/search item {idx} is {type(d).__name__}, expected object",
            file=sys.stderr,
        )
        sys.exit(2)
    uid=d.get("uid")
    if not uid:
        continue
    title=d.get("title") or uid
    folder=d.get("folderTitle") or "General"
    # tab-separated so bash can read safely
    print(f"{uid}\t{folder}\t{title}")
' <<<"$search_json"
)"

if [[ -z "${dash_list//[[:space:]]/}" ]]; then
  echo "WARN: No dashboards returned from Grafana search. Token may lack permissions or wrong org."
  exit 0
fi

# Fresh export after auth/search succeeds.
# Stage into a temp dir and swap into place only when export completes.
previous_count=0
if [[ -d "$OUT_DIR" ]]; then
  previous_count="$(find "$OUT_DIR" -type f -name '*.json' | wc -l | tr -d '[:space:]')"
fi

out_parent="${EXPORT_STAGING_PARENT:-$(dirname "$OUT_DIR")}"
mkdir -p "$out_parent"
out_base="$(basename "$OUT_DIR")"
stage_id="$(date +%Y%m%d-%H%M%S).$$"
STAGING_OUT_DIR="$out_parent/.${out_base}.staging.${stage_id}"
BACKUP_OUT_DIR="$out_parent/.${out_base}.backup.${stage_id}"

# Remove incomplete staging exports on failure. The live output directory is
# swapped only after every dashboard has been fetched and normalized.
cleanup_staging_dir() {
  if [[ -n "${STAGING_OUT_DIR:-}" && -d "${STAGING_OUT_DIR:-}" ]]; then
    rm -rf "${STAGING_OUT_DIR}"
  fi
}
trap cleanup_staging_dir EXIT

mkdir -p "$STAGING_OUT_DIR"

count=0

# ----------------------------
# Export each dashboard
# ----------------------------
while IFS=$'\t' read -r uid folder title; do
  [[ -n "$uid" ]] || continue

  folder_safe="$(printf "%s" "$folder" | safe_folder_name)"
  dir="$STAGING_OUT_DIR/$folder_safe"
  mkdir -p "$dir"

  slug="$(printf "%s" "$title" | slugify)"
  file="$dir/${slug}__${uid}.json"

  raw=""
  if ! raw="$(
    grafana_api_get_or_die "/api/dashboards/uid/$uid"
  )"; then
    echo "WARN: Failed to fetch dashboard UID=$uid (curl error). Skipping."
    continue
  fi

  json_validate_or_die "/api/dashboards/uid/$uid" "$raw"

  echo "  - [$folder_safe] $title ($uid) -> $(basename "$file")"

  # Write ONLY the dashboard model, normalized for Git/provisioning. The API
  # response wrapper contains instance metadata that should not be committed.
  python_cmd -c '
import json,sys
obj=json.load(sys.stdin)
if not isinstance(obj, dict):
    print(f"❌ /api/dashboards/uid returned {type(obj).__name__}, expected object", file=sys.stderr)
    sys.exit(2)
dash=obj.get("dashboard") or {}
if not isinstance(dash, dict) or not dash:
    msg = obj.get("message") or obj.get("error") or "missing dashboard payload"
    print(f"❌ /api/dashboards/uid response missing dashboard object: {msg}", file=sys.stderr)
    sys.exit(2)

def normalize_timing(node):
    if isinstance(node, dict):
        for k, v in list(node.items()):
            if k in ("interval", "minInterval") and isinstance(v, str) and v.strip() == "15s":
                node[k] = "5s"
            elif k == "intervalMs" and v == 15000:
                node[k] = 5000
            else:
                normalize_timing(v)
    elif isinstance(node, list):
        for item in node:
            normalize_timing(item)

dash["id"]=None
dash["version"]=0
dash.pop("iteration", None)
normalize_timing(dash)
print(json.dumps(dash, indent=2, sort_keys=False))
' <<<"$raw" > "$file"

  count=$((count + 1))
done <<<"$dash_list"

if (( count == 0 )); then
  die "Export produced 0 dashboards; leaving existing output unchanged."
fi

if (( previous_count > 0 && count < previous_count )); then
  if [[ "$EXPORT_FAIL_ON_COUNT_DROP" == "1" ]]; then
    echo "       Set EXPORT_FAIL_ON_COUNT_DROP=0 for intentional removals." >&2
    die "Exported dashboard count dropped from $previous_count to $count; refusing to replace existing export."
  fi
  echo "WARN: Exported dashboard count dropped from $previous_count to $count." >&2
fi

backup_kept=0
if [[ -d "$OUT_DIR" ]]; then
  if [[ "$EXPORT_KEEP_BACKUP" == "1" ]]; then
    mv "$OUT_DIR" "$BACKUP_OUT_DIR"
    backup_kept=1
  else
    rm -rf "$OUT_DIR"
  fi
fi

if ! mv "$STAGING_OUT_DIR" "$OUT_DIR"; then
  if (( backup_kept == 1 )) && [[ -d "$BACKUP_OUT_DIR" && ! -d "$OUT_DIR" ]]; then
    mv "$BACKUP_OUT_DIR" "$OUT_DIR" || true
  fi
  die "Failed to promote staged export into $OUT_DIR"
fi
STAGING_OUT_DIR=""

if (( backup_kept == 1 )); then
  echo "[*] Previous export backup kept at: $BACKUP_OUT_DIR"
fi
echo "[*] Done. Exported $count dashboards into: $OUT_DIR"
