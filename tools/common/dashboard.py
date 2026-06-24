"""Shared helpers for Grafana dashboard JSON traversal."""

from __future__ import annotations

from collections.abc import Iterable
from collections.abc import Iterator
from os import PathLike
from pathlib import Path
from typing import Any

from tools.common.files import read_json


Dashboard = dict[str, Any]
Panel = dict[str, Any]
Target = dict[str, Any]
Variable = dict[str, Any]


def dashboard_paths(repo_root: str | PathLike[str], environments: Iterable[str] = ("dev", "prod")) -> list[Path]:
    """Return Grafana dashboard JSON paths for the requested repo environments."""

    root = Path(repo_root)
    paths: list[Path] = []
    for environment in environments:
        base = root / "grafana" / f"dashboards-{environment}"
        paths.extend(base.rglob("*.json"))
    return sorted(paths)


def dashboard_environment(path: str | PathLike[str]) -> str:
    """Infer the dashboard environment from a repo dashboard path."""

    path_obj = Path(path)
    if "dashboards-dev" in path_obj.parts:
        return "dev"
    if "dashboards-prod" in path_obj.parts:
        return "prod"
    path_text = str(path_obj)
    if "dashboards-dev" in path_text:
        return "dev"
    if "dashboards-prod" in path_text:
        return "prod"
    raise ValueError(f"cannot infer dashboard environment from path: {path_obj}")


def load_dashboard(path: str | PathLike[str]) -> Dashboard:
    """Load a Grafana dashboard JSON object from disk."""

    payload = read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"dashboard JSON root must be an object: {path}")
    return payload


def dashboard_uid(dashboard: Dashboard) -> str | None:
    """Return a dashboard UID when present and string-like."""

    uid = dashboard.get("uid")
    return uid if isinstance(uid, str) else None


def dashboard_title(dashboard: Dashboard) -> str | None:
    """Return a dashboard title when present and string-like."""

    title = dashboard.get("title")
    return title if isinstance(title, str) else None


def iter_json_nodes(root: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict node under a JSON-compatible object."""

    if isinstance(root, dict):
        yield root
        for value in root.values():
            yield from iter_json_nodes(value)
    elif isinstance(root, list):
        for item in root:
            yield from iter_json_nodes(item)


def iter_panels(dashboard: Dashboard, *, include_rows: bool = True) -> Iterator[Panel]:
    """Yield top-level and nested panel objects from a Grafana dashboard."""

    panels = dashboard.get("panels")
    if not isinstance(panels, list):
        return
    yield from _iter_panel_list(panels, include_rows=include_rows)


def _iter_panel_list(panels: list[Any], *, include_rows: bool) -> Iterator[Panel]:
    """Yield panels from a Grafana panel list, including collapsed row children."""

    for panel in panels:
        if not isinstance(panel, dict):
            continue
        if include_rows or panel.get("type") != "row":
            yield panel
        nested = panel.get("panels")
        if isinstance(nested, list):
            yield from _iter_panel_list(nested, include_rows=include_rows)


def iter_targets(dashboard: Dashboard, *, include_hidden: bool = False) -> Iterator[tuple[Panel, Target]]:
    """Yield Grafana query target objects with their containing panel."""

    for panel in iter_panels(dashboard, include_rows=False):
        targets = panel.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            if not include_hidden and target.get("hide"):
                continue
            yield panel, target


def iter_variables(dashboard: Dashboard) -> Iterator[Variable]:
    """Yield dashboard templating variables."""

    templating = dashboard.get("templating")
    if not isinstance(templating, dict):
        return
    variables = templating.get("list")
    if not isinstance(variables, list):
        return
    for variable in variables:
        if isinstance(variable, dict):
            yield variable


def iter_promql_exprs(
    dashboard: Dashboard,
    *,
    include_hidden: bool = False,
) -> Iterator[tuple[Panel, Target, str]]:
    """Yield PromQL expressions from dashboard query targets."""

    for panel, target in iter_targets(dashboard, include_hidden=include_hidden):
        expr = target.get("expr")
        if isinstance(expr, str) and expr.strip():
            yield panel, target, expr
