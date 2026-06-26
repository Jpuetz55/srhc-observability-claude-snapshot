#!/usr/bin/env python3
"""Security/contract tests for the human-operated WLC console recorder."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_vocera_wlc_session_console.sh"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_script_contract() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    script_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("script ")]
    require(script_lines, "recorder must invoke script(1)")
    invocation = script_lines[0]
    require(SCRIPT.is_file(), "missing WLC session console recorder")
    require(SCRIPT.stat().st_mode & 0o111, "console recorder should be executable")
    require("script -q -f -e --log-out" in invocation, "recorder must use output-only script logging")
    require("--log-timing" in invocation, "recorder must write timing metadata")
    require("--log-in" not in invocation, "recorder must not log terminal input")
    require("--log-io" not in invocation, "recorder must not combine input/output streams")
    require("[[ \"$WLC_HOST\" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]" in text, "recorder must validate WLC host before building ssh command")
    require("[[ \"$WLC_USER\" =~ ^[A-Za-z_][A-Za-z0-9._-]*$ ]]" in text, "recorder must validate WLC user before building ssh command")
    require("umask 077" in text, "recorder must default to owner-only evidence files")
    require("chmod 0700 \"$terminal_dir\"" in text, "terminal evidence directory should be owner-only")
    require("chmod 0600 \"$out_file\" \"$timing_file\"" in text, "terminal output and timing should be owner-only")
    require("chmod 0600 \"$meta_file\"" in text, "terminal metadata should be owner-only")
    require("ssh -tt -p '$WLC_PORT' '$WLC_USER@$WLC_HOST'" in invocation, "recorder must force TTY allocation and quote validated ssh arguments")
    require("sshpass" not in text, "recorder must not automate SSH passwords")
    require("input_logging_enabled" in text and "False" in text, "metadata must state input logging is disabled")
    require("command_runner" in text and "False" in text, "metadata must state this is not a command runner")


def test_make_and_ui_contract() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    ui = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaWlcCaptureSessions.tsx").read_text(encoding="utf-8")
    api_types = (ROOT / "web" / "study-ui" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    main = (ROOT / "tools" / "study_web" / "main.py").read_text(encoding="utf-8")
    config = (ROOT / "config" / "vocera-media-qoe.yaml").read_text(encoding="utf-8")
    require("vocera-media-qoe-wlc-session-console:" in makefile, "Makefile must expose the console target")
    require("run_vocera_wlc_session_console.sh" in makefile, "Makefile console target must call the recorder")
    require("WLC_SSH_USER" in makefile and "WLC_SSH_HOST" in makefile, "console target must require explicit SSH identity")
    require("WLC_SSH_HOST ?= $(WLC_NAME)" not in makefile, "console SSH host must not default to the WLC display name")
    require('wlc_ssh_host: 10.16.59.252' in config, "site config must define the WLC SSH endpoint separately from wlc_name")
    require('"wlc_ssh_host": wlc.get("wlc_ssh_host") or ""' in main, "Study Web defaults must expose wlc_ssh_host")
    require("wlc_ssh_host?: string" in api_types and "wlc_ssh_port?: number" in api_types, "frontend defaults type must include WLC SSH endpoint fields")
    require("Logged WLC console" in ui, "session UI must expose logged-console command guidance")
    require("vocera-media-qoe-wlc-session-console" in ui, "session UI should generate the console make command")
    require("field(session, 'wlc_name')" not in ui.split("const consoleCommand =", 1)[1].split("const startSheet =", 1)[0], "console command must not use wlc_name as the SSH destination")
    require("WLC_SSH_HOST=${shellQuote(wlcSshHost)}" in ui, "console command should use the configured WLC SSH host")
    require("WLC_SSH_PORT=${shellQuote(String(wlcSshPort))}" in ui, "console command should include the configured WLC SSH port")


def test_help_runs() -> None:
    result = subprocess.run([str(SCRIPT), "--help"], cwd=ROOT, capture_output=True, text=True)
    require(result.returncode == 0, f"--help should succeed: {result.stderr}")
    require("Output artifacts:" in result.stdout, "help should document output artifacts")
    require("not stored" in result.stdout, "help should document password behavior")


def main() -> int:
    test_script_contract()
    test_make_and_ui_contract()
    test_help_runs()
    print("OK: WLC session console recorder tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
