#!/usr/bin/env bash
# Server-side iPad/WLC RF validation refresh for manually staged WLC client
# detail snapshots. This is intentionally independent from Catalyst Center
# device-command workflows and the Vocera ICAP control/test flow.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

run_id="${IPAD_RF_VALIDATION_RUN_ID:-ipad_wlc_ekahau_$(date +%Y_%m_%d_%H%M%S)}"
config="${IPAD_RF_VALIDATION_CONFIG:-config/ipad-rf-validation.yaml}"
client_mac="${IPAD_RF_VALIDATION_CLIENT_MAC:-}"
client_model="${IPAD_RF_VALIDATION_CLIENT_MODEL:-iPad}"
ekahau_project="${IPAD_RF_VALIDATION_EKAHAU_PROJECT:-}"
out_dir="${IPAD_RF_VALIDATION_OUT_DIR:-data/ipad-rf-validation/out/$run_id}"
archive_dir="${IPAD_RF_VALIDATION_ARCHIVE_DIR:-data/ipad-rf-validation/out/archives}"
install_db="${IPAD_RF_VALIDATION_INSTALL_DB:-1}"
load_db="${IPAD_RF_VALIDATION_LOAD_DB:-1}"
psql_bin="${IPAD_RF_VALIDATION_PSQL_BIN:-scripts/vocera_rf_validation_psql_in_container.sh}"
database_url="${IPAD_RF_VALIDATION_DATABASE_URL:-${VOCERA_RF_VALIDATION_DATABASE_URL:-}}"

if [[ -z "$client_mac" ]]; then
  echo "ERROR: set IPAD_RF_VALIDATION_CLIENT_MAC to the iPad Wi-Fi MAC." >&2
  exit 1
fi

if [[ "$run_id" != ipad_* ]]; then
  echo "ERROR: iPad RF validation run ids must start with ipad_ so dashboards stay separated." >&2
  exit 1
fi

if [[ -z "$ekahau_project" ]]; then
  echo "ERROR: set IPAD_RF_VALIDATION_EKAHAU_PROJECT to the Ekahau .esx/.json/.zip survey input." >&2
  exit 1
fi

if [[ ! -e "$ekahau_project" ]]; then
  echo "ERROR: Ekahau input not found: $ekahau_project" >&2
  exit 1
fi

rf_env_path="/etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env"
if [[ -z "$database_url" && -r "$rf_env_path" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$rf_env_path"
  set +a
  db_credential="${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}"
  if [[ -n "$db_credential" ]]; then
    database_url="postgresql://vocera_rf_validation:${db_credential}@127.0.0.1:15433/vocera_rf_validation"
  fi
fi

mkdir -p "$out_dir" "$archive_dir"

client_detail_dir="$out_dir/client-detail-snapshots"
client_json="$out_dir/ipad_scan_events.json"
ekahau_json="$out_dir/ekahau_survey_points.json"
manual_template="$out_dir/manual_ekahau_observations_template.csv"
sql_out="$out_dir/ipad_rf_validation_import.sql"

echo "==> Run id: $run_id"
echo "==> iPad client MAC: $client_mac"
echo "==> Ekahau project: $ekahau_project"
echo "==> Output dir: $out_dir"
echo "==> Collection phase: manual snapshots only"

mkdir -p "$client_detail_dir"
if ! find "$client_detail_dir" -type f -name 'client_detail_*.txt' -print -quit | grep -q .; then
  echo "ERROR: no manually collected WLC client-detail snapshots found under $client_detail_dir" >&2
  echo "Stage files as $client_detail_dir/client_detail_<index>_<timestamp>.txt before running." >&2
  exit 1
fi

PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli \
  --config "$config" \
  --archive-dir "$archive_dir" \
  --archive-label "$run_id" \
  parse-ipad-client-detail \
  --test-run-id "$run_id" \
  --input "$client_detail_dir" \
  --client-mac "$client_mac" \
  --client-model "$client_model" \
  --json-out "$client_json"

PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli \
  --config "$config" \
  --archive-dir "$archive_dir" \
  --archive-label "$run_id" \
  parse-ekahau-json \
  --test-run-id "$run_id" \
  --input "$ekahau_project" \
  --json-out "$ekahau_json"

PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli \
  --config "$config" \
  --archive-dir "$archive_dir" \
  --archive-label "$run_id" \
  manual-template \
  --badge-json "$client_json" \
  --ekahau-json "$ekahau_json" \
  --csv-out "$manual_template"

PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli \
  --config "$config" \
  --archive-dir "$archive_dir" \
  --archive-label "$run_id" \
  emit-sql \
  --badge-json "$client_json" \
  --ekahau-json "$ekahau_json" \
  --template-csv "$manual_template" \
  --sql-out "$sql_out"

if [[ "$install_db" != "0" ]]; then
  if [[ -z "$database_url" ]]; then
    echo "ERROR: database URL is empty. Set IPAD_RF_VALIDATION_DATABASE_URL or install RF-validation secrets." >&2
    exit 1
  fi
  PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config "$config" install-db \
    --postgres-url "$database_url" \
    --psql-bin "$psql_bin"
fi

if [[ "$load_db" != "0" ]]; then
  if [[ -z "$database_url" ]]; then
    echo "ERROR: database URL is empty. Set IPAD_RF_VALIDATION_DATABASE_URL or install RF-validation secrets." >&2
    exit 1
  fi
  "$psql_bin" "$database_url" -v ON_ERROR_STOP=1 -f "$sql_out"
fi

echo "==> iPad RF validation refresh complete."
echo "==> Manual-entry template: $manual_template"
echo "==> SQL import: $sql_out"
