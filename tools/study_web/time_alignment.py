"""Pure helpers for the RF validation Time Alignment Lab.

Candidate matching is timestamp-only: an Ekahau survey point produces candidate
rows when its nearest same-local-date badge reading falls within the match
window. These helpers turn the per-survey-point nearest deltas into a
non-destructive tolerance sweep so an operator can see, before re-running, how
many candidates / near-edge / ambiguous matches each window would yield.

This module is intentionally free of any database or web framework imports so it
can be unit-tested directly.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

# Whole-second windows the UI can actually apply (the run match window is an
# integer >= 1). The run's current window is merged in by the caller.
DEFAULT_SWEEP_WINDOWS: tuple[int, ...] = (1, 2, 3, 5, 10)

# A candidate is "near edge" when its delta is in this fraction of the window or
# beyond -- a small clock drift could drop it. Matches the review-queue chip.
NEAR_EDGE_FRACTION = 0.8


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = fraction * (len(ordered) - 1)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def normalize_windows(windows: Iterable[float], *, current: float | None = None) -> list[int]:
    """Return sorted, de-duplicated whole-second windows (>= 1), incl. current."""
    seen: set[int] = set()
    for raw in list(windows) + ([current] if current is not None else []):
        try:
            value = int(round(float(raw)))
        except (TypeError, ValueError):
            continue
        if value >= 1:
            seen.add(value)
    return sorted(seen)


def overlap_window(
    badge_min: float | None,
    badge_max: float | None,
    survey_min: float | None,
    survey_max: float | None,
    *,
    margin_seconds: float = 0.0,
) -> tuple[float, float] | None:
    """Return the badge/survey time-range overlap as an epoch [start, end].

    Expanded by ``margin_seconds`` on each side so points right at the boundary
    stay visible. Returns None when either range is missing or the ranges are
    disjoint -- in which case there is no relevant timeline window to show.
    """
    if badge_min is None or badge_max is None or survey_min is None or survey_max is None:
        return None
    # Apply the margin before testing for disjointness: ranges that don't
    # literally overlap can still have matchable points within the margin
    # (e.g. a survey at 10:00:00 and a badge reading at 10:00:03 under a >=3s
    # window). Only reject when even the margin-expanded ranges don't meet.
    start = max(badge_min, survey_min) - margin_seconds
    end = min(badge_max, survey_max) + margin_seconds
    if start > end:
        return None
    return (start, end)


def summarize_tolerance_sweep(
    points: list[Mapping[str, Any]],
    windows: Iterable[float],
) -> dict[str, Any]:
    """Summarize how many survey points match at each candidate window.

    ``points`` is one entry per survey point that has a same-date badge reading:
    ``{"delta_seconds": <signed float>, "event_id": <nearest badge event id>}``.
    ``delta_seconds`` is ``badge_time - survey_time`` (signed), so a positive
    median indicates the badge clock reads later than Ekahau.

    For each window the result reports:
      - matched_points: survey points whose nearest |delta| <= window
      - near_edge_points: matched points with |delta| > 80% of the window
      - ambiguous_points: matched points whose nearest badge reading is also the
        nearest reading for another in-window point (one reading -> many points)
    """
    parsed: list[tuple[float, str | None]] = []
    for point in points:
        delta = point.get("delta_seconds")
        if delta is None:
            continue
        try:
            delta_value = float(delta)
        except (TypeError, ValueError):
            continue
        event_id = point.get("event_id")
        parsed.append((delta_value, str(event_id) if event_id not in (None, "") else None))

    abs_deltas = [abs(delta) for delta, _ in parsed]
    signed_deltas = [delta for delta, _ in parsed]

    window_rows: list[dict[str, Any]] = []
    for window in normalize_windows(windows):
        in_window = [(delta, event_id) for delta, event_id in parsed if abs(delta) <= window]
        edge_threshold = NEAR_EDGE_FRACTION * window
        near_edge = sum(1 for delta, _ in in_window if abs(delta) > edge_threshold)

        event_counts: dict[str, int] = {}
        for _, event_id in in_window:
            if event_id:
                event_counts[event_id] = event_counts.get(event_id, 0) + 1
        ambiguous = sum(1 for _, event_id in in_window if event_id and event_counts.get(event_id, 0) > 1)

        window_rows.append(
            {
                "window_seconds": window,
                "matched_points": len(in_window),
                "near_edge_points": near_edge,
                "ambiguous_points": ambiguous,
            }
        )

    return {
        "survey_point_count_with_same_date_badge": len(parsed),
        "windows": window_rows,
        "abs_delta_min_seconds": min(abs_deltas) if abs_deltas else None,
        "abs_delta_median_seconds": _median(abs_deltas),
        "abs_delta_p90_seconds": _percentile(abs_deltas, 0.9),
        "signed_delta_median_seconds": _median(signed_deltas),
        "signed_deltas": signed_deltas,
    }
