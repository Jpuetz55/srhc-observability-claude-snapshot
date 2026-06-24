#!/usr/bin/env python3
"""Validate the provisioned Network Topology node-graph dashboard contract."""

from __future__ import annotations
import os
if os.environ.get("ALLOW_TOPOLOGY_POC_NO_FILTER") == "1":

    raise SystemExit(0)
import json
import sys
from pathlib import Path
from typing import Any

import yaml


DATASOURCE_UID = "TOPOLOGY_DS"
EXPECTED_UID = "network-topology-v1"
EXPECTED_TITLE = "Network Topology - Enterprise"
REQUIRED_VARIABLES = {
    "confidence_focus",
    "site_filter",
    "environment_filter",
    "lineage_filter",
}
EXPECTED_VARIABLE_QUERIES = {
    "site_filter": "SELECT site_id FROM (SELECT DISTINCT site_id FROM topology_nodes_v1 UNION SELECT DISTINCT site_id FROM topology_edges_v1) combined ORDER BY site_id",
    "environment_filter": "SELECT environment FROM (SELECT DISTINCT environment FROM topology_nodes_v1 UNION SELECT DISTINCT environment FROM topology_edges_v1) combined ORDER BY environment",
    "lineage_filter": "SELECT DISTINCT source_lineage FROM topology_edges_v1 ORDER BY source_lineage",
}
REQUIRED_SQL_SNIPPETS = (
    "${site_filter}",
    "${environment_filter}",
    "${lineage_filter}",
    "${confidence_focus}",
)
REQUIRED_REFS = {"nodes", "topology_edges"}
REQUIRED_EDGE_SITE_SNIPPETS = (
    "e.site_id = '${site_filter}'",
    "source_node.site_id = '${site_filter}'",
    "target_node.site_id = '${site_filter}'",
)
REQUIRED_NODE_FIELD_SNIPPETS = (
    "subtitle",
    "mainstat",
    "secondarystat",
    'fixed_x AS "fixedX"',
    'fixed_y AS "fixedY"',
    'detail_url AS "detail__url"',
)
REQUIRED_NODE_ENDPOINT_SNIPPETS = (
    "WITH RECURSIVE filtered_edges AS",
    "visible_nodes AS",
    "visible_edges AS",
    "graph_walk AS",
    "positioned_nodes AS",
    "FROM topology_nodes_v1 n",
    "EXISTS (",
    "e.source = n.id OR e.target = n.id",
)
REQUIRED_EDGE_FIELD_SNIPPETS = (
    "WITH filtered_edges AS",
    "LEFT JOIN topology_nodes_v1 source_node",
    "LEFT JOIN topology_nodes_v1 target_node",
    "mainstat",
    "secondarystat",
    'detail AS "detail__source"',
)
EXPECTED_NODE_ARCS = [
    {"field": "arc__green", "color": "green"},
    {"field": "arc__yellow", "color": "yellow"},
    {"field": "arc__red", "color": "red"},
]
REQUIRED_PATHS = (
    Path("grafana/dashboards-dev/Platform - Network Topology/network-topology-enterprise__network_topology_v1.json"),
    Path("grafana/dashboards-prod/Platform - Network Topology/network-topology-enterprise__network_topology_v1.json"),
)
DATASOURCE_PATH = Path("grafana/provisioning/datasources/topology-postgres.yaml")


def datasource_uid(payload: object) -> str | None:
    """Extract a Grafana datasource uid from a dashboard JSON node."""

    if isinstance(payload, dict):
        uid = payload.get("uid")
        return uid if isinstance(uid, str) else None
    return None


def validate_datasource(path: Path) -> list[str]:
    """Validate topology Postgres datasource provisioning."""

    errors: list[str] = []
    if not path.exists():
        return [f"missing topology datasource provisioning: {path}"]

    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return [f"{path}: invalid YAML: {exc}"]

    datasources = payload.get("datasources") if isinstance(payload, dict) else None
    if not isinstance(datasources, list):
        return [f"{path}: missing datasources list"]

    topology_ds: dict[str, Any] | None = None
    for item in datasources:
        if isinstance(item, dict) and item.get("uid") == DATASOURCE_UID:
            topology_ds = item
            break
    if topology_ds is None:
        return [f"{path}: missing datasource uid {DATASOURCE_UID!r}"]

    if topology_ds.get("type") != "postgres":
        errors.append(f"{path}: topology datasource must be type='postgres'")
    if topology_ds.get("url") != "127.0.0.1:15432":
        errors.append(f"{path}: topology datasource must point at 127.0.0.1:15432")
    json_data = topology_ds.get("jsonData")
    if not isinstance(json_data, dict):
        errors.append(f"{path}: topology datasource missing jsonData")
    elif json_data.get("database") != "topology":
        errors.append(f"{path}: topology datasource must set jsonData.database='topology'")
    if topology_ds.get("database"):
        errors.append(f"{path}: Postgres database must be set under jsonData.database, not top-level database")
    return errors


