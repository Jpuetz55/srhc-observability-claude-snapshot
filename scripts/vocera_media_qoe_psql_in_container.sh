#!/usr/bin/env bash
set -euo pipefail
# Run psql inside the local Vocera media QoE PostgreSQL container.

container="${VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME:-vocera-media-qoe-postgres}"
inner_host="${VOCERA_MEDIA_QOE_POSTGRES_INNER_HOST:-127.0.0.1}"
inner_port="${VOCERA_MEDIA_QOE_POSTGRES_INNER_PORT:-5432}"
database="${VOCERA_MEDIA_QOE_POSTGRES_DB:-vocera_media_qoe}"
user="${VOCERA_MEDIA_QOE_POSTGRES_USER:-vocera_media_qoe}"
VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE="${VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env}"
if [[ -z "${PGPASSWORD:-}" && -z "${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:-}" && -r "$VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE"; set +a
fi
password="${PGPASSWORD:-${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:?VOCERA_MEDIA_QOE_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export PGPASSWORD/VOCERA_MEDIA_QOE_POSTGRES_PASSWORD}}"
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
  echo "Run: make vocera-media-qoe-postgres-install" >&2
  exit 1
fi

args=()
sql_file=""
connection_url=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    postgresql://*)
      [[ -z "$connection_url" ]] || {
        echo "Only one PostgreSQL URL may be supplied." >&2
        exit 2
      }
      connection_url="$1"
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

# The host-side URL may point at the published container port, but its database
# path is still the caller's explicit target. Preserve it when connecting
# inside the container rather than silently falling back to the default DB.
if [[ -n "$connection_url" ]]; then
  authority_and_path="${connection_url#postgresql://}"

  if [[ "$authority_and_path" != */* ]]; then
    echo "PostgreSQL URL must include a database name: $connection_url" >&2
    exit 2
  fi

  database_from_url="${authority_and_path#*/}"
  database_from_url="${database_from_url%%\?*}"
  database_from_url="${database_from_url%%\#*}"

  if [[ -z "$database_from_url" || "$database_from_url" == */* ||
        ! "$database_from_url" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]]; then
    echo "Unsupported database name in PostgreSQL URL: $connection_url" >&2
    exit 2
  fi

  database="$database_from_url"
fi

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
