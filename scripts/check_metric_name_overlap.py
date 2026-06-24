#!/usr/bin/env python3
"""Ensure raw metric names and recording rule names do not collide."""

from __future__ import annotations

import re
import sys
from pathlib import Path


TOP_SECTION_RE = re.compile(r"^([A-Za-z0-9_]+):\s*(.*)$")
ITEM_NAME_RE = re.compile(r"^\s*-\s*name:\s*(.+?)\s*$")


def load_metric_sets(path: Path) -> tuple[set[str], set[str]]:
    """Parse the raw_series and recording_rules sections from the contract."""

    raw_series: set[str] = set()
    recording_rules: set[str] = set()
    section: str | None = None

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        top = TOP_SECTION_RE.match(line)
        if top and not line.startswith(" "):
            section = top.group(1)
            continue

        name_match = ITEM_NAME_RE.match(line)
        if not name_match or section not in {"raw_series", "recording_rules"}:
            continue

        name = name_match.group(1).strip().strip("\"'")
        if section == "raw_series":
            raw_series.add(name)
        else:
            recording_rules.add(name)

    return raw_series, recording_rules


def main() -> int:
    """Fail when the contract declares a name in both metric namespaces."""

    repo_root = Path(__file__).resolve().parents[1]
    contract_path = repo_root / "contracts" / "metric_contract.yaml"

    if not contract_path.exists():
        print(f"ERROR: missing contract file: {contract_path}", file=sys.stderr)
        return 1

    raw_series, recording_rules = load_metric_sets(contract_path)
    overlap = sorted(raw_series & recording_rules)
    if overlap:
        print("ERROR: raw and recording metric names overlap", file=sys.stderr)
        for name in overlap:
            print(f"  - {name}", file=sys.stderr)
        return 1

    print(
        "OK: no overlap between raw_series and recording_rules "
        f"({len(raw_series)} raw metrics, {len(recording_rules)} recording rules)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
