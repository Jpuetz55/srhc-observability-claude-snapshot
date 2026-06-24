"""Central-limit summary statistics for completed RF-validation match rows.

This module is intentionally dependency-free (standard library only) so it can be
unit tested in isolation and imported by the FastAPI backend without pulling in
the heavier RF-validation parsing stack.

A "sample" is a completed match row from the run workflow. The statistic that
matters for validation is the calibrated delta field: the difference between the
badge-side measurement and the Ekahau survey measurement after the configured
vendor/badge offset is applied. The functions here compute descriptive
statistics, standard error of the mean, a 95% confidence interval for the mean,
and outlier flags for that delta series.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

# Default z-score magnitude above which a sample is flagged as an outlier.
DEFAULT_Z_THRESHOLD = 2.0

# 1.96 standard errors gives the classic ~95% confidence interval for the mean
# under the central limit theorem.
Z_95 = 1.959963984540054

# Metrics we summarize, mapped to the sample field they read from.
METRIC_FIELDS: dict[str, str] = {
    "cal_delta": "calibrated_delta_db",
}


def _coerce_float(value: Any) -> float | None:
    """Return ``value`` as a finite float, or ``None`` if it is not numeric."""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if text == "":
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(result):
        return None
    return result


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    return round(value, digits)


def percentile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile (``q`` in ``[0, 1]``) over sorted data."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = q * (len(sorted_values) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[int(rank)]
    frac = rank - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * frac


def summarize_metric(values: Iterable[float]) -> dict[str, Any]:
    """Descriptive + central-limit statistics for one metric series."""
    data = sorted(float(v) for v in values)
    count = len(data)
    if count == 0:
        return {
            "count": 0,
            "mean": None,
            "stddev": None,
            "variance": None,
            "min": None,
            "max": None,
            "range": None,
            "p05": None,
            "p25": None,
            "p50": None,
            "p75": None,
            "p95": None,
            "iqr": None,
            "sem": None,
            "ci95_low": None,
            "ci95_high": None,
        }

    total = math.fsum(data)
    mean = total / count
    if count >= 2:
        variance = math.fsum((v - mean) ** 2 for v in data) / (count - 1)
        stddev = math.sqrt(variance)
        sem = stddev / math.sqrt(count)
        ci_half = Z_95 * sem
        ci_low: float | None = mean - ci_half
        ci_high: float | None = mean + ci_half
    else:
        variance = None
        stddev = None
        sem = None
        ci_low = None
        ci_high = None

    p25 = percentile(data, 0.25)
    p75 = percentile(data, 0.75)
    iqr = (p75 - p25) if (p25 is not None and p75 is not None) else None

    return {
        "count": count,
        "mean": _round(mean),
        "stddev": _round(stddev),
        "variance": _round(variance),
        "min": _round(data[0]),
        "max": _round(data[-1]),
        "range": _round(data[-1] - data[0]),
        "p05": _round(percentile(data, 0.05)),
        "p25": _round(p25),
        "p50": _round(percentile(data, 0.50)),
        "p75": _round(p75),
        "p95": _round(percentile(data, 0.95)),
        "iqr": _round(iqr),
        "sem": _round(sem),
        "ci95_low": _round(ci_low),
        "ci95_high": _round(ci_high),
    }


def _z_score(value: float, mean: float | None, stddev: float | None) -> float | None:
    if mean is None or stddev is None or stddev == 0:
        return None
    return (value - mean) / stddev


def summarize_samples(
    samples: Iterable[dict[str, Any]],
    *,
    z_threshold: float = DEFAULT_Z_THRESHOLD,
) -> dict[str, Any]:
    """Summarize a list of completed match rows.

    Returns a payload with calibrated-delta statistics, the z-score threshold
    used, and the input rows annotated with delta z-scores and outlier flags.
    Outlier flagging requires at least two values and a non-zero standard
    deviation.
    """
    rows = list(samples)
    metric_values: dict[str, list[float]] = {key: [] for key in METRIC_FIELDS}
    parsed: list[dict[str, float | None]] = []
    for row in rows:
        parsed_row: dict[str, float | None] = {}
        for metric, source_field in METRIC_FIELDS.items():
            value = _coerce_float(row.get(source_field))
            parsed_row[metric] = value
            if value is not None:
                metric_values[metric].append(value)
        parsed.append(parsed_row)

    stats = {metric: summarize_metric(values) for metric, values in metric_values.items()}

    annotated: list[dict[str, Any]] = []
    outlier_counts = {metric: 0 for metric in METRIC_FIELDS}
    for row, parsed_row in zip(rows, parsed):
        annotation = dict(row)
        annotation["is_outlier"] = False
        for metric in METRIC_FIELDS:
            value = parsed_row[metric]
            metric_stats = stats[metric]
            z = _z_score(value, metric_stats["mean"], metric_stats["stddev"]) if value is not None else None
            is_outlier = z is not None and abs(z) > z_threshold
            annotation[f"{metric}_z_score"] = _round(z, 4)
            annotation[f"{metric}_is_outlier"] = is_outlier
            if is_outlier:
                outlier_counts[metric] += 1
                annotation["is_outlier"] = True
        annotated.append(annotation)

    for metric in METRIC_FIELDS:
        stats[metric]["outlier_count"] = outlier_counts[metric]

    return {
        "z_threshold": z_threshold,
        "sample_count": len(rows),
        "statistics": stats,
        "samples": annotated,
    }
