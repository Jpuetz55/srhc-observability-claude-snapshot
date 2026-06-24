#!/usr/bin/env python3
"""Smoke test for scripts/check_dashboards.py using a temporary repo."""

import json
import os
import pathlib
import subprocess
import sys
import tempfile


def write_dashboard(path: pathlib.Path, uid: str, title: str) -> None:
    """Create a minimal Grafana dashboard model for validator testing."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"uid": uid, "title": title, "panels": []}), encoding="utf-8")

with tempfile.TemporaryDirectory() as td:
    repo = pathlib.Path(td)
    write_dashboard(repo / "grafana" / "dashboards-dev" / "A" / "a.json", "dash_a", "A")
    write_dashboard(repo / "grafana" / "dashboards-prod" / "B" / "b.json", "dash_b", "B")
    result = subprocess.run(
        [sys.executable, os.path.abspath(os.path.join(os.path.dirname(__file__), "check_dashboards.py"))],
        env={**os.environ, "REPO_ROOT": str(repo)},
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(result.stdout)
        print(result.stderr)
        raise SystemExit("dashboard checker smoke test failed")

print("OK: dashboard checker smoke test passed")
