#!/usr/bin/env python3
"""Fixture-style tests for the Vocera iperf QoE textfile exporter."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_iperf_qoe"))

import vocera_iperf_qoe as qoe  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise an assertion with a clear fixture-specific message."""

    if not condition:
        raise AssertionError(message)


def write_json(path: Path, payload: object, *, bom: bool = False) -> None:
    """Write a JSON fixture, optionally with a UTF-8 BOM."""

    path.parent.mkdir(parents=True, exist_ok=True)
    encoding = "utf-8-sig" if bom else "utf-8"
    path.write_text(json.dumps(payload, indent=2), encoding=encoding)


def wrapped_result(
    *,
    device: str = "S-NW-PROBE2",
    timestamp: int = 1779207456,
    jitter_ms: float = 0.333,
    target: str = "10.16.88.233",
    target_port: int = 5203,
    raw_latency_ms: float | None = None,
) -> dict[str, object]:
    """Build a laptop-wrapper style iperf result fixture."""

    payload = {
        "metadata": {
            "schema": "vocera_iperf_qoe_v1",
            "device": device,
            "site": "srhc",
            "ssid": "srhcvoice2",
            "role": "LaptopB-ClientToClient-Tester",
            "mode": "ClientToPeer",
            "direction": "client_to_client",
            "target": target,
            "target_port": target_port,
            "duration_seconds": 60,
            "bitrate": "64K",
            "payload_bytes": 160,
            "tos": "0xb8",
        },
        "iperf3": {
            "start": {
                "connected": [
                    {
                        "local_host": "10.16.88.1",
                        "local_port": 57334,
                        "remote_host": target,
                        "remote_port": target_port,
                    }
                ],
                "timestamp": {"timesecs": timestamp},
                "connecting_to": {"host": target, "port": target_port},
                "test_start": {
                    "protocol": "UDP",
                    "duration": 60,
                    "blksize": 160,
                    "reverse": 0,
                },
            },
            "intervals": [],
            "end": {
                "sum": {
                    "seconds": 60.007651,
                    "bytes": 479360,
                    "bits_per_second": 63906.5,
                    "jitter_ms": jitter_ms,
                    "lost_packets": 0,
                    "packets": 2996,
                    "lost_percent": 0,
                }
            },
        },
    }
    if raw_latency_ms is not None:
        payload["metadata"]["raw_latency_ms"] = raw_latency_ms
    return payload


def raw_server_pair_result(*, reverse: int = 0) -> dict[str, object]:
    """Build a raw iperf3 JSON fixture without wrapper metadata."""

    return {
        "start": {
            "connected": [
                {
                    "local_host": "10.16.86.28",
                    "local_port": 65235,
                    "remote_host": "10.205.0.20",
                    "remote_port": 5201,
                }
            ],
            "timestamp": {"timesecs": 1779111759},
            "connecting_to": {"host": "10.205.0.20", "port": 5201},
            "test_start": {
                "protocol": "UDP",
                "duration": 60,
                "blksize": 160,
                "reverse": reverse,
            },
        },
        "intervals": [],
        "end": {
            "sum": {
                "seconds": 60.0044,
                "bytes": 479360,
                "bits_per_second": 63910,
                "jitter_ms": 0.144775,
                "lost_packets": 0,
                "packets": 2996,
                "lost_percent": 0,
            }
        },
    }


def test_scan_and_render_latest_results() -> None:
    """Verify scanning keeps latest series and renders core Prometheus metrics."""

    with tempfile.TemporaryDirectory(prefix="vocera-iperf-qoe-") as tmp:
        root = Path(tmp)
        write_json(root / "S-NW-PROBE2" / "raw" / "client_to_client-20260519-104131.json", wrapped_result(timestamp=10, jitter_ms=0.8))
        write_json(
            root / "S-NW-PROBE2" / "raw" / "client_to_client-20260519-111736.json",
            wrapped_result(timestamp=20, jitter_ms=0.3, raw_latency_ms=12.5),
        )
        write_json(
            root / "S-NW-PROBE2" / "raw" / "client_to_client-20260519-110104.iperf.json",
            {
                "start": {"connected": []},
                "intervals": [],
                "end": {},
                "error": "error - unable to connect to server: Connection timed out",
            },
        )
        write_json(root / "S-NW-LT10" / "raw" / "client_to_server-20260518-084238.json", raw_server_pair_result(), bom=True)

        config = {
            "collector": "collectors01",
            "devices": {
                "S-NW-LT10": {
                    "site": "srhc",
                    "ssid": "srhcvoice-test",
                    "role": "LaptopToServer-Tester",
                    "mode": "ServerPair",
                    "tos": "0xb8",
                }
            },
            "targets": {
                "10.16.88.233:5203": {"name": "S-NW-PROBE1"},
                "10.205.0.20:5201": {"name": "server-vm"},
            },
        }
        scan = qoe.scan_incoming(root, config, now=1000)
        require(scan.files_seen == 4, f"unexpected file count: {scan.files_seen}")
        require(scan.ignored_temp_files == 1, f"unexpected ignored temp count: {scan.ignored_temp_files}")
        require(scan.parsed_files == 3, f"unexpected parsed count: {scan.parsed_files}")
        require(len(scan.latest_results) == 2, f"expected two latest series, got {len(scan.latest_results)}")

        probe2 = [result for result in scan.latest_results if result.device == "S-NW-PROBE2"][0]
        require(probe2.timestamp_seconds == 20, f"did not keep latest PROBE2 result: {probe2.timestamp_seconds}")
        require(probe2.jitter_ms == 0.3, f"bad PROBE2 jitter: {probe2.jitter_ms}")
        require(probe2.raw_latency_seconds == 0.0125, f"bad PROBE2 raw latency: {probe2.raw_latency_seconds}")
        require(probe2.target_name == "S-NW-PROBE1", f"bad target name: {probe2.target_name}")
        lt10 = [result for result in scan.latest_results if result.device == "S-NW-LT10"][0]
        require(lt10.direction == "client_to_server", f"bad filename-derived direction: {lt10.direction}")

        prom = qoe.render_prometheus(scan)
        require("vocera_iperf_up" in prom, "missing up metric")
        require('device="S-NW-PROBE2"' in prom, "missing PROBE2 label")
        require('target_name="S-NW-PROBE1"' in prom, "missing target-name label")
        require('ssid="srhcvoice-test"' in prom, "missing config-derived SSID")
        require("vocera_iperf_jitter_seconds" in prom, "missing jitter metric")
        require("vocera_iperf_raw_latency_seconds" in prom, "missing raw latency metric")
        require("vocera_iperf_raw_latency_seconds" in prom and "0.0125" in prom, "bad raw latency value")
        require("vocera_iperf_throughput_bytes_per_second" in prom, "missing throughput metric")
        require("vocera_iperf_loss_ratio" in prom, "missing loss ratio metric")
        require("vocera_iperf_scan_ignored_temp_files" in prom, "missing temp-file scan metric")
        require("Connection timed out" not in prom, "Prometheus output leaked dynamic error text")


