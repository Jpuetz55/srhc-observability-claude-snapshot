"""Execute RF validation parser/import runs from saved run file selections.

This module is intentionally independent of FastAPI. The web backend is the
controller; this executor owns the operational pipeline from selected source
files to parsed artifacts, SQL import, and an execution log.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import load_config


SOURCE_BADGE_LOG = "badge_log"
SOURCE_EKAHAU_JSON = "ekahau_json"
SOURCE_MANUAL_CSV = "manual_csv"
SOURCE_IPAD_CLIENT_DETAIL = "ipad_client_detail"

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9_.-]+$")


@dataclass(frozen=True)
class RunExecutionResult:
    """Summary of a completed RF validation run execution."""

    test_run_id: str
    output_dir: str
    badge_json: str
    ekahau_json: str
    template_csv: str
    matches_json: str
    matches_csv: str
    import_sql: str
    execution_log: str
    run_config: str
    match_window_seconds_used: int | None
    source_summary: dict[str, int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_run_id": self.test_run_id,
            "output_dir": self.output_dir,
            "badge_json": self.badge_json,
            "ekahau_json": self.ekahau_json,
            "template_csv": self.template_csv,
            "matches_json": self.matches_json,
            "matches_csv": self.matches_csv,
            "import_sql": self.import_sql,
            "execution_log": self.execution_log,
            "run_config": self.run_config,
            "match_window_seconds_used": self.match_window_seconds_used,
            "source_summary": self.source_summary,
        }


def _value(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return "" if value is None else str(value).strip()


def _repo_path(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _stored_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _selected_files(files: Iterable[dict[str, Any]], role: str, root: Path) -> list[Path]:
    paths: list[Path] = []
    for row in files:
        if _value(row, "source_role") != role:
            continue
        raw_path = _value(row, "file_path")
        if not raw_path:
            continue
        path = _repo_path(root, raw_path)
        if not path.is_file():
            raise RuntimeError(f"Selected {role} file is not available on disk: {raw_path}")
        paths.append(path)
    return paths


def _one(paths: list[Path], role: str, *, required: bool = False) -> Path | None:
    if not paths:
        if required:
            raise RuntimeError(f"Select one {role} source file before executing the run.")
        return None
    if len(paths) > 1:
        raise RuntimeError(f"Select only one {role} source file for now. Found {len(paths)} selections.")
    return paths[0]


def _run_match_window_seconds(run: dict[str, Any]) -> int | None:
    """Return the per-run match window in whole seconds, or None when unset.

    The match window is stored on the run as an integer >= 1. Anything missing,
    non-numeric, or below 1 falls back to None so the base config value is kept.
    """
    raw = _value(run, "default_match_window_seconds")
    if not raw:
        return None
    try:
        window = int(float(raw))
    except (TypeError, ValueError):
        return None
    return window if window >= 1 else None


def build_effective_run_config(base_config: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Apply per-run execution parameters on top of the base validation config.

    This is what makes per-run tolerance real: the run's match window overrides
    ``default_match_window_seconds`` so candidate generation actually uses it.
    Clock offsets are intentionally not applied yet because the parser/correlation
    path does not consume them; wiring those is a separate change. The base config
    is not mutated.
    """
    effective = deepcopy(base_config)
    window = _run_match_window_seconds(run)
    if window is not None:
        effective["default_match_window_seconds"] = window
    return effective


def _run_command(command: list[str], *, cwd: Path, log_path: Path, env: dict[str, str]) -> None:
    display = " ".join(command)
    with log_path.open("a", encoding="utf-8") as log:
        log.write(f"\n$ {display}\n")
        log.flush()
        completed = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
        log.write(completed.stdout or "")
        log.write(f"\n[exit_code={completed.returncode}]\n")
    if completed.returncode != 0:
        raise RuntimeError(f"Command failed with exit code {completed.returncode}: {display}. See {log_path}")


def _cli_base(config_path: Path) -> list[str]:
    return [sys.executable, "-m", "tools.vocera_rf_validation.cli", "--config", str(config_path), "--no-archive"]


def _execution_output_root(root: Path, scope: str) -> Path:
    configured = os.environ.get("VOCERA_RF_VALIDATION_RUN_OUTPUT_ROOT", "").strip()
    if configured:
        configured_path = Path(configured)
        return (configured_path if configured_path.is_absolute() else root / configured_path).resolve(strict=False)
    if scope == "ipad":
        return root / "data" / "ipad-rf-validation" / "runs"
    return root / "data" / "vocera-rf-validation" / "runs"


