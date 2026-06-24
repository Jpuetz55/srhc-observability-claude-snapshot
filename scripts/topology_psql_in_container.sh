#!/usr/bin/env bash
set -euo pipefail
# psql shim for hosts where the PostgreSQL client is only available inside the
# topology Postgres container.

container="${TOPOLOGY_POSTGRES_CONTAINER_NAME:-network-topology-postgres}"
inner_host="${TOPOLOGY_POSTGRES_INNER_HOST:-127.0.0.1}"
inner_port="${TOPOLOGY_POSTGRES_INNER_PORT:-5432}"
# Source the sops-materialized env file when neither PGPASSWORD nor the
# explicit override is set in the caller's environment.
TOPOLOGY_POSTGRES_SECRETS_FILE="${TOPOLOGY_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/topology-postgres.env}"
if [[ -z "${PGPASSWORD:-}" && -z "${TOPOLOGY_POSTGRES_PASSWORD:-}" && -r "$TOPOLOGY_POSTGRES_SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$TOPOLOGY_POSTGRES_SECRETS_FILE"; set +a
fi
password="${PGPASSWORD:-${TOPOLOGY_POSTGRES_PASSWORD:?TOPOLOGY_POSTGRES_PASSWORD not set; run 'sudo bash scripts/install_secrets.sh' or export PGPASSWORD/TOPOLOGY_POSTGRES_PASSWORD}}"
sslmode="${PGSSLMODE:-disable}"
podman_cmd=(podman)
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
default_published_host_dir="$repo_root/../Network-Topology/data/published"
published_host_dir="${TOPOLOGY_PUBLISHED_DIR:-$default_published_host_dir}"
published_container_dir="${TOPOLOGY_PUBLISHED_CONTAINER_DIR:-/tmp/network-topology-published}"

args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --host|--port|-h|-p)
      shift
      [[ $# -gt 0 ]] || { echo "Missing value for skipped psql option" >&2; exit 2; }
      shift
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if podman container exists "$container" 2>/dev/null; then
  podman_cmd=(podman)
elif sudo -n podman container exists "$container" 2>/dev/null; then
  podman_cmd=(sudo -n podman)
else
  cat >&2 <<EOF
Unable to find topology Postgres container: $container

The service normally runs the container as root, so run:
  sudo -v
  make topology-load

If the service is not running, run:
  make topology-postgres-install
EOF
  exit 125
fi

if [[ -d "$published_host_dir" ]]; then
  published_host_dir="$(cd "$published_host_dir" && pwd -P)"
fi

sql_tmp="$(mktemp)"
trap 'rm -f "$sql_tmp"' EXIT
cat >"$sql_tmp"

if [[ -s "$sql_tmp" && -d "$published_host_dir" ]]; then
  "${podman_cmd[@]}" exec "$container" mkdir -p "$published_container_dir"
  "${podman_cmd[@]}" cp "$published_host_dir/." "$container:$published_container_dir"
  sed_host_path="$(printf '%s' "$published_host_dir" | sed 's/[&|]/\\&/g')"
  sed_container_path="$(printf '%s' "$published_container_dir" | sed 's/[&|]/\\&/g')"
  sed "s|$sed_host_path|$sed_container_path|g" "$sql_tmp" | "${podman_cmd[@]}" exec -i \
    --env "PGPASSWORD=$password" \
    --env "PGSSLMODE=$sslmode" \
    "$container" \
    psql --host "$inner_host" --port "$inner_port" "${args[@]}"
else
  "${podman_cmd[@]}" exec -i \
  --env "PGPASSWORD=$password" \
  --env "PGSSLMODE=$sslmode" \
  "$container" \
    psql --host "$inner_host" --port "$inner_port" "${args[@]}" <"$sql_tmp"
fi
