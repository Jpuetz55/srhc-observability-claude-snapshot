#!/usr/bin/env bash
set -euo pipefail
# Install a local PostgreSQL container used by the Grafana topology datasource.

# Print install usage and PostgreSQL environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_network_topology_postgres.sh [--enable] [--start-now]

Installs network-topology-postgres.service, backed by Podman and exposed on
127.0.0.1:15432 for Grafana datasource UID TOPOLOGY_DS.

Options:
  --enable     Enable network-topology-postgres.service.
  --start-now  Start network-topology-postgres.service after install.

Environment overrides:
  NETWORK_TOPOLOGY_REPO_ROOT      default: current repo root
  TOPOLOGY_POSTGRES_CONTAINER_NAME default: network-topology-postgres
  TOPOLOGY_POSTGRES_IMAGE         default: docker.io/postgres:16.4-alpine
  TOPOLOGY_POSTGRES_PORT          default: 15432
  TOPOLOGY_POSTGRES_DB            default: topology
  TOPOLOGY_POSTGRES_USER          default: topology
  TOPOLOGY_POSTGRES_PASSWORD      required; sourced from $TOPOLOGY_POSTGRES_SECRETS_FILE if set
  TOPOLOGY_POSTGRES_SECRETS_FILE  default: /etc/grafana-mimir-observability/secrets/topology-postgres.env
  TOPOLOGY_POSTGRES_DATA_DIR      default: /var/lib/network-topology/postgres
  TOPOLOGY_POSTGRES_INIT_DIR      default: /etc/network-topology-postgres/init
EOF
}

# Exit with a consistent install error.
die(){ echo "ERROR: $*" >&2; exit 1; }
# Assert that a required command is available before touching systemd.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

ENABLE_SERVICE=0
START_NOW=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --enable)
      ENABLE_SERVICE=1
      ;;
    --start-now)
      START_NOW=1
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
  die "Run as root, for example: sudo bash ./scripts/install_network_topology_postgres.sh"
fi

need_cmd install
need_cmd podman
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${NETWORK_TOPOLOGY_REPO_ROOT:-$DEFAULT_ROOT}"
UNIT_SRC="$REPO_ROOT/systemd/network-topology-postgres.service"
SCHEMA_SRC="$REPO_ROOT/topology/postgres/init/001_topology_tables.sql"
[[ -f "$UNIT_SRC" ]] || die "Missing unit file under repo root: $UNIT_SRC"
[[ -f "$SCHEMA_SRC" ]] || die "Missing topology schema SQL under repo root: $SCHEMA_SRC"

TOPOLOGY_POSTGRES_CONTAINER_NAME="${TOPOLOGY_POSTGRES_CONTAINER_NAME:-network-topology-postgres}"
TOPOLOGY_POSTGRES_IMAGE="${TOPOLOGY_POSTGRES_IMAGE:-docker.io/postgres:16.4-alpine}"
TOPOLOGY_POSTGRES_PORT="${TOPOLOGY_POSTGRES_PORT:-15432}"
TOPOLOGY_POSTGRES_DB="${TOPOLOGY_POSTGRES_DB:-topology}"
TOPOLOGY_POSTGRES_USER="${TOPOLOGY_POSTGRES_USER:-topology}"
TOPOLOGY_POSTGRES_SECRETS_FILE="${TOPOLOGY_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/topology-postgres.env}"
if [[ -z "${TOPOLOGY_POSTGRES_PASSWORD:-}" && -f "$TOPOLOGY_POSTGRES_SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$TOPOLOGY_POSTGRES_SECRETS_FILE"; set +a
fi
TOPOLOGY_POSTGRES_PASSWORD="${TOPOLOGY_POSTGRES_PASSWORD:?TOPOLOGY_POSTGRES_PASSWORD not set. Run 'sudo bash scripts/install_secrets.sh' to materialize $TOPOLOGY_POSTGRES_SECRETS_FILE first, or export TOPOLOGY_POSTGRES_PASSWORD explicitly.}"
TOPOLOGY_POSTGRES_DATA_DIR="${TOPOLOGY_POSTGRES_DATA_DIR:-/var/lib/network-topology/postgres}"
TOPOLOGY_POSTGRES_INIT_DIR="${TOPOLOGY_POSTGRES_INIT_DIR:-/etc/network-topology-postgres/init}"

install -o root -g root -m 0644 "$UNIT_SRC" /etc/systemd/system/network-topology-postgres.service
install -d -o root -g root -m 0755 "$TOPOLOGY_POSTGRES_INIT_DIR"
install -o root -g root -m 0644 "$SCHEMA_SRC" "$TOPOLOGY_POSTGRES_INIT_DIR/001_topology_tables.sql"
install -d -o root -g root -m 0755 "$TOPOLOGY_POSTGRES_DATA_DIR"

if [[ ! -f /etc/default/network-topology-postgres ]]; then
  cat >/etc/default/network-topology-postgres <<EOF
TOPOLOGY_POSTGRES_CONTAINER_NAME=$TOPOLOGY_POSTGRES_CONTAINER_NAME
TOPOLOGY_POSTGRES_IMAGE=$TOPOLOGY_POSTGRES_IMAGE
TOPOLOGY_POSTGRES_PORT=$TOPOLOGY_POSTGRES_PORT
TOPOLOGY_POSTGRES_DB=$TOPOLOGY_POSTGRES_DB
TOPOLOGY_POSTGRES_USER=$TOPOLOGY_POSTGRES_USER
TOPOLOGY_POSTGRES_PASSWORD=$TOPOLOGY_POSTGRES_PASSWORD
TOPOLOGY_POSTGRES_DATA_DIR=$TOPOLOGY_POSTGRES_DATA_DIR
TOPOLOGY_POSTGRES_INIT_DIR=$TOPOLOGY_POSTGRES_INIT_DIR
EOF
else
  echo "Keeping existing /etc/default/network-topology-postgres"
fi
chown root:root /etc/default/network-topology-postgres
chmod 0600 /etc/default/network-topology-postgres

systemctl daemon-reload

if [[ "$ENABLE_SERVICE" == "1" ]]; then
  systemctl enable network-topology-postgres.service
fi

if [[ "$START_NOW" == "1" ]]; then
  systemctl restart network-topology-postgres.service
  systemctl status network-topology-postgres.service --no-pager -l
fi

echo "Installed network-topology-postgres.service"
echo "Datasource listener: 127.0.0.1:$TOPOLOGY_POSTGRES_PORT"
echo "Config file: /etc/default/network-topology-postgres"
