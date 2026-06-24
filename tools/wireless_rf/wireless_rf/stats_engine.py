"""Small descriptive-statistics helpers for reports and summaries."""

from __future__ import annotations

import math
import statistics
from typing import Iterable, List


def percentile(values: List[float], pct: float) -> float | None:
    """Compute an interpolated percentile for a small in-memory sample."""

    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    lower_weight = upper - rank
    upper_weight = rank - lower
    return ordered[lower] * lower_weight + ordered[upper] * upper_weight


def describe(values: Iterable[float]) -> dict[str, float | int | None]:
    """Return the summary shape expected by JSON reports and Streamlit."""

    vals = [float(v) for v in values]
    n = len(vals)
    if n == 0:
        return {
            "n": 0,
            "min": None,
            "max": None,
            "mean": None,
            "median": None,
            "sample_stddev": None,
            "sample_variance": None,
            "standard_error": None,
            "ci95_low": None,
            "ci95_high": None,
            "p25": None,
            "p75": None,
            "p90": None,
            "p95": None,
        }

    mean = statistics.mean(vals)
    sample_stddev = statistics.stdev(vals) if n > 1 else 0.0
    sample_variance = statistics.variance(vals) if n > 1 else 0.0
    standard_error = sample_stddev / math.sqrt(n) if n > 0 else None
    ci_delta = 1.96 * standard_error if standard_error is not None else None

    return {
        "n": n,
        "min": min(vals),
        "max": max(vals),
        "mean": mean,
        "median": statistics.median(vals),
        "sample_stddev": sample_stddev,
        "sample_variance": sample_variance,
        "standard_error": standard_error,
        "ci95_low": mean - ci_delta if ci_delta is not None else None,
        "ci95_high": mean + ci_delta if ci_delta is not None else None,
        "p25": percentile(vals, 0.25),
        "p75": percentile(vals, 0.75),
        "p90": percentile(vals, 0.90),
        "p95": percentile(vals, 0.95),
    }


def summarize_snapshots_by_site(snapshots) -> dict[str, dict[str, object]]:
    """Group AP neighbor-count summaries by site tag."""

    grouped: dict[str, list[int]] = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot.site_tag, []).append(snapshot.neighbor_count)
    return {site_tag: describe(values) for site_tag, values in sorted(grouped.items())}
