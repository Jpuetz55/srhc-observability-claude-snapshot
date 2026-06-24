#!/usr/bin/env bash
set -euo pipefail
# Roll back one run produced by scripts/run_vocera_survey_refresh.sh.
#
# This removes RF validation rows for the run id, removes media QoE rows whose
# source pcaps came from that run's uploaded Pcaps directory, and moves the
# uploaded bundle aside so cached media parses stop being considered current.

# Print rollback usage, scopes, and safety options.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/rollback_vocera_survey_refresh.sh --run-id RUN_ID [options]

Options:
  --run-id RUN_ID       Required run id, for example srhc_vocera_ekahau_2026_06_01_1001.
  --upload-dir PATH     Uploaded job directory. Defaults from the job manifest,
                        then /var/lib/vocera-rf-validation/uploads/RUN_ID.
  --dry-run             Print the rollback actions without changing files or DB rows.
  --keep-upload         Do not move the uploaded bundle to the rolled-back folder.
  --remove-current-outputs
                        Remove generated output files only when the job
                        manifest hash proves they still match this run.
  --skip-rf-db          Do not delete RF validation PostgreSQL rows.
  --skip-media-db       Do not delete media QoE PostgreSQL rows.

Environment overrides:
  VOCERA_SURVEY_JOB_MANIFEST_DIR    default: data/vocera-rf-validation/out/jobs
  VOCERA_SURVEY_UPLOAD_ROOT         default: /var/lib/vocera-rf-validation/uploads
  VOCERA_SURVEY_ROLLBACK_ROOT       default: /var/lib/vocera-rf-validation/rolled-back
  VOCERA_RF_VALIDATION_DATABASE_URL default: local RF validation PostgreSQL URL
  VOCERA_RF_VALIDATION_PSQL_BIN     default: scripts/vocera_rf_validation_psql_in_container.sh
  VOCERA_MEDIA_QOE_DATABASE_URL     default: local media QoE PostgreSQL URL
  VOCERA_MEDIA_QOE_PSQL_BIN         default: scripts/vocera_media_qoe_psql_in_container.sh
EOF
}

# Stop rollback with a concise operator-facing error.
die() { echo "ERROR: $*" >&2; exit 1; }
# Print a high-level rollback step.
info() { echo "==> $*"; }

RUN_ID=""
UPLOAD_DIR=""
DRY_RUN=0
KEEP_UPLOAD=0
REMOVE_CURRENT_OUTPUTS=0
SKIP_RF_DB=0
SKIP_MEDIA_DB=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run-id)
      shift
      [[ $# -gt 0 ]] || die "missing value for --run-id"
      RUN_ID="$1"
      ;;
    --upload-dir)
      shift
      [[ $# -gt 0 ]] || die "missing value for --upload-dir"
      UPLOAD_DIR="$1"
      ;;
    --dry-run)
      DRY_RUN=1
      ;;
    --keep-upload)
      KEEP_UPLOAD=1
      ;;
    --remove-current-outputs)
      REMOVE_CURRENT_OUTPUTS=1
      ;;
    --skip-rf-db)
      SKIP_RF_DB=1
      ;;
    --skip-media-db)
      SKIP_MEDIA_DB=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$RUN_ID" ]] || { usage; die "--run-id is required"; }
[[ "$RUN_ID" =~ ^[A-Za-z0-9_.:-]+$ ]] || die "run id contains unsupported characters: $RUN_ID"

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

