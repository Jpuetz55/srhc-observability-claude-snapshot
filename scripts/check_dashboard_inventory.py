#!/usr/bin/env python3
"""Validate the intentional final Grafana dashboard inventory."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DASHBOARDS = {
    Path("grafana/dashboards-dev/Platform - Wireless RF/vocera-iperf-qoe__vocera_iperf_qoe.json"): {
        "title": "Vocera Iperf QoE",
        "uid": "vocera_iperf_qoe",
    },
    Path("grafana/dashboards-prod/Platform - Wireless RF/vocera-iperf-qoe__vocera_iperf_qoe.json"): {
        "title": "Vocera Iperf QoE",
        "uid": "vocera_iperf_qoe",
    },
    Path("grafana/dashboards-dev/Platform - WLC Control Plane/wlc-control-plane__wlc_control_plane.json"): {
        "title": "WLC Control Plane",
        "uid": "wlc_control_plane",
    },
    Path("grafana/dashboards-prod/Platform - WLC Control Plane/wlc-control-plane__wlc_control_plane.json"): {
        "title": "WLC Control Plane",
        "uid": "wlc_control_plane",
    },
}

WLC_REQUIRED_PANEL_TITLES = {
    "WLC CPU One-Minute",
    "Control Process CPU",
    "Control Process Memory",
    "Control Process CPU by HA Member",
    "Control Process Current State",
    "Telemetry Scrape Samples",
}

WLC_REQUIRED_METRICS = {
    "wireless_wlc_cpu_one_minute_pct",
    "wireless_wlc_control_process_cpu_average_pct",
    "wireless_wlc_control_process_memory_used_pct",
    "wireless_wlc_control_process_load_average",
}


def die(message: str) -> None:
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def dashboard_paths() -> set[Path]:
    paths: set[Path] = set()
    for root in (ROOT / "grafana" / "dashboards-dev", ROOT / "grafana" / "dashboards-prod"):
        paths.update(path.relative_to(ROOT) for path in root.rglob("*.json"))
    return paths


def load_dashboard(path: Path) -> dict:
    try:
        return json.loads((ROOT / path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{path}: invalid JSON: {exc}")


def validate_wlc_dashboard(path: Path, dashboard: dict) -> None:
    text = json.dumps(dashboard)
    panels = {panel.get("title") for panel in dashboard.get("panels", []) if isinstance(panel, dict)}
    missing_panels = sorted(WLC_REQUIRED_PANEL_TITLES - panels)
    if missing_panels:
        die(f"{path}: missing WLC control-plane panels: {', '.join(missing_panels)}")
    missing_metrics = sorted(metric for metric in WLC_REQUIRED_METRICS if metric not in text)
    if missing_metrics:
        die(f"{path}: missing WLC control-plane metrics: {', '.join(missing_metrics)}")
    if "Cisco_IOS_XE_" in text:
        die(f"{path}: dashboard should use normalized wireless_wlc_* metrics, not raw Cisco IOS XE series")


def main() -> int:
    actual = dashboard_paths()
    expected = set(EXPECTED_DASHBOARDS)
    extra = sorted(actual - expected)
    missing = sorted(expected - actual)
    if extra or missing:
        if extra:
            print("ERROR: unexpected dashboard JSON files:", file=sys.stderr)
            for path in extra:
                print(f"  - {path}", file=sys.stderr)
        if missing:
            print("ERROR: missing expected dashboard JSON files:", file=sys.stderr)
            for path in missing:
                print(f"  - {path}", file=sys.stderr)
        return 1

    for path, expected_metadata in EXPECTED_DASHBOARDS.items():
        dashboard = load_dashboard(path)
        for key, expected_value in expected_metadata.items():
            actual_value = dashboard.get(key)
            if actual_value != expected_value:
                die(f"{path}: expected {key}={expected_value!r}, got {actual_value!r}")
        if expected_metadata["uid"] == "wlc_control_plane":
            validate_wlc_dashboard(path, dashboard)

    print("OK: dashboard inventory contains only Vocera Iperf QoE and WLC Control Plane")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
