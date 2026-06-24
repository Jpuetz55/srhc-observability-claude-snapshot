#!/usr/bin/env python3
"""Fixture-style tests for the path probe collector."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "path_probe"))

from path_probe import ProbeResult  # noqa: E402
from path_probe import ProbeTarget  # noqa: E402
from path_probe import parse_linux_ping_output  # noqa: E402
from path_probe import render_prometheus  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise path-probe failure message."""

    if not condition:
        raise AssertionError(message)


def test_linux_ping_parser() -> None:
    """Verify collector-originated ping output produces stable probe stats."""

    text = """
PING 192.0.2.10 (192.0.2.10) 56(84) bytes of data.
64 bytes from 192.0.2.10: icmp_seq=1 ttl=64 time=10.0 ms
64 bytes from 192.0.2.10: icmp_seq=2 ttl=64 time=20.0 ms
64 bytes from 192.0.2.10: icmp_seq=4 ttl=64 time=25.0 ms
64 bytes from 192.0.2.10: icmp_seq=5 ttl=64 time=30.0 ms

--- 192.0.2.10 ping statistics ---
5 packets transmitted, 4 received, 20% packet loss, time 4006ms
rtt min/avg/max/mdev = 10.000/21.250/30.000/7.395 ms
"""
    stats = parse_linux_ping_output(text, now=1000)
    require(stats.sent == 5, f"unexpected sent count: {stats.sent}")
    require(stats.received == 4, f"unexpected received count: {stats.received}")
    require(stats.loss_pct == 20.0, f"unexpected loss pct: {stats.loss_pct}")
    require(stats.rtt_min_ms == 10.0, f"unexpected min RTT: {stats.rtt_min_ms}")
    require(stats.rtt_avg_ms == 21.25, f"unexpected avg RTT: {stats.rtt_avg_ms}")
    require(stats.rtt_max_ms == 30.0, f"unexpected max RTT: {stats.rtt_max_ms}")
    require(stats.rtt_p95_ms == 30.0, f"unexpected p95 RTT: {stats.rtt_p95_ms}")
    require(round(stats.rtt_mdev_ms or 0, 3) == 7.395, f"unexpected RTT mdev: {stats.rtt_mdev_ms}")
    require(stats.rtt_pdv_p95_ms == 20.0, f"unexpected RTT PDV p95: {stats.rtt_pdv_p95_ms}")
    require(stats.rtt_pdv_range_ms == 20.0, f"unexpected RTT PDV range: {stats.rtt_pdv_range_ms}")
    require(round(stats.jitter_ms or 0, 3) == 7.395, f"unexpected legacy jitter: {stats.jitter_ms}")
    require(stats.last_success_timestamp_seconds == 1000, "successful probe should set last success")


def test_prometheus_renderer() -> None:
    """Verify stable metric names and labels for node_exporter textfiles."""

    target = ProbeTarget(
        segment="collector_to_ap",
        source="collectors01",
        target="SF1-BOILERROOM",
        target_type="ap",
        address="192.0.2.30",
        method="system_ping",
    )
    stats = parse_linux_ping_output(
        """
PING 192.0.2.30 (192.0.2.30) 56(84) bytes of data.
64 bytes from 192.0.2.30: icmp_seq=1 ttl=64 time=4.0 ms
64 bytes from 192.0.2.30: icmp_seq=2 ttl=64 time=6.0 ms
64 bytes from 192.0.2.30: icmp_seq=3 ttl=64 time=10.0 ms
--- 192.0.2.30 ping statistics ---
3 packets transmitted, 3 received, 0% packet loss, time 2000ms
""",
        now=3000,
    )
    prom = render_prometheus([ProbeResult(target=target, stats=stats)])
    require("wireless_path_probe_up" in prom, "missing up metric")
    require("wireless_path_probe_rtt_min_ms" in prom, "missing min RTT metric")
    require("wireless_path_probe_rtt_avg_ms" in prom, "missing avg RTT metric")
    require("wireless_path_probe_rtt_max_ms" in prom, "missing max RTT metric")
    require("wireless_path_probe_rtt_p95_ms" in prom, "missing p95 RTT metric")
    require("wireless_path_probe_rtt_pdv_range_ms" in prom, "missing RTT PDV range metric")
    require("wireless_path_probe_jitter_ms" in prom, "missing deprecated jitter metric")
    require("wireless_path_probe_packet_loss_pct" in prom, "missing packet loss metric")
    require("wireless_path_probe_last_success_timestamp_seconds" in prom, "missing last success metric")
    require("wireless_path_probe_last_run_timestamp_seconds" in prom, "missing last run metric")
    require('segment="collector_to_ap"' in prom, "missing segment label")
    require('source="collectors01"' in prom, "missing source label")
    require('target="SF1-BOILERROOM"' in prom, "missing target label")
    require('target_type="ap"' in prom, "missing target_type label")
    require('method="system_ping"' in prom, "missing method label")


def main() -> int:
    """Run path-probe tests without requiring pytest."""

    test_linux_ping_parser()
    test_prometheus_renderer()
    print("OK: path probe parser tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
