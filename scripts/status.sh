#!/usr/bin/env bash
set -euo pipefail
# Read-only status report for DEV Grafana, repo dashboard files, and PROD DB.

# Print command usage for the read-only status modes.
usage() {
  cat <<'EOF'
Usage:
  ./scripts/status.sh [--dev-only | --repo-only | --prod-only] [--verbose]

What it shows (read-only):
  DEV (Grafana API):
    - org name
    - dashboard count
    - folders list + dashboard counts per folder
  REPO (filesystem):
    - dashboards-dev: folder list + json counts
    - dashboards-prod: folder list + json counts
  PROD (Grafana SQLite + runtime):
    - runtime folders on disk (/var/lib/grafana/dashboards-prod)
    - Grafana DB folder objects in dashboard table (is_folder=1)
    - Which DB folders are "stale" (not on disk)
    - Which DB folders are "empty" (no active dashboards referencing them)

Options:
  --dev-only     Only DEV API section
  --repo-only    Only REPO filesystem section
  --prod-only    Only PROD DB/runtime section
  --verbose      Print extra details (UIDs, raw lists)

Optional env:
  GRAFANA_URL      default: http://localhost:3000
  DEV_ORG_ID       default: 2
  DEV_TOKEN_FILE   default: /etc/{observability,onservability}/grafana_token_dev
  PROD_ORG_ID      default: 1

Path defaults (override via scripts/lib/paths.sh env vars):
  Repo dashboards-dev : OBS_REPO_DASH_DEV_DIR
  Repo dashboards-prod: OBS_REPO_DASH_PROD_DIR
  PROD runtime dir    : OBS_RUNTIME_DASH_PROD_DIR
  Grafana DB          : OBS_RUNTIME_GRAFANA_DB

Notes:
  - This script never writes anything.
  - If DEV token file is root-readable only, it uses sudo to read it.
EOF
}

# Return a wall-clock timestamp for log lines.
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
# Print a timestamped status message.
log(){ echo "[$(ts)] $*"; }
# Stop with a consistent error message.
die(){ echo "❌ $*" >&2; exit 1; }

# Assert that a command required by the selected status mode exists.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
# Resolve the git repository root or fail outside a checkout.
repo_root(){ git rev-parse --show-toplevel 2>/dev/null || die "Not in a git repo"; }

# Query the DEV Grafana API using the resolved service-account token.
curl_json_dev() {
  local method="$1" url="$2" data="${3:-}"
  if [[ "$method" == "GET" ]]; then
    curl -sS \
      -H "Authorization: Bearer $GRAFANA_TOKEN_DEV" \
      -H "X-Grafana-Org-Id: $DEV_ORG_ID" \
      "$url"
  else
    curl -sS -X "$method" \
      -H "Authorization: Bearer $GRAFANA_TOKEN_DEV" \
      -H "X-Grafana-Org-Id: $DEV_ORG_ID" \
      -H "Content-Type: application/json" \
      "$url" -d "$data"
  fi
}

# Print a high-visibility section divider.
section() { echo; echo "==================== $* ===================="; }

MODE="all"
VERBOSE=0
mode_flags=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dev-only)
      ((mode_flags+=1))
      MODE="dev"
      shift
      ;;
    --repo-only)
      ((mode_flags+=1))
      MODE="repo"
      shift
      ;;
    --prod-only)
      ((mode_flags+=1))
      MODE="prod"
      shift
      ;;
    --verbose) VERBOSE=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done

if [[ "$mode_flags" -gt 1 ]]; then
  die "Only one of --dev-only, --repo-only, or --prod-only may be set"
fi

need_dev=0
need_repo=0
need_prod=0
case "$MODE" in
  all)
    need_dev=1
    need_repo=1
    need_prod=1
    ;;
  dev)
    need_dev=1
    ;;
  repo)
    need_repo=1
    ;;
  prod)
    need_prod=1
    ;;
esac

need_cmd git
need_cmd find
need_cmd sort
need_cmd wc
need_cmd sed

