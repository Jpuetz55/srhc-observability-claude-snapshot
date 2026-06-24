#!/usr/bin/env python3
"""Synthetic tests for DNAC topology publisher mappings."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publish_dnac_topology as topo  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise an assertion with a clear fixture-specific message."""

    if not condition:
        raise AssertionError(message)


def test_dnac_topology_mapping() -> None:
    """Verify DNAC nodes/links become Grafana node-graph rows."""

    sites_by_id = topo.build_site_index(
        {
            "sites": [
                {
                    "id": "site-1",
                    "groupNameHierarchy": "Global/SRHC/Main",
                    "name": "Main",
                }
            ]
        }
    )
    devices = [
        {
            "id": "dev-a",
            "hostname": "core-a",
            "managementIpAddress": "10.0.0.1",
            "reachabilityStatus": "Reachable",
            "family": "Switches and Hubs",
        },
        {
            "id": "dev-b",
            "hostname": "wlc-a",
            "managementIpAddress": "10.0.0.2",
            "reachabilityStatus": "Unreachable",
            "family": "Wireless Controller",
        },
    ]
    nodes = [
        {
            "id": "dev-a",
            "label": "core-a",
            "ip": "10.0.0.1",
            "family": "Switches and Hubs",
            "role": "CORE",
            "additionalInfo": {"siteid": "site-1"},
        },
        {
            "id": "dev-b",
            "label": "wlc-a",
            "ip": "10.0.0.2",
            "family": "Wireless Controller",
            "role": "ACCESS",
            "additionalInfo": {"siteid": "site-1"},
        },
    ]
    links = [
        {
            "id": "link-1",
            "source": "dev-a",
            "target": "dev-b",
            "startPortName": "Ten1/0/1",
            "endPortName": "Gi0",
            "startPortSpeed": "10G",
            "linkStatus": "UP",
        }
    ]
    node_rows = topo.build_node_rows(
        nodes,
        links,
        topo.build_device_indexes(devices),
        sites_by_id,
        base_url="https://dnac.example",
        environment="prod",
        source_lineage="dnac_physical_topology",
    )
    nodes_by_id = {row["id"]: row for row in node_rows}
    edge_rows = topo.build_edge_rows(
        links,
        nodes_by_id,
        source_lineage="dnac_physical_topology",
    )

    require(len(node_rows) == 2, f"expected two node rows: {node_rows}")
    require(len(edge_rows) == 1, f"expected one edge row: {edge_rows}")
    require(nodes_by_id["dev-a"]["confidence"] == "high", f"bad reachable confidence: {nodes_by_id['dev-a']}")
    require(nodes_by_id["dev-b"]["confidence"] == "low", f"bad unreachable confidence: {nodes_by_id['dev-b']}")
    require(nodes_by_id["dev-a"]["site_id"] == "Global/SRHC/Main", f"bad site label: {nodes_by_id['dev-a']}")
    require(edge_rows[0]["source"] == "dev-a" and edge_rows[0]["target"] == "dev-b", f"bad edge endpoints: {edge_rows[0]}")
    require(edge_rows[0]["confidence"] == "high", f"bad edge confidence: {edge_rows[0]}")
    require(edge_rows[0]["mainstat"] == "10 Gbps", f"bad edge bandwidth label: {edge_rows[0]}")
    require(edge_rows[0]["color"] == topo.link_speed_color(10.0), f"bad edge bandwidth color: {edge_rows[0]}")
    require("bandwidth=10 Gbps" in edge_rows[0]["detail"], f"missing bandwidth detail: {edge_rows[0]}")
    require(edge_rows[0]["site_id"] == "Global/SRHC/Main", f"bad edge site: {edge_rows[0]}")


def test_link_speed_normalization() -> None:
    """Verify DNAC link speed variants normalize to Gbps labels and colors."""

    require(topo.link_speed_gbps("10000000") == 10.0, "DNAC numeric speed should be interpreted as Kbps")
    require(topo.link_speed_gbps("-1", "2500000") == 2.5, "invalid start speed should fall back to end speed")
    require(topo.link_speed_gbps("1000M") == 1.0, "Mbps suffix should normalize to Gbps")
    require(topo.format_link_speed_gbps(0.1) == "0.1 Gbps", "sub-gig speeds must still be labeled in Gbps")
    require(topo.format_link_speed_gbps(25.0) == "25 Gbps", "integer Gbps labels should not include decimals")
    require(topo.link_speed_color(100.0) == "#b877d9", "100 Gbps color changed unexpectedly")
    require(topo.link_speed_color(10.0) == "#33b5e5", "10 Gbps color changed unexpectedly")
    require(topo.link_speed_color(0.1) == "#e02f44", "sub-gig color changed unexpectedly")
    require(topo.link_speed_color(None) == topo.UNKNOWN_LINK_SPEED_COLOR, "unknown speed should use neutral color")


def main() -> int:
    """Run the standalone DNAC topology publisher tests."""

    test_dnac_topology_mapping()
    test_link_speed_normalization()
    print("OK: DNAC topology publisher tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
