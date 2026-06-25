#!/usr/bin/env bash
set -euo pipefail
# Open a human-operated WLC SSH console while recording output-only evidence.
#
# This is deliberately not a command runner. It starts an ordinary interactive
# SSH session and records terminal output with util-linux script(1). It never
# logs stdin, never supplies a password, and never replays commands.

usage() {
  cat <<'EOF'
Usage:
  bash scripts/run_vocera_wlc_session_console.sh \
    --session-dir /var/lib/vocera-media-qoe/raw/wlc-sessions/<study>/<session> \
    --wlc-host SRHC-WLC-40G-SEC \
    --wlc-user <operator-wlc-user> [--wlc-port 22] [--operator name]

The WLC SSH password and the SCP export password are entered interactively in
the terminal. They are not stored by this script, Study Web, or PostgreSQL.

Output artifacts:
  cli/terminal/wlc-terminal-<timestamp>.out
  cli/terminal/wlc-terminal-<timestamp>.timing
  cli/terminal/wlc-terminal-<timestamp>.json
EOF
}

die(){ echo "ERROR: $*" >&2; exit 1; }
need_cmd(){ command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"; }

SESSION_DIR=""
WLC_HOST=""
WLC_USER=""
WLC_PORT="22"
OPERATOR="${USER:-unknown}"
RECORDER_VERSION="1"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --session-dir)
      shift; [[ $# -gt 0 ]] || die "missing value for --session-dir"; SESSION_DIR="$1" ;;
    --wlc-host)
      shift; [[ $# -gt 0 ]] || die "missing value for --wlc-host"; WLC_HOST="$1" ;;
    --wlc-user)
      shift; [[ $# -gt 0 ]] || die "missing value for --wlc-user"; WLC_USER="$1" ;;
    --wlc-port)
      shift; [[ $# -gt 0 ]] || die "missing value for --wlc-port"; WLC_PORT="$1" ;;
    --operator)
      shift; [[ $# -gt 0 ]] || die "missing value for --operator"; OPERATOR="$1" ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      usage; die "unknown argument: $1" ;;
  esac
  shift
done

[[ -n "$SESSION_DIR" ]] || die "Set --session-dir"
[[ -n "$WLC_HOST" ]] || die "Set --wlc-host"
[[ -n "$WLC_USER" ]] || die "Set --wlc-user"
[[ "$WLC_PORT" =~ ^[0-9]+$ ]] || die "--wlc-port must be numeric"
[[ "$WLC_HOST" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] || die "--wlc-host must contain only letters, digits, dots, underscores, or hyphens and must start with a letter or digit"
[[ "$WLC_USER" =~ ^[A-Za-z_][A-Za-z0-9._-]*$ ]] || die "--wlc-user must contain only letters, digits, dots, underscores, or hyphens and must start with a letter or underscore"
[[ -f "$SESSION_DIR/session.json" ]] || die "session.json not found under --session-dir"
[[ -t 0 && -t 1 ]] || die "Run this from an interactive terminal; stdin/stdout must be a TTY"

need_cmd script
need_cmd ssh
need_cmd sha256sum
need_cmd python3

umask 077
terminal_dir="$SESSION_DIR/cli/terminal"
mkdir -p "$terminal_dir"
chmod 0700 "$terminal_dir"

stamp="$(date -u +%Y%m%dT%H%M%SZ)"
base="$terminal_dir/wlc-terminal-$stamp"
out_tmp="$base.out.tmp"
timing_tmp="$base.timing.tmp"
out_file="$base.out"
timing_file="$base.timing"
meta_file="$base.json"
started_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

echo "Opening output-recorded WLC console for session: $SESSION_DIR"
echo "WLC target: ${WLC_USER}@${WLC_HOST}:${WLC_PORT}"
echo "Output log: $out_file"
echo "Timing log: $timing_file"
echo
echo "Security: this records terminal OUTPUT only. It does not use --log-in or --log-io."
echo "Do not paste secrets into visible command text."
echo

set +e
script -q -f -e --log-out "$out_tmp" --log-timing "$timing_tmp" --command "ssh -tt -p '$WLC_PORT' '$WLC_USER@$WLC_HOST'"
exit_code=$?
set -e

ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
mv "$out_tmp" "$out_file"
mv "$timing_tmp" "$timing_file"
chmod 0600 "$out_file" "$timing_file"

output_sha256="$(sha256sum "$out_file" | awk '{print $1}')"
timing_sha256="$(sha256sum "$timing_file" | awk '{print $1}')"
export SESSION_DIR WLC_HOST WLC_USER WLC_PORT OPERATOR RECORDER_VERSION
export started_at ended_at exit_code out_file timing_file output_sha256 timing_sha256 meta_file
python3 - <<'PY'
import json
import os
from pathlib import Path

session_dir = Path(os.environ["SESSION_DIR"])
session = {}
try:
    session = json.loads((session_dir / "session.json").read_text(encoding="utf-8"))
except Exception:
    session = {}

payload = {
    "schema_version": 1,
    "artifact_type": "wlc_terminal_output",
    "session_id": session.get("session_id") or session_dir.name,
    "study_id": session.get("study_id"),
    "wlc_host": os.environ["WLC_HOST"],
    "wlc_ssh_user": os.environ["WLC_USER"],
    "wlc_ssh_port": int(os.environ["WLC_PORT"]),
    "operator": os.environ["OPERATOR"],
    "started_at": os.environ["started_at"],
    "ended_at": os.environ["ended_at"],
    "exit_code": int(os.environ["exit_code"]),
    "output_path": os.environ["out_file"],
    "timing_path": os.environ["timing_file"],
    "output_sha256": os.environ["output_sha256"],
    "timing_sha256": os.environ["timing_sha256"],
    "recorder": "util-linux script",
    "recorder_version": os.environ["RECORDER_VERSION"],
    "input_logging_enabled": False,
    "command_runner": False,
    "dnac_used": False,
    "notes": "Output-only interactive WLC SSH transcript. Password prompts may appear, but hidden password input is not logged.",
}
Path(os.environ["meta_file"]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
chmod 0600 "$meta_file"

echo
echo "Console ended with exit code: $exit_code"
echo "Recorded output: $out_file"
echo "Recorded timing: $timing_file"
echo "Recorded metadata: $meta_file"
exit "$exit_code"
