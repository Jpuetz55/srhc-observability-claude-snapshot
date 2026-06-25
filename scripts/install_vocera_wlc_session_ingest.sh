#!/usr/bin/env bash
set -euo pipefail
# Install the WLC capture-session EPC ingest service/timer.
#
# A one-minute timer pokes the local Study Web ingest-scan endpoint so an
# exported EPC the WLC SCP-pushes to the collector is validated, finalized as a
# service-owned pcaps/ artifact, registered as a wlc_epc capture, and parsed --
# with no operator action. Study Web owns the ingest; this unit only triggers it
# on localhost. It stores no WLC or SCP secrets and never SSHes.

usage() {
  cat <<'EOF'
Usage:
  sudo bash ./scripts/install_vocera_wlc_session_ingest.sh [--start-now] [--no-enable]

Installs the Vocera WLC capture-session EPC ingest service/timer and, by
default, enables and starts the one-minute timer.

Options:
  --start-now  Run vocera-media-qoe-wlc-session-ingest.service once after install.
  --no-enable  Install the units without enabling/starting the timer (useful for a
               rehearsal install where the ingest scan is triggered manually).
  -h, --help   Show this help.

Environment overrides (written to /etc/default only when that file is absent):
  STUDY_WEB_INGEST_HOST       default: 127.0.0.1
  STUDY_WEB_INGEST_PORT       default: 8097
  STUDY_WEB_INGEST_TIMEOUT    default: 600  (curl max-time; keep > parser timeout)
  VOCERA_MEDIA_QOE_RAW_DIR    default: /var/lib/vocera-media-qoe/raw
  STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT
                              default: $VOCERA_MEDIA_QOE_RAW_DIR/wlc-sessions
  STUDY_WEB_WLC_INGEST_LOCK_FILE
                              default: /run/vocera-media-qoe/wlc-session-ingest.lock
  STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES
                              default: 536870912
  VOCERA_MEDIA_QOE_REPO_ROOT  default: current repo root
EOF
}

# Exit with a consistent install error.
die(){ echo "ERROR: $*" >&2; exit 1; }
# Assert that a required command is available before touching systemd.
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }
# Add a key to the EnvironmentFile only when the operator has not set it.
ensure_env_key(){
  local file="$1" key="$2" value="$3"
  if ! grep -q "^${key}=" "$file"; then
    printf '%s=%s\n' "$key" "$value" >>"$file"
  fi
}

START_NOW=0
ENABLE_TIMER=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --start-now) START_NOW=1 ;;
    --no-enable) ENABLE_TIMER=0 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; die "Unknown argument: $1" ;;
  esac
  shift
done

if [[ "$EUID" -ne 0 ]]; then
  die "Run as root, for example: sudo bash ./scripts/install_vocera_wlc_session_ingest.sh"
fi

need_cmd install
need_cmd systemctl

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="${VOCERA_MEDIA_QOE_REPO_ROOT:-$DEFAULT_ROOT}"
SERVICE=vocera-media-qoe-wlc-session-ingest.service
TIMER=vocera-media-qoe-wlc-session-ingest.timer
[[ -f "$REPO_ROOT/systemd/$SERVICE" ]] || die "Missing unit file under repo root: $REPO_ROOT/systemd/$SERVICE"
[[ -f "$REPO_ROOT/systemd/$TIMER" ]] || die "Missing timer file under repo root: $REPO_ROOT/systemd/$TIMER"
[[ -f "$REPO_ROOT/scripts/run_vocera_wlc_session_ingest.sh" ]] || die "Missing trigger script under repo root: $REPO_ROOT/scripts/run_vocera_wlc_session_ingest.sh"

STUDY_WEB_INGEST_HOST="${STUDY_WEB_INGEST_HOST:-127.0.0.1}"
STUDY_WEB_INGEST_PORT="${STUDY_WEB_INGEST_PORT:-8097}"
STUDY_WEB_INGEST_TIMEOUT="${STUDY_WEB_INGEST_TIMEOUT:-600}"
VOCERA_MEDIA_QOE_RAW_DIR="${VOCERA_MEDIA_QOE_RAW_DIR:-/var/lib/vocera-media-qoe/raw}"
STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT="${STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT:-$VOCERA_MEDIA_QOE_RAW_DIR/wlc-sessions}"
STUDY_WEB_WLC_INGEST_LOCK_FILE="${STUDY_WEB_WLC_INGEST_LOCK_FILE:-/run/vocera-media-qoe/wlc-session-ingest.lock}"
STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES="${STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES:-536870912}"

install -o root -g root -m 0644 "$REPO_ROOT/systemd/$SERVICE" "/etc/systemd/system/$SERVICE"
install -o root -g root -m 0644 "$REPO_ROOT/systemd/$TIMER" "/etc/systemd/system/$TIMER"

# Pin WorkingDirectory to the real repo root so the relative ExecStart trigger
# script resolves regardless of where the repo is deployed.
install -d -o root -g root -m 0755 "/etc/systemd/system/$SERVICE.d"
cat >"/etc/systemd/system/$SERVICE.d/override.conf" <<EOF
[Service]
WorkingDirectory=$REPO_ROOT
EOF

DEFAULT_FILE=/etc/default/vocera-media-qoe-wlc-session-ingest
if [[ ! -f "$DEFAULT_FILE" ]]; then
  cat >"$DEFAULT_FILE" <<EOF
STUDY_WEB_INGEST_HOST=$STUDY_WEB_INGEST_HOST
STUDY_WEB_INGEST_PORT=$STUDY_WEB_INGEST_PORT
STUDY_WEB_INGEST_TIMEOUT=$STUDY_WEB_INGEST_TIMEOUT
VOCERA_MEDIA_QOE_RAW_DIR=$VOCERA_MEDIA_QOE_RAW_DIR
STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT=$STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT
STUDY_WEB_WLC_INGEST_LOCK_FILE=$STUDY_WEB_WLC_INGEST_LOCK_FILE
STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES=$STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES
EOF
else
  echo "Keeping existing $DEFAULT_FILE"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_INGEST_HOST "$STUDY_WEB_INGEST_HOST"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_INGEST_PORT "$STUDY_WEB_INGEST_PORT"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_INGEST_TIMEOUT "$STUDY_WEB_INGEST_TIMEOUT"
  ensure_env_key "$DEFAULT_FILE" VOCERA_MEDIA_QOE_RAW_DIR "$VOCERA_MEDIA_QOE_RAW_DIR"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT "$STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_WLC_INGEST_LOCK_FILE "$STUDY_WEB_WLC_INGEST_LOCK_FILE"
  ensure_env_key "$DEFAULT_FILE" STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES "$STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES"
fi

systemctl daemon-reload

if [[ "$START_NOW" == "1" ]]; then
  systemctl start "$SERVICE"
  systemctl status "$SERVICE" --no-pager -l || true
fi

if [[ "$ENABLE_TIMER" == "1" ]]; then
  systemctl enable --now "$TIMER"
  systemctl is-enabled "$TIMER" || true
  systemctl is-active "$TIMER" || true
  systemctl list-timers "$TIMER" --no-pager || true
else
  echo "Units installed but timer not enabled (--no-enable). Enable with: systemctl enable --now $TIMER"
fi

echo "Installed $SERVICE and $TIMER"
echo "Repo root override: $REPO_ROOT"
echo "Config file: $DEFAULT_FILE"
echo "Trigger: POST http://$STUDY_WEB_INGEST_HOST:$STUDY_WEB_INGEST_PORT/api/media-qoe/wlc/sessions/ingest-scan (localhost only)"
