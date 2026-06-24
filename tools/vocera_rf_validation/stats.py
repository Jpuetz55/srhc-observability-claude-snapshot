"""Small in-process statistics helpers for RF validation tests and exports."""

from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from .models import CorrelatedMatch


def annotate_outliers(
    matches: Iterable[CorrelatedMatch],
    *,
    minimum_samples: int = 30,
    z_score_threshold: float = 2.0,
) -> list[dict[str, object]]:
    """Add per-floor/band z-score outlier fields to complete matches."""
    grouped: dict[tuple[str | None, str | None], list[CorrelatedMatch]] = defaultdict(list)
    for match in matches:
        if match.manual_entry_status == "complete" and match.calibrated_delta_db is not None:
            grouped[(match.floor, match.band)].append(match)

    output: list[dict[str, object]] = []
    for group_matches in grouped.values():
        values = [match.calibrated_delta_db for match in group_matches if match.calibrated_delta_db is not None]
        mean_delta = statistics.mean(values)
        stddev_delta = statistics.stdev(values) if len(values) > 1 else 0.0
        for match in group_matches:
            if len(values) < minimum_samples:
                status = "insufficient_samples"
                z_score = None
            elif stddev_delta == 0:
                status = "no_variance"
                z_score = None
            else:
                z_score = ((match.calibrated_delta_db or 0.0) - mean_delta) / stddev_delta
                status = "outlier" if abs(z_score) > z_score_threshold else "normal"
            payload = match.to_dict()
            payload.update(
                {
                    "sample_count": len(values),
                    "mean_delta": mean_delta,
                    "stddev_delta": stddev_delta,
                    "z_score": z_score,
                    "outlier_status": status,
                }
            )
            output.append(payload)
    return output
