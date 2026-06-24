#!/usr/bin/env python3
"""Publish Catalyst Center physical topology into Grafana node-graph CSVs."""

from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools" / "wireless_rf"))

from tools.common.config import env_bool  # noqa: E402
from tools.common.config import env_value  # noqa: E402
from tools.common.config import load_env_file  # noqa: E402
from tools.common.files import write_csv as common_write_csv  # noqa: E402
from tools.common.files import write_json  # noqa: E402
from wireless_rf.dnac_client import CatalystCenterTopologyReadClient  # noqa: E402


NODE_HEADERS = [
    "id",
    "title",
    "subtitle",
    "mainstat",
    "secondarystat",
    "color",
    "confidence",
    "arc__green",
    "arc__yellow",
    "arc__red",
    "site_id",
    "environment",
    "source_lineage",
    "detail_url",
]

EDGE_HEADERS = [
    "id",
    "source",
    "target",
    "mainstat",
    "secondarystat",
    "color",
    "confidence",
    "site_id",
    "environment",
    "source_lineage",
    "detail",
]

ACTIVE_DEVICE_STATES = {"reachable", "managed", "active", "success"}
DOWN_DEVICE_STATES = {"unreachable", "down", "inactive", "failed", "partial collection failure"}
ACTIVE_LINK_STATES = {"up", "active", "connected"}
DOWN_LINK_STATES = {"down", "inactive", "disconnected", "failed"}
UNKNOWN_LINK_SPEED_COLOR = "#8a8f98"
LINK_SPEED_COLOR_SCHEME = (
    (100.0, "#b877d9"),
    (40.0, "#705da0"),
    (25.0, "#5794f2"),
    (10.0, "#33b5e5"),
    (5.0, "#73bf69"),
    (2.5, "#f2cc0c"),
    (1.0, "#ff9830"),
    (0.0, "#e02f44"),
)


def response_payload(payload: Any) -> Any:
    """Unwrap Catalyst Center responses that nest data under `response`."""

    if isinstance(payload, dict) and "response" in payload:
        return payload["response"]
    return payload


def response_list(payload: Any, key: str | None = None) -> list[dict[str, Any]]:
    """Return a list of mapping rows from common Catalyst Center payload shapes."""

    response = response_payload(payload)
    if isinstance(response, dict) and key and isinstance(response.get(key), list):
        response = response[key]
    if not isinstance(response, list):
        return []
    return [dict(item) for item in response if isinstance(item, Mapping)]


def text(*values: Any, default: str = "unknown") -> str:
    """Return the first non-empty value as text."""

    for value in values:
        if value not in (None, ""):
            normalized = str(value).strip()
            if normalized:
                return normalized
    return default


def nested(mapping: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    """Return a nested mapping value or an empty mapping."""

    value = mapping.get(key)
    return value if isinstance(value, Mapping) else {}


def confidence_color(confidence: str) -> str:
    """Map normalized confidence to Grafana node/edge colors."""

    if confidence == "high":
        return "#299c46"
    if confidence == "medium":
        return "#e0b400"
    return "#d44a3a"


def confidence_arcs(confidence: str) -> tuple[int, int, int]:
    """Return green/yellow/red arc flags for Grafana node graph confidence."""

    if confidence == "high":
        return 1, 0, 0
    if confidence == "medium":
        return 0, 1, 0
    return 0, 0, 1


def parse_link_speed_gbps(value: Any) -> float | None:
    """Return a link speed in Gbps from Catalyst Center speed values."""

    if value in (None, ""):
        return None
    raw = str(value).strip().lower().replace(",", "")
    if not raw or raw in {"-1", "unknown", "none", "null", "n/a"}:
        return None

    suffix_factor = 1.0 / 1_000_000.0
    for suffix, factor in (
        ("gbps", 1.0),
        ("gbit/s", 1.0),
        ("g", 1.0),
        ("mbps", 1.0 / 1000.0),
        ("mbit/s", 1.0 / 1000.0),
        ("m", 1.0 / 1000.0),
        ("kbps", 1.0 / 1_000_000.0),
        ("kbit/s", 1.0 / 1_000_000.0),
        ("k", 1.0 / 1_000_000.0),
    ):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)].strip()
            suffix_factor = factor
            break

    try:
        speed = float(raw) * suffix_factor
    except ValueError:
        return None
    return speed if speed > 0 else None


def link_speed_gbps(*values: Any) -> float | None:
    """Return the first parseable link speed from candidate DNAC fields."""

    for value in values:
        speed = parse_link_speed_gbps(value)
        if speed is not None:
            return speed
    return None


