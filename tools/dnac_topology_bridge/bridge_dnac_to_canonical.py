#!/usr/bin/env python3
"""Bridge DNAC raw export into canonical Network-Topology working CSVs.

Fills the gap between scripts/import_dnac_inventory.py (which dumps raw DNAC
data to data/raw/dnac_export_<DATE>/*.csv) and scripts/publish_node_graph.py
(which only reads data/working/*.v1.csv). Three things:

  1. Layer assignment per device, from a YAML lookup (role -> layer, family
     -> layer, hostname pattern overrides). Layers: 0=Edge/WAN, 1=Core,
     2=Distribution, 3=Access/WLC, 4=Endpoints, 5=Other. The layer is held
     in memory only; it is used inside the bridge to do (2) below.

  2. Normalized link direction so a_device_id is always at a LOWER layer
     than z_device_id. DNAC's /topology/physical-topology returns link
     endpoints without semantic direction, which makes the dashboard's BFS
     hierarchy SQL collapse every node to graph_depth = 0 (everything in
     one flat row). With direction normalized, "root" nodes are the layer-0
     edge devices and depth grows downward as expected.

  3. evidence_ref rewritten to CFG-DNAC-<YYYY-MM-DD> so
     publish_node_graph.py's classify_link_confidence() returns "high" and
     classify_source_lineage_from_evidence() returns "config_export" -
     DNAC-observed links are treated as high-confidence operational facts
     rather than the "manual_or_unknown" lineage they get with the raw
     DNAC_TOPOLOGY:... evidence string.

Run from the Network-Topology repo root, after import_dnac_inventory.py:

    python3 scripts/bridge_dnac_to_canonical.py \\
        --raw-dir data/raw \\
        --working-dir data/working \\
        --role-layer-config config/dnac_role_layer.yaml
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import fnmatch
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    import yaml
except ImportError:  # pragma: no cover - operator environment surfaces this directly
    sys.exit("PyYAML is required: pip install pyyaml")


# Canonical schemas. These must stay aligned with publish_node_graph.py's
# devices.v1.csv / links.v1.csv readers - re-running this bridge does not write
# any column the publisher does not expect.
DEVICE_HEADERS = [
    "device_id",
    "hostname",
    "mgmt_ip",
    "site_id",
    "role",
    "vendor",
    "model",
    "os_version",
    "owner",
    "criticality",
    "status",
    "last_verified_at",
]
LINK_HEADERS = [
    "link_id",
    "a_device_id",
    "a_interface_id",
    "z_device_id",
    "z_interface_id",
    "medium",
    "capacity",
    "is_wan",
    "status",
    "evidence_ref",
]

DEFAULT_LAYER = 5  # "Other / unknown" - landing zone for anything the lookup misses.
EXPORT_DIR_RE = re.compile(r"^dnac_export_(\d{4}-\d{2}-\d{2})$")


def load_role_layer_config(path: Path) -> dict[str, Any]:
    """Load role/family/hostname layer rules used to orient DNAC links."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: top-level YAML must be a mapping")

    def _upper_map(section: str) -> dict[str, int]:
        """Normalize one YAML mapping section to uppercase string keys and int layers."""

        return {
            str(k).upper(): int(v)
            for k, v in (raw.get(section) or {}).items()
        }

    patterns: list[dict[str, Any]] = []
    for entry in raw.get("hostname_patterns") or []:
        if not isinstance(entry, dict) or "pattern" not in entry or "layer" not in entry:
            raise ValueError(
                f"{path}: hostname_patterns entries need 'pattern' and 'layer' keys"
            )
        patterns.append(
            {"pattern": str(entry["pattern"]).upper(), "layer": int(entry["layer"])}
        )
    return {
        "role": _upper_map("role"),
        "family": _upper_map("family"),
        "hostname_patterns": patterns,
    }


def device_layer(device: Mapping[str, str], cfg: Mapping[str, Any]) -> int:
    """Return the topology layer for one DNAC device row."""

    hostname = (device.get("hostname") or "").upper()
    device_id = (device.get("device_id") or "").upper()
    role = (device.get("role") or "").upper().strip()

    for entry in cfg["hostname_patterns"]:
        if fnmatch.fnmatchcase(hostname, entry["pattern"]) or fnmatch.fnmatchcase(
            device_id, entry["pattern"]
        ):
            return entry["layer"]

    if role in cfg["role"]:
        return cfg["role"][role]

    for fam_key, layer in cfg["family"].items():
        if fam_key and fam_key in role:
            return layer

    return DEFAULT_LAYER


