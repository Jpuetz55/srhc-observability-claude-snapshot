#!/usr/bin/env bash
set -euo pipefail
# Install a local PostgreSQL container for Vocera media QoE capture-time history.

# Print install usage and PostgreSQL environment overrides.
usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_vocera_media_qoe_postgres.sh [--enable] [--start-now]

Installs vocera-media-qoe-postgres.service, backed by Podman and exposed on
127.0.0.1:15434 for Grafana datasource UID VOCERA_MEDIA_QOE_DS.

Options:
  --enable     Enable vocera-media-qoe-postgres.service.
  --start-now  Start vocera-media-qoe-postgres.service after install.

Environment overrides:
  VOCERA_MEDIA_QOE_REPO_ROOT                    default: current repo root
  VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME      default: vocera-media-qoe-postgres
  VOCERA_MEDIA_QOE_POSTGRES_IMAGE               default: docker.io/postgres:16.4-alpine
  VOCERA_MEDIA_QOE_POSTGRES_PORT                default: 15434
  VOCERA_MEDIA_QOE_POSTGRES_DB                  default: vocera_media_qoe
  VOCERA_MEDIA_QOE_POSTGRES_USER                default: vocera_media_qoe
  VOCERA_MEDIA_QOE_POSTGRES_PASSWORD            required; sourced from VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE if set
  VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE        default: /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env
  VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR            default: /var/lib/vocera-media-qoe/postgres
  VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR            default: /etc/vocera-media-qoe-postgres/init
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
  die "Run as root, for example: sudo bash ./scripts/install_vocera_media_qoe_postgres.sh"
fi

need_cmd install
need_cmd podman
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${VOCERA_MEDIA_QOE_REPO_ROOT:-$DEFAULT_ROOT}"
UNIT_SRC="$REPO_ROOT/systemd/vocera-media-qoe-postgres.service"
SCHEMA_SRC="$REPO_ROOT/sql/vocera_media_qoe_schema.sql"
VIEWS_SRC="$REPO_ROOT/sql/vocera_media_qoe_views.sql"
[[ -f "$UNIT_SRC" ]] || die "Missing unit file under repo root: $UNIT_SRC"
[[ -f "$SCHEMA_SRC" ]] || die "Missing schema SQL under repo root: $SCHEMA_SRC"
[[ -f "$VIEWS_SRC" ]] || die "Missing views SQL under repo root: $VIEWS_SRC"

VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME="${VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME:-vocera-media-qoe-postgres}"
VOCERA_MEDIA_QOE_POSTGRES_IMAGE="${VOCERA_MEDIA_QOE_POSTGRES_IMAGE:-docker.io/postgres:16.4-alpine}"
VOCERA_MEDIA_QOE_POSTGRES_PORT="${VOCERA_MEDIA_QOE_POSTGRES_PORT:-15434}"
VOCERA_MEDIA_QOE_POSTGRES_DB="${VOCERA_MEDIA_QOE_POSTGRES_DB:-vocera_media_qoe}"
VOCERA_MEDIA_QOE_POSTGRES_USER="${VOCERA_MEDIA_QOE_POSTGRES_USER:-vocera_media_qoe}"
VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE="${VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE:-/etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env}"
if [[ -z "${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:-}" && -f "$VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE"; set +a
fi
VOCERA_MEDIA_QOE_POSTGRES_PASSWORD="${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD:?VOCERA_MEDIA_QOE_POSTGRES_PASSWORD not set. Run 'sudo bash scripts/install_secrets.sh' to materialize $VOCERA_MEDIA_QOE_POSTGRES_SECRETS_FILE first, or export VOCERA_MEDIA_QOE_POSTGRES_PASSWORD explicitly.}"
VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR="${VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR:-/var/lib/vocera-media-qoe/postgres}"
VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR="${VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR:-/etc/vocera-media-qoe-postgres/init}"

install -o root -g root -m 0644 "$UNIT_SRC" /etc/systemd/system/vocera-media-qoe-postgres.service
install -d -o root -g root -m 0755 "$VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR"
install -o root -g root -m 0644 "$SCHEMA_SRC" "$VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR/001_vocera_media_qoe_schema.sql"
install -o root -g root -m 0644 "$VIEWS_SRC" "$VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR/002_vocera_media_qoe_views.sql"
install -d -o root -g root -m 0755 "$VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR"

DEFAULT_FILE=/etc/default/vocera-media-qoe-postgres
if [[ ! -f "$DEFAULT_FILE" ]]; then
  cat >"$DEFAULT_FILE" <<EOF
VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME=$VOCERA_MEDIA_QOE_POSTGRES_CONTAINER_NAME
VOCERA_MEDIA_QOE_POSTGRES_IMAGE=$VOCERA_MEDIA_QOE_POSTGRES_IMAGE
VOCERA_MEDIA_QOE_POSTGRES_PORT=$VOCERA_MEDIA_QOE_POSTGRES_PORT
VOCERA_MEDIA_QOE_POSTGRES_DB=$VOCERA_MEDIA_QOE_POSTGRES_DB
VOCERA_MEDIA_QOE_POSTGRES_USER=$VOCERA_MEDIA_QOE_POSTGRES_USER
VOCERA_MEDIA_QOE_POSTGRES_PASSWORD=$VOCERA_MEDIA_QOE_POSTGRES_PASSWORD
VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR=$VOCERA_MEDIA_QOE_POSTGRES_DATA_DIR
VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR=$VOCERA_MEDIA_QOE_POSTGRES_INIT_DIR
EOF
else
  echo "Keeping existing $DEFAULT_FILE"
fi
chown root:root "$DEFAULT_FILE"
chmod 0600 "$DEFAULT_FILE"

systemctl daemon-reload

if [[ "$ENABLE_SERVICE" == "1" ]]; then
  systemctl enable vocera-media-qoe-postgres.service
fi

if [[ "$START_NOW" == "1" ]]; then
  systemctl restart vocera-media-qoe-postgres.service
  systemctl status vocera-media-qoe-postgres.service --no-pager -l
fi

echo "Installed vocera-media-qoe-postgres.service"
echo "Datasource listener: 127.0.0.1:$VOCERA_MEDIA_QOE_POSTGRES_PORT"
echo "Config file: $DEFAULT_FILE"