def execute_selected_run(
    *,
    test_run_id: str,
    run: dict[str, Any],
    files: list[dict[str, Any]],
    root: str | Path,
    config_path: str | Path,
    postgres_url: str,
    psql_bin: str,
    scope: str = "vocera_badge",
) -> RunExecutionResult:
    """Execute the parser/import pipeline for one saved run selection."""

    if not _SAFE_RUN_ID.match(test_run_id):
        raise RuntimeError(f"Unsafe test_run_id for filesystem output path: {test_run_id}")

    root_path = Path(root).resolve(strict=False)
    config = _repo_path(root_path, str(config_path))
    if not config.is_file():
        raise RuntimeError(f"RF validation config file was not found: {config}")

    badge_log = _one(_selected_files(files, SOURCE_BADGE_LOG, root_path), SOURCE_BADGE_LOG)
    ipad_inputs = _selected_files(files, SOURCE_IPAD_CLIENT_DETAIL, root_path)
    ekahau_json = _one(_selected_files(files, SOURCE_EKAHAU_JSON, root_path), SOURCE_EKAHAU_JSON, required=True)
    manual_csv = _one(_selected_files(files, SOURCE_MANUAL_CSV, root_path), SOURCE_MANUAL_CSV)

    if badge_log and ipad_inputs:
        raise RuntimeError("Select either a badge log or iPad/client-detail source, not both.")
    if not badge_log and not ipad_inputs:
        raise RuntimeError("Select a badge log or iPad/client-detail source before executing the run.")

    output_dir = _execution_output_root(root_path, scope) / test_run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write a run-scoped effective config so per-run parameters (match window)
    # actually drive parsing/correlation instead of only the global YAML. The
    # CLI reads .json config via stdlib json, so no YAML dumper is needed.
    effective_config = build_effective_run_config(load_config(config), run)
    match_window_used = effective_config.get("default_match_window_seconds")
    run_config_path = output_dir / "run-config.json"
    run_config_path.write_text(
        json.dumps(effective_config, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )

    badge_json = output_dir / "badge.json"
    parsed_ekahau_json = output_dir / "ekahau.json"
    template_csv = output_dir / "manual-template.csv"
    matches_json = output_dir / "matches.json"
    matches_csv = output_dir / "matches.csv"
    import_sql = output_dir / "import.sql"
    execution_log = output_dir / "execution.log"
    execution_log.write_text(
        "RF validation run execution\n"
        f"test_run_id={test_run_id}\n"
        f"scope={scope}\n"
        f"output_dir={output_dir}\n"
        f"badge_log={badge_log or ''}\n"
        f"ipad_client_detail_count={len(ipad_inputs)}\n"
        f"ekahau_json={ekahau_json}\n"
        f"manual_csv={manual_csv or ''}\n",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PYTHONPATH"] = str(root_path) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")

    if badge_log:
        command = [*_cli_base(run_config_path), "parse-badge", "--test-run-id", test_run_id, "--input", str(badge_log), "--json-out", str(badge_json)]
        if _value(run, "badge_mac"):
            command.extend(["--badge-mac", _value(run, "badge_mac")])
        if _value(run, "badge_model"):
            command.extend(["--badge-model", _value(run, "badge_model")])
        _run_command(command, cwd=root_path, log_path=execution_log, env=env)
    else:
        command = [*_cli_base(run_config_path), "parse-ipad-client-detail", "--test-run-id", test_run_id, "--json-out", str(badge_json)]
        for path in ipad_inputs:
            command.extend(["--input", str(path)])
        if _value(run, "badge_mac"):
            command.extend(["--client-mac", _value(run, "badge_mac")])
        command.extend(["--client-model", _value(run, "badge_model") or "iPad"])
        _run_command(command, cwd=root_path, log_path=execution_log, env=env)

    _run_command(
        [*_cli_base(run_config_path), "parse-ekahau-json", "--test-run-id", test_run_id, "--input", str(ekahau_json), "--json-out", str(parsed_ekahau_json)],
        cwd=root_path,
        log_path=execution_log,
        env=env,
    )
    _run_command(
        [*_cli_base(run_config_path), "manual-template", "--badge-json", str(badge_json), "--ekahau-json", str(parsed_ekahau_json), "--csv-out", str(template_csv)],
        cwd=root_path,
        log_path=execution_log,
        env=env,
    )

    correlate_command = [*_cli_base(run_config_path), "correlate", "--template-csv", str(template_csv), "--json-out", str(matches_json), "--csv-out", str(matches_csv)]
    if manual_csv:
        correlate_command.extend(["--manual-csv", str(manual_csv)])
    _run_command(correlate_command, cwd=root_path, log_path=execution_log, env=env)

    _run_command(
        [
            *_cli_base(run_config_path),
            "emit-sql",
            "--badge-json",
            str(badge_json),
            "--ekahau-json",
            str(parsed_ekahau_json),
            "--template-csv",
            str(template_csv),
            "--matches-json",
            str(matches_json),
            "--sql-out",
            str(import_sql),
        ],
        cwd=root_path,
        log_path=execution_log,
        env=env,
    )

    _run_command([psql_bin, postgres_url, "-X", "-v", "ON_ERROR_STOP=1", "-f", str(import_sql)], cwd=root_path, log_path=execution_log, env=env)

    return RunExecutionResult(
        test_run_id=test_run_id,
        output_dir=_stored_path(root_path, output_dir),
        badge_json=_stored_path(root_path, badge_json),
        ekahau_json=_stored_path(root_path, parsed_ekahau_json),
        template_csv=_stored_path(root_path, template_csv),
        matches_json=_stored_path(root_path, matches_json),
        matches_csv=_stored_path(root_path, matches_csv),
        import_sql=_stored_path(root_path, import_sql),
        execution_log=_stored_path(root_path, execution_log),
        run_config=_stored_path(root_path, run_config_path),
        match_window_seconds_used=match_window_used,
        source_summary={
            SOURCE_BADGE_LOG: 1 if badge_log else 0,
            SOURCE_IPAD_CLIENT_DETAIL: len(ipad_inputs),
            SOURCE_EKAHAU_JSON: 1,
            SOURCE_MANUAL_CSV: 1 if manual_csv else 0,
        },
    )
