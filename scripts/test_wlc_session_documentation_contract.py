#!/usr/bin/env python3
"""Guard the WLC session workflow's documented safety boundaries.

This intentionally checks only durable, operator-visible invariants. It does
not try to grade prose. The goal is to catch a code change that removes the
WLC package isolation, local-only ingest boundary, or retry contract without
updating the canonical runbooks and their explanatory comments.
"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def require(condition: bool, message: str) -> None:
    """Raise a readable assertion when a required documentation contract drifts."""

    if not condition:
        raise AssertionError(message)


def read(relative: str) -> str:
    """Read one repository-relative UTF-8 source or Markdown file."""

    return (ROOT / relative).read_text(encoding="utf-8")


def test_operator_docs_cover_session_ingest_contract() -> None:
    """Keep the canonical WLC docs aligned with the deployed ingest lifecycle."""

    continuous = read("docs/wireless/vocera-wlc-continuous-capture-runbook.md")
    transfer = read("docs/wireless/vocera-wlc-capture-transfer.md")
    recovery = read("docs/wireless/vocera-wlc-capture-recovery.md")
    rehearsal = read("docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md")
    security = read("docs/wireless/vocera-wlc-capture-security.md")
    index = read("docs/README.md")

    require("incoming/" in continuous and "root-owned" in continuous and "pcaps/" in continuous,
            "continuous-capture runbook must explain root-owned incoming/ -> pcaps/ finalization")
    require("wlc-sessions/" in transfer and "wlc-attempts/" in transfer,
            "transfer boundary must document generic-scan exclusions")
    require("do not manually move" in transfer.lower(),
            "transfer boundary must tell operators not to bypass session ingest")
    require("retry" in recovery.lower() and "pcaps/" in recovery and "root:root" in recovery,
            "recovery runbook must document retry from finalized service-owned evidence")
    require("localhost-only" in rehearsal.lower(),
            "rehearsal runbook must document the local-only ingest trigger")
    require("do not store" in security.lower() and "password" in security.lower(),
            "security runbook must preserve the no-password-storage boundary")
    require("vocera-wlc-session-maintainer-contract.md" in index,
            "documentation index must link the maintainer contract")


def test_critical_code_comments_explain_safety_boundaries() -> None:
    """Require explanatory comments where behavior is easy to weaken accidentally."""

    ingest = read("tools/vocera_media_qoe/vocera_wlc_session_ingest.py")
    study_web = read("tools/study_web/main.py")
    console = read("scripts/run_vocera_wlc_session_console.sh")

    require("scanner is the *only* path that looks at session packages" in ingest,
            "ingest module needs an explicit package-isolation comment")
    require("two unchanged observations" in ingest,
            "ingest module needs an explicit SCP-stability comment")
    require("only the local systemd timer" in study_web,
            "Study Web needs an explicit local-only trigger comment")
    require("Finalization into pcaps/ happens before registration and parsing" in study_web,
            "Study Web needs an explicit finalized-artifact retry comment")
    require("stores no WLC or SCP secrets" in console,
            "console recorder needs an explicit no-secrets/no-runner comment")


def main() -> int:
    test_operator_docs_cover_session_ingest_contract()
    test_critical_code_comments_explain_safety_boundaries()
    print("OK: WLC session documentation and comment contract passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
