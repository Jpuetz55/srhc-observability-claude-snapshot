#!/usr/bin/env bash
set -euo pipefail
# Deploy-only workflow.
# Flow: repo -> PROD (files only).
# No DEV access. No Git mutations.
# Manual-only (no automation assumed).

# Print deploy-only workflow usage and safety options.
usage() {
  cat <<'EOF'
Usage:
  ./scripts/promote_repo_to_prod.sh [--dry-run] [--skip-folder-cleanup] [--local-vm] [--allow-dirty]

Behavior:
  - Preflight checks
  - Require CLEAN git tree (unless dry-run)
  - Sync local Mimir config/unit -> /etc/mimir + systemd and ensure Mimir is running
  - Sync Prometheus config/rules repo -> /etc/prometheus + reload (only if changed)
  - (optional) Sync Telegraf repo -> /etc/telegraf + restart (only if telegraf/ exists; only if changed)
  - Sync Grafana dashboards repo -> /var/lib/grafana/dashboards-prod (only if changed)
  - Sync Grafana dashboard provisioning -> /etc/grafana/provisioning/dashboards (if present)
  - Sync Grafana datasource provisioning -> /etc/grafana/provisioning/datasources (if present)
  - Sync Grafana alerting provisioning -> /etc/grafana/provisioning/alerting (if present)
  - Sync Grafana systemd drop-ins -> /etc/systemd/system/grafana-server.service.d (if present)
  - Stop grafana-server (only if dashboards changed OR folder cleanup enabled)
  - (default) Delete stale EMPTY PROD folders from grafana.db (dashboard.is_folder=1) not present on disk
  - Start grafana-server (only if stopped)
  - Alloy (if alloy/ exists in repo):
      - Deploy prod config -> /etc/alloy/config.alloy + validate (does NOT restart prod by default)
      - Deploy canary config -> /etc/alloy/config-canary.alloy + validate
      - Deploy canary unit  -> /etc/systemd/system/alloy-canary.service + daemon-reload
      - Enable/start/restart alloy-canary if changed

Options:
  --dry-run              Print actions; no writes (assumes changes for restart/reload messaging)
  --skip-folder-cleanup  Debug: do NOT touch grafana.db folder cleanup
  --local-vm             Run preflight in local VM mode (skip ansible/k8s-only gates)
  --allow-dirty          Allow promote from a dirty git tree (recommended only for local-vm workflow)

Optional env:
  PROM_URL             default: http://localhost:9090 (Prometheus base URL)
  MIMIR_URL            default: http://127.0.0.1:9009 (Mimir base URL)
  GRAFANA_URL          default: http://127.0.0.1:3000
  PROD_ORG_ID          default: 1
  NO_PROMOTE=1         Skip promotion step entirely
  ALLOY_RESTART_PROD=1 If set, restart 'alloy' (prod) when /etc/alloy/config.alloy changes
  INSTALL_WIRELESS_RF_TEXTFILE=1 Auto-install wireless-rf-textfile systemd unit/timer during deploy when installer script exists
  INSTALL_WIRELESS_RF_HOURLY=1   Auto-install wireless-rf-hourly systemd unit/timer during deploy when installer script exists
  INSTALL_WIRELESS_BADGE_HOURLY=1 Auto-install wireless-badge-hourly systemd unit/timer during deploy when installer script exists
  INSTALL_VOCERA_MEDIA_QOE_TEXTFILE=1 Auto-install Vocera media PCAP QoE systemd unit/timer during deploy when installer script exists
  PROMOTE_LOCK_FILE    default: /tmp/grafana-dev-promote.lock
  PROMOTE_DISABLE_LOCK=1  Disable promote lock (not recommended)
  OBS_* path overrides (see scripts/lib/paths.sh)

Runtime path defaults:
  PROD dashboards runtime: OBS_RUNTIME_DASH_PROD_DIR
  Grafana DB            : OBS_RUNTIME_GRAFANA_DB
  Telegraf runtime      : OBS_RUNTIME_TELEGRAF_DIR
  Alloy runtime         : OBS_RUNTIME_ALLOY_DIR
EOF
}

# Return a wall-clock timestamp for promotion logs.
ts(){ date +"%Y-%m-%d %H:%M:%S"; }
# Print a timestamped promotion log line.
log(){ echo "[$(ts)] $*"; }
# Stop promotion with a consistent error message.
die(){ echo "❌ $*" >&2; exit 1; }

# Assert that a command needed by promotion is available.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
# Resolve the git repository root or fail outside a checkout.
repo_root(){ git rev-parse --show-toplevel 2>/dev/null || die "Not in a git repo"; }

DRY_RUN=0
SKIP_FOLDER_CLEANUP=0
LOCAL_VM_MODE=0
ALLOW_DIRTY=0
NO_PROMOTE="${NO_PROMOTE:-0}"
ALLOY_RESTART_PROD="${ALLOY_RESTART_PROD:-0}"
INSTALL_WIRELESS_RF_TEXTFILE="${INSTALL_WIRELESS_RF_TEXTFILE:-1}"
INSTALL_WIRELESS_RF_HOURLY="${INSTALL_WIRELESS_RF_HOURLY:-1}"
INSTALL_WIRELESS_BADGE_HOURLY="${INSTALL_WIRELESS_BADGE_HOURLY:-1}"
INSTALL_VOCERA_MEDIA_QOE_TEXTFILE="${INSTALL_VOCERA_MEDIA_QOE_TEXTFILE:-1}"
PROMOTE_LOCK_FILE="${PROMOTE_LOCK_FILE:-/tmp/grafana-dev-promote.lock}"
PROMOTE_DISABLE_LOCK="${PROMOTE_DISABLE_LOCK:-0}"

# Execute a command or log the exact argv in dry-run mode.
run_cmd() {
  local rendered=""
  printf -v rendered '%q ' "$@"
  rendered="${rendered% }"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] $rendered"
    return 0
  fi
  "$@"
}
# Centralize sudo usage so dry-run output shows privileged operations without
# touching the host.
sudo_cmd() {
  local rendered=""
  printf -v rendered '%q ' "$@"
  rendered="${rendered% }"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo $rendered"
    return 0
  fi
  sudo "$@"
}

# Return success when the repository has no tracked or untracked changes.
git_is_clean(){ [[ -z "$(git status --porcelain)" ]]; }
# Enforce a clean worktree before mutating production runtime files.
require_clean_git_tree(){
  if ! git_is_clean; then
    git status --porcelain >&2 || true
    die "Git tree is not clean. Commit/stash before promote."
  fi
}

