#!/usr/bin/env python3
"""Fixture-style tests for shared Grafana dashboard helpers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.common.dashboard import dashboard_environment  # noqa: E402
from tools.common.dashboard import dashboard_paths  # noqa: E402
from tools.common.dashboard import dashboard_title  # noqa: E402
from tools.common.dashboard import dashboard_uid  # noqa: E402
from tools.common.dashboard import iter_panels  # noqa: E402
from tools.common.dashboard import iter_promql_exprs  # noqa: E402
from tools.common.dashboard import iter_targets  # noqa: E402
from tools.common.dashboard import iter_variables  # noqa: E402
from tools.common.dashboard import load_dashboard  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise common-helper failure message."""

    if not condition:
        raise AssertionError(message)


def write_json(path: Path, payload: object) -> None:
    """Write compact JSON to a test fixture path."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_dashboard_discovery(root: Path) -> None:
    """Verify repo dashboard path discovery and environment inference."""

    write_json(root / "grafana" / "dashboards-dev" / "A" / "a.json", {"uid": "a", "title": "A"})
    write_json(root / "grafana" / "dashboards-prod" / "B" / "b.json", {"uid": "b", "title": "B"})

    paths = dashboard_paths(root)
    require(len(paths) == 2, "dashboard_paths should find dev and prod dashboards")
    require(dashboard_environment(paths[0]) == "dev", "first fixture should be dev")
    require(dashboard_environment(paths[1]) == "prod", "second fixture should be prod")


def test_dashboard_metadata(root: Path) -> None:
    """Verify dashboard loading and metadata helpers."""

    path = root / "grafana" / "dashboards-dev" / "Meta" / "meta.json"
    write_json(path, {"uid": "meta_uid", "title": "Meta Dashboard"})
    dashboard = load_dashboard(path)

    require(dashboard_uid(dashboard) == "meta_uid", "dashboard_uid should return string UIDs")
    require(dashboard_title(dashboard) == "Meta Dashboard", "dashboard_title should return string titles")


def test_dashboard_traversal(root: Path) -> None:
    """Verify panel, target, variable, and PromQL traversal helpers."""

    path = root / "grafana" / "dashboards-dev" / "Traversal" / "traversal.json"
    write_json(
        path,
        {
            "uid": "traversal",
            "title": "Traversal",
            "templating": {"list": [{"name": "site"}, {"name": "band"}]},
            "panels": [
                {
                    "type": "row",
                    "title": "Collapsed Row",
                    "panels": [
                        {
                            "type": "timeseries",
                            "title": "Nested",
                            "targets": [
                                {"expr": "nested_metric"},
                                {"expr": "hidden_metric", "hide": True},
                            ],
                        }
                    ],
                },
                {
                    "type": "table",
                    "title": "Visible",
                    "targets": [
                        {"expr": "visible_metric"},
                        {"rawSql": "select 1"},
                    ],
                },
            ],
        },
    )
    dashboard = load_dashboard(path)

    all_panel_titles = [panel.get("title") for panel in iter_panels(dashboard)]
    visible_panel_titles = [panel.get("title") for panel in iter_panels(dashboard, include_rows=False)]
    require(all_panel_titles == ["Collapsed Row", "Nested", "Visible"], "iter_panels should include nested row panels")
    require(visible_panel_titles == ["Nested", "Visible"], "include_rows=False should skip row panels")

    visible_targets = list(iter_targets(dashboard))
    all_targets = list(iter_targets(dashboard, include_hidden=True))
    require(len(visible_targets) == 3, "iter_targets should skip hidden targets by default")
    require(len(all_targets) == 4, "include_hidden=True should include hidden targets")

    exprs = [expr for _panel, _target, expr in iter_promql_exprs(dashboard)]
    require(exprs == ["nested_metric", "visible_metric"], "iter_promql_exprs should return visible PromQL expressions")

    variable_names = [variable.get("name") for variable in iter_variables(dashboard)]
    require(variable_names == ["site", "band"], "iter_variables should return templating variables")


def main() -> int:
    """Run common dashboard helper tests without requiring pytest."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_dashboard_discovery(root)
        test_dashboard_metadata(root)
        test_dashboard_traversal(root)
    print("OK: common dashboard helper tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
