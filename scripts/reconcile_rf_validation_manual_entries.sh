#!/usr/bin/env bash
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RF_PSQL_BIN="${VOCERA_RF_VALIDATION_PSQL_BIN:-scripts/vocera_rf_validation_psql_in_container.sh}"

if [[ -z "${VOCERA_RF_VALIDATION_DATABASE_URL:-}" && -z "${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env; set +a
fi

RF_DATABASE_URL="${VOCERA_RF_VALIDATION_DATABASE_URL:-postgresql://vocera_rf_validation:${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:?VOCERA_RF_VALIDATION_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export VOCERA_RF_VALIDATION_DATABASE_URL}@127.0.0.1:15433/vocera_rf_validation}"

echo "Applying RF validation schema/views..."
PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli install-db \
  --postgres-url "$RF_DATABASE_URL" \
  --psql-bin "$RF_PSQL_BIN"

echo "Reconciling completed manual entries against pending candidates..."
"$RF_PSQL_BIN" "$RF_DATABASE_URL" \
  -v ON_ERROR_STOP=1 \
  -f sql/vocera_rf_validation_reconcile_manual_entries.sql