def format_link_speed_gbps(speed_gbps: float | None) -> str:
    """Format a normalized Gbps value for node-graph edge labels."""

    if speed_gbps is None:
        return "unknown"
    if speed_gbps.is_integer():
        return f"{int(speed_gbps)} Gbps"
    return f"{speed_gbps:.3f}".rstrip("0").rstrip(".") + " Gbps"


def link_speed_color(speed_gbps: float | None) -> str:
    """Color edges by link speed, using gray for unknown speeds."""

    if speed_gbps is None:
        return UNKNOWN_LINK_SPEED_COLOR
    for threshold, color in LINK_SPEED_COLOR_SCHEME:
        if speed_gbps >= threshold:
            return color
    return UNKNOWN_LINK_SPEED_COLOR


def normalize_device_confidence(device: Mapping[str, Any] | None) -> str:
    """Classify device confidence from Catalyst Center health/state fields."""

    if not device:
        return "medium"
    states = [
        str(device.get("reachabilityStatus") or "").strip().lower(),
        str(device.get("managementState") or "").strip().lower(),
        str(device.get("collectionStatus") or "").strip().lower(),
    ]
    if any(state in ACTIVE_DEVICE_STATES for state in states):
        return "high"
    if any(state in DOWN_DEVICE_STATES for state in states):
        return "low"
    return "medium"


def normalize_link_confidence(link_status: Any) -> str:
    """Classify physical-link confidence from Catalyst Center link status."""

    status = str(link_status or "").strip().lower()
    if status in ACTIVE_LINK_STATES:
        return "high"
    if status in DOWN_LINK_STATES:
        return "low"
    return "medium"


def site_label(site: Mapping[str, Any]) -> str:
    """Return the most useful site label from Catalyst Center site metadata."""

    return text(
        site.get("groupNameHierarchy"),
        site.get("displayName"),
        site.get("name"),
        site.get("id"),
        default="unknown",
    )


def device_status(device: Mapping[str, Any] | None) -> str:
    """Return a compact device status label for Grafana mainstat."""

    if not device:
        return "discovered"
    return text(device.get("reachabilityStatus"), device.get("managementState"), default="discovered").lower()


def detail_url(base_url: str, node_id: str) -> str:
    """Build a Catalyst Center network-device API URL for drilldowns."""

    encoded = urllib.parse.quote(node_id, safe="")
    return f"{base_url.rstrip()}/dna/intent/api/v1/network-device/{encoded}"


