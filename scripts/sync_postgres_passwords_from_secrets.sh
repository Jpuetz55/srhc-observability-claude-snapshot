#!/usr/bin/env bash
set -euo pipefail
# Apply materialized SOPS Postgres passwords to already-initialized local
# Postgres containers. The official Postgres image only consumes
# POSTGRES_PASSWORD during first database initialization; later secret changes
# need ALTER ROLE.

usage() {
  cat <<'EOF'
Usage:
  sudo bash scripts/sync_postgres_passwords_from_secrets.sh [--restart-grafana]

Reads /etc/grafana-mimir-observability/secrets/*.env and updates the matching
Postgres role password inside each local Podman-backed datasource container.

Options:
  --restart-grafana  Restart grafana-server after role passwords are updated.
EOF
}

die(){ echo "ERROR: $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

RESTART_GRAFANA=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --restart-grafana)
      RESTART_GRAFANA=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "Unknown argument: $1"
      ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  die "Run as root, for example: sudo bash scripts/sync_postgres_passwords_from_secrets.sh"
fi

need_cmd podman
need_cmd systemctl

sql_identifier() {
  local value="$1"
  value="${value//\"/\"\"}"
  printf '"%s"' "$value"
}

sql_literal() {
  local value="$1"
  value="${value//\'/\'\'}"
  printf "'%s'" "$value"
}

load_secret() {
  local env_file="$1" env_key="$2"
  [[ -r "$env_file" ]] || die "Secret env file is not readable: $env_file"
  # shellcheck disable=SC1090
  set -a; source "$env_file"; set +a
  [[ -n "${!env_key:-}" ]] || die "$env_key is empty after sourcing $env_file"
  printf '%s' "${!env_key}"
}

run_psql() {
  local container="$1" connect_user="$2" db="$3" sql="$4"
  printf '%s\n' "$sql" | podman exec -i "$container" \
    psql --username "$connect_user" --dbname "$db" --no-password \
      --set=ON_ERROR_STOP=1 --quiet >/dev/null
}

sync_role_password() {
  local label="$1" unit="$2" container="$3" db="$4" role="$5" env_file="$6" env_key="$7"
  local password role_ident password_literal sql

  password="$(load_secret "$env_file" "$env_key")"

  if ! systemctl is-active --quiet "$unit"; then
    echo "Starting $unit"
    systemctl start "$unit"
  fi
  podman container exists "$container" || die "Container is not present: $container"

  role_ident="$(sql_identifier "$role")"
  password_literal="$(sql_literal "$password")"
  sql="SET standard_conforming_strings = on; ALTER ROLE $role_ident WITH PASSWORD $password_literal;"

  if run_psql "$container" "$role" "$db" "$sql"; then
    echo "Updated $label role password: $role"
    return 0
  fi

  # Some clusters may still have the default postgres superuser. Try it as a
  # fallback, but do not require it because these containers are initialized
  # with service-specific superusers.
  if run_psql "$container" "postgres" "postgres" "$sql"; then
    echo "Updated $label role password via postgres superuser: $role"
    return 0
  fi

  die "Could not connect locally to $container as $role or postgres"
}

sync_role_password \
  "Network Topology" \
  "network-topology-postgres.service" \
  "network-topology-postgres" \
  "topology" \
  "topology" \
  "/etc/grafana-mimir-observability/secrets/topology-postgres.env" \
  "TOPOLOGY_POSTGRES_PASSWORD"

sync_role_password \
  "Vocera Media QoE" \
  "vocera-media-qoe-postgres.service" \
  "vocera-media-qoe-postgres" \
  "vocera_media_qoe" \
  "vocera_media_qoe" \
  "/etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env" \
  "VOCERA_MEDIA_QOE_POSTGRES_PASSWORD"

sync_role_password \
  "Vocera RF Validation" \
  "vocera-rf-validation-postgres.service" \
  "vocera-rf-validation-postgres" \
  "vocera_rf_validation" \
  "vocera_rf_validation" \
  "/etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env" \
  "VOCERA_RF_VALIDATION_POSTGRES_PASSWORD"

if [[ "$RESTART_GRAFANA" == "1" ]]; then
  systemctl restart grafana-server
  systemctl is-active --quiet grafana-server
  echo "Restarted grafana-server"
else
  echo "Postgres role passwords synced. Restart grafana-server if datasource auth was already cached."
fi
