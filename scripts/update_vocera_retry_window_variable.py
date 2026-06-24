#!/usr/bin/env python3
"""Update the Vocera retry-window dashboard variable.

The retry outlier panel uses a custom Grafana variable whose values are PromQL
range selectors with an @ timestamp. Regenerate this file-owned variable so the
dashboard keeps a current-day default plus fixed historical windows.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_PATHS = (
    ROOT / "grafana" / "dashboards-dev" / "Platform - Wireless RF" / "vocera-badge-80211r-impact__vocera_badge_80211r_impact.json",
    ROOT / "grafana" / "dashboards-prod" / "Platform - Wireless RF" / "vocera-badge-80211r-impact__vocera_badge_80211r_impact.json",
)
DEFAULT_TZ = "America/Chicago"
DEFAULT_WINDOW_HOURS = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14, help="Number of local days to include in historical windows.")
    parser.add_argument(
        "--window-hours",
        type=int,
        default=DEFAULT_WINDOW_HOURS,
        help="Historical window size in hours. Must divide 24 evenly.",
    )
    parser.add_argument("--timezone", default=DEFAULT_TZ, help="IANA timezone used for labels and epoch calculations.")
    parser.add_argument(
        "--now",
        help="Optional ISO datetime for deterministic regeneration, interpreted in --timezone when naive.",
    )
    parser.add_argument("--dashboard", action="append", help="Dashboard JSON path to update. Defaults to DEV and PROD.")
    return parser.parse_args()


def local_now(value: str | None, tz: ZoneInfo) -> datetime:
    if not value:
        return datetime.now(tz)
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=tz)
    return parsed.astimezone(tz)


def epoch_seconds(dt: datetime) -> int:
    return int(dt.timestamp())


def option(text: str, value: str, selected: bool = False) -> dict[str, object]:
    return {"selected": selected, "text": text, "value": value}


def build_options(now: datetime, days: int, window_hours: int) -> list[dict[str, object]]:
    today = now.date()
    today_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    today_end = today_start + timedelta(days=1) - timedelta(seconds=1)
    options = [
        option(
            f"Current day {today:%Y-%m-%d} 00:00-23:59",
            f"[24h] @ {epoch_seconds(today_end)}",
            selected=True,
        )
    ]

    for day_offset in range(days):
        day = today - timedelta(days=day_offset)
        for hour in range(0, 24, window_hours):
            start = datetime.combine(day, time(hour, 0), tzinfo=now.tzinfo)
            end = start + timedelta(hours=window_hours) - timedelta(seconds=1)
            options.append(
                option(
                    f"{day:%Y-%m-%d} {hour:02d}:00-{hour + window_hours - 1:02d}:59",
                    f"[{window_hours}h] @ {epoch_seconds(end)}",
                )
            )
    return options


def variable_from_options(options: list[dict[str, object]]) -> dict[str, object]:
    current = options[0]
    query = ",".join(f"{item['text']} : {item['value']}" for item in options)
    return {
        "current": {"selected": True, "text": current["text"], "value": current["value"]},
        "hide": 0,
        "includeAll": False,
        "multi": False,
        "name": "retry_window_selector",
        "options": options,
        "query": query,
        "type": "custom",
    }


def upsert_variable(dashboard: dict[str, object], variable: dict[str, object]) -> None:
    templating = dashboard.setdefault("templating", {})
    variables = templating.setdefault("list", [])
    if not isinstance(variables, list):
        raise TypeError("dashboard templating.list is not a list")

    for index, existing in enumerate(variables):
        if isinstance(existing, dict) and existing.get("name") == variable["name"]:
            variables[index] = variable
            return
    variables.append(variable)


def main() -> int:
    args = parse_args()
    if args.days < 1:
        raise SystemExit("--days must be >= 1")
    if args.window_hours < 1 or 24 % args.window_hours != 0:
        raise SystemExit("--window-hours must divide 24 evenly")
    tz = ZoneInfo(args.timezone)
    variable = variable_from_options(build_options(local_now(args.now, tz), args.days, args.window_hours))
    paths = tuple(Path(path) for path in args.dashboard) if args.dashboard else DASHBOARD_PATHS

    for path in paths:
        dashboard = json.loads(path.read_text(encoding="utf-8"))
        upsert_variable(dashboard, variable)
        path.write_text(json.dumps(dashboard, indent=2) + "\n", encoding="utf-8")
        print(f"updated {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
