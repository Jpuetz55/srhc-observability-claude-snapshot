#!/usr/bin/env bash
set -euo pipefail
# One-command Vocera survey refresh for the SRHC badge/ICAP validation flow.
#
# Two distinct sub-flows, with different per-device semantics:
#
#  - PCAP / media QoE: uploaded PCAPs are parsed as one current study. The
#    parser/server configuration maps streams to control/test devices by packet
#    metadata and source path, then Grafana compares those labeled rows.
#
#  - RF validation (badge-vs-Ekahau): a single badge log feeds one analysis
#    run against the shared Ekahau survey. No control/test split here - the
#    flow uses one selected badge log (override via VOCERA_SURVEY_BADGE_INPUT /
#    VOCERA_SURVEY_BADGE_MAC if needed).
#
# The Windows upload script sets VOCERA_SURVEY_MEDIA_RAW_DIR to the per-run
# upload root. Optional CONTROL_/TEST_ variables are still accepted for
# server-side split parsing, but the laptop script does not own that logic.
#
# Legacy single-device invocations (VOCERA_SURVEY_BADGE_MAC and
# VOCERA_SURVEY_MEDIA_RAW_DIR set, none of the CONTROL_ vars) still work and
# leave output paths unsuffixed.

RUN_ID_PREFIX="${VOCERA_SURVEY_RUN_ID_PREFIX:-srhc_vocera_ekahau}"

