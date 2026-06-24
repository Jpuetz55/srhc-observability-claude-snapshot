#!/usr/bin/env python3
"""Fixture-style tests for shared file IO helpers."""

from __future__ import annotations

import csv
import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.common.files import read_json  # noqa: E402
from tools.common.files import read_text  # noqa: E402
from tools.common.files import write_csv  # noqa: E402
from tools.common.files import write_json  # noqa: E402
from tools.common.files import write_text  # noqa: E402
from tools.common.files import write_text_atomic  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise common-helper failure message."""

    if not condition:
        raise AssertionError(message)


def test_text_helpers(root: Path) -> None:
    """Verify parent creation and atomic text replacement."""

    path = root / "nested" / "sample.txt"
    write_text(path, "first")
    require(read_text(path) == "first", "write_text should create parents and write UTF-8")

    write_text_atomic(path, "second")
    require(read_text(path) == "second", "write_text_atomic should replace existing text")
    require(not list(path.parent.glob(".sample.txt.*.tmp")), "atomic helper should clean temp files")


def test_json_helpers(root: Path) -> None:
    """Verify deterministic JSON writing and configurable trailing newline."""

    path = root / "json" / "payload.json"
    write_json(path, {"b": 2, "a": 1}, trailing_newline=True)
    require(path.read_text(encoding="utf-8").endswith("\n"), "JSON trailing newline should be configurable")
    require(read_json(path) == {"a": 1, "b": 2}, "read_json should round-trip payloads")
    require(json.loads(path.read_text(encoding="utf-8")) == {"a": 1, "b": 2}, "write_json should emit valid JSON")


def test_csv_helper(root: Path) -> None:
    """Verify CSV header order and parent directory creation."""

    path = root / "csv" / "rows.csv"
    write_csv(path, ["a", "b"], [{"b": 2, "a": 1}], extrasaction="ignore")
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    require(rows == [{"a": "1", "b": "2"}], "write_csv should preserve explicit header order")


def main() -> int:
    """Run common file helper tests without requiring pytest."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        test_text_helpers(root)
        test_json_helpers(root)
        test_csv_helper(root)
    print("OK: common file helper tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
