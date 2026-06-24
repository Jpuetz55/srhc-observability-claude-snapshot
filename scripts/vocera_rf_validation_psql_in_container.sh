#!/usr/bin/env bash
set -euo pipefail
# Run psql inside the local Vocera RF validation PostgreSQL container.

container="${VOCERA_RF_VALIDATION_POSTGRES_CONTAINER_NAME:-vocera-rf-validation-postgres}"
inner_host="${VOCERA_RF_VALIDATION_POSTGRES_INNER_HOST:-127.0.0.1}"
inner_port="${VOCERA_RF_VALIDATION_POSTGRES_INNER_PORT:-5432}"
database="${VOCERA_RF_VALIDATION_POSTGRES_DB:-vocera_rf_validation}"
user="${VOCERA_RF_VALIDATION_POSTGRES_USER:-vocera_rf_validation}"
VOCERA_RF_VALIDATION_POSTGRES_SECRETS_FILE="${VOCERA_RF_VALIDATION_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env}"
if [[ -z "${PGPASSWORD:-}" && -z "${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}" && -r "$VOCERA_RF_VALIDATION_POSTGRES_SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$VOCERA_RF_VALIDATION_POSTGRES_SECRETS_FILE"; set +a
fi
password="${PGPASSWORD:-${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:?VOCERA_RF_VALIDATION_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export PGPASSWORD/VOCERA_RF_VALIDATION_POSTGRES_PASSWORD}}"
sslmode="${PGSSLMODE:-disable}"

if ! command -v podman >/dev/null 2>&1; then
  echo "Missing required command: podman" >&2
  exit 127
fi

podman_cmd=(podman)
if podman container exists "$container" 2>/dev/null; then
  podman_cmd=(podman)
elif sudo -n podman container exists "$container" 2>/dev/null; then
  podman_cmd=(sudo -n podman)
elif [[ -t 0 ]] && sudo podman container exists "$container" 2>/dev/null; then
  podman_cmd=(sudo podman)
else
  echo "PostgreSQL container is not present: $container" >&2
  echo "Run: make vocera-rf-validation-postgres-install" >&2
  exit 1
fi

args=()
sql_file=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    postgresql://*)
      # The host-side URL points at the port mapping. Inside the container,
      # connect directly to the local server with the configured db/user.
      ;;
    -h|--host|-p|--port)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for skipped psql option" >&2; exit 2; }
      ;;
    -f|--file)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for psql file option" >&2; exit 2; }
      sql_file="$1"
      ;;
    *)
      args+=("$1")
      ;;
  esac
  shift
done

psql_cmd=(
  "${podman_cmd[@]}" exec -i
  --env "PGPASSWORD=$password"
  --env "PGSSLMODE=$sslmode"
  "$container"
  psql --host "$inner_host" --port "$inner_port" --username "$user" --dbname "$database"
  "${args[@]}"
)

if [[ -n "$sql_file" ]]; then
  exec "${psql_cmd[@]}" <"$sql_file"
fi

exec "${psql_cmd[@]}"
