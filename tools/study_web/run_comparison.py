"""Pure helpers for the RF validation Run Comparison view.

Run comparison is read-only: it summarizes every run in a study side by side so
an operator can see how match-window choices traded off candidate volume against
ambiguity / Cal Delta outliers. All database access lives in the web layer; this
module only derives per-row completion and a plain-English interpretation, so it
can be unit-tested directly.
"""

from __future__ import annotations

from typing import Any, Mapping


def completion_percent(completed: float | None, pending: float | None) -> float | None:
    """Percent of this run's candidates that are completed (completed / completed+pending)."""
    done = completed or 0
    total = done + (pending or 0)
    if total <= 0:
        return None
    return round(100.0 * done / total, 1)


def _effective_window(row: Mapping[str, Any]) -> float | None:
    """The window a run actually ran with, falling back to its configured window."""
    used = row.get("match_window_seconds_used")
    return used if used is not None else row.get("default_match_window_seconds")


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _direction(low: float | None, high: float | None) -> str:
    if low is None or high is None:
        return "changed"
    if high > low:
        return "increased"
    if high < low:
        return "decreased"
    return "held steady"


def _interpret(rows: list[Mapping[str, Any]]) -> str:
    if not rows:
        return "No runs in this study yet."
    if len(rows) == 1:
        return (
            "Only one run in this study so far. Add runs — for example the same data re-run at "
            "different match windows — to compare tolerance trade-offs."
        )

    usable = [row for row in rows if _effective_window(row) is not None]
    windows = {_effective_window(row) for row in usable}
    if len(usable) < 2 or len(windows) < 2:
        return (
            "These runs use the same match window, so differences reflect the data or collection "
            "rather than tolerance. Re-run at different windows in the Time Alignment Lab to compare trade-offs."
        )

    low = min(usable, key=lambda row: _effective_window(row) or 0)
    high = max(usable, key=lambda row: _effective_window(row) or 0)
    candidate_direction = _direction(low.get("candidate_match_count"), high.get("candidate_match_count"))
    parts = [
        f"From the ±{_fmt(_effective_window(low))}s run to the ±{_fmt(_effective_window(high))}s run, "
        f"candidate matches {candidate_direction} "
        f"({_fmt(low.get('candidate_match_count'))} → {_fmt(high.get('candidate_match_count'))})"
    ]
    if low.get("outlier_count") is not None and high.get("outlier_count") is not None:
        outlier_direction = _direction(low.get("outlier_count"), high.get("outlier_count"))
        parts.append(
            f"and Cal Delta outliers {outlier_direction} "
            f"({_fmt(low.get('outlier_count'))} → {_fmt(high.get('outlier_count'))})"
        )
    text = ", ".join(parts) + "."

    wider_adds_candidates = (high.get("candidate_match_count") or 0) > (low.get("candidate_match_count") or 0)
    wider_adds_outliers = (high.get("outlier_count") or 0) > (low.get("outlier_count") or 0)
    if wider_adds_candidates or wider_adds_outliers:
        text += (
            " Wider windows tend to capture more matches but can add ambiguity and outliers — prefer the "
            "smallest window that still yields enough completed matches."
        )
    return text


def build_run_comparison(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Enrich per-run rows with completion percent and a plain-English interpretation.

    Input rows carry already-parsed numeric fields (ints/floats or None). The
    returned rows preserve input order (the caller orders by run creation time).
    """
    enriched: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["completion_percent"] = completion_percent(
            row.get("completed_match_count"), row.get("pending_candidate_match_count")
        )
        enriched.append(item)
    return {"rows": enriched, "interpretation": _interpret(enriched)}