# Media (PCAP) defaults; per-device PCAP dir is resolved later.
MEDIA_DEFAULT_RAW_DIR="${VOCERA_SURVEY_MEDIA_RAW_DIR:-/var/lib/vocera-media-qoe/raw}"
MEDIA_CONFIG="${VOCERA_SURVEY_MEDIA_CONFIG:-config/vocera-media-qoe.yaml}"
MEDIA_OUT_DIR="${VOCERA_SURVEY_MEDIA_OUT_DIR:-data/vocera-media-qoe/out}"
MEDIA_PARSED_DIR_BASE="$MEDIA_OUT_DIR/captures"
MEDIA_ARCHIVE="${VOCERA_SURVEY_MEDIA_ARCHIVE:-0}"
MEDIA_ARCHIVE_DIR="${VOCERA_SURVEY_MEDIA_ARCHIVE_DIR:-/var/lib/vocera-media-qoe/archives}"
MEDIA_TEXTFILE_BASE="${VOCERA_SURVEY_MEDIA_TEXTFILE_OUT:-/var/lib/node_exporter/textfile_collector/vocera_media_qoe.prom}"
MEDIA_DELETE_UPLOADED_PCAPS="${VOCERA_SURVEY_MEDIA_DELETE_UPLOADED_PCAPS:-1}"
if [[ -z "${VOCERA_SURVEY_MEDIA_DATABASE_URL:-}" && -z "${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env; set +a
fi
MEDIA_DATABASE_URL="${VOCERA_SURVEY_MEDIA_DATABASE_URL:-postgresql://vocera_media_qoe:${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:?VOCERA_MEDIA_QOE_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export VOCERA_SURVEY_MEDIA_DATABASE_URL}@127.0.0.1:15434/vocera_media_qoe}"
MEDIA_PSQL_BIN="${VOCERA_SURVEY_MEDIA_PSQL_BIN:-scripts/vocera_media_qoe_psql_in_container.sh}"
MEDIA_LOAD_DB="${VOCERA_SURVEY_MEDIA_LOAD_DB:-1}"

# RF validation defaults - single-device flow.
RF_RAW_DIR="${VOCERA_SURVEY_RF_RAW_DIR:-/var/lib/vocera-rf-validation/raw}"
RF_CONFIG="${VOCERA_SURVEY_RF_CONFIG:-config/vocera-rf-validation.yaml}"
RF_EKAHAU_PROJECT="${VOCERA_SURVEY_EKAHAU_PROJECT:-$RF_RAW_DIR/Main_Campus_Base_Project.esx}"
RF_OUT_DIR="${VOCERA_SURVEY_RF_OUT_DIR:-data/vocera-rf-validation/out}"
RF_BADGE_JSON="$RF_OUT_DIR/badge_scan_events.json"
RF_EKAHAU_JSON="$RF_OUT_DIR/ekahau_survey_points.json"
RF_MANUAL_TEMPLATE="$RF_OUT_DIR/manual_ekahau_observations_template.csv"
RF_MANUAL_CSV="$RF_OUT_DIR/manual_ekahau_observations.csv"
RF_MATCHES_JSON="$RF_OUT_DIR/badge_ekahau_matches.json"
RF_MATCHES_CSV="$RF_OUT_DIR/badge_ekahau_matches.csv"
RF_SQL_OUT="$RF_OUT_DIR/vocera_rf_validation_import.sql"
RF_ARCHIVE_DIR="$RF_OUT_DIR/archives"
if [[ -z "${VOCERA_SURVEY_RF_DATABASE_URL:-}" && -z "${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env; set +a
fi
RF_DATABASE_URL="${VOCERA_SURVEY_RF_DATABASE_URL:-postgresql://vocera_rf_validation:${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:?VOCERA_RF_VALIDATION_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export VOCERA_SURVEY_RF_DATABASE_URL}@127.0.0.1:15433/vocera_rf_validation}"
RF_PSQL_BIN="${VOCERA_SURVEY_RF_PSQL_BIN:-scripts/vocera_rf_validation_psql_in_container.sh}"
RF_LOAD_DB="${VOCERA_SURVEY_RF_LOAD_DB:-1}"
RF_SKIP="${VOCERA_SURVEY_SKIP_RF:-0}"

DOWNLOAD_ICAP="${VOCERA_SURVEY_DOWNLOAD_ICAP:-0}"
DNAC_ENV_FILE="${VOCERA_SURVEY_DNAC_ENV_FILE:-/etc/grafana-mimir-observability/secrets/dnac-readonly.env}"
DNAC_CAPTURE_TYPE="${VOCERA_SURVEY_DNAC_CAPTURE_TYPE:-FULL}"
DNAC_LIMIT="${VOCERA_SURVEY_DNAC_LIMIT:-20}"

DRY_RUN="${VOCERA_SURVEY_DRY_RUN:-0}"
OUTPUT_OWNER="${VOCERA_SURVEY_OUTPUT_OWNER:-${SUDO_USER:-}}"
UPLOAD_DIR="${VOCERA_SURVEY_UPLOAD_DIR:-}"
JOB_MANIFEST_DIR="${VOCERA_SURVEY_JOB_MANIFEST_DIR:-$RF_OUT_DIR/jobs}"

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

run() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  "$@"
}

run_env() {
  printf '+'
  printf ' %q' "$@"
  printf '\n'
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  env "$@"
}

need_file() {
  [[ -f "$1" ]] || die "required file not found: $1"
}

need_path() {
  [[ -e "$1" ]] || die "required path not found: $1"
}

# Newest badge diagnostic archive matching one badge MAC under $RF_RAW_DIR.
# Filename convention (badge firmware export):
#   <YYYYMMDD>_<HHMMSS>-V<ver>-Test_<one|Two>-<mac-hex>-udd.tar.gz
# The MAC-hex substring is what we match on.
latest_badge_input_for() {
  local badge_mac="$1"
  local token="${badge_mac//[^0-9A-Fa-f]/}"
  find "$RF_RAW_DIR" -maxdepth 1 -type f \
    \( -iname "*${token}*.tar.gz" -o -iname "*${token}*.tgz" -o -iname "*${token}*.zip" -o -iname "*${token}*sys*" \) \
    -printf '%T@ %p\n' 2>/dev/null \
    | sort -n \
    | tail -1 \
    | cut -d' ' -f2-
}

# Append `_<suffix>` before the extension. Empty suffix returns the path
# unchanged - used by legacy single-device mode.
suffix_path() {
  local path="$1" suffix="$2"
  if [[ -z "$suffix" ]]; then
    printf '%s' "$path"
    return
  fi
  local dir base ext
  dir="$(dirname "$path")"
  base="$(basename "$path")"
  if [[ "$base" == *.* ]]; then
    ext="${base##*.}"
    base="${base%.*}"
    printf '%s/%s_%s.%s' "$dir" "$base" "$suffix" "$ext"
  else
    printf '%s/%s_%s' "$dir" "$base" "$suffix"
  fi
}

maybe_restore_output_owner() {
  if [[ -z "$OUTPUT_OWNER" || "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  local group
  group="$(id -gn "$OUTPUT_OWNER" 2>/dev/null || true)"
  [[ -n "$group" ]] || return 0
  chown -R "$OUTPUT_OWNER:$group" "$MEDIA_OUT_DIR" "$RF_OUT_DIR" 2>/dev/null || true
}

delete_uploaded_pcaps_for_device() {
  local pcap_dir="$1"
  [[ "$MEDIA_DELETE_UPLOADED_PCAPS" == "1" ]] || return 0
  [[ "$MEDIA_LOAD_DB" == "1" ]] || return 0
  [[ -n "$UPLOAD_DIR" ]] || return 0
  case "$pcap_dir" in
    "$UPLOAD_DIR"|"$UPLOAD_DIR"/*) ;;
    *) return 0 ;;
  esac
  [[ -d "$pcap_dir" ]] || return 0
  info "[media] Deleting uploaded PCAP files after successful parse/load: $pcap_dir"
  find "$pcap_dir" -type f \
    \( -iname '*.pcap' -o -iname '*.pcapng' -o -iname '*.cap' -o -iname '*.pcap.json' -o -iname '*.pcapng.json' -o -iname '*.cap.json' \) \
    -delete
}

# Build the PCAP device list. CONTROL is required when running in multi-device
# mode; TEST is optional. Legacy mode (no CONTROL_ vars) leaves the list with
# a single empty-role entry so output paths stay unsuffixed.
declare -a MEDIA_DEVICE_ROLES=()
declare -A MEDIA_DEVICE_BADGE_MAC
declare -A MEDIA_DEVICE_PCAP_DIR
if [[ -n "${VOCERA_SURVEY_CONTROL_BADGE_MAC:-}" ]]; then
  MEDIA_DEVICE_ROLES+=("control")
  MEDIA_DEVICE_BADGE_MAC["control"]="$VOCERA_SURVEY_CONTROL_BADGE_MAC"
  MEDIA_DEVICE_PCAP_DIR["control"]="${VOCERA_SURVEY_CONTROL_PCAP_DIR:-$MEDIA_DEFAULT_RAW_DIR}"
  if [[ -n "${VOCERA_SURVEY_TEST_BADGE_MAC:-}" ]]; then
    [[ "$VOCERA_SURVEY_TEST_BADGE_MAC" != "$VOCERA_SURVEY_CONTROL_BADGE_MAC" ]] \
      || die "control and test badge MACs must differ ($VOCERA_SURVEY_TEST_BADGE_MAC)"
    MEDIA_DEVICE_ROLES+=("test")
    MEDIA_DEVICE_BADGE_MAC["test"]="$VOCERA_SURVEY_TEST_BADGE_MAC"
    MEDIA_DEVICE_PCAP_DIR["test"]="${VOCERA_SURVEY_TEST_PCAP_DIR:-$MEDIA_DEFAULT_RAW_DIR}"
  fi
else
  MEDIA_DEVICE_ROLES+=("__single")
  MEDIA_DEVICE_BADGE_MAC["__single"]="${VOCERA_SURVEY_BADGE_MAC:-00:09:ef:54:5f:46}"
  MEDIA_DEVICE_PCAP_DIR["__single"]="$MEDIA_DEFAULT_RAW_DIR"
fi

# Pick the badge log + MAC that drive the single RF validation run.
# Precedence: explicit override -> control device (new mode) -> legacy single.
RF_BADGE_MAC="${VOCERA_SURVEY_BADGE_MAC:-}"
RF_BADGE_INPUT="${VOCERA_SURVEY_BADGE_INPUT:-}"
if [[ -z "$RF_BADGE_MAC" ]]; then
  if [[ -n "${VOCERA_SURVEY_CONTROL_BADGE_MAC:-}" ]]; then
    RF_BADGE_MAC="$VOCERA_SURVEY_CONTROL_BADGE_MAC"
  else
    RF_BADGE_MAC="${MEDIA_DEVICE_BADGE_MAC[${MEDIA_DEVICE_ROLES[0]}]}"
  fi
fi
if [[ -z "$RF_BADGE_INPUT" ]]; then
  RF_BADGE_INPUT="${VOCERA_SURVEY_CONTROL_BADGE_INPUT:-}"
fi

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

need_file "$MEDIA_CONFIG"
need_file "$RF_CONFIG"

RUN_ID_BASE="${VOCERA_SURVEY_RUN_ID:-${RUN_ID_PREFIX}_$(date +%Y_%m_%d_%H%M)}"

mkdir -p "$MEDIA_OUT_DIR" "$MEDIA_PARSED_DIR_BASE" "$RF_OUT_DIR"

# Parse one device's pcaps under its own role-suffixed outputs and DB
# scoping. RF validation never runs here.
process_media_for_device() {
  local role_key="$1"
  local role="$role_key"
  if [[ "$role_key" == "__single" ]]; then
    role=""
  fi
  local badge_mac="${MEDIA_DEVICE_BADGE_MAC[$role_key]}"
  local pcap_dir="${MEDIA_DEVICE_PCAP_DIR[$role_key]}"
  local run_id="$RUN_ID_BASE"
  if [[ -n "$role" ]]; then
    run_id="${RUN_ID_BASE}_${role}"
  fi

  local media_parsed_dir
  if [[ -n "$role" ]]; then
    media_parsed_dir="${MEDIA_PARSED_DIR_BASE}_${role}"
  else
    media_parsed_dir="$MEDIA_PARSED_DIR_BASE"
  fi
  mkdir -p "$media_parsed_dir"

  local media_prom_out media_json_out media_sql_out media_textfile_out
  media_prom_out="$(suffix_path "$MEDIA_OUT_DIR/vocera_media_qoe.prom" "$role")"
  media_json_out="$(suffix_path "$MEDIA_OUT_DIR/vocera_media_qoe_summary.json" "$role")"
  media_sql_out="$(suffix_path "$MEDIA_OUT_DIR/vocera_media_qoe_import.sql" "$role")"
  media_textfile_out="$(suffix_path "$MEDIA_TEXTFILE_BASE" "$role")"

  need_path "$pcap_dir"

  info "[media ${role:-single}] run_id=$run_id badge=$badge_mac pcaps=$pcap_dir"

  if [[ "$DOWNLOAD_ICAP" == "1" ]]; then
    info "[media ${role:-single}] Downloading latest DNAC ICAP capture for $badge_mac"
    run_env PYTHONPATH=tools/vocera_media_qoe:tools/wireless_rf python3 -m vocera_dnac_icap \
      --env-file "$DNAC_ENV_FILE" \
      --client-mac "$badge_mac" \
      --capture-type "$DNAC_CAPTURE_TYPE" \
      --lookback-minutes 0 \
      --limit "$DNAC_LIMIT" \
      --out-dir "$pcap_dir"
  fi

  info "[media ${role:-single}] Parsing ICAP pcaps and publishing media QoE outputs"
  local media_args=(
    PYTHONPATH=tools/vocera_media_qoe
    python3 -m vocera_media_qoe_batch
    --raw-dir "$pcap_dir"
    --config "$MEDIA_CONFIG"
    --prom-out "$media_prom_out"
    --json-out "$media_json_out"
    --parsed-dir "$media_parsed_dir"
    --textfile-out "$media_textfile_out"
    --sql-out "$media_sql_out"
  )
  if [[ "$MEDIA_ARCHIVE" == "1" ]]; then
    media_args+=(--archive-dir "$MEDIA_ARCHIVE_DIR" --archive-label "$run_id")
  else
    media_args+=(--no-archive)
  fi
  if [[ "$MEDIA_LOAD_DB" == "1" ]]; then
    media_args+=(--postgres-url "$MEDIA_DATABASE_URL" --psql-bin "$MEDIA_PSQL_BIN")
  fi
  run_env "${media_args[@]}"
  delete_uploaded_pcaps_for_device "$pcap_dir"

  append_media_to_manifest "$role" "$run_id" "$badge_mac" "$pcap_dir" \
    "$media_prom_out" "$media_json_out" "$media_sql_out" "$media_textfile_out"

  echo
  echo "Media outputs refreshed [${role:-single}] (run_id=$run_id):"
  echo "  Prometheus: $media_prom_out"
  echo "  JSON:       $media_json_out"
  echo "  SQL:        $media_sql_out"
  echo "  Textfile:   $media_textfile_out"
}

# Single-shot RF validation: badge parse + Ekahau parse + manual template +
# optional correlate + SQL emit + optional DB load. No control/test split.
process_rf_validation() {
  local badge_mac="$1"
  local badge_input="$2"
  local run_id="$RUN_ID_BASE"

  if [[ "$RF_SKIP" == "1" ]]; then
    info "[rf] Skipping RF validation by request (VOCERA_SURVEY_SKIP_RF=1)"
    return 0
  fi
  if [[ ! -e "$RF_EKAHAU_PROJECT" ]]; then
    info "[rf] Skipping RF validation; Ekahau project not found: $RF_EKAHAU_PROJECT"
    return 0
  fi
  if [[ -z "$badge_input" ]]; then
    badge_input="$(latest_badge_input_for "$badge_mac")"
  fi
  if [[ -z "$badge_input" ]]; then
    info "[rf] Skipping RF validation; no badge diagnostic archive found in $RF_RAW_DIR for badge $badge_mac"
    return 0
  fi
  if [[ ! -e "$badge_input" ]]; then
    info "[rf] Skipping RF validation; badge diagnostic archive not found: $badge_input"
    return 0
  fi

  info "[rf] run_id=$run_id badge=$badge_mac badge_log=$badge_input ekahau=$RF_EKAHAU_PROJECT"

  info "[rf] Parsing badge diagnostics"
  run_env PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$RF_CONFIG" \
    --archive-dir "$RF_ARCHIVE_DIR" --archive-label "$run_id" parse-badge \
    --test-run-id "$run_id" \
    --input "$badge_input" \
    --badge-mac "$badge_mac" \
    --json-out "$RF_BADGE_JSON"

  info "[rf] Parsing Ekahau survey timestamps"
  run_env PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$RF_CONFIG" \
    --archive-dir "$RF_ARCHIVE_DIR" --archive-label "$run_id" parse-ekahau-json \
    --test-run-id "$run_id" \
    --input "$RF_EKAHAU_PROJECT" \
    --json-out "$RF_EKAHAU_JSON"

  info "[rf] Writing manual Ekahau observation template"
  run_env PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$RF_CONFIG" \
    --archive-dir "$RF_ARCHIVE_DIR" --archive-label "$run_id" manual-template \
    --badge-json "$RF_BADGE_JSON" \
    --ekahau-json "$RF_EKAHAU_JSON" \
    --csv-out "$RF_MANUAL_TEMPLATE"

  local correlated_this_run=0
  if [[ -f "$RF_MANUAL_CSV" ]]; then
    info "[rf] Correlating manual Ekahau observations"
    run_env PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$RF_CONFIG" \
      --archive-dir "$RF_ARCHIVE_DIR" --archive-label "$run_id" correlate \
      --template-csv "$RF_MANUAL_TEMPLATE" \
      --manual-csv "$RF_MANUAL_CSV" \
      --json-out "$RF_MATCHES_JSON" \
      --csv-out "$RF_MATCHES_CSV"
    correlated_this_run=1
  else
    info "[rf] Skipping correlation; optional manual CSV not present: $RF_MANUAL_CSV"
  fi

  info "[rf] Writing RF validation PostgreSQL import SQL"
  local sql_args=(
    PYTHONPATH=.
    python3 -m tools.vocera_rf_validation.cli
    --config "$RF_CONFIG"
    --archive-dir "$RF_ARCHIVE_DIR"
    --archive-label "$run_id"
    emit-sql
    --badge-json "$RF_BADGE_JSON"
    --ekahau-json "$RF_EKAHAU_JSON"
    --template-csv "$RF_MANUAL_TEMPLATE"
    --sql-out "$RF_SQL_OUT"
  )
  if [[ "$correlated_this_run" == "1" ]]; then
    sql_args+=(--matches-json "$RF_MATCHES_JSON")
  fi
  run_env "${sql_args[@]}"

  if [[ "$RF_LOAD_DB" == "1" ]]; then
    info "[rf] Loading RF validation PostgreSQL outputs"
    run "$RF_PSQL_BIN" "$RF_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$RF_SQL_OUT"
  fi

  set_rf_validation_in_manifest "$run_id" "$badge_mac" "$badge_input"

  echo
  echo "RF validation outputs refreshed (run_id=$run_id):"
  echo "  Badge JSON:   $RF_BADGE_JSON"
  echo "  Ekahau JSON:  $RF_EKAHAU_JSON"
  echo "  Manual CSV:   $RF_MANUAL_TEMPLATE"
  echo "  Matches JSON: $RF_MATCHES_JSON"
  echo "  Matches CSV:  $RF_MATCHES_CSV"
  echo "  SQL:          $RF_SQL_OUT"
}

# Manifest helpers - the file lives at $JOB_MANIFEST_DIR/$RUN_ID_BASE.json and
# is built up across this run: media entries appended per device, RF
# validation block set once.
append_media_to_manifest() {
  if [[ "$DRY_RUN" == "1" ]]; then return 0; fi
  mkdir -p "$JOB_MANIFEST_DIR"
  ROLE="$1" RUN_ID="$2" BADGE_MAC="$3" PCAP_DIR="$4" \
  MEDIA_PROM_OUT="$5" MEDIA_JSON_OUT="$6" MEDIA_SQL_OUT="$7" MEDIA_TEXTFILE_OUT="$8" \
  RUN_ID_BASE="$RUN_ID_BASE" UPLOAD_DIR="$UPLOAD_DIR" \
  RF_EKAHAU_PROJECT="$RF_EKAHAU_PROJECT" \
  python3 - "$JOB_MANIFEST_DIR/$RUN_ID_BASE.json" <<'PY'
import hashlib, json, os, sys
from datetime import datetime, timezone

def artifact(path):
    item = {"path": path, "exists": False}
    if not path or not os.path.isfile(path):
        return item
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    item.update({"exists": True, "size_bytes": os.path.getsize(path), "sha256": digest.hexdigest()})
    return item

manifest_path = sys.argv[1]
entry = {
    "role": os.environ["ROLE"] or "single",
    "test_run_id": os.environ["RUN_ID"],
    "badge_mac": os.environ["BADGE_MAC"],
    "pcap_dir": os.environ["PCAP_DIR"],
    "artifacts": [
        artifact(os.environ[k])
        for k in ("MEDIA_PROM_OUT", "MEDIA_JSON_OUT", "MEDIA_SQL_OUT", "MEDIA_TEXTFILE_OUT")
    ],
}
if os.path.isfile(manifest_path):
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
else:
    manifest = {
        "run_id_base": os.environ["RUN_ID_BASE"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upload_dir": os.environ.get("UPLOAD_DIR") or None,
        "shared": {"ekahau_project": os.environ["RF_EKAHAU_PROJECT"]},
        "media_devices": [],
        "rf_validation": None,
    }
manifest.setdefault("media_devices", [])
manifest["media_devices"] = [d for d in manifest["media_devices"] if d.get("role") != entry["role"]]
manifest["media_devices"].append(entry)
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

set_rf_validation_in_manifest() {
  if [[ "$DRY_RUN" == "1" ]]; then return 0; fi
  mkdir -p "$JOB_MANIFEST_DIR"
  RUN_ID="$1" BADGE_MAC="$2" BADGE_INPUT="$3" \
  RUN_ID_BASE="$RUN_ID_BASE" UPLOAD_DIR="$UPLOAD_DIR" \
  RF_EKAHAU_PROJECT="$RF_EKAHAU_PROJECT" RF_EKAHAU_JSON="$RF_EKAHAU_JSON" \
  RF_BADGE_JSON="$RF_BADGE_JSON" RF_MANUAL_TEMPLATE="$RF_MANUAL_TEMPLATE" \
  RF_MATCHES_JSON="$RF_MATCHES_JSON" RF_MATCHES_CSV="$RF_MATCHES_CSV" \
  RF_SQL_OUT="$RF_SQL_OUT" \
  python3 - "$JOB_MANIFEST_DIR/$RUN_ID_BASE.json" <<'PY'
import hashlib, json, os, sys
from datetime import datetime, timezone

def artifact(path):
    item = {"path": path, "exists": False}
    if not path or not os.path.isfile(path):
        return item
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    item.update({"exists": True, "size_bytes": os.path.getsize(path), "sha256": digest.hexdigest()})
    return item

manifest_path = sys.argv[1]
rf = {
    "test_run_id": os.environ["RUN_ID"],
    "badge_mac": os.environ["BADGE_MAC"],
    "badge_input": os.environ["BADGE_INPUT"],
    "artifacts": [
        artifact(os.environ[k])
        for k in (
            "RF_BADGE_JSON", "RF_EKAHAU_JSON", "RF_MANUAL_TEMPLATE",
            "RF_MATCHES_JSON", "RF_MATCHES_CSV", "RF_SQL_OUT",
        )
    ],
}
if os.path.isfile(manifest_path):
    with open(manifest_path, encoding="utf-8") as fh:
        manifest = json.load(fh)
else:
    manifest = {
        "run_id_base": os.environ["RUN_ID_BASE"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "upload_dir": os.environ.get("UPLOAD_DIR") or None,
        "shared": {"ekahau_project": os.environ["RF_EKAHAU_PROJECT"]},
        "media_devices": [],
        "rf_validation": None,
    }
manifest.setdefault("shared", {})["ekahau_project"] = os.environ["RF_EKAHAU_PROJECT"]
manifest["shared"]["ekahau_json"] = os.environ["RF_EKAHAU_JSON"]
manifest["rf_validation"] = rf
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2, sort_keys=True)
    fh.write("\n")
PY
}

# Process each device's pcaps, then run RF validation once.
for role in "${MEDIA_DEVICE_ROLES[@]}"; do
  process_media_for_device "$role"
done

process_rf_validation "$RF_BADGE_MAC" "$RF_BADGE_INPUT"

maybe_restore_output_owner

echo
echo "Run id base: $RUN_ID_BASE"
echo "Manifest:    $JOB_MANIFEST_DIR/$RUN_ID_BASE.json"
