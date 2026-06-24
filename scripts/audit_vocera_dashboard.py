#!/usr/bin/env python3
"""Audit Vocera dashboard panel expressions against live Mimir data and semantics."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from check_dashboard_metric_contract import extract_metric_names


DEFAULT_DASHBOARD = (
    "grafana/dashboards-prod/Platform - Wireless RF/"
    "vocera-badge-80211r-impact__vocera_badge_80211r_impact.json"
)
VAR_RE = re.compile(
    r"\$(?:\{(?P<braced>[A-Za-z_][A-Za-z0-9_]*)(?::[A-Za-z0-9_]+)?\}|(?P<plain>[A-Za-z_][A-Za-z0-9_]*))"
)
MS_UNITS = {"ms", "milliseconds", "millisecond"}


@dataclass(frozen=True)
class QueryResult:
    """Minimal Prometheus instant-query result used in audit output."""

    count: int
    sample: str


@dataclass(frozen=True)
class PanelTarget:
    """Dashboard panel target with semantic metadata for reporting."""

    panel_id: int
    title: str
    ref_id: str
    expr: str
    rendered_expr: str
    unit: str
    source_type: str
    metrics: set[str]


def load_dashboard(path: Path) -> dict:
    """Load a Grafana dashboard JSON document from disk."""

    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def variable_defaults(dashboard: dict) -> dict[str, str]:
    """Return Grafana variable values suitable for an instant PromQL audit."""

    values: dict[str, str] = {}
    for item in dashboard.get("templating", {}).get("list", []):
        name = item.get("name")
        if not name:
            continue
        current = item.get("current", {})
        value = current.get("value", "")
        if value == "$__all":
            value = item.get("allValue") or ".*"
        elif isinstance(value, list):
            value = "|".join(str(part) for part in value) or ".*"
        elif not value:
            value = ".*" if item.get("includeAll") else ""
        values[name] = str(value)
    return values


def render_expr(expr: str, variables: dict[str, str]) -> str:
    """Substitute the dashboard's current variable values into a PromQL string."""

    def replace(match: re.Match[str]) -> str:
        """Replace one Grafana variable token with its resolved audit value."""

        name = match.group("braced") or match.group("plain")
        return variables.get(name, match.group(0))

    return VAR_RE.sub(replace, expr)


def _unit(panel: dict) -> str:
    """Return the panel unit string, using Grafana's implicit 'none' default."""

    return str(panel.get("fieldConfig", {}).get("defaults", {}).get("unit", "none") or "none")


def classify_source(metrics: Iterable[str]) -> str:
    """Classify a panel expression by the metric family it reads."""

    metrics = set(metrics)
    kinds: set[str] = set()
    for metric in metrics:
        if metric.startswith("wireless_ap_ac_") or metric.endswith("_cli"):
            kinds.add("CLI raw")
        elif metric.startswith("wireless_ap_voice_latency_"):
            kinds.add("recording rule (CLI AP voice AC)")
        elif metric.startswith("wireless_ap_"):
            kinds.add("recording rule (RF/AP context)")
        elif metric.startswith("wireless_badge_client_"):
            if metric.endswith("_cc"):
                kinds.add("client detail raw")
            else:
                kinds.add("recording rule (MDT/client)")
        elif metric.startswith("platform_"):
            kinds.add("recording rule (platform)")
        elif metric.startswith("Cisco_IOS_XE_"):
            kinds.add("MDT raw")
        else:
            kinds.add("external/other")
    return " + ".join(sorted(kinds)) if kinds else "unknown"


def iter_panel_targets(dashboard: dict) -> Iterable[PanelTarget]:
    """Yield visible Prometheus targets with rendered expressions and metadata."""

    variables = variable_defaults(dashboard)
    for panel in dashboard.get("panels", []):
        if panel.get("type") == "row":
            continue
        title = str(panel.get("title") or f"panel {panel.get('id', 'unknown')}")
        unit = _unit(panel)
        for target in panel.get("targets", []):
            expr = target.get("expr")
            if not expr or target.get("hide"):
                continue
            metrics = extract_metric_names(expr)
            yield PanelTarget(
                panel_id=int(panel.get("id") or 0),
                title=title,
                ref_id=str(target.get("refId") or "?"),
                expr=expr,
                rendered_expr=render_expr(expr, variables),
                unit=unit,
                source_type=classify_source(metrics),
                metrics=metrics,
            )


def query_prometheus(base_url: str, org_id: str, expr: str, timeout: float) -> QueryResult:
    """Run a Prometheus/Mimir instant query and return count plus sample value."""

    url = base_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": expr})
    request = urllib.request.Request(url)
    if org_id:
        request.add_header("X-Scope-OrgID", org_id)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("status") != "success":
        raise RuntimeError(payload.get("error") or "query failed")
    data = payload.get("data", {})
    result_type = data.get("resultType")
    result = data.get("result", [])
    if result_type == "scalar":
        return QueryResult(count=1, sample=str(result[1]) if len(result) > 1 else "n/a")
    if not isinstance(result, list):
        return QueryResult(count=0, sample="n/a")
    if not result:
        return QueryResult(count=0, sample="n/a")
    first = result[0]
    if isinstance(first, dict):
        value = first.get("value") or ["", "n/a"]
        sample = str(value[1]) if len(value) > 1 else "n/a"
    else:
        sample = "n/a"
    return QueryResult(count=len(result), sample=sample)