REPO_ROOT="$(repo_root)"
cd "$REPO_ROOT"
if [[ -f "$REPO_ROOT/scripts/lib/paths.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/paths.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/paths.sh"
fi
if [[ "$need_dev" == "1" ]]; then
  if [[ -f "$REPO_ROOT/scripts/lib/grafana_auth.sh" ]]; then
    source "$REPO_ROOT/scripts/lib/grafana_auth.sh"
  else
    die "Missing required file: $REPO_ROOT/scripts/lib/grafana_auth.sh"
  fi
fi

if [[ "$need_dev" == "1" ]]; then
  need_cmd curl
  need_cmd jq
fi
if [[ "$need_prod" == "1" ]]; then
  need_cmd sqlite3
fi

GRAFANA_URL="${GRAFANA_URL:-http://localhost:3000}"
DEV_ORG_ID="${DEV_ORG_ID:-2}"
DEV_TOKEN_FILE="${DEV_TOKEN_FILE:-${OBS_DEV_TOKEN_FILE:-}}"
PROD_ORG_ID="${PROD_ORG_ID:-1}"

REPO_DEV_DIR="$OBS_REPO_DASH_DEV_DIR"
REPO_PROD_DIR="$OBS_REPO_DASH_PROD_DIR"
RUNTIME_PROD_DIR="$OBS_RUNTIME_DASH_PROD_DIR"
DB="$OBS_RUNTIME_GRAFANA_DB"

log "Repo root     : $REPO_ROOT"
log "GRAFANA_URL   : $GRAFANA_URL"
log "DEV_ORG_ID    : $DEV_ORG_ID"
log "PROD_ORG_ID   : $PROD_ORG_ID"
log "Repo user     : $(id -un)"

# -------- DEV --------
if [[ "$MODE" == "all" || "$MODE" == "dev" ]]; then
  section "DEV (Grafana API)"

  # DEV status uses the API because DEV dashboards are editable Grafana objects.
  GRAFANA_TOKEN_DEV="${GRAFANA_TOKEN_DEV:-}"
  if [[ -z "$GRAFANA_TOKEN_DEV" ]]; then
    GRAFANA_TOKEN_DEV="$(obs_read_token_file "$DEV_TOKEN_FILE" || true)"
  fi
  [[ -n "$GRAFANA_TOKEN_DEV" ]] || die "Unable to read DEV token. Expected file: $DEV_TOKEN_FILE"

  dev_org="$(curl_json_dev GET "$GRAFANA_URL/api/org" | jq -r '.name // empty' || true)"
  [[ -n "$dev_org" ]] || die "DEV token/org invalid. Check DEV_ORG_ID and $DEV_TOKEN_FILE"
  log "DEV org name  : $dev_org"

  search_json="$(curl_json_dev GET "$GRAFANA_URL/api/search?type=dash-db&limit=500")"
  jq -e 'type=="array"' >/dev/null <<<"$search_json" || die "Unexpected DEV /api/search response (not array)."

  dev_count="$(jq 'length' <<<"$search_json")"
  log "DEV dashboards: $dev_count"

  echo
  echo "DEV folders (by folderTitle) -> dashboard count:"
  jq -r '
    map(.folderTitle // "General")
    | group_by(.)
    | map({folder: .[0], count: length})
    | sort_by(.folder)
    | .[]
    | "\(.count)\t\(.folder)"
  ' <<<"$search_json" | sed 's/^/  /'

  if [[ "$VERBOSE" == "1" ]]; then
    echo
    echo "DEV dashboards (uid -> title -> folderTitle):"
    jq -r '.[] | "\(.uid)\t\(.title)\t\(.folderTitle // "General")"' <<<"$search_json" | sed 's/^/  /'
  fi
fi

# -------- REPO --------
if [[ "$MODE" == "all" || "$MODE" == "repo" ]]; then
  section "REPO (filesystem)"

  # Repo status is filesystem-only and shows what is committed/promotable.
  for d in "$REPO_DEV_DIR" "$REPO_PROD_DIR"; do
    [[ -d "$d" ]] || { log "Missing required dir: $d"; continue; }
    label="$(basename "$d")"
    log "$label path: $d"

    total_json="$(find "$d" -type f -name '*.json' | wc -l | tr -d ' ')"
    log "$label json files: $total_json"

    echo
    echo "$label folders (top-level) -> json count:"
    while IFS= read -r folder; do
      c="$(find "$d/$folder" -type f -name '*.json' 2>/dev/null | wc -l | tr -d ' ')"
      printf "  %s\t%s\n" "$c" "$folder"
    done < <(find "$d" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort)

    if [[ "$VERBOSE" == "1" ]]; then
      echo
      echo "$label dashboard uids (filenames) by folder:"
      find "$d" -mindepth 2 -maxdepth 2 -type f -name '*.json' -printf "%h/%f\n" \
        | sed "s|^$d/||" \
        | sort \
        | sed 's/^/  /'
    fi

    echo
  done
fi

# -------- PROD (runtime + DB) --------
if [[ "$MODE" == "all" || "$MODE" == "prod" ]]; then
  section "PROD (runtime + Grafana DB)"

  # PROD status reads provisioned files plus Grafana SQLite metadata. It does
  # not mutate the DB.
  if [[ ! -d "$RUNTIME_PROD_DIR" ]]; then
    log "Runtime PROD dir missing: $RUNTIME_PROD_DIR"
  else
    log "Runtime PROD dir: $RUNTIME_PROD_DIR"
    echo
    echo "Runtime folders on disk (top-level):"
    find "$RUNTIME_PROD_DIR" -mindepth 1 -maxdepth 1 -type d -printf "  %f\n" | sort
  fi

  sudo test -f "$DB" || die "Grafana DB not found: $DB"
  log "Grafana DB     : $DB"

  echo
  echo "DB folder objects (dashboard table, is_folder=1, deleted IS NULL, org_id=$PROD_ORG_ID):"
  sudo sqlite3 "$DB" "
SELECT id, uid, title
FROM dashboard
WHERE org_id=$PROD_ORG_ID AND is_folder=1 AND deleted IS NULL
ORDER BY lower(title);
" | sed 's/^/  /'

  echo
  echo "DB folders that are STALE (present in DB, not present on disk):"

  # Build insert statements for disk folder titles (escaped)
  disk_inserts="$(
    { echo "INSERT OR IGNORE INTO tmp_disk_titles(title) VALUES ('General');";
      if [[ -d "$RUNTIME_PROD_DIR" ]]; then
        find "$RUNTIME_PROD_DIR" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | while read -r f; do
          esc="$(printf "%s" "$f" | sed "s/'/''/g")"
          echo "INSERT OR IGNORE INTO tmp_disk_titles(title) VALUES ('$esc');"
        done
      fi
    } )"

  # One sqlite session so TEMP table persists
  sudo sqlite3 "$DB" <<SQL | sed 's/^/  /'
DROP TABLE IF EXISTS tmp_disk_titles;
CREATE TEMP TABLE tmp_disk_titles (title TEXT PRIMARY KEY);
${disk_inserts}

SELECT d.id, d.uid, d.title
FROM dashboard d
WHERE d.org_id=$PROD_ORG_ID
  AND d.is_folder=1
  AND d.deleted IS NULL
  AND d.title NOT IN (SELECT title FROM tmp_disk_titles)
ORDER BY lower(d.title);
SQL

  echo
  echo "DB folders that are EMPTY (no active dashboards referencing them by folder_uid):"
  sudo sqlite3 "$DB" "
SELECT d.id, d.uid, d.title
FROM dashboard d
WHERE d.org_id=$PROD_ORG_ID
  AND d.is_folder=1
  AND d.deleted IS NULL
  AND NOT EXISTS (
    SELECT 1
    FROM dashboard x
    WHERE x.org_id=$PROD_ORG_ID
      AND x.deleted IS NULL
      AND x.is_folder=0
      AND x.folder_uid = d.uid
  )
ORDER BY lower(d.title);
" | sed 's/^/  /'

  if [[ "$VERBOSE" == "1" ]]; then
    echo
    echo "Active dashboards in PROD DB by folder_uid (folder uid -> count):"
    sudo sqlite3 "$DB" "
SELECT folder_uid, COUNT(*) AS active_dashboards
FROM dashboard
WHERE org_id=$PROD_ORG_ID AND deleted IS NULL AND is_folder=0
GROUP BY folder_uid
ORDER BY active_dashboards DESC;
" | sed 's/^/  /'
  fi
fi

section "Done"
