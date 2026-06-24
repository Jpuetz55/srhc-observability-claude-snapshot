#!/usr/bin/env python3
"""Fixture-style tests for shared Prometheus textfile helpers."""

from __future__ import annotations

import math
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.common.prometheus import bool_value  # noqa: E402
from tools.common.prometheus import emit_help  # noqa: E402
from tools.common.prometheus import emit_metric  # noqa: E402
from tools.common.prometheus import emit_type  # noqa: E402
from tools.common.prometheus import escape_label  # noqa: E402
from tools.common.prometheus import format_labels  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise common-helper failure message."""

    if not condition:
        raise AssertionError(message)


def test_label_escaping() -> None:
    """Verify Prometheus label escaping and configurable empty defaults."""

    require(escape_label('a"b\\c\nd') == 'a\\"b\\\\c\\nd', "bad label escaping")
    require(escape_label(None) == "", "None should default to empty label text")
    require(
        escape_label("", empty_value="unknown") == "unknown",
        "empty label override should be honored",
    )
    require(
        escape_label(None, none_value="unknown") == "unknown",
        "None label override should be honored",
    )


def test_label_formatting() -> None:
    """Verify stable insertion and sorted label rendering modes."""

    labels = {"b": "two", "a": "one"}
    require(format_labels(labels) == 'b="two",a="one"', "insertion order should be preserved by default")
    require(format_labels(labels, sort=True) == 'a="one",b="two"', "sorted label mode should sort keys")
    require(format_labels({"empty": ""}, empty_value="unknown") == 'empty="unknown"', "bad empty label default")


def test_metric_rendering() -> None:
    """Verify samples are rendered or omitted consistently."""

    require(emit_metric("example_up", {"job": "demo"}, True) == 'example_up{job="demo"} 1\n', "bad bool sample")
    require(bool_value(False) == 0, "bad false bool conversion")
    require(emit_metric("example_missing", {"job": "demo"}, None) == "", "None sample should be omitted")
    require(emit_metric("example_nan", {"job": "demo"}, math.nan) == "", "NaN sample should be omitted")
    require(emit_metric("example_total", "", 3) == "example_total 3\n", "empty labels should render no braces")
    require(
        emit_metric("example_info", {"z": "", "a": None}, 1, sort_labels=True, none_label_value="unknown", empty_label_value="unknown")
        == 'example_info{a="unknown",z="unknown"} 1\n',
        "bad sorted unknown-default labels",
    )


def test_help_and_type() -> None:
    """Verify HELP and TYPE line helpers."""

    require(emit_help("example_metric", "Example help.") == "# HELP example_metric Example help.\n", "bad HELP line")
    require(emit_type("example_metric", "gauge") == "# TYPE example_metric gauge\n", "bad TYPE line")


def main() -> int:
    """Run common Prometheus helper tests without requiring pytest."""

    test_label_escaping()
    test_label_formatting()
    test_metric_rendering()
    test_help_and_type()
    print("OK: common Prometheus helper tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