def semantic_issues(target: PanelTarget, duplicate_titles: set[str]) -> list[str]:
    """Return semantic risks that can be detected from title, unit, and PromQL."""

    issues: list[str] = []
    title = target.title.lower()
    expr = target.expr
    metrics = target.metrics

    if "roam duration" in title:
        issues.append("title uses Roam Duration without a distinct roam-duration metric")

    if any(metric.startswith("wireless_badge_client_run_state_latency") for metric in metrics):
        if any(token in title for token in ("voice", "rtp", "ap -> client", "ap-to-client")):
            issues.append("client RUN-state metric is labeled as voice/RTP/AP-to-client latency")

    if any(metric.startswith("wireless_ap_voice_latency_") for metric in metrics):
        if "run-state" in title or "roam duration" in title:
            issues.append("AP voice AC metric is labeled as client RUN-state or roam duration")

    has_microsecond_metric = any(metric.endswith("_us") or "_us_" in metric for metric in metrics)
    if target.unit in MS_UNITS and has_microsecond_metric and not re.search(r"/\s*1000\b", expr):
        issues.append("microsecond metric is displayed with millisecond unit without /1000 conversion")

    if "wireless_ap_ac_latency_avg_us_cli" in metrics and "wireless_ap_ac_latency_sample" not in expr:
        issues.append("raw AP voice latency is used without an explicit freshness/sample-age filter")

    duplicate_conflicts = {
        title for title in duplicate_titles
        if title_family(title) != title_family(target.title)
    }
    if duplicate_conflicts:
        joined = ", ".join(sorted(duplicate_conflicts))
        issues.append(f"same expression is used by a different semantic title family: {joined}")

    return issues


def title_family(title: str) -> str:
    """Classify titles so intentional stat/trend reuse is not a false failure."""

    lowered = title.lower()
    if "roam duration" in lowered:
        return "roam_duration"
    if "run-state" in lowered:
        return "run_state"
    if "ap -> client voice" in lowered or "ap voice" in lowered:
        return "ap_voice_ac"
    if "ft adoption" in lowered:
        return "ft_adoption"
    if "retry" in lowered:
        return "retry"
    if "rssi" in lowered:
        return "rssi"
    if "snr" in lowered:
        return "snr"
    return re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")


def duplicate_expression_titles(targets: list[PanelTarget]) -> dict[str, set[str]]:
    """Return PromQL expressions reused by more than one panel title."""

    seen: dict[str, set[str]] = {}
    for target in targets:
        normalized = re.sub(r"\s+", " ", target.expr).strip()
        seen.setdefault(normalized, set()).add(target.title)
    return {expr: titles for expr, titles in seen.items() if len(titles) > 1}


def run_audit(args: argparse.Namespace) -> int:
    """Run semantic and live-query checks for every dashboard panel target."""

    dashboard = load_dashboard(args.dashboard)
    targets = list(iter_panel_targets(dashboard))
    duplicate_map = duplicate_expression_titles(targets)
    failures = 0

    for target in targets:
        normalized_expr = re.sub(r"\s+", " ", target.expr).strip()
        duplicate_titles = duplicate_map.get(normalized_expr, set()) - {target.title}
        issues = semantic_issues(target, duplicate_titles)
        try:
            query = query_prometheus(args.mimir_url, args.org_id, target.rendered_expr, args.timeout)
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
            query = QueryResult(count=0, sample="n/a")
            issues.append(f"query failed: {exc}")
        if query.count == 0:
            issues.append("no data")

        status = "PASS" if not issues else "FAIL"
        if issues:
            failures += 1
        issue_text = "" if not issues else " issues=" + "; ".join(issues)
        print(
            f"{status} | panel={target.title} | ref={target.ref_id} | "
            f"count={query.count} | sample={query.sample} | unit={target.unit} | "
            f"source={target.source_type}{issue_text}"
        )

    print(f"SUMMARY panels={len(targets)} failures={failures}")
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    """Parse dashboard audit CLI arguments."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dashboard",
        type=Path,
        default=Path(DEFAULT_DASHBOARD),
        help="Dashboard JSON file to audit",
    )
    parser.add_argument(
        "--mimir-url",
        default=os.environ.get("MIMIR_PROM_URL", "http://127.0.0.1:9009/prometheus"),
        help="Prometheus-compatible API base URL",
    )
    parser.add_argument(
        "--org-id",
        default=os.environ.get("MIMIR_ORG_ID", "observability"),
        help="Optional X-Scope-OrgID header value",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="HTTP query timeout in seconds")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for the Vocera dashboard audit."""

    return run_audit(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