JOB_MANIFEST_DIR="${VOCERA_SURVEY_JOB_MANIFEST_DIR:-data/vocera-rf-validation/out/jobs}"
UPLOAD_ROOT="${VOCERA_SURVEY_UPLOAD_ROOT:-/var/lib/vocera-rf-validation/uploads}"
ROLLBACK_ROOT="${VOCERA_SURVEY_ROLLBACK_ROOT:-/var/lib/vocera-rf-validation/rolled-back}"
if [[ -z "${VOCERA_RF_VALIDATION_DATABASE_URL:-}" && -z "${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env; set +a
fi
RF_DATABASE_URL="${VOCERA_RF_VALIDATION_DATABASE_URL:-postgresql://vocera_rf_validation:${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:?VOCERA_RF_VALIDATION_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export VOCERA_RF_VALIDATION_DATABASE_URL}@127.0.0.1:15433/vocera_rf_validation}"
RF_PSQL_BIN="${VOCERA_RF_VALIDATION_PSQL_BIN:-scripts/vocera_rf_validation_psql_in_container.sh}"
if [[ -z "${VOCERA_MEDIA_QOE_DATABASE_URL:-}" && -z "${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env; set +a
fi
MEDIA_DATABASE_URL="${VOCERA_MEDIA_QOE_DATABASE_URL:-postgresql://vocera_media_qoe:${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:?VOCERA_MEDIA_QOE_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export VOCERA_MEDIA_QOE_DATABASE_URL}@127.0.0.1:15434/vocera_media_qoe}"
MEDIA_PSQL_BIN="${VOCERA_MEDIA_QOE_PSQL_BIN:-scripts/vocera_media_qoe_psql_in_container.sh}"
MANIFEST="$JOB_MANIFEST_DIR/$RUN_ID.json"

if [[ -z "$UPLOAD_DIR" && -f "$MANIFEST" ]]; then
  # Prefer the manifest path over the default upload root because Windows
  # uploads can override the destination per run.
  UPLOAD_DIR="$(python3 - "$MANIFEST" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle).get("upload_dir") or "")
PY
)"
fi
UPLOAD_DIR="${UPLOAD_DIR:-$UPLOAD_ROOT/$RUN_ID}"
PCAP_DIR="$UPLOAD_DIR/Pcaps"

# Run one rollback command, showing the exact argv and honoring dry-run mode.
run_cmd() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  "$@"
}

# Generate SQL that deletes RF validation rows for exactly one test run id.
write_rf_sql() {
  local path="$1"
  # Delete in dependency order. The RF schema uses foreign keys from child
  # evidence rows back to validation_test_runs.
  RUN_ID="$RUN_ID" python3 - "$path" <<'PY'
import os
import sys

def lit(value: str) -> str:
    """Quote a string literal for the generated rollback SQL."""

    return "'" + value.replace("'", "''") + "'"

run_id = lit(os.environ["RUN_ID"])
sql = f"""begin;
delete from badge_ekahau_matches where test_run_id = {run_id};
delete from badge_ekahau_candidate_matches where test_run_id = {run_id};
delete from manual_ekahau_observations where test_run_id = {run_id};
delete from ekahau_survey_points where test_run_id = {run_id};
delete from badge_rrm_neighbors where test_run_id = {run_id};
delete from badge_radio_signal_samples where test_run_id = {run_id};
delete from badge_scan_candidates using badge_scan_events
where badge_scan_candidates.event_id = badge_scan_events.event_id
  and badge_scan_events.test_run_id = {run_id};
delete from badge_scan_events where test_run_id = {run_id};
delete from validation_source_files where test_run_id = {run_id};
delete from validation_test_runs where test_run_id = {run_id};
commit;
"""
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(sql)
PY
}

# Generate SQL that deletes media captures sourced from this upload's Pcaps dir.
write_media_sql() {
  local path="$1"
  # Media QoE rows do not store the RF validation run id; for upload-driven
  # runs the source pcap path under the job's Pcaps directory is the rollback
  # scope. Stream samples cascade from vocera_media_captures.
  RUN_ID="$RUN_ID" PCAP_DIR="$PCAP_DIR" python3 - "$path" <<'PY'
import os
import sys

def lit(value: str) -> str:
    """Quote a string literal for the generated rollback SQL."""

    return "'" + value.replace("'", "''") + "'"

pcap_dir = os.environ["PCAP_DIR"].rstrip("/")
like_prefix = pcap_dir + "/%"
sql = f"""begin;
delete from vocera_media_captures
where source_path like {lit(like_prefix)};
commit;
"""
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    handle.write(sql)
PY
}

# Remove standard output artifacts only when their hashes match the manifest.
remove_current_outputs() {
  [[ -f "$MANIFEST" ]] || die "cannot remove generated outputs without job manifest: $MANIFEST"
  info "Removing generated outputs that still match manifest hashes"
  # Hash checking prevents an old rollback from deleting outputs generated by a
  # newer, good run that reused the standard JSON/CSV/prom file paths.
  MANIFEST="$MANIFEST" DRY_RUN="$DRY_RUN" python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path

manifest_path = Path(os.environ["MANIFEST"])
dry_run = os.environ.get("DRY_RUN") == "1"

with manifest_path.open(encoding="utf-8") as handle:
    manifest = json.load(handle)

for artifact in manifest.get("artifacts", []):
    path_value = artifact.get("path")
    expected = artifact.get("sha256")
    if not path_value or not expected:
        continue
    path = Path(path_value)
    if not path.is_file():
        print(f"skip missing {path}")
        continue
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != expected:
        print(f"skip changed {path}")
        continue
    print(f"+ rm -f {path}")
    if not dry_run:
        path.unlink()
PY
}

info "Rollback run id: $RUN_ID"
info "Job manifest: $MANIFEST"
info "Upload dir: $UPLOAD_DIR"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

if [[ "$SKIP_RF_DB" != "1" ]]; then
  rf_sql="$tmp_dir/rf_rollback.sql"
  write_rf_sql "$rf_sql"
  info "Deleting RF validation rows for $RUN_ID"
  run_cmd "$RF_PSQL_BIN" "$RF_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$rf_sql"
fi

if [[ "$SKIP_MEDIA_DB" != "1" ]]; then
  media_sql="$tmp_dir/media_rollback.sql"
  write_media_sql "$media_sql"
  info "Deleting media QoE rows whose source_path is under $PCAP_DIR"
  run_cmd "$MEDIA_PSQL_BIN" "$MEDIA_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$media_sql"
fi

if [[ "$KEEP_UPLOAD" != "1" ]]; then
  if [[ -d "$UPLOAD_DIR" ]]; then
    destination="$ROLLBACK_ROOT/${RUN_ID}-$(date +%Y%m%dT%H%M%S)"
    info "Moving uploaded bundle to $destination"
    if [[ "$DRY_RUN" == "1" ]]; then
      printf '+ mkdir -p %q\n' "$ROLLBACK_ROOT"
      printf '+ mv %q %q\n' "$UPLOAD_DIR" "$destination"
    else
      mkdir -p "$ROLLBACK_ROOT"
      mv "$UPLOAD_DIR" "$destination"
    fi
  else
    info "No upload directory present to move"
  fi
fi

if [[ "$REMOVE_CURRENT_OUTPUTS" == "1" ]]; then
  remove_current_outputs
fi

cat <<EOF

Rollback complete for $RUN_ID.

Notes:
  - Parser ZIP archives are retained for audit.
  - Standard output files are retained unless --remove-current-outputs is used.
  - Re-run the upload/refresh workflow with corrected data to publish fresh outputs.
EOF