# Promotion mutates service config and Grafana DB state, so serialize it
# across shells.
acquire_promote_lock() {
  local lock_file="$1"
  exec 9>"$lock_file" || die "Unable to open promote lock file: $lock_file"
  if ! flock -n 9; then
    die "Another promote is already running (lock: $lock_file)"
  fi
}

# ---------- rsync helpers (detect changes) ----------

# Return 0 if NO changes, 1 if CHANGES occurred.
# For dry-run we return CHANGES (1) so downstream steps show intended restarts/reloads.
# Sync a directory and return 1 when rsync itemization reports changes.
rsync_changed_dir() {
  local src="$1" dst="$2" out
  out="$(mktemp)"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo rsync -a --delete --itemize-changes '$src' '$dst'"
    rm -f "$out"
    return 1
  fi

  if ! sudo rsync -a --delete --itemize-changes "$src" "$dst" | tee "$out" >/dev/null; then
    rm -f "$out"
    die "rsync failed while syncing directory: $src -> $dst"
  fi
  if [[ -s "$out" ]]; then
    rm -f "$out"
    return 1
  fi

  rm -f "$out"
  return 0
}

# Return 0 if NO changes, 1 if CHANGES occurred.
# Sync a single file and return 1 when rsync itemization reports changes.
rsync_changed_file() {
  local src="$1" dst="$2" out
  out="$(mktemp)"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo rsync -a --itemize-changes '$src' '$dst'"
    rm -f "$out"
    return 1
  fi

  if ! sudo rsync -a --itemize-changes "$src" "$dst" | tee "$out" >/dev/null; then
    rm -f "$out"
    die "rsync failed while syncing file: $src -> $dst"
  fi
  if [[ -s "$out" ]]; then
    rm -f "$out"
    return 1
  fi

  rm -f "$out"
  return 0
}

# Restart and verify a systemd unit only when its inputs changed.
restart_if_changed() {
  local changed="$1" unit="$2"
  if [[ "$DRY_RUN" != "1" ]]; then
    need_cmd systemctl
  fi
  if [[ "$changed" == "1" ]]; then
    sudo_cmd systemctl restart "$unit"
    sudo_cmd systemctl is-active --quiet "$unit"
    if [[ "$DRY_RUN" == "1" ]]; then
      log "✅ [dry-run] restart simulated: $unit"
    else
      log "✅ Restarted: $unit"
    fi
  else
    log "$unit unchanged; no restart"
  fi
}

# Provisioned files must be readable by the grafana user after rsync and
# after any operator-created directories.
ensure_grafana_provisioning_readable() {
  local root="$1"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] would ensure Grafana can read provisioning root: $root"
    return 0
  fi
  sudo_cmd install -d -o grafana -g grafana -m 0750 "$root"
  sudo_cmd chown -R grafana:grafana "$root"
  sudo_cmd chmod -R u=rwX,g=rX,o= "$root"
}

# Poll a local HTTP health endpoint until it is ready or promotion fails.
wait_http_ready() {
  local url="$1" name="$2" i
  if [[ "$DRY_RUN" == "1" ]]; then
    log "✅ [dry-run] $name readiness check simulated: $url"
    return 0
  fi
  # Give local single-binary services (notably Mimir after WAL/head replay)
  # enough time to come up on slower hosts before failing promotion.
  for i in {1..90}; do
    if curl -fsS "$url" >/dev/null 2>&1; then
      log "✅ $name ready: $url"
      return 0
    fi
    sleep 1
  done
  die "$name did not become ready: $url"
}