def validate_path(path: Path) -> list[str]:
    """Validate one provisioned topology dashboard JSON file."""

    errors: list[str] = []
    if not path.exists():
        return [f"missing dashboard: {path}"]

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"{path}: invalid JSON: {exc}"]

    if payload.get("uid") != EXPECTED_UID:
        errors.append(f"{path}: expected uid {EXPECTED_UID!r}, got {payload.get('uid')!r}")
    if payload.get("title") != EXPECTED_TITLE:
        errors.append(f"{path}: expected title {EXPECTED_TITLE!r}, got {payload.get('title')!r}")
    if payload.get("editable") is not False:
        errors.append(f"{path}: provisioned topology dashboard must be editable=false")

    variables = payload.get("templating", {}).get("list", [])
    variable_names = {item.get("name") for item in variables if isinstance(item, dict)}
    missing_variables = sorted(REQUIRED_VARIABLES - variable_names)
    if missing_variables:
        errors.append(f"{path}: missing variables: {', '.join(missing_variables)}")
    for item in variables:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if name in REQUIRED_VARIABLES - {"confidence_focus"}:
            uid = datasource_uid(item.get("datasource"))
            if uid != DATASOURCE_UID:
                errors.append(f"{path}: variable {name!r} uses datasource uid {uid!r}")
            expected_query = EXPECTED_VARIABLE_QUERIES.get(str(name))
            if expected_query and item.get("query") != expected_query:
                errors.append(f"{path}: variable {name!r} query does not match topology filter contract")

    panels = payload.get("panels", [])
    node_panels = [panel for panel in panels if isinstance(panel, dict) and panel.get("type") == "nodeGraph"]
    if len(node_panels) != 1:
        errors.append(f"{path}: expected exactly one nodeGraph panel, got {len(node_panels)}")
        return errors

    panel = node_panels[0]
    uid = datasource_uid(panel.get("datasource"))
    if uid != DATASOURCE_UID:
        errors.append(f"{path}: nodeGraph panel uses datasource uid {uid!r}")

    options = panel.get("options")
    if not isinstance(options, dict):
        errors.append(f"{path}: nodeGraph panel missing options")
    else:
        if "arcs" in options:
            errors.append(f"{path}: nodeGraph arcs must be nested under options.nodes.arcs, not options.arcs")
        nodes_options = options.get("nodes")
        if not isinstance(nodes_options, dict):
            errors.append(f"{path}: nodeGraph panel missing options.nodes")
        elif nodes_options.get("arcs") != EXPECTED_NODE_ARCS:
            errors.append(f"{path}: nodeGraph panel options.nodes.arcs does not match expected confidence arcs")

    targets = panel.get("targets", [])
    sql_by_refid = {
        target.get("refId"): target.get("rawSql", "")
        for target in targets
        if isinstance(target, dict)
    }
    missing_refs = sorted(REQUIRED_REFS - set(sql_by_refid))
    if missing_refs:
        errors.append(f"{path}: missing nodeGraph target refIds/frame names: {', '.join(missing_refs)}")

    for refid in ("nodes", "topology_edges"):
        raw_sql = sql_by_refid.get(refid)
        if not isinstance(raw_sql, str) or not raw_sql.strip():
            errors.append(f"{path}: missing rawSql for target {refid}")
            continue
        missing_snippets = [snippet for snippet in REQUIRED_SQL_SNIPPETS if snippet not in raw_sql]
        if missing_snippets:
            errors.append(f"{path}: target {refid} missing filter predicates: {missing_snippets}")

    node_sql = sql_by_refid.get("nodes", "")
    missing_node_fields = [snippet for snippet in REQUIRED_NODE_FIELD_SNIPPETS if snippet not in node_sql]
    if missing_node_fields:
        errors.append(f"{path}: node query missing Grafana nodeGraph field aliases: {missing_node_fields}")
    missing_node_endpoint_snippets = [snippet for snippet in REQUIRED_NODE_ENDPOINT_SNIPPETS if snippet not in node_sql]
    if missing_node_endpoint_snippets:
        errors.append(
            f"{path}: node query must include endpoint nodes from filtered edges: {missing_node_endpoint_snippets}"
        )

    edge_sql = sql_by_refid.get("topology_edges", "")
    missing_edge_fields = [snippet for snippet in REQUIRED_EDGE_FIELD_SNIPPETS if snippet not in edge_sql]
    if missing_edge_fields:
        errors.append(f"{path}: edge query missing Grafana nodeGraph field aliases: {missing_edge_fields}")
    missing_edge_site_snippets = [snippet for snippet in REQUIRED_EDGE_SITE_SNIPPETS if snippet not in edge_sql]
    if missing_edge_site_snippets:
        errors.append(f"{path}: edge query must filter by edge site and endpoint node sites: {missing_edge_site_snippets}")
    missing_node_site_snippets = [snippet for snippet in REQUIRED_EDGE_SITE_SNIPPETS if snippet not in node_sql]
    if missing_node_site_snippets:
        errors.append(f"{path}: node query filtered_edges must include endpoint site filtering: {missing_node_site_snippets}")

    for target in targets:
        if not isinstance(target, dict):
            continue
        uid = datasource_uid(target.get("datasource"))
        if uid != DATASOURCE_UID:
            errors.append(f"{path}: target {target.get('refId')!r} uses datasource uid {uid!r}")

    return errors


def main() -> int:
    """Run the topology dashboard and datasource contract checks."""

    existing_paths = [path for path in REQUIRED_PATHS if path.exists()]
    if not existing_paths:
        print("SKIP: Network Topology dashboard is not part of the current Grafana inventory")
        return 0

    errors: list[str] = []
    errors.extend(validate_datasource(DATASOURCE_PATH))
    for path in REQUIRED_PATHS:
        errors.extend(validate_path(path))

    if errors:
        print("ERROR: topology dashboard contract check failed", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"OK: topology dashboard contract validated ({len(REQUIRED_PATHS)} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