def build_device_indexes(devices: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Index DNAC device inventory by every identifier topology nodes may use."""

    index: dict[str, dict[str, Any]] = {}
    for device in devices:
        row = dict(device)
        for key in ("id", "instanceUuid", "uuid", "managementIpAddress", "hostname"):
            value = str(device.get(key) or "").strip()
            if value:
                index[value] = row
    return index


def build_site_index(site_topology: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index Catalyst Center site topology by site id."""

    sites = site_topology.get("sites")
    if not isinstance(sites, list):
        return {}
    return {
        str(site.get("id")): dict(site)
        for site in sites
        if isinstance(site, Mapping) and site.get("id")
    }


def node_site_id(
    node: Mapping[str, Any],
    device: Mapping[str, Any] | None,
    sites_by_id: Mapping[str, Mapping[str, Any]],
) -> str:
    """Resolve a topology node's site label from node metadata or device inventory."""

    site_id = text(nested(node, "additionalInfo").get("siteid"), default="")
    if site_id and site_id in sites_by_id:
        return site_label(sites_by_id[site_id])
    if device:
        return text(device.get("locationName"), device.get("snmpLocation"), default="unknown")
    return "unknown"


def build_node_rows(
    nodes: Iterable[Mapping[str, Any]],
    links: Iterable[Mapping[str, Any]],
    devices_by_key: Mapping[str, dict[str, Any]],
    sites_by_id: Mapping[str, Mapping[str, Any]],
    *,
    base_url: str,
    environment: str,
    source_lineage: str,
) -> list[dict[str, Any]]:
    """Convert DNAC physical-topology nodes into Grafana node-graph rows."""

    rows_by_id: dict[str, dict[str, Any]] = {}
    for node in nodes:
        node_id = text(node.get("id"), default="")
        if not node_id:
            continue
        device = (
            devices_by_key.get(node_id)
            or devices_by_key.get(text(node.get("ip"), default=""))
            or devices_by_key.get(text(node.get("label"), default=""))
        )
        confidence = normalize_device_confidence(device)
        green, yellow, red = confidence_arcs(confidence)
        family = text(node.get("family"), device.get("family") if device else None, default="network_device")
        role = text(node.get("role"), device.get("role") if device else None, default=family)
        site_id = node_site_id(node, device, sites_by_id)
        rows_by_id[node_id] = {
            "id": node_id,
            "title": text(node.get("label"), device.get("hostname") if device else None, node.get("ip"), node_id),
            "subtitle": f"{family} | {site_id} | confidence={confidence}",
            "mainstat": device_status(device),
            "secondarystat": confidence,
            "color": confidence_color(confidence),
            "confidence": confidence,
            "arc__green": green,
            "arc__yellow": yellow,
            "arc__red": red,
            "site_id": site_id,
            "environment": environment,
            "source_lineage": source_lineage,
            "detail_url": detail_url(base_url, node_id),
            "_role": role,
        }

    for link in links:
        for endpoint in (link.get("source"), link.get("target")):
            node_id = text(endpoint, default="")
            if not node_id or node_id in rows_by_id:
                continue
            confidence = "medium"
            green, yellow, red = confidence_arcs(confidence)
            rows_by_id[node_id] = {
                "id": node_id,
                "title": node_id,
                "subtitle": f"endpoint from link-only topology | unknown | confidence={confidence}",
                "mainstat": "discovered",
                "secondarystat": confidence,
                "color": confidence_color(confidence),
                "confidence": confidence,
                "arc__green": green,
                "arc__yellow": yellow,
                "arc__red": red,
                "site_id": "unknown",
                "environment": environment,
                "source_lineage": source_lineage,
                "detail_url": detail_url(base_url, node_id),
                "_role": "unknown",
            }

    return [
        {key: value for key, value in row.items() if key in NODE_HEADERS}
        for _node_id, row in sorted(rows_by_id.items())
    ]


def link_id(link: Mapping[str, Any], idx: int, seen: set[str]) -> str:
    """Return a stable unique id for one topology edge."""

    base = text(link.get("id"), default="")
    if not base:
        base = "|".join(
            [
                text(link.get("source"), default=""),
                text(link.get("target"), default=""),
                text(link.get("startPortName"), default=""),
                text(link.get("endPortName"), default=""),
            ]
        ).strip("|")
    if not base:
        base = f"dnac-link-{idx}"
    candidate = base
    suffix = 2
    while candidate in seen:
        candidate = f"{base}-{suffix}"
        suffix += 1
    seen.add(candidate)
    return candidate


def build_edge_rows(
    links: Iterable[Mapping[str, Any]],
    nodes_by_id: Mapping[str, Mapping[str, Any]],
    *,
    source_lineage: str,
) -> list[dict[str, Any]]:
    """Convert DNAC physical-topology links into Grafana node-graph edges."""

    rows: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for idx, link in enumerate(links, start=1):
        source = text(link.get("source"), default="")
        target = text(link.get("target"), default="")
        if not source or not target:
            continue
        confidence = normalize_link_confidence(link.get("linkStatus"))
        source_node = nodes_by_id.get(source, {})
        target_node = nodes_by_id.get(target, {})
        source_site = text(source_node.get("site_id"), default="unknown")
        target_site = text(target_node.get("site_id"), default="unknown")
        source_env = text(source_node.get("environment"), default="unknown")
        target_env = text(target_node.get("environment"), default="unknown")
        site_id = source_site if source_site == target_site else "inter-site"
        environment = source_env if source_env == target_env else "mixed"
        start_port = text(link.get("startPortName"), default="")
        end_port = text(link.get("endPortName"), default="")
        speed_gbps = link_speed_gbps(link.get("startPortSpeed"), link.get("endPortSpeed"), link.get("speed"))
        speed_label = format_link_speed_gbps(speed_gbps)
        status = text(link.get("linkStatus"), default="unknown")
        rows.append(
            {
                "id": link_id(link, idx, seen_ids),
                "source": source,
                "target": target,
                "mainstat": speed_label,
                "secondarystat": confidence,
                "color": link_speed_color(speed_gbps),
                "confidence": confidence,
                "site_id": site_id,
                "environment": environment,
                "source_lineage": source_lineage,
                "detail": f"{start_port} -> {end_port} | bandwidth={speed_label} | status={status} | confidence={confidence}",
            }
        )
    return rows


def write_csv(path: Path, headers: list[str], rows: list[Mapping[str, Any]]) -> None:
    """Write Grafana CSV data with deterministic headers."""

    common_write_csv(path, headers, rows)


def fetch_network_devices(client: CatalystCenterTopologyReadClient, page_limit: int) -> list[dict[str, Any]]:
    """Fetch Catalyst Center device inventory, using pagination when available."""

    return client.list_network_devices(page_limit)


def publish_dnac_topology(
    *,
    client: CatalystCenterTopologyReadClient,
    output_dir: Path,
    raw_out_dir: Path | None,
    environment: str,
    source_lineage: str,
    page_limit: int,
) -> tuple[int, int]:
    """Fetch DNAC topology/inventory and publish node/edge CSV artifacts."""

    site_payload = client.get_site_topology()
    physical_payload = client.get_physical_topology()
    devices = fetch_network_devices(client, page_limit)

    site_topology = response_payload(site_payload)
    physical_topology = response_payload(physical_payload)
    if not isinstance(site_topology, Mapping):
        site_topology = {}
    if not isinstance(physical_topology, Mapping):
        physical_topology = {}

    nodes = response_list(physical_payload, "nodes")
    links = response_list(physical_payload, "links")
    sites_by_id = build_site_index(site_topology)
    devices_by_key = build_device_indexes(devices)
    node_rows = build_node_rows(
        nodes,
        links,
        devices_by_key,
        sites_by_id,
        base_url=client.base_url,
        environment=environment,
        source_lineage=source_lineage,
    )
    nodes_by_id = {str(row["id"]): row for row in node_rows}
    edge_rows = build_edge_rows(links, nodes_by_id, source_lineage=source_lineage)

    write_csv(output_dir / "topology_nodes_v1.csv", NODE_HEADERS, node_rows)
    write_csv(output_dir / "topology_edges_v1.csv", EDGE_HEADERS, edge_rows)

    if raw_out_dir:
        stamp = str(int(time.time()))
        write_json(raw_out_dir / f"{stamp}-site-topology.json", site_payload)
        write_json(raw_out_dir / f"{stamp}-physical-topology.json", physical_payload)
        write_json(raw_out_dir / f"{stamp}-network-device.json", {"response": devices})

    return len(node_rows), len(edge_rows)


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    """Parse DNAC topology publisher CLI arguments."""

    parser = argparse.ArgumentParser(description="Publish Catalyst Center topology CSVs for Grafana Node Graph.")
    parser.add_argument("--env-file", default=os.environ.get("TOPOLOGY_DNAC_ENV_FILE", "/etc/grafana-mimir-observability/secrets/dnac-readonly.env"))
    parser.add_argument("--base-url", default=os.environ.get("DNAC_BASE_URL"))
    parser.add_argument("--username", default=os.environ.get("DNAC_USERNAME"))
    parser.add_argument("--password", default=os.environ.get("DNAC_PASSWORD"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/network-topology/dnac"))
    parser.add_argument("--raw-out-dir", type=Path)
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--source-lineage", default="dnac_physical_topology")
    parser.add_argument("--page-limit", type=int, default=500)
    parser.add_argument("--insecure", action="store_true", help="Disable Catalyst Center TLS verification.")
    return parser.parse_args(list(argv))


def main(argv: Iterable[str]) -> int:
    """CLI entrypoint for publishing Catalyst Center topology CSVs."""

    args = parse_args(argv)
    env_file_values = load_env_file(args.env_file)
    base_url = args.base_url or env_value("DNAC_BASE_URL", env_file_values)
    username = args.username or env_value("DNAC_USERNAME", env_file_values)
    credential = args.password or env_value("DNAC_PASSWORD", env_file_values)
    insecure = args.insecure
    if not insecure:
        insecure = not env_bool("DNAC_VERIFY_TLS", True, env_file_values)
    if not insecure:
        insecure = env_bool("TOPOLOGY_DNAC_INSECURE", False, env_file_values)
    missing = [
        name for name, value in {
            "DNAC_BASE_URL": base_url,
            "DNAC_USERNAME": username,
            "DNAC_PASSWORD": credential,
        }.items() if not value
    ]
    if missing:
        print("ERROR: missing DNAC values: " + ", ".join(missing), file=sys.stderr)
        return 2
    if args.page_limit < 1:
        print("ERROR: --page-limit must be positive", file=sys.stderr)
        return 2

    client_kwargs = {
        "base_url": str(base_url),
        "username": str(username),
        "verify_tls": not insecure,
    }
    client_kwargs["password"] = str(credential)
    client = CatalystCenterTopologyReadClient(**client_kwargs)
    try:
        node_count, edge_count = publish_dnac_topology(
            client=client,
            output_dir=args.output_dir,
            raw_out_dir=args.raw_out_dir,
            environment=args.environment,
            source_lineage=args.source_lineage,
            page_limit=args.page_limit,
        )
    except Exception as exc:
        print(f"ERROR: failed to publish DNAC topology: {exc}", file=sys.stderr)
        return 1
    print(f"Published DNAC topology: {node_count} nodes, {edge_count} edges to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