# Reject common Prometheus/Mimir URL mixups before runtime checks run.
validate_service_urls() {
  case "$PROM_URL" in
    */prometheus|*/prometheus/*)
      die "PROM_URL must point at Prometheus itself, for example http://127.0.0.1:9090. It currently points at Mimir's /prometheus API path: $PROM_URL"
      ;;
  esac
  case "$MIMIR_URL" in
    */prometheus|*/prometheus/*)
      die "MIMIR_URL must point at Mimir's base URL, for example http://127.0.0.1:9009. Do not include /prometheus: $MIMIR_URL"
      ;;
  esac
}

# Validate every repo rule file before copying runtime Prometheus config.
check_repo_prometheus_rules() {
  local rules_dir="$1"
  local -a rule_files=()
  mapfile -t rule_files < <(find "$rules_dir" -type f -name '*.yml' | sort)
  [[ "${#rule_files[@]}" -gt 0 ]] || die "No Prometheus rule files found under: $rules_dir"
  promtool check rules "${rule_files[@]}" >/dev/null
}

# Build the folder title allowlist used to prune stale empty Grafana folders.
build_allowed_folders_file() {
  local runtime_dir="$1"
  local out="$2"
  : > "$out"
  printf "General\n" >> "$out"
  if [[ -d "$runtime_dir" ]]; then
    find "$runtime_dir" -mindepth 1 -maxdepth 1 -type d -printf "%f\n" | sort >> "$out"
  elif [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] WARN: runtime dir missing for folder allowlist build: $runtime_dir"
  else
    die "Runtime dir missing for folder allowlist build: $runtime_dir"
  fi
}

# Delete only stale folder rows that are empty; non-empty folders are left in
# place even when their title is not on disk.
cleanup_prod_stale_empty_folders() {
  local allowlist_file="$1"
  local db="${OBS_RUNTIME_GRAFANA_DB:-/var/lib/grafana/grafana.db}"

  if [[ "$DRY_RUN" == "1" ]]; then
    if [[ ! -f "$db" ]]; then
      log "[dry-run] WARN: Grafana DB not found at $db (required for non-dry folder cleanup)"
    fi
  else
    sudo test -f "$db" || die "Grafana DB not found: $db"
  fi
  [[ -f "$allowlist_file" ]] || die "Allowlist file missing: $allowlist_file"

  log "Cleaning Grafana DB: removing stale EMPTY PROD folders (dashboard.is_folder=1) not present on disk (org_id=$PROD_ORG_ID)"

  local backup="/var/lib/grafana/grafana.db.bak.$(date +%Y%m%d-%H%M%S)"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] would back up DB: $db -> $backup"
  else
    sudo cp -a "$db" "$backup"
    log "DB backup created: $backup"
  fi

  local sql; sql="$(mktemp)"
  {
    echo "BEGIN TRANSACTION;"
    echo "DROP TABLE IF EXISTS tmp_allowed_titles;"
    echo "CREATE TEMP TABLE tmp_allowed_titles (title TEXT PRIMARY KEY);"

    while IFS= read -r t; do
      t="${t//$'\r'/}"
      [[ -n "$t" ]] || continue
      esc="$(printf "%s" "$t" | sed "s/'/''/g")"
      echo "INSERT OR IGNORE INTO tmp_allowed_titles(title) VALUES ('$esc');"
    done < "$allowlist_file"

    cat <<SQL
DELETE FROM dashboard
WHERE org_id = $PROD_ORG_ID
  AND is_folder = 1
  AND deleted IS NULL
  AND title NOT IN (SELECT title FROM tmp_allowed_titles)
  AND NOT EXISTS (
    SELECT 1
    FROM dashboard d2
    WHERE d2.org_id = $PROD_ORG_ID
      AND d2.deleted IS NULL
      AND d2.is_folder = 0
      AND d2.folder_uid = dashboard.uid
  );
SQL
    echo "COMMIT;"
  } >"$sql"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "DRY-RUN: would execute folder cleanup SQL:"
    sed 's/^/  /' "$sql"
  else
    sudo sqlite3 "$db" <"$sql"
    log "✅ Stale EMPTY PROD folders removed from Grafana DB (dashboard table)"
  fi

  rm -f "$sql"
}

# Grafana provisioning cannot always overwrite existing DB-managed
# datasources cleanly, so remove known repo-managed rows just before startup.
cleanup_grafana_managed_datasources() {
  local db="${OBS_RUNTIME_GRAFANA_DB:-/var/lib/grafana/grafana.db}"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] would remove repo-managed datasource rows from Grafana DB before provisioning"
    return 0
  fi

  sudo test -f "$db" || die "Grafana DB not found: $db"
  log "Cleaning Grafana DB: removing repo-managed datasource rows before provisioning (org_id=$PROD_ORG_ID)"

  local backup="/var/lib/grafana/grafana.db.bak.$(date +%Y%m%d-%H%M%S).datasources"
  sudo cp -a "$db" "$backup"
  log "DB backup created: $backup"

  local sql; sql="$(mktemp)"
  cat >"$sql" <<SQL
BEGIN TRANSACTION;
DELETE FROM data_source
WHERE org_id = $PROD_ORG_ID
  AND (
    uid IN ('efbjrspdsbl6oa', 'loki_dev', 'TOPOLOGY_DS', 'VOCERA_MEDIA_QOE_DS')
    OR name IN ('Mimir', 'Loki', 'Topology PostgreSQL', 'Vocera Media QoE PostgreSQL')
  );
SELECT 'deleted_datasource_rows=' || changes();
COMMIT;
SQL

  sudo sqlite3 "$db" <"$sql"
  log "✅ Repo-managed datasource rows removed from Grafana DB"
  rm -f "$sql"
}

# Build the dashboard UID allowlist from committed JSON before pruning PROD.
build_allowed_dashboard_uids_file() {
  local dashboards_dir="$1"
  local out="$2"
  python3 - "$dashboards_dir" "$out" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
uids = []
for path in sorted(root.rglob("*.json")):
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    uid = data.get("uid")
    if isinstance(uid, str) and uid.strip():
        uids.append(uid.strip())
out.write_text("\n".join(uids) + ("\n" if uids else ""), encoding="utf-8")
PY
}

# Keep PROD Grafana DB aligned with repo-managed dashboard UIDs.
cleanup_prod_unmanaged_dashboards() {
  local allowlist_file="$1"
  local db="${OBS_RUNTIME_GRAFANA_DB:-/var/lib/grafana/grafana.db}"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] would remove non-repo dashboards from Grafana DB"
    return 0
  fi

  sudo test -f "$db" || die "Grafana DB not found: $db"
  [[ -s "$allowlist_file" ]] || die "Dashboard UID allowlist is empty: $allowlist_file"
  log "Cleaning Grafana DB: removing non-repo dashboards (org_id=$PROD_ORG_ID)"

  local backup="/var/lib/grafana/grafana.db.bak.$(date +%Y%m%d-%H%M%S).dashboards"
  sudo cp -a "$db" "$backup"
  log "DB backup created: $backup"

  local sql; sql="$(mktemp)"
  {
    echo "BEGIN TRANSACTION;"
    echo "DROP TABLE IF EXISTS tmp_allowed_dashboard_uids;"
    echo "CREATE TEMP TABLE tmp_allowed_dashboard_uids (uid TEXT PRIMARY KEY);"

    while IFS= read -r uid; do
      uid="${uid//$'\r'/}"
      [[ -n "$uid" ]] || continue
      esc="$(printf "%s" "$uid" | sed "s/'/''/g")"
      echo "INSERT OR IGNORE INTO tmp_allowed_dashboard_uids(uid) VALUES ('$esc');"
    done < "$allowlist_file"

    cat <<SQL
DELETE FROM dashboard
WHERE org_id = $PROD_ORG_ID
  AND is_folder = 0
  AND deleted IS NULL
  AND uid NOT IN (SELECT uid FROM tmp_allowed_dashboard_uids);
SELECT 'deleted_dashboard_rows=' || changes();
DELETE FROM dashboard_provisioning
WHERE dashboard_id NOT IN (SELECT id FROM dashboard);
COMMIT;
SQL
  } >"$sql"

  sudo sqlite3 "$db" <"$sql"
  log "✅ Non-repo dashboards removed from Grafana DB"
  rm -f "$sql"
}

# -------- args --------
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift;;
    --skip-folder-cleanup) SKIP_FOLDER_CLEANUP=1; shift;;
    --local-vm) LOCAL_VM_MODE=1; shift;;
    --allow-dirty) ALLOW_DIRTY=1; shift;;
    -h|--help) usage; exit 0;;
    *) die "Unknown arg: $1";;
  esac
done

if [[ "$EUID" -eq 0 && "$DRY_RUN" != "1" ]]; then
  die "Do not run as root. Run as appsadmin; sudo is used only for runtime steps."
fi

need_cmd git
if [[ "$DRY_RUN" != "1" ]]; then
  need_cmd rsync
  need_cmd curl
  need_cmd sed
  need_cmd find
  need_cmd python3
  need_cmd sqlite3
else
  # In dry-run mode, folder cleanup still builds/escapes SQL unless explicitly skipped.
  # find is only needed if runtime dashboard dir exists (otherwise allowlist logs a warning).
  if [[ "$SKIP_FOLDER_CLEANUP" != "1" ]]; then
    need_cmd sed
    if [[ -d "${OBS_RUNTIME_DASH_PROD_DIR:-/var/lib/grafana/dashboards-prod}" ]]; then
      need_cmd find
    fi
  fi
fi

if [[ "$DRY_RUN" != "1" && "$PROMOTE_DISABLE_LOCK" != "1" ]]; then
  need_cmd flock
fi

REPO_ROOT="$(repo_root)"
cd "$REPO_ROOT"
if [[ -f "$REPO_ROOT/scripts/lib/paths.sh" ]]; then
  source "$REPO_ROOT/scripts/lib/paths.sh"
else
  die "Missing required file: $REPO_ROOT/scripts/lib/paths.sh"
fi

PROM_URL="${PROM_URL:-http://localhost:9090}"
MIMIR_URL="${MIMIR_URL:-http://127.0.0.1:9009}"
GRAFANA_URL="${GRAFANA_URL:-http://127.0.0.1:3000}"
PROD_ORG_ID="${PROD_ORG_ID:-1}"
PROM_URL="${PROM_URL%/}"
MIMIR_URL="${MIMIR_URL%/}"
GRAFANA_URL="${GRAFANA_URL%/}"

MIMIR_REPO_DIR="$OBS_REPO_MIMIR_DIR"
MIMIR_REPO_CONFIG="$OBS_REPO_MIMIR_CONFIG"
MIMIR_REPO_UNIT="$OBS_REPO_MIMIR_UNIT"
MIMIR_RUNTIME_CONFIG_DIR="$OBS_RUNTIME_MIMIR_CONFIG_DIR"
MIMIR_RUNTIME_CONFIG="$OBS_RUNTIME_MIMIR_CONFIG"
MIMIR_RUNTIME_UNIT="$OBS_RUNTIME_MIMIR_UNIT"
MIMIR_RUNTIME_DATA_DIR="$OBS_RUNTIME_MIMIR_DATA_DIR"
MIMIR_RUNTIME_USER="$OBS_RUNTIME_MIMIR_USER"
MIMIR_RUNTIME_GROUP="$OBS_RUNTIME_MIMIR_GROUP"

PROM_SYSTEMD_REPO_DIR="$OBS_REPO_PROM_SYSTEMD_DIR"
PROM_SYSTEMD_RUNTIME_DIR="$OBS_RUNTIME_PROM_SYSTEMD_DIR"
PROM_CONFIG_REPO="$OBS_REPO_PROM_CONFIG"
PROM_CONFIG_RUNTIME="$OBS_RUNTIME_PROM_CONFIG"
RULES_REPO_DIR="$OBS_REPO_RULES_DIR"
RULES_RUNTIME_DIR="$OBS_RUNTIME_PROM_RULES_DIR"

REPO_PROD_DIR="$OBS_REPO_DASH_PROD_DIR"
RUNTIME_PROD_DIR="$OBS_RUNTIME_DASH_PROD_DIR"
REPO_GRAFANA_DASHBOARDS_PROVISIONING_DIR="$OBS_REPO_GRAFANA_DASHBOARDS_PROVISIONING_DIR"
RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR="$OBS_RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR"
REPO_GRAFANA_DATASOURCES_DIR="$OBS_REPO_GRAFANA_DATASOURCES_DIR"
RUNTIME_GRAFANA_PROVISIONING_DIR="$OBS_RUNTIME_GRAFANA_PROVISIONING_DIR"
RUNTIME_GRAFANA_DATASOURCES_DIR="$OBS_RUNTIME_GRAFANA_DATASOURCES_DIR"
REPO_GRAFANA_SYSTEMD_DIR="$OBS_REPO_GRAFANA_SYSTEMD_DIR"
RUNTIME_GRAFANA_SYSTEMD_DIR="$OBS_RUNTIME_GRAFANA_SYSTEMD_DIR"
REPO_GRAFANA_ALERTING_DIR="${OBS_REPO_GRAFANA_ALERTING_DIR:-$REPO_ROOT/grafana/provisioning/alerting}"
RUNTIME_GRAFANA_ALERTING_DIR="${OBS_RUNTIME_GRAFANA_ALERTING_DIR:-$RUNTIME_GRAFANA_PROVISIONING_DIR/alerting}"

# Telegraf (optional: only if repo has telegraf/)
TELEGRAF_REPO_DIR="$OBS_REPO_TELEGRAF_DIR"
TELEGRAF_RUNTIME_DIR="$OBS_RUNTIME_TELEGRAF_DIR"
TELEGRAF_RUNTIME_MAIN="$OBS_RUNTIME_TELEGRAF_MAIN"
TELEGRAF_RUNTIME_D="$OBS_RUNTIME_TELEGRAF_D"

# Alloy (optional: only if repo has alloy/)
ALLOY_REPO_DIR="$OBS_REPO_ALLOY_DIR"
ALLOY_REPO_PROD_CFG="$OBS_REPO_ALLOY_PROD_CFG"
ALLOY_REPO_CANARY_CFG="$OBS_REPO_ALLOY_CANARY_CFG"
ALLOY_REPO_CANARY_UNIT="$OBS_REPO_ALLOY_CANARY_UNIT"

ALLOY_RUNTIME_DIR="$OBS_RUNTIME_ALLOY_DIR"
ALLOY_RUNTIME_PROD_CFG="$OBS_RUNTIME_ALLOY_PROD_CFG"
ALLOY_RUNTIME_CANARY_CFG="$OBS_RUNTIME_ALLOY_CANARY_CFG"
ALLOY_RUNTIME_CANARY_UNIT="$OBS_RUNTIME_ALLOY_CANARY_UNIT"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

log "PROM URL             : $PROM_URL"
log "Mimir URL            : $MIMIR_URL"
log "Grafana URL          : $GRAFANA_URL"
log "PROD org ID          : $PROD_ORG_ID"
log "Mimir repo dir       : $MIMIR_REPO_DIR"
log "Mimir data dir       : $MIMIR_RUNTIME_DATA_DIR"
log "Prom systemd dir     : $PROM_SYSTEMD_REPO_DIR"
log "Repo PROD dir        : $REPO_PROD_DIR"
log "Runtime PROD dir     : $RUNTIME_PROD_DIR"
log "Grafana provisioning : $RUNTIME_GRAFANA_PROVISIONING_DIR"
log "Grafana dashboards   : $REPO_GRAFANA_DASHBOARDS_PROVISIONING_DIR"
log "Grafana datasources  : $REPO_GRAFANA_DATASOURCES_DIR"
log "Grafana systemd dir  : $REPO_GRAFANA_SYSTEMD_DIR"
log "Grafana alerting dir : $REPO_GRAFANA_ALERTING_DIR"
log "Telegraf repo dir    : $TELEGRAF_REPO_DIR"
log "Alloy repo dir       : $ALLOY_REPO_DIR"
log "DRY_RUN              : $DRY_RUN"
log "SKIP_FOLDER_CLEANUP  : $SKIP_FOLDER_CLEANUP"
log "LOCAL_VM_MODE        : $LOCAL_VM_MODE"
log "ALLOW_DIRTY          : $ALLOW_DIRTY"
log "NO_PROMOTE           : $NO_PROMOTE"
log "ALLOY_RESTART_PROD   : $ALLOY_RESTART_PROD"
log "PROMOTE_LOCK_FILE    : $PROMOTE_LOCK_FILE"
log "PROMOTE_DISABLE_LOCK : $PROMOTE_DISABLE_LOCK"
log "Repo user            : $(id -un)"

validate_service_urls

if [[ "$DRY_RUN" == "1" ]]; then
  log "[dry-run] skipping promote lock acquisition"
elif [[ "$PROMOTE_DISABLE_LOCK" != "1" ]]; then
  acquire_promote_lock "$PROMOTE_LOCK_FILE"
  log "Acquired promote lock: $PROMOTE_LOCK_FILE"
else
  log "Promote lock disabled by PROMOTE_DISABLE_LOCK=1"
fi

log "Preflight checks"
[[ -f "$REPO_ROOT/scripts/preflight.sh" ]] || die "Missing required file: $REPO_ROOT/scripts/preflight.sh"
preflight_env=()
if [[ "$LOCAL_VM_MODE" == "1" ]]; then
  preflight_env+=("SKIP_ANSIBLE_VM_STRATEGY_CHECKS=1" "SKIP_K8S_GATES=1")
fi
run_cmd env "${preflight_env[@]}" bash "$REPO_ROOT/scripts/preflight.sh"
if [[ "$DRY_RUN" == "1" ]]; then
  log "✅ [dry-run] Preflight execution simulated"
else
  log "✅ Preflight passed"
fi

if [[ "$NO_PROMOTE" == "1" ]]; then
  log "NO_PROMOTE=1 set; skipping promotion."
  exit 0
fi

log "Require clean git tree before promote"
if [[ "$DRY_RUN" != "1" && "$ALLOW_DIRTY" != "1" ]]; then
  require_clean_git_tree
elif [[ "$DRY_RUN" != "1" && "$ALLOW_DIRTY" == "1" ]]; then
  log "ALLOW_DIRTY=1; skipping clean-tree enforcement"
else
  log "[dry-run] skipping clean-tree enforcement"
fi

# -------------------- Mimir local VM --------------------
if [[ -d "$MIMIR_REPO_DIR" ]]; then
  log "Promoting local Mimir config"
  [[ -f "$MIMIR_REPO_CONFIG" ]] || die "Mimir repo config missing: $MIMIR_REPO_CONFIG"
  [[ -f "$MIMIR_REPO_UNIT" ]] || die "Mimir systemd unit missing: $MIMIR_REPO_UNIT"

  if [[ "$DRY_RUN" != "1" ]]; then
    need_cmd systemctl
    need_cmd curl
    [[ -x /usr/local/bin/mimir ]] || die "Missing /usr/local/bin/mimir. Run: sudo bash ./scripts/install_mimir_local_vm.sh"
    getent passwd "$MIMIR_RUNTIME_USER" >/dev/null || die "Missing $MIMIR_RUNTIME_USER user. Install/start Prometheus first."
  fi

  sudo_cmd install -d -o root -g root -m 0755 "$MIMIR_RUNTIME_CONFIG_DIR"
  sudo_cmd install -d -o "$MIMIR_RUNTIME_USER" -g "$MIMIR_RUNTIME_GROUP" -m 0750 "$MIMIR_RUNTIME_DATA_DIR"
  sudo_cmd install -d -o root -g root -m 0755 "$(dirname "$MIMIR_RUNTIME_UNIT")"

  mimir_config_changed=0
  mimir_unit_changed=0
  if rsync_changed_file "$MIMIR_REPO_CONFIG" "$MIMIR_RUNTIME_CONFIG"; then
    : # no change
  else
    mimir_config_changed=1
  fi
  if rsync_changed_file "$MIMIR_REPO_UNIT" "$MIMIR_RUNTIME_UNIT"; then
    : # no change
  else
    mimir_unit_changed=1
  fi
  sudo_cmd chown root:root "$MIMIR_RUNTIME_CONFIG" "$MIMIR_RUNTIME_UNIT"
  sudo_cmd chmod 0644 "$MIMIR_RUNTIME_CONFIG" "$MIMIR_RUNTIME_UNIT"

  if [[ "$DRY_RUN" == "1" || "$mimir_unit_changed" == "1" ]]; then
    sudo_cmd systemctl daemon-reload
  fi
  if [[ "$DRY_RUN" != "1" ]]; then
    sudo_cmd systemctl reset-failed mimir
  fi
  sudo_cmd systemctl enable --now mimir
  if [[ "$DRY_RUN" == "1" || "$mimir_config_changed" == "1" || "$mimir_unit_changed" == "1" ]]; then
    sudo_cmd systemctl restart mimir
  fi
  sudo_cmd systemctl is-active --quiet mimir
  wait_http_ready "$MIMIR_URL/ready" "Mimir"
else
  log "Mimir repo dir not present; skipping local Mimir deploy"
fi

# -------------------- Prometheus config and rules --------------------
log "Promoting Prometheus config and rules"
[[ -f "$PROM_CONFIG_REPO" ]] || die "Repo Prometheus config missing: $PROM_CONFIG_REPO"
[[ -d "$RULES_REPO_DIR" ]] || die "Repo rules dir missing: $RULES_REPO_DIR"
if command -v promtool >/dev/null 2>&1; then
  promtool check config "$PROM_CONFIG_REPO" >/dev/null
  check_repo_prometheus_rules "$RULES_REPO_DIR"
else
  log "WARN: promtool not found; skipping Prometheus config/rule syntax validation"
fi

prom_systemd_changed=0
if [[ -d "$PROM_SYSTEMD_REPO_DIR" ]]; then
  log "Promoting Prometheus systemd override"
  sudo_cmd mkdir -p "$PROM_SYSTEMD_RUNTIME_DIR"
  if rsync_changed_dir "$PROM_SYSTEMD_REPO_DIR/" "$PROM_SYSTEMD_RUNTIME_DIR/"; then
    prom_systemd_changed=0
  else
    prom_systemd_changed=1
  fi
  sudo_cmd chown -R root:root "$PROM_SYSTEMD_RUNTIME_DIR"
  if [[ "$DRY_RUN" == "1" || "$prom_systemd_changed" == "1" ]]; then
    sudo_cmd systemctl daemon-reload
  fi
else
  log "Prometheus systemd override dir not present; skipping"
fi

sudo_cmd mkdir -p "$(dirname "$PROM_CONFIG_RUNTIME")" "$RULES_RUNTIME_DIR"

prom_config_changed=0
if rsync_changed_file "$PROM_CONFIG_REPO" "$PROM_CONFIG_RUNTIME"; then
  prom_config_changed=0
else
  prom_config_changed=1
fi
sudo_cmd chown root:root "$PROM_CONFIG_RUNTIME"
sudo_cmd chmod 0644 "$PROM_CONFIG_RUNTIME"

rules_changed=0
if rsync_changed_dir "$RULES_REPO_DIR/" "$RULES_RUNTIME_DIR/"; then
  rules_changed=0
else
  rules_changed=1
fi

if [[ "$DRY_RUN" == "1" || "$prom_systemd_changed" == "1" || "$prom_config_changed" == "1" || "$rules_changed" == "1" ]]; then
  if [[ "$DRY_RUN" != "1" ]]; then
    if [[ "$prom_systemd_changed" == "1" ]]; then
      sudo_cmd systemctl restart prometheus
      wait_http_ready "$PROM_URL/-/healthy" "Prometheus"
      log "✅ Prometheus systemd override applied + service restarted"
    elif ! sudo systemctl is-active --quiet prometheus; then
      sudo_cmd systemctl start prometheus
      wait_http_ready "$PROM_URL/-/healthy" "Prometheus"
    else
      sudo_cmd curl -sS -X POST "$PROM_URL/-/reload" -o /dev/null
    fi
  else
    if [[ "$prom_systemd_changed" == "1" ]]; then
      sudo_cmd systemctl restart prometheus
      wait_http_ready "$PROM_URL/-/healthy" "Prometheus"
    else
      sudo_cmd curl -sS -X POST "$PROM_URL/-/reload" -o /dev/null
    fi
  fi
  if [[ "$DRY_RUN" == "1" ]]; then
    log "✅ [dry-run] Prometheus systemd/config/rules sync simulated"
  else
    log "✅ Prometheus systemd/config/rules synced"
  fi
else
  log "Prometheus systemd/config/rules unchanged; skipping reload"
fi

# -------------------- Telegraf (optional) --------------------
if [[ -d "$TELEGRAF_REPO_DIR" ]]; then
  log "Promoting Telegraf config"
  [[ -f "$TELEGRAF_REPO_DIR/telegraf.conf" ]] || die "Missing: telegraf/telegraf.conf"

  sudo_cmd mkdir -p "$TELEGRAF_RUNTIME_DIR" "$TELEGRAF_RUNTIME_D"

  telegraf_changed=0
  if rsync_changed_file "$TELEGRAF_REPO_DIR/telegraf.conf" "$TELEGRAF_RUNTIME_MAIN"; then
    : # no change
  else
    telegraf_changed=1
  fi

  if [[ -d "$TELEGRAF_REPO_DIR/telegraf.d" ]]; then
    if rsync_changed_dir "$TELEGRAF_REPO_DIR/telegraf.d/" "$TELEGRAF_RUNTIME_D/"; then
      : # no change
    else
      telegraf_changed=1
    fi
  fi

  restart_if_changed "$telegraf_changed" "telegraf"
else
  log "Telegraf repo dir not present; skipping Telegraf deploy"
fi

# -------------------- Wireless RF textfile service (optional, auto-install) --------------------
WIRELESS_RF_INSTALLER="$REPO_ROOT/scripts/install_wireless_rf_textfile.sh"
if [[ "$INSTALL_WIRELESS_RF_TEXTFILE" == "1" && -f "$WIRELESS_RF_INSTALLER" ]]; then
  log "Ensuring wireless-rf-textfile systemd unit/timer is installed"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo bash '$WIRELESS_RF_INSTALLER' --enable"
  else
    sudo_cmd bash "$WIRELESS_RF_INSTALLER" --enable
  fi
elif [[ "$INSTALL_WIRELESS_RF_TEXTFILE" == "0" ]]; then
  log "INSTALL_WIRELESS_RF_TEXTFILE=0; skipping wireless-rf-textfile systemd install"
else
  log "Wireless RF installer script not present; skipping wireless-rf-textfile systemd install"
fi

# -------------------- Wireless RF hourly collector (optional, auto-install) --------------------
WIRELESS_RF_HOURLY_INSTALLER="$REPO_ROOT/scripts/install_wireless_rf_hourly.sh"
if [[ "$INSTALL_WIRELESS_RF_HOURLY" == "1" && -f "$WIRELESS_RF_HOURLY_INSTALLER" ]]; then
  log "Ensuring wireless-rf-hourly systemd unit/timer is installed"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo bash '$WIRELESS_RF_HOURLY_INSTALLER'"
  else
    sudo_cmd bash "$WIRELESS_RF_HOURLY_INSTALLER"
  fi
elif [[ "$INSTALL_WIRELESS_RF_HOURLY" == "0" ]]; then
  log "INSTALL_WIRELESS_RF_HOURLY=0; skipping wireless-rf-hourly systemd install"
else
  log "Wireless RF hourly installer script not present; skipping wireless-rf-hourly systemd install"
fi

# -------------------- Wireless Badge hourly collector (optional, auto-install) --------------------
WIRELESS_BADGE_HOURLY_INSTALLER="$REPO_ROOT/scripts/install_wireless_badge_hourly.sh"
if [[ "$INSTALL_WIRELESS_BADGE_HOURLY" == "1" && -f "$WIRELESS_BADGE_HOURLY_INSTALLER" ]]; then
  log "Ensuring wireless-badge-hourly systemd unit/timer is installed"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo bash '$WIRELESS_BADGE_HOURLY_INSTALLER'"
  else
    sudo_cmd bash "$WIRELESS_BADGE_HOURLY_INSTALLER"
  fi
elif [[ "$INSTALL_WIRELESS_BADGE_HOURLY" == "0" ]]; then
  log "INSTALL_WIRELESS_BADGE_HOURLY=0; skipping wireless-badge-hourly systemd install"
else
  log "Wireless Badge hourly installer script not present; skipping wireless-badge-hourly systemd install"
fi

# -------------------- Vocera media PCAP QoE textfile service (optional, auto-install) --------------------
VOCERA_MEDIA_QOE_INSTALLER="$REPO_ROOT/scripts/install_vocera_media_qoe_textfile.sh"
if [[ "$INSTALL_VOCERA_MEDIA_QOE_TEXTFILE" == "1" && -f "$VOCERA_MEDIA_QOE_INSTALLER" ]]; then
  log "Ensuring vocera-media-qoe-textfile systemd unit/timer is installed"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] sudo bash '$VOCERA_MEDIA_QOE_INSTALLER' --enable"
  else
    sudo_cmd bash "$VOCERA_MEDIA_QOE_INSTALLER" --enable
  fi
elif [[ "$INSTALL_VOCERA_MEDIA_QOE_TEXTFILE" == "0" ]]; then
  log "INSTALL_VOCERA_MEDIA_QOE_TEXTFILE=0; skipping vocera-media-qoe-textfile systemd install"
else
  log "Vocera media QoE installer script not present; skipping vocera-media-qoe-textfile systemd install"
fi

# -------------------- Alloy (optional) --------------------
if [[ -d "$ALLOY_REPO_DIR" ]]; then
  log "Promoting Alloy configs"
  if [[ "$DRY_RUN" != "1" ]]; then
    need_cmd systemctl
  fi

  # Only require 'alloy' binary if we actually have configs to validate.
  if [[ "$DRY_RUN" != "1" && ( -f "$ALLOY_REPO_PROD_CFG" || -f "$ALLOY_REPO_CANARY_CFG" ) ]]; then
    need_cmd alloy
  fi

  sudo_cmd mkdir -p "$ALLOY_RUNTIME_DIR"

  # ---- prod config (deploy + validate; restart optional via ALLOY_RESTART_PROD=1) ----
  alloy_prod_changed=0
  if [[ -f "$ALLOY_REPO_PROD_CFG" ]]; then
    if rsync_changed_file "$ALLOY_REPO_PROD_CFG" "$ALLOY_RUNTIME_PROD_CFG"; then
      : # no change
    else
      alloy_prod_changed=1
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
      log "[dry-run] would validate: alloy validate '$ALLOY_RUNTIME_PROD_CFG'"
    else
      sudo_cmd alloy validate "$ALLOY_RUNTIME_PROD_CFG"
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      log "✅ [dry-run] Alloy prod config deploy/validate simulated"
    else
      log "✅ Alloy prod config deployed + validated"
    fi
  else
    log "Alloy prod config not present in repo; skipping prod config deploy"
  fi

  if [[ "$ALLOY_RESTART_PROD" == "1" ]]; then
    restart_if_changed "$alloy_prod_changed" "alloy"
  else
    if [[ "$alloy_prod_changed" == "1" ]]; then
      if [[ "$DRY_RUN" == "1" ]]; then
        log "[dry-run] Alloy prod config change assumed; prod restart policy simulation: no restart (set ALLOY_RESTART_PROD=1 to enable)"
      else
        log "Alloy prod config changed; NOT restarting alloy (set ALLOY_RESTART_PROD=1 to enable)"
      fi
    else
      log "Alloy prod config unchanged"
    fi
  fi

  # ---- canary config + unit (enable/start canary; restart if changed) ----
  alloy_canary_changed=0
  alloy_canary_unit_changed=0

  if [[ -f "$ALLOY_REPO_CANARY_CFG" ]]; then
    if rsync_changed_file "$ALLOY_REPO_CANARY_CFG" "$ALLOY_RUNTIME_CANARY_CFG"; then
      : # no change
    else
      alloy_canary_changed=1
    fi

    if [[ "$DRY_RUN" == "1" ]]; then
      log "[dry-run] would validate: alloy validate '$ALLOY_RUNTIME_CANARY_CFG'"
    else
      sudo_cmd alloy validate "$ALLOY_RUNTIME_CANARY_CFG"
    fi
    if [[ "$DRY_RUN" == "1" ]]; then
      log "✅ [dry-run] Alloy canary config deploy/validate simulated"
    else
      log "✅ Alloy canary config deployed + validated"
    fi
  else
    log "Alloy canary config not present in repo; skipping canary config deploy"
  fi

  if [[ -f "$ALLOY_REPO_CANARY_UNIT" ]]; then
    sudo_cmd mkdir -p "$(dirname "$ALLOY_RUNTIME_CANARY_UNIT")"
    if rsync_changed_file "$ALLOY_REPO_CANARY_UNIT" "$ALLOY_RUNTIME_CANARY_UNIT"; then
      : # no change
    else
      alloy_canary_unit_changed=1
    fi

    sudo_cmd systemctl daemon-reload
    sudo_cmd systemctl enable --now alloy-canary

    # restart canary if either unit OR config changed (or dry-run)
    if [[ "$DRY_RUN" == "1" ]]; then
      log "[dry-run] would restart: alloy-canary"
    else
      if [[ "$alloy_canary_changed" == "1" || "$alloy_canary_unit_changed" == "1" ]]; then
        sudo_cmd systemctl restart alloy-canary
      fi
    fi

    # Best-effort status check
    sudo_cmd systemctl is-active --quiet alloy-canary
    if [[ "$DRY_RUN" == "1" ]]; then
      log "✅ [dry-run] alloy-canary running state check simulated"
    else
      log "✅ alloy-canary ensured running"
    fi
  else
    log "Alloy canary unit not present in repo; skipping canary unit deploy"
  fi
else
  log "Alloy repo dir not present; skipping Alloy deploy"
fi

# -------------------- Grafana dashboards --------------------
log "Promoting Grafana dashboards (files)"
[[ -d "$REPO_PROD_DIR" ]] || die "Repo PROD dashboards dir missing: $REPO_PROD_DIR"
sudo_cmd mkdir -p "$RUNTIME_PROD_DIR"

grafana_files_changed=0
if rsync_changed_dir "$REPO_PROD_DIR/" "$RUNTIME_PROD_DIR/"; then
  grafana_files_changed=0
else
  grafana_files_changed=1
fi

if ! sudo_cmd chown -R grafana:grafana "$RUNTIME_PROD_DIR"; then
  log "WARN: chown failed for $RUNTIME_PROD_DIR (continuing)"
fi

# -------------------- Grafana dashboard provisioning --------------------
grafana_dashboard_provisioning_changed=0
if [[ -d "$REPO_GRAFANA_DASHBOARDS_PROVISIONING_DIR" ]]; then
  log "Promoting Grafana dashboard provisioning"
  sudo_cmd install -d -o grafana -g grafana -m 0750 "$RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR"
  if rsync_changed_dir "$REPO_GRAFANA_DASHBOARDS_PROVISIONING_DIR/" "$RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR/"; then
    grafana_dashboard_provisioning_changed=0
  else
    grafana_dashboard_provisioning_changed=1
  fi
  if ! sudo_cmd chown -R grafana:grafana "$RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR"; then
    log "WARN: chown failed for $RUNTIME_GRAFANA_DASHBOARDS_PROVISIONING_DIR (continuing)"
  fi
else
  log "Grafana dashboard provisioning dir not present; skipping"
fi

# -------------------- Grafana datasource provisioning --------------------
grafana_datasources_changed=0
if [[ -d "$REPO_GRAFANA_DATASOURCES_DIR" ]]; then
  log "Promoting Grafana datasource provisioning"
  sudo_cmd install -d -o grafana -g grafana -m 0750 "$RUNTIME_GRAFANA_DATASOURCES_DIR"
  if rsync_changed_dir "$REPO_GRAFANA_DATASOURCES_DIR/" "$RUNTIME_GRAFANA_DATASOURCES_DIR/"; then
    grafana_datasources_changed=0
  else
    grafana_datasources_changed=1
  fi
  if ! sudo_cmd chown -R grafana:grafana "$RUNTIME_GRAFANA_DATASOURCES_DIR"; then
    log "WARN: chown failed for $RUNTIME_GRAFANA_DATASOURCES_DIR (continuing)"
  fi
else
  log "Grafana datasource provisioning dir not present; skipping"
fi

# -------------------- Grafana systemd drop-ins --------------------
grafana_systemd_changed=0
if [[ -d "$REPO_GRAFANA_SYSTEMD_DIR" ]]; then
  log "Promoting Grafana systemd drop-ins"
  sudo_cmd install -d -o root -g root -m 0755 "$RUNTIME_GRAFANA_SYSTEMD_DIR"
  if rsync_changed_dir "$REPO_GRAFANA_SYSTEMD_DIR/" "$RUNTIME_GRAFANA_SYSTEMD_DIR/"; then
    grafana_systemd_changed=0
  else
    grafana_systemd_changed=1
  fi
  sudo_cmd chown -R root:root "$RUNTIME_GRAFANA_SYSTEMD_DIR"
  sudo_cmd chmod -R u=rwX,go=rX "$RUNTIME_GRAFANA_SYSTEMD_DIR"
  if [[ "$grafana_systemd_changed" == "1" || "$DRY_RUN" == "1" ]]; then
    sudo_cmd systemctl daemon-reload
  fi
else
  log "Grafana systemd override dir not present; skipping"
fi

# -------------------- Grafana alerting provisioning --------------------
grafana_alerting_changed=0
if [[ -d "$REPO_GRAFANA_ALERTING_DIR" ]]; then
  log "Promoting Grafana alerting provisioning"
  sudo_cmd install -d -o grafana -g grafana -m 0750 "$RUNTIME_GRAFANA_ALERTING_DIR"
  if rsync_changed_dir "$REPO_GRAFANA_ALERTING_DIR/" "$RUNTIME_GRAFANA_ALERTING_DIR/"; then
    grafana_alerting_changed=0
  else
    grafana_alerting_changed=1
  fi
  if ! sudo_cmd chown -R grafana:grafana "$RUNTIME_GRAFANA_ALERTING_DIR"; then
    log "WARN: chown failed for $RUNTIME_GRAFANA_ALERTING_DIR (continuing)"
  fi
else
  log "Grafana alerting provisioning dir not present; skipping"
fi
ensure_grafana_provisioning_readable "$RUNTIME_GRAFANA_PROVISIONING_DIR"

# Decide whether Grafana needs restart:
# - If dashboards changed, restart is safest for provisioning refresh
# - If folder cleanup will touch grafana.db, we stop/start
need_grafana_restart=0
[[ "$grafana_files_changed" == "1" ]] && need_grafana_restart=1
[[ "$grafana_dashboard_provisioning_changed" == "1" ]] && need_grafana_restart=1
[[ "$grafana_datasources_changed" == "1" ]] && need_grafana_restart=1
[[ "$grafana_systemd_changed" == "1" ]] && need_grafana_restart=1
[[ "$grafana_alerting_changed" == "1" ]] && need_grafana_restart=1
[[ "$SKIP_FOLDER_CLEANUP" == "0" ]] && need_grafana_restart=1

if [[ "$need_grafana_restart" == "1" ]]; then
  if ! sudo_cmd systemctl stop grafana-server; then
    log "WARN: systemctl stop grafana-server failed (continuing)"
  fi
else
  log "Grafana unchanged and folder cleanup skipped; skipping grafana-server stop/start"
fi

# -------------------- Dashboard DB cleanup --------------------
dashboard_uid_allowlist="$tmp/allowed_dashboard_uids.txt"
build_allowed_dashboard_uids_file "$REPO_PROD_DIR" "$dashboard_uid_allowlist"
if [[ "$DRY_RUN" == "1" ]]; then
  log "[dry-run] allowed dashboard UIDs:"
  sed 's/^/  - /' "$dashboard_uid_allowlist"
fi
cleanup_prod_unmanaged_dashboards "$dashboard_uid_allowlist"

# -------------------- Folder cleanup (optional) --------------------
if [[ "$SKIP_FOLDER_CLEANUP" == "1" ]]; then
  log "Skipping folder cleanup (--skip-folder-cleanup)."
else
  allowlist="$tmp/allowed_folders.txt"
  allowlist_source="$RUNTIME_PROD_DIR"
  if [[ "$DRY_RUN" == "1" ]]; then
    allowlist_source="$REPO_PROD_DIR"
    log "[dry-run] building folder allowlist from repo dir"
  fi
  build_allowed_folders_file "$allowlist_source" "$allowlist"

  if [[ "$DRY_RUN" == "1" ]]; then
    log "[dry-run] allowlist folder titles:"
    sed 's/^/  - /' "$allowlist"
    log "[dry-run] would run stale EMPTY folder cleanup"
  else
    allowlist_root="/tmp/grafana_allowed_folders.txt"
    cp -f "$allowlist" "$allowlist_root"
    chmod 0644 "$allowlist_root"
    cleanup_prod_stale_empty_folders "$allowlist_root"
    rm -f "$allowlist_root"
  fi
fi

if [[ -d "$REPO_GRAFANA_DATASOURCES_DIR" ]]; then
  cleanup_grafana_managed_datasources
fi

if [[ "$need_grafana_restart" == "1" ]]; then
  sudo_cmd systemctl reset-failed grafana-server
  sudo_cmd systemctl start grafana-server
  sudo_cmd systemctl is-active --quiet grafana-server
  wait_http_ready "$GRAFANA_URL/api/health" "Grafana"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "✅ [dry-run] Grafana running state check simulated"
  else
    log "✅ Grafana ensured running"
  fi
fi

if [[ "$DRY_RUN" == "1" ]]; then
  log "✅ [dry-run] Promotion simulation complete"
else
  log "✅ Promotion complete"
fi
