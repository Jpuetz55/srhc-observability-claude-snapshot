#!/usr/bin/env python3
"""Live smoke checks for the RF validation project/study workflow."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL URL for the RF validation database.")
    parser.add_argument(
        "--psql-bin",
        default=str(ROOT / "scripts" / "vocera_rf_validation_psql_in_container.sh"),
        help="psql executable or wrapper script.",
    )
    parser.add_argument("--api-base", default="http://127.0.0.1:8097", help="Study web API base URL.")
    parser.add_argument("--skip-api", action="store_true", help="Only run SQL smoke checks.")
    return parser.parse_args()


def psql_rows(psql_bin: str, postgres_url: str, sql: str) -> list[dict[str, str]]:
    completed = subprocess.run(
        [psql_bin, postgres_url, "-X", "--csv", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = completed.stdout.strip()
    if not output:
        return []
    return list(csv.DictReader(StringIO(output)))


def psql_int(psql_bin: str, postgres_url: str, sql: str, column: str = "value") -> int:
    rows = psql_rows(psql_bin, postgres_url, sql)
    if not rows:
        raise RuntimeError(f"SQL returned no rows: {sql}")
    return int(rows[0].get(column) or 0)


def api_json(api_base: str, path: str) -> dict[str, Any]:
    url = api_base.rstrip("/") + path
    with urlopen(url, timeout=10) as response:
        body = response.read().decode("utf-8")
    return json.loads(body)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS {message}")


def run_sql_checks(args: argparse.Namespace) -> None:
    psql_bin = args.psql_bin
    postgres_url = args.postgres_url

    require(
        psql_int(psql_bin, postgres_url, "select count(*) as value from vocera_projects;") >= 1,
        "vocera_projects exists and has at least one project",
    )
    require(
        psql_int(psql_bin, postgres_url, "select count(*) as value from vocera_studies;") >= 1,
        "vocera_studies exists and has at least one study",
    )

    for view_name in (
        "v_vocera_projects",
        "v_vocera_studies",
        "v_vocera_rf_project_completed_matches",
        "v_vocera_rf_project_canonical_completed_matches",
        "v_vocera_rf_project_duplicate_datapoints",
    ):
        psql_int(psql_bin, postgres_url, f"select count(*) as value from {view_name};")
        print(f"PASS {view_name} is queryable")

    require(
        psql_int(psql_bin, postgres_url, "select count(*) as value from validation_test_runs where study_id is null;") == 0,
        "all validation_test_runs rows have study_id",
    )
    require(
        psql_int(
            psql_bin,
            postgres_url,
            """
            select count(*) as value
            from validation_test_runs tr
            join vocera_studies s on s.study_id = tr.study_id
            where s.study_type = 'rf_validation'
              and s.study_scope <> vocera_rf_validation_study_scope(tr.test_run_id);
            """,
        )
        == 0,
        "RF validation run IDs match attached study_scope",
    )
    require(
        psql_int(
            psql_bin,
            postgres_url,
            """
            select count(*) as value
            from vocera_studies s
            join vocera_projects p on p.project_id = s.project_id
            where p.deleted_at is not null
              and s.deleted_at is null;
            """,
        )
        == 0,
        "deleted projects do not expose active studies",
    )


def run_api_checks(args: argparse.Namespace) -> None:
    backend = api_json(args.api_base, "/api/backend-status")
    backend_row = backend.get("backend") or {}
    require(backend.get("ok") is True, "backend-status endpoint returns ok")
    require(backend_row.get("backend_status") == "ready", "backend reports ready")
    for key in ("project_table", "study_table", "project_view", "study_view", "project_canonical_view", "project_duplicate_view"):
        require(backend_row.get(key) == "ok", f"backend reports {key}=ok")

    projects = api_json(args.api_base, "/api/projects")
    require(projects.get("ok") is True and isinstance(projects.get("projects"), list), "projects endpoint returns a list")

    project_id = "project_rf_validation_default"
    project = api_json(args.api_base, f"/api/projects/{project_id}")
    require(project.get("ok") is True and project.get("project", {}).get("project_id") == project_id, "default RF project is readable")

    studies = api_json(args.api_base, f"/api/projects/{project_id}/studies")
    require(studies.get("ok") is True and isinstance(studies.get("studies"), list), "default RF project studies are readable")

    results = api_json(args.api_base, f"/api/projects/{project_id}/rf-results")
    require(results.get("ok") is True and isinstance(results.get("results"), list), "canonical RF project results are readable")

    raw_results = api_json(args.api_base, f"/api/projects/{project_id}/rf-results/raw")
    require(raw_results.get("ok") is True and isinstance(raw_results.get("results"), list), "raw RF project results are readable")

    duplicates = api_json(args.api_base, f"/api/projects/{project_id}/duplicates")
    require(duplicates.get("ok") is True and isinstance(duplicates.get("duplicates"), list), "RF project duplicates are readable")


def main() -> int:
    args = parse_args()
    try:
        run_sql_checks(args)
        if not args.skip_api:
            run_api_checks(args)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(exc.stderr)
        sys.stderr.write(f"FAIL command exited {exc.returncode}: {' '.join(exc.cmd)}\n")
        return exc.returncode or 1
    except (AssertionError, RuntimeError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        sys.stderr.write(f"FAIL {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
