#!/usr/bin/env python3
"""Verify dashboards only reference metrics declared in the metric contract."""

import json
import os
import re
import sys
from glob import glob
from typing import Dict, List, Set


TOP_SECTION_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")
SECTION_NAME_RE = re.compile(r"^\s{2}([A-Za-z0-9_]+):\s*(.*)$")
ITEM_NAME_RE = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$")
LIST_ITEM_RE = re.compile(r"^\s{4}-\s*(.+?)\s*$")

RE_REMOVE_STRINGS = re.compile(r'"([^"\\]|\\.)*"')
RE_REMOVE_GRAFANA_VARS = re.compile(
    r"\$(?:\{[A-Za-z_][A-Za-z0-9_]*(?::[A-Za-z0-9_]+)?\}|[A-Za-z_][A-Za-z0-9_]*)"
)
RE_REMOVE_LABEL_CTX = re.compile(
    r"\b(?:by|without|on|ignoring|group_left|group_right)\s*\([^)]*\)"
)
RE_METRIC_BRACED = re.compile(
    r"(?<![A-Za-z0-9_:])([A-Za-z_:][A-Za-z0-9_:]*)(?=\s*(?:\{|\[))"
)
RE_METRIC_BARE = re.compile(
    r"(?<![A-Za-z0-9_:])([A-Za-z_:][A-Za-z0-9_:]*)(?=\s*(?:\)|\+|-|\*|/|,|$|==|!=|<=|>=|<|>|\b(?:and|or|unless)\b))"
)
RE_LABEL_VALUES = re.compile(r"label_values\s*\(\s*([A-Za-z_:][A-Za-z0-9_:]*)")

PROMQL_KEYWORDS = {"and", "or", "unless", "bool"}
PROMQL_FUNCTIONS = {
    "abs",
    "absent",
    "absent_over_time",
    "acos",
    "acosh",
    "asin",
    "asinh",
    "atan",
    "atanh",
    "avg_over_time",
    "ceil",
    "changes",
    "clamp",
    "clamp_max",
    "clamp_min",
    "cos",
    "cosh",
    "count_over_time",
    "day_of_month",
    "day_of_week",
    "day_of_year",
    "days_in_month",
    "deg",
    "delta",
    "deriv",
    "double_exponential_smoothing",
    "exp",
    "floor",
    "histogram_avg",
    "histogram_count",
    "histogram_fraction",
    "histogram_quantile",
    "histogram_stddev",
    "histogram_stdvar",
    "histogram_sum",
    "holt_winters",
    "hour",
    "idelta",
    "increase",
    "info",
    "irate",
    "label_replace",
    "label_join",
    "last_over_time",
    "ln",
    "log10",
    "log2",
    "mad_over_time",
    "max_over_time",
    "min_over_time",
    "minute",
    "month",
    "pi",
    "predict_linear",
    "present_over_time",
    "quantile_over_time",
    "rad",
    "rate",
    "resets",
    "round",
    "scalar",
    "sgn",
    "sin",
    "sinh",
    "sort",
    "sort_desc",
    "sqrt",
    "stddev_over_time",
    "stdvar_over_time",
    "sum_over_time",
    "tan",
    "tanh",
    "time",
    "timestamp",
    "vector",
    "year",
    "avg",
    "sum",
    "min",
    "max",
    "count",
    "group",
    "topk",
    "bottomk",
    "count_values",
    "limitk",
    "limit_ratio",
}

DEFAULT_EXTERNAL_METRICS = {
    "ALERTS",
    "up",
    "scrape_duration_seconds_bucket",
    "scrape_samples_scraped",
}
DEFAULT_EXTERNAL_PREFIXES = {
    "prometheus_",
    "process_",
    "cpu_",
    "mem_",
    "disk_",
    "diskio_",
}


def clean_scalar(value: str) -> str:
    """Strip quotes from the small YAML subset parsed by this script."""

    value = value.strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        return value[1:-1].strip()
    return value


def load_contract(path: str) -> Dict[str, Set[str]]:
    """Load metric names from contracts/metric_contract.yaml.

    The repo avoids requiring PyYAML for this preflight check, so this parses
    only the contract sections needed by dashboard validation.
    """

    try:
        lines = open(path, "r", encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        raise SystemExit(f"ERROR: contract file not found: {path}")

    section = None
    subsection = None
    raw_series: Set[str] = set()
    recording_rules: Set[str] = set()
    external_metrics: Set[str] = set(DEFAULT_EXTERNAL_METRICS)
    external_prefixes: Set[str] = set(DEFAULT_EXTERNAL_PREFIXES)
    prototype_metrics: Set[str] = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        top = TOP_SECTION_RE.match(line)
        if top and not line.startswith(" "):
            section = top.group(1)
            subsection = None
            continue

        if section == "recording_rules":
            name_match = ITEM_NAME_RE.match(line)
            if name_match:
                recording_rules.add(clean_scalar(name_match.group(1)))
                continue

        if section == "raw_series":
            name_match = ITEM_NAME_RE.match(line)
            if name_match:
                raw_series.add(clean_scalar(name_match.group(1)))
                continue

        if section == "dashboard_metric_contract":
            section_match = SECTION_NAME_RE.match(line)
            if section_match:
                subsection = section_match.group(1)
                continue

            if subsection == "external_metrics":
                item_match = LIST_ITEM_RE.match(line)
                if item_match:
                    external_metrics.add(clean_scalar(item_match.group(1)))
                continue

            if subsection == "external_metric_prefixes":
                item_match = LIST_ITEM_RE.match(line)
                if item_match:
                    external_prefixes.add(clean_scalar(item_match.group(1)))
                continue

            if subsection == "prototype_metrics":
                item_match = LIST_ITEM_RE.match(line)
                if item_match:
                    prototype_metrics.add(clean_scalar(item_match.group(1)))
                continue

    if not recording_rules:
        raise SystemExit("ERROR: no recording_rules names found in contracts/metric_contract.yaml")

    return {
        "raw_series": raw_series,
        "recording_rules": recording_rules,
        "external_metrics": external_metrics,
        "external_prefixes": external_prefixes,
        "prototype_metrics": prototype_metrics,
    }


def relpath(path: str, root: str) -> str:
    """Return a repository-relative path using forward slashes."""

    return os.path.relpath(path, root).replace("\\", "/")


def iter_json_nodes(root: object):
    """Yield every dict node in a dashboard JSON document."""

    stack = [root]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            yield node
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)