def test_completed_error_result_is_down() -> None:
    """Verify completed iperf error files publish a down sample, not no sample."""

    with tempfile.TemporaryDirectory(prefix="vocera-iperf-qoe-") as tmp:
        root = Path(tmp)
        write_json(
            root / "S-NW-PROBE2" / "raw" / "client_to_client-20260519-120000.json",
            {
                "metadata": {
                    "device": "S-NW-PROBE2",
                    "site": "srhc",
                    "ssid": "srhcvoice2",
                    "mode": "ClientToPeer",
                    "direction": "client_to_client",
                    "target": "10.16.88.233",
                    "target_port": 5203,
                },
                "iperf3": {
                    "start": {
                        "timestamp": {"timesecs": 30},
                        "connecting_to": {"host": "10.16.88.233", "port": 5203},
                        "test_start": {"protocol": "UDP", "reverse": 0},
                    },
                    "end": {},
                    "error": "unable to connect",
                },
            },
        )

        scan = qoe.scan_incoming(root, {}, now=1000)
        require(len(scan.latest_results) == 1, "expected one down result")
        result = scan.latest_results[0]
        require(result.up == 0, f"expected down result, got up={result.up}")
        prom = qoe.render_prometheus(scan)
        require("vocera_iperf_up" in prom, "missing down up metric")
        require("vocera_iperf_last_success_timestamp_seconds" in prom, "missing last success metric")
        require("unable to connect" not in prom, "Prometheus output leaked error text")


def test_reverse_udp_prefers_sum_received() -> None:
    """For `iperf3 -J --reverse` UDP runs, jitter and loss live in
    `sum_received`; `sum_sent` lacks them. The parser must prefer the block
    that carries the receiver-side stats."""
    with tempfile.TemporaryDirectory(prefix="vocera-iperf-qoe-reverse-") as tmp:
        root = Path(tmp)
        write_json(
            root / "S-NW-PROBE2" / "raw" / "client_to_client-20260520-090000.json",
            {
                "metadata": {
                    "device": "S-NW-PROBE2",
                    "site": "srhc",
                    "ssid": "srhcvoice2",
                    "mode": "ClientToPeer",
                    "direction": "client_to_client",
                    "target": "10.16.88.233",
                    "target_port": 5203,
                    "duration_seconds": 60,
                },
                "iperf3": {
                    "start": {
                        "timestamp": {"timesecs": 100},
                        "connecting_to": {"host": "10.16.88.233", "port": 5203},
                        "test_start": {"protocol": "UDP", "reverse": 1},
                    },
                    "intervals": [],
                    "end": {
                        "sum_sent": {
                            "seconds": 60.0,
                            "bytes": 480000,
                            "bits_per_second": 64000,
                            "packets": 3000,
                        },
                        "sum_received": {
                            "seconds": 60.0,
                            "bytes": 478880,
                            "bits_per_second": 63850,
                            "jitter_ms": 0.421,
                            "lost_packets": 7,
                            "packets": 3000,
                            "lost_percent": 0.2333,
                        },
                    },
                },
            },
        )

        scan = qoe.scan_incoming(root, {}, now=200)
        require(len(scan.latest_results) == 1, "expected one reverse result")
        result = scan.latest_results[0]
        require(result.jitter_ms == 0.421, f"expected sum_received jitter, got {result.jitter_ms}")
        require(result.lost_packets == 7, f"expected sum_received lost_packets, got {result.lost_packets}")


def main() -> int:
    """Run the standalone Vocera iperf QoE tests."""

    test_scan_and_render_latest_results()
    test_completed_error_result_is_down()
    test_reverse_udp_prefers_sum_received()
    print("OK: vocera iperf QoE parser tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