def find_latest_export_dir(raw_dir: Path) -> Path:
    """Find the newest data/raw/dnac_export_<DATE> directory."""

    if not raw_dir.is_dir():
        raise FileNotFoundError(f"raw-dir does not exist: {raw_dir}")
    candidates = [
        child
        for child in raw_dir.iterdir()
        if child.is_dir() and EXPORT_DIR_RE.match(child.name)
    ]
    if not candidates:
        raise FileNotFoundError(
            f"No dnac_export_<DATE> subdirectory found under {raw_dir}"
        )
    return max(candidates, key=lambda c: c.name)


def read_csv_rows(path: Path) -> list[dict]:
    """Read a CSV file as dictionaries, accepting UTF-8 BOMs from Excel."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict]) -> None:
    """Write canonical CSV rows using the exact publisher header order."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def normalize_link_direction(
    link: Mapping[str, str], layer_by_device: Mapping[str, int]
) -> dict:
    """Orient one physical link from lower-numbered layer to higher-numbered layer."""

    out = dict(link)
    a_id = out.get("a_device_id", "")
    z_id = out.get("z_device_id", "")
    a_layer = layer_by_device.get(a_id, DEFAULT_LAYER)
    z_layer = layer_by_device.get(z_id, DEFAULT_LAYER)
    # a_* must have the LOWER layer (closer to network edge / top of dashboard).
    # When layers tie, sort by id so direction is deterministic across runs.
    swap = a_layer > z_layer or (a_layer == z_layer and a_id > z_id)
    if swap:
        out["a_device_id"], out["z_device_id"] = out["z_device_id"], out["a_device_id"]
        out["a_interface_id"], out["z_interface_id"] = (
            out["z_interface_id"],
            out["a_interface_id"],
        )
    return out


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse DNAC-to-canonical bridge CLI arguments."""

    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--raw-dir", type=Path, default=Path("data/raw"))
    p.add_argument("--working-dir", type=Path, default=Path("data/working"))
    p.add_argument(
        "--role-layer-config",
        type=Path,
        default=Path("config/dnac_role_layer.yaml"),
    )
    p.add_argument(
        "--export-dir",
        type=Path,
        help="Optional explicit dnac_export_<DATE> dir. Default: newest under --raw-dir.",
    )
    p.add_argument(
        "--as-of",
        default=None,
        help="YYYY-MM-DD used in the evidence_ref CFG-DNAC-<date>. Default: today (UTC).",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    """Bridge the selected raw DNAC export into canonical working CSVs."""

    args = parse_args(argv)
    cfg = load_role_layer_config(args.role_layer_config)
    export_dir = args.export_dir or find_latest_export_dir(args.raw_dir)

    devices_in = export_dir / "device_intake_from_dnac.csv"
    links_in = export_dir / "link_evidence_from_dnac.csv"
    for required in (devices_in, links_in):
        if not required.exists():
            sys.exit(f"Missing input from import_dnac_inventory.py: {required}")

    devices = read_csv_rows(devices_in)
    links = read_csv_rows(links_in)

    layer_by_device = {
        (row.get("device_id") or ""): device_layer(row, cfg) for row in devices
    }

    as_of = (args.as_of or dt.datetime.now(dt.timezone.utc).date().isoformat()).strip()
    evidence_ref = f"CFG-DNAC-{as_of}"
    normalized_links = []
    for link in links:
        normalized = normalize_link_direction(link, layer_by_device)
        normalized["evidence_ref"] = evidence_ref
        normalized_links.append(normalized)

    write_csv(args.working_dir / "devices.v1.csv", DEVICE_HEADERS, devices)
    write_csv(args.working_dir / "links.v1.csv", LINK_HEADERS, normalized_links)

    layer_counts: dict[int, int] = {}
    for layer in layer_by_device.values():
        layer_counts[layer] = layer_counts.get(layer, 0) + 1
    unknown_devices = [
        d.get("device_id") or d.get("hostname") or "?"
        for d in devices
        if layer_by_device.get(d.get("device_id") or "") == DEFAULT_LAYER
    ]
    print(f"Bridged {len(devices)} devices and {len(normalized_links)} links from {export_dir}")
    print(f"  Devices per layer: {dict(sorted(layer_counts.items()))}")
    print(f"  Evidence ref:      {evidence_ref}")
    print(f"  Output:")
    print(f"    {args.working_dir / 'devices.v1.csv'}")
    print(f"    {args.working_dir / 'links.v1.csv'}")
    if unknown_devices:
        sample = ", ".join(unknown_devices[:5])
        more = f" (+{len(unknown_devices) - 5} more)" if len(unknown_devices) > 5 else ""
        print(
            f"  WARNING: {len(unknown_devices)} devices landed at layer {DEFAULT_LAYER} "
            f"(unknown). Add a role/family entry or hostname override to fix: {sample}{more}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
