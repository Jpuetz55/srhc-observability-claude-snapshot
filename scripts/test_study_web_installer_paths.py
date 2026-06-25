#!/usr/bin/env python3
"""Contract checks for checkout-safe Study Web service installation.

These assertions intentionally inspect installer/template text instead of
starting systemd. They prevent a deployment regression where the service was
installed from a newer checkout but continued to run scripts, helpers, or UI
assets from an older hard-coded repository path.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIT = ROOT / "systemd" / "vocera-rf-validation-study-web.service"
INSTALLER = ROOT / "scripts" / "install_vocera_rf_validation_study_web.sh"
WRAPPER = ROOT / "scripts" / "run_study_web.sh"
DOCS = ROOT / "docs" / "study-workflow-web-ui.md"
MAKEFILE = ROOT / "Makefile"


def require(text: str, marker: str, description: str) -> None:
    if marker not in text:
        raise AssertionError(f"missing {description}: {marker!r}")


def require_line(text: str, prefix: str, expected: str, description: str) -> None:
    matches = [line for line in text.splitlines() if line.startswith(prefix)]
    if not matches:
        raise AssertionError(f"missing {description} line beginning {prefix!r}")
    if not any(expected in line for line in matches):
        raise AssertionError(f"{description} must contain {expected!r}: {matches!r}")


def main() -> None:
    unit = UNIT.read_text(encoding="utf-8")
    installer = INSTALLER.read_text(encoding="utf-8")
    wrapper = WRAPPER.read_text(encoding="utf-8")
    docs = DOCS.read_text(encoding="utf-8")
    makefile = MAKEFILE.read_text(encoding="utf-8")

    # The base unit must be rendered at installation time rather than embedding
    # one historical checkout path in its operational commands.
    for prefix, description in (
        ("Documentation=file:", "documentation"),
        ("WorkingDirectory=", "working directory"),
        ("Environment=PYTHONPATH=", "python path"),
        ("Environment=VOCERA_RF_VALIDATION_PSQL_BIN=", "RF psql helper"),
        ("Environment=VOCERA_MEDIA_QOE_PSQL_BIN=", "Media QoE psql helper"),
        ("Environment=STUDY_WEB_STATIC_DIR=", "static asset directory"),
        ("ExecStart=", "launch command"),
    ):
        require_line(unit, prefix, "@STUDY_WEB_REPO_ROOT@", description)

    require(installer, "rendered_unit=\"$(mktemp)\"", "rendered unit staging")
    require(installer, "zz-study-web-repo-root.conf", "late checkout-path override")
    require(installer, "s/@STUDY_WEB_REPO_ROOT@/", "template token rendering")
    require(installer, "Environment=STUDY_WEB_REPO_ROOT=$repo_root", "runtime repository environment")
    require(installer, "ExecStart=\nExecStart=/bin/bash $repo_root/scripts/run_study_web.sh", "override launch command")
    require(installer, "20-grafana-embed.conf", "Grafana drop-in preservation comment")

    require(wrapper, "default_repo_root=", "self-resolved wrapper checkout")
    require(wrapper, "repo_root=\"${STUDY_WEB_REPO_ROOT:-$default_repo_root}\"", "explicit runtime checkout override")
    if "/home/appsadmin/grafana-mimir-observability" in wrapper:
        raise AssertionError("launch wrapper still hard-codes the retired checkout")

    require(docs, "zz-study-web-repo-root.conf", "cutover documentation")
    require(docs, "stale `override.conf`", "stale override explanation")
    require(makefile, "python3 ./scripts/test_study_web_installer_paths.py", "Makefile test target")

    print("OK: Study Web installer checkout-path contract passed")


if __name__ == "__main__":
    main()
