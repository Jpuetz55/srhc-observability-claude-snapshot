"""Shared helpers for Prometheus textfile exposition rendering."""

from __future__ import annotations

import math
from collections.abc import Mapping


def escape_label(value: object, *, none_value: str = "", empty_value: str | None = None) -> str:
    """Escape a value for Prometheus label syntax."""

    text = none_value if value is None else str(value)
    if text == "" and empty_value is not None:
        text = empty_value
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def format_labels(
    labels: Mapping[str, object],
    *,
    sort: bool = False,
    none_value: str = "",
    empty_value: str | None = None,
) -> str:
    """Render label pairs into Prometheus syntax."""

    keys = sorted(labels) if sort else labels.keys()
    return ",".join(
        f'{key}="{escape_label(labels[key], none_value=none_value, empty_value=empty_value)}"'
        for key in keys
    )


def bool_value(value: bool | None) -> int:
    """Render optional booleans as Prometheus-friendly 0/1 gauges."""

    return 1 if value else 0


def _sample_value(value: object) -> object | None:
    """Normalize Python values for Prometheus samples."""

    if value is None:
        return None
    if isinstance(value, bool):
        return bool_value(value)
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


def emit_metric(
    name: str,
    labels: Mapping[str, object] | str,
    value: object,
    *,
    sort_labels: bool = False,
    none_label_value: str = "",
    empty_label_value: str | None = None,
) -> str:
    """Render one Prometheus sample, omitting unavailable values."""

    sample = _sample_value(value)
    if sample is None:
        return ""

    label_text = (
        labels
        if isinstance(labels, str)
        else format_labels(
            labels,
            sort=sort_labels,
            none_value=none_label_value,
            empty_value=empty_label_value,
        )
    )
    if not label_text:
        return f"{name} {sample}\n"
    return f"{name}{{{label_text}}} {sample}\n"


def emit_help(name: str, text: str) -> str:
    """Render a Prometheus HELP line."""

    return f"# HELP {name} {text}\n"


def emit_type(name: str, metric_type: str) -> str:
    """Render a Prometheus TYPE line."""

    return f"# TYPE {name} {metric_type}\n"