def extract_metric_names(expr: str) -> Set[str]:
    """Extract likely metric identifiers from a PromQL expression."""

    prepared = RE_REMOVE_STRINGS.sub('""', expr)
    prepared = RE_REMOVE_GRAFANA_VARS.sub("", prepared)
    prepared = RE_REMOVE_LABEL_CTX.sub("", prepared)

    metrics: Set[str] = set(RE_METRIC_BRACED.findall(prepared))
    for match in RE_METRIC_BARE.findall(prepared):
        if match in PROMQL_KEYWORDS or match in PROMQL_FUNCTIONS:
            continue
        metrics.add(match)

    metrics.update(RE_LABEL_VALUES.findall(expr))
    return metrics


def is_allowed(
    metric: str,
    raw_series: Set[str],
    rules: Set[str],
    external_metrics: Set[str],
    external_prefixes: Set[str],
) -> bool:
    """Return whether a dashboard metric is covered by contract policy."""

    if metric in raw_series or metric in rules or metric in external_metrics:
        return True
    for prefix in external_prefixes:
        if metric.startswith(prefix):
            return True
    return False


def main() -> int:
    """Check all dev/prod dashboard JSON files against the contract."""

    repo_root = os.environ.get("REPO_ROOT")
    if not repo_root:
        repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    enforce = os.environ.get("ENFORCE_DASHBOARD_METRIC_CONTRACT", "0") == "1"

    contract_path = os.path.join(repo_root, "contracts", "metric_contract.yaml")
    contract = load_contract(contract_path)
    raw_series = contract["raw_series"]
    recording_rules = contract["recording_rules"]
    external_metrics = contract["external_metrics"]
    external_prefixes = contract["external_prefixes"]
    prototype_metrics = contract["prototype_metrics"]

    dash_globs = [
        os.path.join(repo_root, "grafana", "dashboards-dev", "**", "*.json"),
        os.path.join(repo_root, "grafana", "dashboards-prod", "**", "*.json"),
    ]
    dashboard_paths = sorted({p for g in dash_globs for p in glob(g, recursive=True)})
    if not dashboard_paths:
        print("ERROR: no dashboards found under grafana/dashboards-dev or grafana/dashboards-prod", file=sys.stderr)
        return 1

    unknown_refs: Dict[str, Set[str]] = {}
    prototype_refs: Dict[str, Set[str]] = {}
    referenced_metrics: Set[str] = set()
    parse_errors: List[str] = []

    for path in dashboard_paths:
        rp = relpath(path, repo_root)
        try:
            payload = json.load(open(path, "r", encoding="utf-8"))
        except Exception as exc:
            parse_errors.append(f"{rp}: invalid JSON ({exc})")
            continue

        metrics_in_file: Set[str] = set()
        for node in iter_json_nodes(payload):
            expr = node.get("expr")
            if isinstance(expr, str):
                metrics_in_file.update(extract_metric_names(expr))

            definition = node.get("definition")
            if isinstance(definition, str) and "label_values(" in definition:
                metrics_in_file.update(RE_LABEL_VALUES.findall(definition))

            query = node.get("query")
            if isinstance(query, str) and "label_values(" in query:
                metrics_in_file.update(RE_LABEL_VALUES.findall(query))

        for metric in sorted(metrics_in_file):
            referenced_metrics.add(metric)
            if is_allowed(metric, raw_series, recording_rules, external_metrics, external_prefixes):
                continue
            if metric in prototype_metrics:
                prototype_refs.setdefault(metric, set()).add(rp)
                continue
            unknown_refs.setdefault(metric, set()).add(rp)

    if parse_errors:
        print("ERROR: dashboard metric contract check failed", file=sys.stderr)
        for msg in parse_errors:
            print(f"  - {msg}", file=sys.stderr)
        return 1

    unknown_count = len(unknown_refs)
    prototype_count = len(prototype_refs)
    ref_count = len(referenced_metrics)
    mode = "enforce" if enforce else "warn"

    if unknown_count > 0:
        header = (
            "ERROR: dashboard metric contract drift detected"
            if enforce
            else "WARN: dashboard metric contract drift detected"
        )
        stream = sys.stderr if enforce else sys.stdout
        print(
            f"{header} (mode={mode}, unknown_metrics={unknown_count}, referenced_metrics={ref_count})",
            file=stream,
        )
        for metric in sorted(unknown_refs):
            refs = sorted(unknown_refs[metric])
            joined = ", ".join(refs)
            print(f"  - {metric}: {joined}", file=stream)
        if enforce:
            return 1

    if prototype_count > 0:
        print(
            "WARN: dashboard metric prototype debt detected "
            f"(prototype_metrics={prototype_count}, referenced_metrics={ref_count})"
        )
        for metric in sorted(prototype_refs):
            refs = sorted(prototype_refs[metric])
            joined = ", ".join(refs)
            print(f"  - {metric}: {joined}")

    print(
        "OK: dashboard metric contract check "
        f"(mode={mode}, referenced_metrics={ref_count}, unknown_metrics={unknown_count}, prototype_metrics={prototype_count})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
