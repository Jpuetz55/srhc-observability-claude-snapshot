#!/usr/bin/env python3
"""Regression tests: the WLC capture-session Make target must not silently force.

The session-init CLI refuses to overwrite an existing capture-session package
unless ``--force`` is passed. The Make target must preserve that protection, so
``--force`` may only appear in the expanded recipe when the operator explicitly
opts in via ``WLC_SESSION_FORCE``. These tests assert the real ``make -n``
expansion rather than just the Makefile source text.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = "vocera-media-qoe-wlc-session-init"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def expand_target(*overrides: str) -> str:
    """Return the dry-run (``make -n``) expansion of the session-init recipe."""

    # Drop any inherited jobserver flags so the nested make runs standalone when
    # this test is itself launched from `make test`.
    env = {key: value for key, value in os.environ.items() if key not in {"MAKEFLAGS", "MFLAGS"}}
    result = subprocess.run(
        ["make", "-n", TARGET, *overrides],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    require(
        result.returncode == 0,
        f"`make -n {TARGET} {' '.join(overrides)}` failed: {result.stderr.strip()}",
    )
    return result.stdout


def test_make_target_defines_force_default() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    require("WLC_SESSION_FORCE ?=" in makefile, "Makefile must define a WLC_SESSION_FORCE default")
    require(
        "$(if $(filter 1 yes true,$(WLC_SESSION_FORCE)),--force,)" in makefile,
        "session-init must gate --force behind WLC_SESSION_FORCE",
    )


def test_force_off_by_default() -> None:
    expansion = expand_target()
    require("vocera_wlc_session init" in expansion, "session-init must still invoke the CLI")
    require("--force" not in expansion, "session-init must not force-overwrite by default")
    require("--force" not in expand_target("WLC_SESSION_FORCE=0"), "explicit WLC_SESSION_FORCE=0 must not force")


def test_force_opt_in() -> None:
    for value in ("1", "yes", "true"):
        require(
            "--force" in expand_target(f"WLC_SESSION_FORCE={value}"),
            f"WLC_SESSION_FORCE={value} must enable --force",
        )


def test_short_validation_smoke_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    require("vocera-media-qoe-wlc-session-smoke-init:" in makefile, "Makefile must expose a 90-second smoke package target")
    require("WLC_CAPTURE_MODE=short_validation" in makefile, "smoke target must force short validation mode")
    require("WLC_SHORT_VALIDATION_DURATION_SECONDS=90" in makefile, "smoke target must force the 90-second duration")
    expansion = expand_target("WLC_CAPTURE_MODE=short_validation", "WLC_SHORT_VALIDATION_DURATION_SECONDS=90")
    require("--capture-mode \"short_validation\"" in expansion, "session init must pass short validation mode to the CLI")
    require("--short-validation-duration-seconds \"90\"" in expansion, "session init must pass the smoke duration to the CLI")


def main() -> int:
    test_make_target_defines_force_default()
    test_force_off_by_default()
    test_force_opt_in()
    test_short_validation_smoke_target()
    print("OK: WLC session Make safety tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
