#!/usr/bin/env python3
"""Synthetic tests for the Vocera media QoE offline analyzer."""

from __future__ import annotations

import contextlib
import io
import json
import os
import struct
import sys
import tempfile
import time
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))
sys.path.insert(0, str(ROOT / "tools" / "wireless_rf"))

import vocera_dnac_icap as icap  # noqa: E402
import vocera_media_qoe as qoe  # noqa: E402
import vocera_media_qoe_batch as batch  # noqa: E402
import vocera_media_qoe_sql as history  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise an assertion with a clear fixture-specific message."""

    if not condition:
        raise AssertionError(message)


def relaxed_rtp_mapping(payload: dict, *, min_sequence_progression_ratio: float = 0.0) -> dict:
    """Return a config mapping for short synthetic RTP fixtures."""

    out = dict(payload)
    min_packets = int(out.pop("min_rtp_qoe_packets", 2))
    out.setdefault("payload_clock_rates", {"default": 8000, 0: 8000, 8: 8000, 9: 8000, 18: 8000})
    out["rtp_plausibility"] = {
        "strict": True,
        "require_known_clock_rate": False,
        "min_packets": min_packets,
        "min_duration_seconds": 0,
        "max_interarrival_ms": 1000,
        "max_jitter_ms": 10_000,
        "min_sequence_progression_ratio": min_sequence_progression_ratio,
        "min_timestamp_progression_ratio": 0,
        "max_timestamp_wallclock_error_ms": 1_000_000_000,
        "min_packetization_ms": 1,
        "max_packetization_ms": 1_000_000_000,
        "max_loss_ratio": 1,
        "max_duplicate_ratio": 1,
        "max_out_of_order_ratio": 1,
    }
    return out


def ipv4_udp_frame(
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
    *,
    dscp: int = 46,
) -> bytes:
    """Build a minimal Ethernet/IPv4/UDP frame for parser tests."""

    src_octets = bytes(int(part) for part in src_ip.split("."))
    dst_octets = bytes(int(part) for part in dst_ip.split("."))
    udp_len = 8 + len(payload)
    total_len = 20 + udp_len
    ethernet = b"\x00\x11\x22\x33\x44\x55" + b"\x66\x77\x88\x99\xaa\xbb" + struct.pack("!H", 0x0800)
    ip_header = struct.pack(
        "!BBHHHBBH4s4s",
        0x45,
        dscp << 2,
        total_len,
        1,
        0,
        64,
        17,
        0,
        src_octets,
        dst_octets,
    )
    udp_header = struct.pack("!HHHH", src_port, dst_port, udp_len, 0)
    return ethernet + ip_header + udp_header + payload


def rtp_payload(sequence: int, timestamp: int, *, ssrc: int = 0x12345678, payload_type: int = 0) -> bytes:
    """Build a minimal RTP payload with a 12-byte RTP header."""

    return struct.pack("!BBHII", 0x80, payload_type, sequence, timestamp, ssrc) + b"\x00" * 20


def radiotap_80211_udp_frame(
    src_ip: str,
    src_port: int,
    dst_ip: str,
    dst_port: int,
    payload: bytes,
    *,
    dscp: int = 46,
) -> bytes:
    """Build a minimal radiotap 802.11 data frame carrying IPv4/UDP."""

    radiotap = b"\x00\x00\x08\x00\x00\x00\x00\x00"
    frame_control = 0x0008 | 0x0100
    wifi_header = (
        struct.pack("<HH", frame_control, 0)
        + b"\x00\x11\x22\x33\x44\x55"
        + b"\x66\x77\x88\x99\xaa\xbb"
        + b"\xcc\xdd\xee\xff\x00\x11"
        + struct.pack("<H", 0)
    )
    llc_snap = b"\xaa\xaa\x03\x00\x00\x00" + struct.pack("!H", 0x0800)
    ethernet_frame = ipv4_udp_frame(src_ip, src_port, dst_ip, dst_port, payload, dscp=dscp)
    return radiotap + wifi_header + llc_snap + ethernet_frame[14:]


def pcap_bytes(frames: list[tuple[float, bytes]], *, linktype: int = 1) -> bytes:
    """Build a little-endian classic pcap containing frames."""

    out = bytearray()
    out.extend(struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 256, linktype))
    for ts, frame in frames:
        sec = int(ts)
        usec = int(round((ts - sec) * 1_000_000))
        out.extend(struct.pack("<IIII", sec, usec, len(frame), len(frame)))
        out.extend(frame)
    return bytes(out)


def pcapng_bytes(frames: list[tuple[float, bytes]], *, linktype: int = 1) -> bytes:
    """Build a little-endian pcapng containing Enhanced Packet Blocks."""

    def block(block_type: int, body: bytes) -> bytes:
        """Wrap one pcapng block with padding and repeated total length."""

        padding = b"\x00" * ((4 - (len(body) % 4)) % 4)
        total_len = 12 + len(body) + len(padding)
        return struct.pack("<II", block_type, total_len) + body + padding + struct.pack("<I", total_len)

    out = bytearray()
    shb_body = struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1)
    out.extend(block(0x0A0D0D0A, shb_body))
    idb_body = struct.pack("<HHI", linktype, 0, 65535)
    out.extend(block(1, idb_body))
    for ts, frame in frames:
        timestamp = int(round(ts * 1_000_000))
        body = struct.pack(
            "<IIIII",
            0,
            timestamp >> 32,
            timestamp & 0xFFFFFFFF,
            len(frame),
            len(frame),
        ) + frame
        out.extend(block(6, body))
    return bytes(out)


def write_pcap(frames: list[tuple[float, bytes]], *, linktype: int = 1) -> Path:
    """Write a temporary classic pcap fixture and return its path."""

    tmp = tempfile.NamedTemporaryFile(prefix="vocera-qoe-", suffix=".pcap", delete=False)
    path = Path(tmp.name)
    tmp.close()
    path.write_bytes(pcap_bytes(frames, linktype=linktype))
    return path


def write_pcapng(frames: list[tuple[float, bytes]], *, linktype: int = 1) -> Path:
    """Write a temporary pcapng fixture and return its path."""

    tmp = tempfile.NamedTemporaryFile(prefix="vocera-qoe-", suffix=".pcapng", delete=False)
    path = Path(tmp.name)
    tmp.close()
    path.write_bytes(pcapng_bytes(frames, linktype=linktype))
    return path


def test_rtp_jitter_loss_duplicate_and_out_of_order() -> None:
    """Verify RTP stream math from a synthetic badge-to-server capture."""

    frames = [
        (1000.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1000, 0))),
        (1000.021, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1001, 160))),
        # Sequence 1002 is missing.
        (1000.060, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1003, 480))),
        # Duplicate of 1003.
        (1000.061, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1003, 480))),
        # Late out-of-order sequence.
        (1000.082, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1002, 320))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "site": "lab",
            "capture_point": "server_span",
            "expected_dscp": 46,
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "min_rtp_qoe_packets": 2,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    streams = [stream for stream in result.streams if stream.measurement_mode == "rtp"]
    require(len(streams) == 1, f"expected one RTP stream, got {len(streams)}")
    stream = streams[0]
    require(stream.direction == "badge_to_server", f"bad direction: {stream.direction}")
    require(stream.server == "vocera-server", f"bad server label: {stream.server}")
    require(stream.packet_count == 5, f"bad packet count: {stream.packet_count}")
    require(stream.expected_packets == 4, f"bad expected count: {stream.expected_packets}")
    require(stream.lost_packets == 0, f"late packet should close loss gap: {stream.lost_packets}")
    require(stream.duplicate_packets == 1, f"bad duplicate count: {stream.duplicate_packets}")
    require(stream.out_of_order_packets == 1, f"bad out-of-order count: {stream.out_of_order_packets}")
    require(stream.jitter_ms is not None and stream.jitter_ms > 0, "expected positive RTP jitter")
    prom = qoe.render_prometheus(result)
    require("vocera_media_rtp_jitter_ms" in prom, "missing RTP jitter metric")
    require('src_role="badge"' in prom, "missing safe src_role label")
    require("192.0.2.20" not in prom, "Prometheus output leaked badge IP")
    require(stream.identity.src_ip == "192.0.2.20", "JSON stream identity should retain badge IP")


def test_control_test_device_labels() -> None:
    """Configured device metadata must survive parse, JSON, and Prom output."""

    frames = [
        (2000.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1, 0))),
        (2000.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(2, 160))),
        (2000.040, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(3, 320))),
        (2000.000, ipv4_udp_frame("192.0.2.30", 41000, "192.0.2.10", 20000, rtp_payload(10, 0, ssrc=0x87654321))),
        (2000.021, ipv4_udp_frame("192.0.2.30", 41000, "192.0.2.10", 20000, rtp_payload(11, 160, ssrc=0x87654321))),
        (2000.041, ipv4_udp_frame("192.0.2.30", 41000, "192.0.2.10", 20000, rtp_payload(12, 320, ssrc=0x87654321))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "site": "lab",
            "capture_point": "server_span",
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "devices": [
                {"name": "Control Device", "role": "control", "config": "production", "ip": "192.0.2.20"},
                {"name": "Test Device", "role": "test", "config": "test", "ip": "192.0.2.30"},
            ],
            "min_rtp_qoe_packets": 2,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    streams = sorted(
        [stream for stream in result.streams if stream.measurement_mode == "rtp"],
        key=lambda stream: stream.device_role,
    )
    require(len(streams) == 2, f"expected two RTP streams, got {len(streams)}")
    roles = {stream.device_role: stream for stream in streams}
    require(roles["control"].device_name == "Control Device", f"bad control label: {roles['control']}")
    require(roles["control"].device_config == "production", "bad control config label")
    require(roles["test"].device_name == "Test Device", f"bad test label: {roles['test']}")
    require(roles["test"].device_config == "test", "bad test config label")
    payload = result.to_json()
    require(payload["streams"][0].get("device_role") in {"control", "test"}, "JSON missing device_role")
    prom = qoe.render_prometheus(result)
    require('device_role="control"' in prom, "Prometheus missing control device role")
    require('device_role="test"' in prom, "Prometheus missing test device role")
    require("192.0.2.20" not in prom and "192.0.2.30" not in prom, "Prometheus output leaked device IP")
    sql = "\n".join(history._stream_inserts(payload))  # type: ignore[attr-defined]
    require("device_role" in sql and "'control'" in sql and "'test'" in sql, "SQL history missing device labels")


def test_device_label_falls_back_to_source_mac() -> None:
    """When endpoint IPs do not match config, the pcap source MAC labels the capture owner."""

    with tempfile.TemporaryDirectory(prefix="vocera-qoe-mac-fallback-") as tmp:
        path = Path(tmp) / "0009ef502a28_80211_capture.pcap"
        path.write_bytes(
            pcap_bytes(
                [
                    (2500.000, ipv4_udp_frame("192.0.2.55", 40000, "192.0.2.10", 20000, rtp_payload(1, 0))),
                    (2500.020, ipv4_udp_frame("192.0.2.55", 40000, "192.0.2.10", 20000, rtp_payload(2, 160))),
                    (2500.040, ipv4_udp_frame("192.0.2.55", 40000, "192.0.2.10", 20000, rtp_payload(3, 320))),
                ]
            )
        )
        config = qoe.config_from_mapping(
            relaxed_rtp_mapping(
                {
                "site": "lab",
                "capture_point": "server_span",
                "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
                "badge_subnets": ["192.0.2.0/24"],
                "devices": [
                    {
                        "name": "Test Device",
                        "role": "test",
                        "config": "test",
                        "mac": "00:09:ef:50:2a:28",
                    }
                ],
                "min_rtp_qoe_packets": 2,
                },
            )
        )

        result = qoe.analyze_pcap(path, config)
        streams = [stream for stream in result.streams if stream.measurement_mode == "rtp"]
        require(len(streams) == 1, f"expected one RTP stream, got {streams}")
        require(streams[0].device_role == "test", f"source MAC fallback did not label test role: {streams[0]}")
        require(streams[0].device_name == "Test Device", "source MAC fallback did not label device name")


def test_rtp_unknown_clock_rate_is_visible() -> None:
    """An RTP stream whose payload type lacks a configured clock rate must be
    flagged with clock_rate_known=False so operators can spot jitter that was
    computed against the 8 kHz fallback (which is 2x wrong for 16 kHz codecs)."""

    frames = [
        (3000.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1, 0, payload_type=99))),
        (3000.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(2, 160, payload_type=99))),
        (3000.040, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(3, 320, payload_type=99))),
        (3000.060, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(4, 480, payload_type=99))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "site": "lab",
            "capture_point": "server_span",
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "payload_clock_rates": {"default": 8000, 0: 8000, 8: 8000},
            "min_rtp_qoe_packets": 2,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    streams = [stream for stream in result.streams if stream.measurement_mode == "rtp"]
    require(len(streams) == 1, f"expected one RTP stream, got {len(streams)}")
    require(streams[0].clock_rate_known is False, "unknown payload type should set clock_rate_known=False")
    prom = qoe.render_prometheus(result)
    require("vocera_media_rtp_unknown_clock_streams" in prom, "missing unknown-clock-streams gauge")


def test_strict_plausibility_accepts_clean_rtp() -> None:
    """A clean 20 ms G.711-like stream should be trusted as RTP."""

    frames = [
        (
            5000.000 + (index * 0.020),
            ipv4_udp_frame(
                "192.0.2.20",
                40000,
                "192.0.2.10",
                20000,
                rtp_payload(1000 + index, index * 160),
            ),
        )
        for index in range(30)
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        {
            "site": "lab",
            "capture_point": "server_span",
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "payload_clock_rates": {0: 8000},
        }
    )
    result = qoe.analyze_pcap(path, config)
    streams = [stream for stream in result.streams if stream.measurement_mode == "rtp"]
    require(len(streams) == 1, f"expected one trusted RTP stream, got {result.to_json()}")
    stream = streams[0]
    require(stream.rtp_plausibility is not None, "trusted RTP stream missing plausibility details")
    require(stream.rtp_plausibility.is_plausible, f"clean RTP was marked implausible: {stream.rtp_plausibility}")
    require(stream.rtp_plausibility.estimated_packetization_ms == 20.0, f"bad packetization estimate: {stream.rtp_plausibility}")
    require(stream.rtp_plausibility.timestamp_wallclock_error_ms is not None, "missing timestamp/wallclock error")
    require(stream.rtp_plausibility.timestamp_wallclock_error_ms < 1, f"clean RTP wallclock error too high: {stream.rtp_plausibility}")
    prom = qoe.render_prometheus(result)
    require("vocera_media_rtp_plausible_streams" in prom, "missing plausible RTP metric")
    require("vocera_media_rtp_candidate_rejected_streams{" not in prom, "clean RTP emitted rejection metrics")


def test_strict_plausibility_rejects_random_rtp_lookalike() -> None:
    """Random UDP that happens to parse as RTP must not emit trusted QoE."""

    frames = []
    for index in range(30):
        sequence = (index * 12347 + 4000) % 65536
        timestamp = (index * 987654321 + 12345678) % (2 ** 32)
        frames.append(
            (
                5100.000 + (index * 0.020),
                ipv4_udp_frame(
                    "192.0.2.20",
                    40000,
                    "192.0.2.10",
                    20000,
                    rtp_payload(sequence, timestamp),
                ),
            )
        )
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        {
            "site": "lab",
            "capture_point": "server_span",
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "payload_clock_rates": {0: 8000},
        }
    )
    result = qoe.analyze_pcap(path, config)
    trusted = [stream for stream in result.streams if stream.measurement_mode == "rtp"]
    rejected = [stream for stream in result.streams if stream.measurement_mode == "rtp_candidate_rejected"]
    require(len(trusted) == 0, f"random RTP-looking UDP was trusted: {trusted}")
    require(len(rejected) == 1, f"expected one rejected RTP candidate, got {result.to_json()}")
    stream = rejected[0]
    require(stream.jitter_ms is None and stream.loss_ratio is None, f"rejected stream emitted trusted RTP metrics: {stream}")
    require(stream.rtp_plausibility is not None, "rejected RTP candidate missing plausibility details")
    require(
        {"sequence_not_progressing", "timestamp_wallclock_mismatch"} & set(stream.rtp_rejection_reasons),
        f"rejected RTP candidate missing expected reasons: {stream.rtp_rejection_reasons}",
    )
    prom = qoe.render_prometheus(result)
    require("vocera_media_rtp_candidate_rejected_streams" in prom, "missing rejected RTP stream metric")
    require("vocera_media_rtp_candidate_rejected_packets" in prom, "missing rejected RTP packet metric")
    require("192.0.2.20" not in prom, "rejected RTP metrics leaked client IP")


def test_rtp_debug_cli_output() -> None:
    """Verify --rtp-debug writes packet-level RTP candidate diagnostics."""

    frames = [
        (
            5200.000 + (index * 0.020),
            ipv4_udp_frame(
                "192.0.2.20",
                40000,
                "192.0.2.10",
                20000,
                rtp_payload(1000 + index, index * 160),
            ),
        )
        for index in range(30)
    ]
    path = write_pcap(frames)
    with tempfile.TemporaryDirectory(prefix="vocera-qoe-debug-") as tmp:
        root = Path(tmp)
        config_path = root / "config.yaml"
        prom_out = root / "out.prom"
        json_out = root / "summary.json"
        debug_out = root / "debug.json"
        config_path.write_text(
            "\n".join(
                [
                    "site: lab",
                    "capture_point: server_span",
                    "servers:",
                    "  - name: vocera-server",
                    "    ip: 192.0.2.10",
                    "badge_subnets:",
                    "  - 192.0.2.0/24",
                    "payload_clock_rates:",
                    "  0: 8000",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            rc = qoe.main(
                [
                    "--pcap",
                    str(path),
                    "--config",
                    str(config_path),
                    "--prom-out",
                    str(prom_out),
                    "--json-out",
                    str(json_out),
                    "--rtp-debug",
                    "--rtp-debug-out",
                    str(debug_out),
                    "--no-archive",
                ]
            )
        payload = json.loads(debug_out.read_text(encoding="utf-8"))
    require(rc == 0, f"CLI returned failure for debug run: {rc}")
    require(payload["candidate_count"] == 1, f"expected one RTP debug candidate: {payload}")
    require(payload["candidates"][0]["packets"][1]["rtp_delta_ms"] == 20.0, f"bad debug RTP delta: {payload}")


def test_rtp_loss_detection() -> None:
    """Verify missing RTP sequence numbers become estimated loss."""

    frames = [
        (2000.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(10, 0))),
        (2000.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(11, 160))),
        (2000.060, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(13, 480))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "min_rtp_qoe_packets": 2,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    stream = [stream for stream in result.streams if stream.measurement_mode == "rtp"][0]
    require(stream.expected_packets == 4, f"bad expected count: {stream.expected_packets}")
    require(stream.lost_packets == 1, f"bad lost count: {stream.lost_packets}")
    require(stream.loss_ratio == 0.25, f"bad loss ratio: {stream.loss_ratio}")


def test_sparse_rtp_candidate_does_not_emit_qoe() -> None:
    """Two RTP-looking packets are not enough evidence for RTP QoE claims."""

    frames = [
        (2500.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(100, 0))),
        (2500.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(101, 160))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
        }
    )
    result = qoe.analyze_pcap(path, config)
    require(len(result.streams) == 1, f"expected one stream, got {len(result.streams)}")
    stream = result.streams[0]
    require(stream.measurement_mode == "rtp_candidate_rejected", f"sparse RTP candidate claimed QoE: {stream.measurement_mode}")
    require("too_few_packets" in stream.rtp_rejection_reasons, f"sparse RTP missing rejection reason: {stream.rtp_rejection_reasons}")
    require(stream.jitter_ms is None, f"sparse RTP candidate emitted jitter: {stream.jitter_ms}")
    require(stream.loss_ratio is None, f"sparse RTP candidate emitted loss: {stream.loss_ratio}")


def test_large_rtp_sequence_jump_is_not_counted_as_loss() -> None:
    """A corrupt/restarted RTP sequence jump should not imply massive loss."""

    frames = [
        (2600.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1000, 0))),
        (2600.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1001, 160))),
        (2600.040, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(20000, 320))),
        (2600.060, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1002, 480))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "min_rtp_qoe_packets": 2,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    stream = [stream for stream in result.streams if stream.measurement_mode == "rtp"][0]
    require(stream.expected_packets == 3, f"bad expected count after jump: {stream.expected_packets}")
    require(stream.lost_packets == 0, f"large sequence jump counted as loss: {stream.lost_packets}")
    require(stream.loss_ratio == 0.0, f"bad loss ratio after jump: {stream.loss_ratio}")


def test_large_rtp_timestamp_jump_does_not_poison_jitter() -> None:
    """A corrupt RTP timestamp jump should reset jitter instead of spiking it."""

    frames = [
        (2700.000, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1000, 0))),
        (2700.020, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1001, 160))),
        (2700.040, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1002, 80_000_000))),
        (2700.060, ipv4_udp_frame("192.0.2.20", 40000, "192.0.2.10", 20000, rtp_payload(1003, 480))),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        relaxed_rtp_mapping(
            {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "min_rtp_qoe_packets": 2,
            "max_rtp_transit_delta_seconds": 1.0,
            },
        )
    )
    result = qoe.analyze_pcap(path, config)
    stream = [stream for stream in result.streams if stream.measurement_mode == "rtp"][0]
    require(stream.jitter_ms is not None and stream.jitter_ms < 1, f"timestamp jump poisoned jitter: {stream.jitter_ms}")


def test_udp_interarrival_only() -> None:
    """Verify generic UDP does not emit RTP jitter/loss claims."""

    frames = [
        (3000.000, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"not rtp one")),
        (3000.035, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"not rtp two")),
        (3000.090, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"not rtp three")),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
        }
    )
    result = qoe.analyze_pcap(path, config)
    require(len(result.streams) == 1, f"expected one UDP stream, got {len(result.streams)}")
    stream = result.streams[0]
    require(stream.measurement_mode == "udp_interarrival_only", f"bad mode: {stream.measurement_mode}")
    require(stream.loss_ratio is None, "generic UDP should not have loss ratio")
    require(stream.jitter_ms is None, "generic UDP should not have RTP jitter")
    require(round(stream.interarrival_p95_ms or 0, 3) == 55.0, f"bad interarrival p95: {stream.interarrival_p95_ms}")
    prom = qoe.render_prometheus(result)
    require("vocera_media_non_rtp_udp_streams" in prom, "missing non-RTP stream metric")
    require("vocera_media_rtp_jitter_ms" not in "\n".join(line for line in prom.splitlines() if "udp_interarrival_only" in line), "UDP mode emitted RTP jitter")


def test_future_packet_timestamps_are_quarantined() -> None:
    """Verify impossible future pcap timestamps do not define capture age or gaps."""

    base = time.time() - 60
    future = time.time() + 86400
    frames = [
        (base, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"one")),
        (base + 0.020, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"two")),
        (future, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"future")),
    ]
    path = write_pcap(frames)
    config = qoe.config_from_mapping(
        {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
            "max_capture_future_skew_seconds": 300,
        }
    )
    result = qoe.analyze_pcap(path, config)
    require(result.parse_success == 1, f"future outlier should not fail whole capture: {result.error}")
    require(result.udp_packets_seen == 3, f"raw UDP count should include future packet: {result.udp_packets_seen}")
    require(result.timestamp_outlier_packets == 1, f"future packet not counted: {result.timestamp_outlier_packets}")
    require(result.last_capture_timestamp_seconds is not None, "missing cleaned capture timestamp")
    require(result.last_capture_timestamp_seconds < future, "future packet defined capture timestamp")
    stream = result.streams[0]
    require(stream.packet_count == 2, f"future packet should not be analyzed: {stream.packet_count}")
    require(stream.interarrival_max_ms is not None and stream.interarrival_max_ms < 100, f"future packet stretched max gap: {stream.interarrival_max_ms}")
    prom = qoe.render_prometheus(result)
    require("vocera_media_timestamp_outlier_packets" in prom, "missing timestamp outlier metric")


def test_radiotap_80211_udp() -> None:
    """Verify unencrypted radiotap 802.11 pcaps are decoded into IP/UDP."""

    frames = [
        (
            4000.000,
            radiotap_80211_udp_frame("192.0.2.20", 42000, "192.0.2.10", 22000, b"not rtp one"),
        ),
        (
            4000.020,
            radiotap_80211_udp_frame("192.0.2.20", 42000, "192.0.2.10", 22000, b"not rtp two"),
        ),
    ]
    path = write_pcap(frames, linktype=qoe.IEEE802_11_RADIOTAP_LINKTYPE)
    config = qoe.config_from_mapping(
        {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
        }
    )
    result = qoe.analyze_pcap(path, config)
    require(result.packets_read == 2, f"bad packet read count: {result.packets_read}")
    require(result.udp_packets_seen == 2, f"bad UDP packet count: {result.udp_packets_seen}")
    require(len(result.streams) == 1, f"expected one stream, got {len(result.streams)}")
    stream = result.streams[0]
    require(stream.direction == "badge_to_server", f"bad direction: {stream.direction}")
    require(stream.measurement_mode == "udp_interarrival_only", f"bad mode: {stream.measurement_mode}")


def test_pcapng_udp() -> None:
    """Verify pcapng enhanced-packet blocks are decoded into UDP streams."""

    frames = [
        (4500.000, ipv4_udp_frame("192.0.2.20", 43000, "192.0.2.10", 23000, b"pcapng one")),
        (4500.050, ipv4_udp_frame("192.0.2.20", 43000, "192.0.2.10", 23000, b"pcapng two")),
    ]
    path = write_pcapng(frames)
    config = qoe.config_from_mapping(
        {
            "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
            "badge_subnets": ["192.0.2.0/24"],
        }
    )
    result = qoe.analyze_pcap(path, config)
    require(result.packets_read == 2, f"bad pcapng packet count: {result.packets_read}")
    require(result.udp_packets_seen == 2, f"bad pcapng UDP count: {result.udp_packets_seen}")
    require(result.last_capture_timestamp_seconds == 4500.05, f"bad pcapng timestamp: {result.last_capture_timestamp_seconds}")


def test_truncated_pcap_record_rejected() -> None:
    """Verify malformed/truncated pcaps fail closed instead of publishing metrics."""

    frame = ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"truncated")
    path = write_pcap([(5000.000, frame)])
    path.write_bytes(path.read_bytes()[:-5])
    config = qoe.config_from_mapping({})
    try:
        qoe.analyze_pcap(path, config)
    except RuntimeError as exc:
        require("truncated pcap record" in str(exc), f"wrong truncation error: {exc}")
    else:
        raise AssertionError("truncated pcap should be rejected")


def test_batch_publisher_parses_only_new_captures() -> None:
    """Verify batch mode caches parsed captures and archives run inputs."""

    with tempfile.TemporaryDirectory(prefix="vocera-qoe-batch-") as tmp:
        root = Path(tmp)
        raw_dir = root / "raw"
        out_dir = root / "out"
        parsed_dir = out_dir / "captures"
        raw_dir.mkdir()
        config = qoe.config_from_mapping(
            {
                "site": "lab",
                "capture_point": "server_span",
                "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
                "badge_subnets": ["192.0.2.0/24"],
            }
        )

        old_pcap = raw_dir / "old.pcap"
        new_pcap = raw_dir / "new.pcap"
        old_pcap.write_bytes(
            pcap_bytes([(1000.000, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"old"))])
        )
        new_pcap.write_bytes(
            pcap_bytes([(2000.000, ipv4_udp_frame("192.0.2.20", 41001, "192.0.2.10", 21001, b"new"))])
        )
        os.utime(old_pcap, ns=(1_000_000_000, 1_000_000_000))
        os.utime(new_pcap, ns=(2_000_000_000, 2_000_000_000))

        first = batch.publish_unparsed_captures(
            raw_dir=raw_dir,
            config=config,
            prom_out=out_dir / "vocera_media_qoe.prom",
            json_out=out_dir / "vocera_media_qoe_summary.json",
            parsed_dir=parsed_dir,
            textfile_out=out_dir / "textfile" / "vocera_media_qoe.prom",
            archive_dir=out_dir / "archives",
            archive_label="test-batch",
        )
        require(len(first.parsed) == 2, f"expected two parsed captures, got {first.parsed}")
        require(first.published_pcap == new_pcap, f"expected newest pcap to publish, got {first.published_pcap}")
        require(first.archive_zip is not None and first.archive_zip.is_file(), f"missing archive: {first.archive_zip}")
        with zipfile.ZipFile(first.archive_zip) as archive:
            names = archive.namelist()
        require("manifest.json" in names, "archive missing manifest")
        require("logs/run.log" in names, "archive missing run log")
        require(any(name.endswith("/old.pcap") for name in names), f"archive missing old pcap: {names}")
        require(any(name.endswith("/new.pcap") for name in names), f"archive missing new pcap: {names}")

        second = batch.publish_unparsed_captures(
            raw_dir=raw_dir,
            config=config,
            prom_out=out_dir / "vocera_media_qoe.prom",
            json_out=out_dir / "vocera_media_qoe_summary.json",
            parsed_dir=parsed_dir,
            textfile_out=out_dir / "textfile" / "vocera_media_qoe.prom",
        )
        require(len(second.parsed) == 0, f"expected no reparsed captures, got {second.parsed}")
        require(len(second.skipped) == 2, f"expected two skipped captures, got {second.skipped}")
        payload = json.loads((out_dir / "vocera_media_qoe_summary.json").read_text(encoding="utf-8"))
        require(payload["source_pcap"]["name"] == "new.pcap", f"wrong published source: {payload.get('source_pcap')}")


def test_batch_rejects_dnac_size_mismatch_and_emits_history_sql() -> None:
    """Verify DNAC sidecar size mismatches are recorded and skipped."""

    with tempfile.TemporaryDirectory(prefix="vocera-qoe-history-") as tmp:
        root = Path(tmp)
        raw_dir = root / "raw"
        out_dir = root / "out"
        parsed_dir = out_dir / "captures"
        raw_dir.mkdir()
        config = qoe.config_from_mapping(
            {
                "site": "lab",
                "capture_point": "server_span",
                "servers": [{"name": "vocera-server", "ip": "192.0.2.10"}],
                "badge_subnets": ["192.0.2.0/24"],
            }
        )

        good = raw_dir / "good.pcap"
        bad = raw_dir / "bad.pcap"
        good.write_bytes(
            pcap_bytes(
                [
                    (6000.000, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"one")),
                    (6000.020, ipv4_udp_frame("192.0.2.20", 41000, "192.0.2.10", 21000, b"two")),
                ]
            )
        )
        bad.write_bytes(pcap_bytes([]))
        bad.with_suffix(".pcap.json").write_text(
            json.dumps({"capture": {"fileSize": bad.stat().st_size + 1000}}),
            encoding="utf-8",
        )

        result = batch.publish_unparsed_captures(
            raw_dir=raw_dir,
            config=config,
            prom_out=out_dir / "vocera_media_qoe.prom",
            json_out=out_dir / "vocera_media_qoe_summary.json",
            parsed_dir=parsed_dir,
            sql_out=out_dir / "vocera_media_qoe_import.sql",
        )
        require(result.history_sql == out_dir / "vocera_media_qoe_import.sql", f"bad sql output: {result.history_sql}")

        bad_json, _bad_prom = batch.cache_paths(parsed_dir, bad)
        bad_payload = json.loads(bad_json.read_text(encoding="utf-8"))
        require(bad_payload["parse_success"] == 0, f"size-mismatched pcap parsed: {bad_payload}")
        require("does not match Catalyst Center metadata" in bad_payload["error"], f"bad mismatch error: {bad_payload['error']}")

        sql = (out_dir / "vocera_media_qoe_import.sql").read_text(encoding="utf-8")
        require("vocera_media_stream_samples" in sql, "history SQL missing stream insert")
        require("truncate table vocera_media_stream_samples" not in sql, "history SQL should not truncate other role captures")
        require("delete from vocera_media_stream_samples where capture_id" in sql, "history SQL should replace only current capture rows")
        require("to_timestamp(6000.02)" in sql, f"history SQL did not use packet timestamp: {sql}")
        require(len(history.load_current_payloads(parsed_dir)) == 2, "expected both current payloads in history source")


def test_media_study_sql_contract() -> None:
    """Verify the dashboard-facing study workflow is schema-backed."""

    schema = (ROOT / "sql" / "vocera_media_qoe_schema.sql").read_text(encoding="utf-8")
    views = (ROOT / "sql" / "vocera_media_qoe_views.sql").read_text(encoding="utf-8")
    makefile_text = (ROOT / "Makefile").read_text(encoding="utf-8")
    fastapi_text = (ROOT / "tools" / "study_web" / "main.py").read_text(encoding="utf-8")
    api_client_text = (ROOT / "web" / "study-ui" / "src" / "api" / "client.ts").read_text(encoding="utf-8")
    api_types_text = (ROOT / "web" / "study-ui" / "src" / "api" / "types.ts").read_text(encoding="utf-8")
    app_text = (ROOT / "web" / "study-ui" / "src" / "App.tsx").read_text(encoding="utf-8")
    media_page_text = (ROOT / "web" / "study-ui" / "src" / "pages" / "MediaQoeStudy.tsx").read_text(encoding="utf-8")
    multicast_page_text = (ROOT / "web" / "study-ui" / "src" / "pages" / "VoceraMulticastStudy.tsx").read_text(encoding="utf-8")
    media_raw_file_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaRawFileList.tsx").read_text(encoding="utf-8")
    media_execution_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaCaptureExecution.tsx").read_text(encoding="utf-8")
    media_capture_list_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaCaptureList.tsx").read_text(encoding="utf-8")
    media_duplicate_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaDuplicateCaptures.tsx").read_text(encoding="utf-8")
    media_stream_list_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaStreamList.tsx").read_text(encoding="utf-8")
    media_stream_review_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaStreamReview.tsx").read_text(encoding="utf-8")
    media_parse_run_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaParseRunList.tsx").read_text(encoding="utf-8")
    media_execution_status_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaExecutionStatus.tsx").read_text(encoding="utf-8")
    media_capture_filters_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaCaptureFilters.tsx").read_text(encoding="utf-8")
    media_stream_filters_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaStreamFilters.tsx").read_text(encoding="utf-8")
    media_severity_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaStreamSeverityBadge.tsx").read_text(encoding="utf-8")
    media_severity_helper_text = (ROOT / "web" / "study-ui" / "src" / "components" / "mediaQoeSeverity.ts").read_text(encoding="utf-8")
    media_triage_summary_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaTriageSummary.tsx").read_text(encoding="utf-8")
    media_dnac_status_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaDnacStatus.tsx").read_text(encoding="utf-8")
    media_dnac_search_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaDnacCaptureSearch.tsx").read_text(encoding="utf-8")
    media_dnac_list_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaDnacCaptureList.tsx").read_text(encoding="utf-8")
    media_wlc_sessions_text = (ROOT / "web" / "study-ui" / "src" / "components" / "MediaWlcCaptureSessions.tsx").read_text(encoding="utf-8")
    rf_page_text = (ROOT / "web" / "study-ui" / "src" / "pages" / "RfValidationStudy.tsx").read_text(encoding="utf-8")
    project_selector_text = (ROOT / "web" / "study-ui" / "src" / "components" / "ProjectSelector.tsx").read_text(encoding="utf-8")
    study_selector_text = (ROOT / "web" / "study-ui" / "src" / "components" / "StudySelector.tsx").read_text(encoding="utf-8")
    study_web_unit_text = (ROOT / "systemd" / "vocera-rf-validation-study-web.service").read_text(encoding="utf-8")
    batch_text = (ROOT / "tools" / "vocera_media_qoe" / "vocera_media_qoe_batch.py").read_text(encoding="utf-8")
    history_text = (ROOT / "tools" / "vocera_media_qoe" / "vocera_media_qoe_sql.py").read_text(encoding="utf-8")
    require("create table if not exists vocera_media_study_archives" in schema, "missing media study archive table")
    require("create table if not exists vocera_projects" in schema, "missing media project table")
    require("create table if not exists vocera_studies" in schema, "missing media study table")
    require("study_id text references vocera_studies" in schema, "media captures should attach to studies")
    require("capture_status text not null default 'complete'" in schema, "media captures should have workflow status")
    require("'registered', 'queued', 'running', 'complete', 'failed', 'deleted'" in schema, "media captures should constrain execution statuses")
    require("source_sha256 text" in schema, "media captures should include duplicate-detection source hash")
    require("source_discovered_at timestamptz" in schema, "media captures should track source discovery time")
    require("source_registered_at timestamptz" in schema, "media captures should track registration time")
    require("source_size_bytes bigint" in schema, "media captures should track source size")
    require("source_mtime timestamptz" in schema, "media captures should track source mtime")
    require("parse_started_at timestamptz" in schema, "media captures should track parser start time")
    require("parse_finished_at timestamptz" in schema, "media captures should track parser finish time")
    require("parse_duration_seconds double precision" in schema, "media captures should track parser duration")
    require("parse_exit_code integer" in schema, "media captures should track parser exit code")
    require("parse_stdout text" in schema and "parse_stderr text" in schema, "media captures should capture parser stdout/stderr")
    require("parse_requested_by text" in schema and "parse_requested_at timestamptz" in schema, "media captures should track parser requester")
    require("create table if not exists vocera_media_capture_parse_runs" in schema, "missing media capture parse-run history table")
    require("idx_vocera_media_parse_runs_capture_time" in schema, "missing parse-run capture/time index")
    require("idx_vocera_media_parse_runs_study_time" in schema, "missing parse-run study/time index")
    require("create table if not exists vocera_media_execution_locks" in schema, "missing media QoE execution lock table")
    require("idx_vocera_media_execution_locks_expires" in schema, "missing media QoE execution lock expiry index")
    require("stream_classification text" in schema, "media streams should include review classification")
    require("review_status text not null default 'unreviewed'" in schema, "media streams should include review status")
    require("project_media_qoe_default" in schema, "missing default media QoE project")
    require("study_media_qoe_default" in schema, "missing default media QoE study")
    require("idx_vocera_media_captures_study_time" in schema, "missing media capture study/time index")
    require("idx_vocera_media_stream_review" in schema, "missing media stream review index")
    require("vocera_media_archive_current_study" in schema, "missing archive-current-study function")
    require("vocera_media_archive_and_clear_current_study" in schema, "missing archive-and-clear function")
    require("vocera_media_clear_current_study" in schema, "missing clear-current-study function")
    require("vocera_media_apply_current_study_action" in schema, "missing dashboard study action dispatcher")
    require("vocera_media_update_study_archive" in schema, "missing archive update function")
    require("vocera_media_delete_study_archive" in schema, "missing archive delete function")
    require("create table if not exists vocera_media_broadcast_attempts" in schema, "missing manual WLC attempt table")
    require("create table if not exists vocera_media_capture_sessions" in schema, "missing manual WLC capture session table")
    require("create table if not exists vocera_media_capture_session_events" in schema, "missing manual WLC session event table")
    require("create table if not exists vocera_media_multicast_observations" in schema, "missing normalized multicast observation table")
    require("capture_session_id text references vocera_media_capture_sessions" in schema, "attempts should attach to capture sessions")
    require("dynamic_multicast_ip inet" in schema and "dynamic_multicast_mac text" in schema, "attempts should store dynamic multicast evidence")
    require("configured_vocera_vlan integer not null default 684" in schema, "capture sessions should preserve configured Vocera VLAN default")
    require("resolved_group_vlan integer" in schema and "vlan_context_state text" in schema, "schema should separate configured and resolved VLAN context")
    require("sender_client_vlan integer" in schema and "receiver_multicast_vlan integer" in schema, "WLC snapshots should store badge-side VLAN observations separately")
    require("create table if not exists vocera_media_attempt_artifacts" in schema, "missing manual WLC attempt artifact table")
    require("create table if not exists vocera_media_wlc_snapshots" in schema, "missing manual WLC snapshot table")
    require("create table if not exists vocera_media_attempt_findings" in schema, "missing manual WLC attempt finding table")
    require("create or replace view v_vocera_media_qoe_projects" in views, "missing media QoE project view")
    require("create or replace view v_vocera_media_qoe_studies" in views, "missing media QoE study view")
    study_view = views.split(
        "create or replace view v_vocera_media_qoe_studies", 1
    )[1].split("create or replace view ", 1)[0]
    require(
        "s.deleted_at,\n  s.study_type\nfrom vocera_studies s" in study_view,
        "media QoE study view must expose study_type for API/UI selectors",
    )
    require("create or replace view v_vocera_media_qoe_study_captures" in views, "missing media QoE study capture view")
    study_capture_view = views.split(
        "create or replace view v_vocera_media_qoe_study_captures", 1
    )[1].split("create or replace view ", 1)[0]
    require("lossy_stream_count" in study_capture_view, "study capture view should expose per-capture lossy stream count")
    require("jitter_p95_ms" in study_capture_view, "study capture view should expose per-capture jitter p95")
    require("loss_p95_ratio" in study_capture_view, "study capture view should expose per-capture loss p95")
    require("interarrival_p95_ms" in study_capture_view, "study capture view should expose per-capture interarrival p95")
    require("trusted_rtp_dscp_mismatch_stream_count" in study_capture_view, "study capture view should expose trusted RTP DSCP mismatch count")
    require("non_rtp_dscp_mismatch_stream_count" in study_capture_view, "study capture view should expose non-RTP DSCP mismatch count")
    require("create or replace view v_vocera_media_qoe_study_streams" in views, "missing media QoE study stream view")
    require("create or replace view v_vocera_media_qoe_parse_runs" in views, "missing media QoE parse-run view")
    require("create or replace view v_vocera_media_qoe_project_summary" in views, "missing media QoE project summary view")
    require("create or replace view v_vocera_media_qoe_duplicate_captures" in views, "missing media QoE duplicate capture view")
    require("create or replace view v_vocera_media_current_study" in views, "missing current study summary view")
    require("create or replace view v_vocera_media_current_device_summary" in views, "missing current device summary view")
    require("create or replace view v_vocera_media_current_control_test_delta" in views, "missing control/test delta view")
    require("create or replace view v_vocera_media_current_rtp_classification" in views, "missing RTP classification view")
    require("create or replace view v_vocera_media_current_rtp_rejection_reasons" in views, "missing RTP rejection reasons view")
    require("create or replace view v_vocera_media_broadcast_attempts" in views, "missing manual WLC attempt view")
    require("create or replace view v_vocera_media_capture_sessions" in views, "missing manual WLC capture session view")
    require("create or replace view v_vocera_media_capture_session_events" in views, "missing manual WLC session event view")
    require("create or replace view v_vocera_media_multicast_observations" in views, "missing multicast observation view")
    require("create or replace view v_vocera_media_vocera_group_explorer" in views, "missing Vocera group explorer view")
    require("create or replace view v_vocera_media_multicast_attempt_matrix" in views, "missing multicast attempt matrix view")
    require("create or replace view v_vocera_media_attempt_summary" in views, "missing manual WLC attempt summary view")
    # WLC view migration compatibility contract.
    require(
        "drop view if exists v_vocera_media_broadcast_attempts" in views,
        "broadcast-attempt view migration must recreate the legacy view safely",
    )
    require(
        "drop view if exists v_vocera_media_attempt_summary" in views,
        "attempt-summary view migration must recreate the legacy view safely",
    )
    require(
        "snapshot_stats.receiver_group_member as snapshot_receiver_group_member" in views,
        "broadcast-attempt view must distinguish stored and snapshot membership evidence",
    )
    require(
        "--single-transaction" in history_text,
        "media schema and views must install atomically",
    )
    require("vocera-media-qoe-wlc-attempt-init" in makefile_text, "missing manual WLC attempt init target")
    require("vocera-media-qoe-wlc-attempt-ingest" in makefile_text, "missing manual WLC attempt ingest target")
    require("vocera-media-qoe-wlc-session-init" in makefile_text, "missing manual WLC session init target")
    require("vocera-media-qoe-wlc-session-mark" in makefile_text, "missing manual WLC session marker target")
    require("rtp_candidate_rejected_stream_count" in views, "current study views should expose rejected RTP stream counts")
    require("rtp_duplicate_packet_ratio" in views, "device summary should expose normalized duplicate packet ratio")
    require("rtp_out_of_order_packet_ratio" in views, "device summary should expose normalized out-of-order packet ratio")
    require("jitter_p05_ms" in views, "device summary should expose jitter p05")
    require("jitter_mean_ms" in views, "device summary should expose jitter mean")
    require("interarrival_p05_ms" in views, "device summary should expose interarrival p05")
    require("interarrival_mean_ms" in views, "device summary should expose interarrival mean")
    require("RTP jitter p05 ms" in views, "control/test delta should compare jitter p05")
    require("RTP jitter mean ms" in views, "control/test delta should compare jitter mean")
    require("RTP interarrival p05 ms" in views, "control/test delta should compare interarrival p05")
    require("RTP interarrival mean ms" in views, "control/test delta should compare interarrival mean")
    require("RTP duplicate packet %" in views, "control/test delta should compare duplicate packet percent")
    require("Trusted RTP duplicate packets" in views, "raw duplicate counts should be clearly scoped to trusted RTP")
    require("worst" not in views.lower(), "study interface should not include worst-stream drilldowns")
    require("def validate_media_study_id" in fastapi_text, "Study Web should validate media_qoe study IDs")
    require("def validate_media_project_id" in fastapi_text, "Study Web should validate media_qoe project IDs")
    require("@app.get(\"/api/media-qoe/summary\")" in fastapi_text, "Study Web should expose media QoE summary")
    for route in (
        '@app.get("/api/media-qoe/projects")',
        '@app.post("/api/media-qoe/projects")',
        '@app.get("/api/media-qoe/projects/{project_id}/studies")',
        '@app.post("/api/media-qoe/projects/{project_id}/studies")',
        '@app.get("/api/media-qoe/studies/{study_id}")',
    ):
        require(route in fastapi_text, f"Study Web should expose Media QoE ownership route {route}")
    media_project_routes = fastapi_text.split('@app.get("/api/media-qoe/projects")', 1)[1].split('@app.get("/api/media-qoe/execution/status")', 1)[0]
    require("media_query_rows(" in media_project_routes and "media_query_one(" in media_project_routes, "Media QoE ownership routes must use the Media QoE database connection")
    require("\n    query_rows(" not in media_project_routes and "\n    query_one(" not in media_project_routes, "Media QoE ownership routes must not use the primary RF/Study database connection")
    require("@app.get(\"/api/media-qoe/execution/status\")" in fastapi_text, "Study Web should expose media execution guardrail status")
    require("@app.get(\"/api/projects/{project_id}/media-qoe/summary\")" in fastapi_text, "Study Web should expose media project summary")
    require("@app.get(\"/api/projects/{project_id}/media-qoe/captures\")" in fastapi_text, "Study Web should expose media project captures")
    require("@app.get(\"/api/projects/{project_id}/media-qoe/streams\")" in fastapi_text, "Study Web should expose media project streams")
    require("@app.get(\"/api/projects/{project_id}/media-qoe/duplicates\")" in fastapi_text, "Study Web should expose media duplicate captures")
    require("@app.get(\"/api/studies/{study_id}/media-qoe/captures\")" in fastapi_text, "Study Web should expose media study captures")
    require("@app.get(\"/api/studies/{study_id}/media-qoe/streams\")" in fastapi_text, "Study Web should expose media study streams")
    require("@app.get(\"/api/studies/{study_id}/media-qoe/raw-files\")" in fastapi_text, "Study Web should expose raw capture scan")
    require("@app.get(\"/api/media-qoe/dnac/status\")" in fastapi_text, "Study Web should expose DNAC/iCAP readiness")
    require("@app.get(\"/api/media-qoe/wlc/defaults\")" in fastapi_text, "Study Web should expose WLC capture defaults")
    require("@app.post(\"/api/studies/{study_id}/media-qoe/wlc/sessions\")" in fastapi_text, "Study Web should create manual WLC capture sessions")
    require("@app.get(\"/api/media-qoe/wlc/sessions/{session_id}\")" in fastapi_text, "Study Web should expose an explicit WLC session detail read model")
    require("@app.post(\"/api/media-qoe/wlc/sessions/{session_id}/events\")" in fastapi_text, "Study Web should record WLC session event markers")
    require("collector_scp_password" not in fastapi_text and "wlc_password" not in fastapi_text, "Study Web must not model WLC/SCP password fields")
    require("@app.get(\"/api/studies/{study_id}/media-qoe/dnac/captures\")" in fastapi_text, "Study Web should expose read-only DNAC/iCAP capture listing")
    require("@app.post(\"/api/studies/{study_id}/media-qoe/dnac/captures/download\")" in fastapi_text, "Study Web should expose selected DNAC/iCAP capture download")
    require("@app.post(\"/api/studies/{study_id}/media-qoe/captures/register\")" in fastapi_text, "Study Web should expose capture registration")
    require("@app.post(\"/api/media-qoe/captures/{capture_id}/execute\")" in fastapi_text, "Study Web should expose single-capture execution")
    require("@app.get(\"/api/media-qoe/captures/{capture_id}/parse-runs\")" in fastapi_text, "Study Web should expose parse-run history")
    for env_name in (
        "STUDY_WEB_MEDIA_QOE_RAW_DIR",
        "STUDY_WEB_MEDIA_QOE_ALLOWED_EXTENSIONS",
        "STUDY_WEB_MEDIA_QOE_MAX_SCAN_FILES",
        "STUDY_WEB_MEDIA_QOE_MAX_PARSE_BYTES",
        "STUDY_WEB_MEDIA_QOE_EXECUTION_ENABLED",
        "STUDY_WEB_MEDIA_QOE_ARCHIVE_ENABLED",
        "STUDY_WEB_MEDIA_QOE_PARSE_TIMEOUT_SECONDS",
        "STUDY_WEB_MEDIA_QOE_DNAC_ENV_FILE",
        "STUDY_WEB_MEDIA_QOE_DNAC_DOWNLOAD_ENABLED",
    ):
        require(env_name in fastapi_text, f"Study Web should honor {env_name}")
        require(env_name in study_web_unit_text, f"Study Web systemd unit should set {env_name}")
    require("resolve(strict=True)" in fastapi_text and "relative_to(root)" in fastapi_text, "Study Web should validate resolved raw paths under raw dir")
    require("\"--no-archive\"" in fastapi_text, "Study Web parser execution should force archives off")
    require("\"--skip-install-db\"" in fastapi_text and "\"VOCERA_MEDIA_QOE_INSTALL_DB\": \"0\"" in fastapi_text, "Study Web parser execution should skip schema/view install")
    require("vocera_media_qoe_batch" in fastapi_text, "Study Web should invoke the existing media QoE batch parser")
    require("@app.patch(\"/api/media-qoe/streams/{capture_id}/{stream_id}\")" in fastapi_text, "Study Web should expose media stream review patch")
    require("MEDIA_STREAM_CLASSIFICATIONS" in fastapi_text, "Study Web should constrain media stream classifications")
    require(
        "MEDIA_QOE_PARSE_LOCK_NAME" in fastapi_text
        and "media_acquire_parse_lock" in fastapi_text
        and "media_release_parse_lock" in fastapi_text,
        "Study Web should enforce a Media QoE parse execution lock",
    )
    require(
        "status_code=409" in fastapi_text
        and "Another Media QoE parse is already running" in fastapi_text,
        "Study Web should reject concurrent Media QoE parses with HTTP 409",
    )
    require(
        "parse_running" in fastapi_text and "active_parse" in fastapi_text,
        "Media execution status should expose active parse lock state",
    )
    require(
        "DNAC ICAP download is disabled by STUDY_WEB_MEDIA_QOE_DNAC_DOWNLOAD_ENABLED" in fastapi_text
        and "download_icap_capture_file" in fastapi_text
        and "capture_file_size" in fastapi_text
        and "write_metadata" in fastapi_text
        and "register_study_media_qoe_capture" in fastapi_text,
        "Study Web should safely download selected ICAP captures and register them without parsing",
    )
    require(
        '"parse_success": parse_success' in fastapi_text
        and '"parse_success": study_match.get("parse_success")' in fastapi_text,
        "Study Web should expose parse_success in DNAC and raw-file capture state",
    )
    for field_name in ("dscp_mismatch_stream_count", "lossy_stream_count", "jitter_p95_ms", "loss_p95_ratio", "interarrival_p95_ms"):
        require(field_name in fastapi_text, f"Study Web should expose {field_name} in DNAC/raw capture state")
    for field_name in ("trusted_rtp_dscp_mismatch_stream_count", "non_rtp_dscp_mismatch_stream_count"):
        require(field_name in fastapi_text, f"Study Web should expose {field_name} in DNAC/raw capture state")
    require((ROOT / "scripts" / "smoke_vocera_media_qoe_workflow.py").is_file(), "missing media QoE live smoke script")
    media_smoke_text = (ROOT / "scripts" / "smoke_vocera_media_qoe_workflow.py").read_text(encoding="utf-8")
    require("/api/media-qoe/projects" in media_smoke_text, "media QoE smoke should verify Media QoE-owned project routes")
    require("--create-disposable-wlc-session" in media_smoke_text, "media QoE smoke should offer a disposable WLC session ownership path")
    require("projectType?: ProjectType" in project_selector_text, "ProjectSelector should support projectType filtering")
    require("project_type === projectType || project.project_type === 'mixed'" in project_selector_text, "ProjectSelector should allow mixed projects")
    require("studyType?: StudyType" in study_selector_text, "StudySelector should support studyType filtering")
    require("s.study_type === studyType" in study_selector_text, "StudySelector should filter requested study type")
    require(
        "type === 'rf_validation' || type === 'mixed'" in rf_page_text,
        "RF page should filter projects to RF validation or mixed projects",
    )
    require(
        "s.study_type === 'rf_validation'" in rf_page_text,
        "RF page should filter project studies to RF validation studies",
    )
    require("ProjectSelector" in media_page_text, "Media QoE page should use ProjectSelector")
    require("StudySelector" in media_page_text, "Media QoE page should use StudySelector")
    require('projectType="media_qoe"' in media_page_text, "Media QoE page should select media_qoe projects")
    require('studyType="media_qoe"' in media_page_text, "Media QoE page should select media_qoe studies")
    require("listMediaQoeProjects" in media_page_text and "listMediaQoeProjectStudies" in media_page_text, "Media QoE page should load Media QoE-owned project/study options")
    require("listProjects" not in media_page_text and "listProjectStudies" not in media_page_text, "Media QoE page must not use generic RF/Study project ownership APIs")
    require("summaryResponse?.studies" not in media_page_text, "Media QoE page should not build study options only from default media summary")
    require("ICAP QoE" in app_text and "Vocera multicast" in app_text, "Study Web should expose separate ICAP and multicast navigation entries")
    require("VoceraMulticastStudy" in app_text, "Study Web should mount the multicast investigation page separately")
    require("MediaWlcCaptureSessions" not in media_page_text, "ICAP QoE page must not embed WLC multicast session controls")
    require("Catalyst Center ICAP" in media_page_text, "ICAP QoE page should retain ICAP workflow")
    require("Vocera multicast" in multicast_page_text and "MediaWlcCaptureSessions" in multicast_page_text, "multicast page should own WLC capture sessions")
    require("ICAP capture QoE remains on its own page" in multicast_page_text, "multicast page should explicitly separate itself from ICAP QoE")
    require("listMediaQoeProjects" in multicast_page_text and "listMediaQoeProjectStudies" in multicast_page_text, "multicast page should load Media QoE-owned project/study options")
    require("createMediaQoeProject" in multicast_page_text and "createMediaQoeProjectStudy" in multicast_page_text, "multicast page should create Media QoE-owned investigations")
    require("listProjects" not in multicast_page_text and "listProjectStudies" not in multicast_page_text, "multicast page must not use generic RF/Study project ownership APIs")
    require("MediaExecutionStatusResponse" in api_types_text, "API types should include media execution status response")
    require("MediaDnacStatusResponse" in api_types_text, "API types should include DNAC/iCAP readiness response")
    require("MediaDnacCapturesResponse" in api_types_text and "MediaDnacCaptureQuery" in api_types_text, "API types should include DNAC/iCAP capture listing response")
    require("MediaDnacCaptureDownloadRequest" in api_types_text and "MediaDnacCaptureDownloadResponse" in api_types_text, "API types should include DNAC/iCAP download/register response")
    require("parse_success?: string | boolean" in api_types_text, "media raw/DNAC capture types should expose parse success for usefulness badges")
    for field_name in ("dscp_mismatch_stream_count", "lossy_stream_count", "jitter_p95_ms", "loss_p95_ratio", "interarrival_p95_ms"):
        require(field_name in api_types_text, f"media raw/DNAC capture types should expose {field_name}")
    for field_name in ("trusted_rtp_dscp_mismatch_stream_count", "non_rtp_dscp_mismatch_stream_count"):
        require(field_name in api_types_text, f"media raw/DNAC capture types should expose {field_name}")
    require("raw_dir_readable" in api_types_text and "archive_enabled" in api_types_text, "media execution status type should expose guardrails")
    require("parse_running" in api_types_text and "active_parse" in api_types_text, "media execution status type should expose active parse state")
    require("getMediaQoeExecutionStatus" in api_client_text, "API client should expose media execution status")
    require("listMediaQoeProjects" in api_client_text and "createMediaQoeProject" in api_client_text, "API client should expose Media QoE project ownership helpers")
    require("listMediaQoeProjectStudies" in api_client_text and "createMediaQoeProjectStudy" in api_client_text, "API client should expose Media QoE study ownership helpers")
    require("getMediaQoeStudy" in api_client_text, "API client should expose Media QoE study lookup")
    require("getMediaQoeDnacStatus" in api_client_text, "API client should expose DNAC/iCAP readiness status")
    require("getMediaQoeWlcDefaults" in api_client_text, "API client should expose WLC defaults")
    require("createStudyMediaQoeWlcSession" in api_client_text, "API client should create WLC sessions")
    require("createMediaQoeWlcSessionEvent" in api_client_text, "API client should mark WLC session events")
    require("MediaWlcSessionCreateRequest" in api_types_text, "API types should include WLC session create request")
    require("MediaWlcSessionDetailResponse" in api_types_text, "API types should include WLC session detail response")
    require("resolved_group_vlan?: number" in api_types_text and "vlan_selection_source?" in api_types_text, "API types should support active group VLAN resolution")
    require("collector_scp_password" not in api_types_text and "wlc_password" not in api_types_text, "API types must not include password fields")
    require("getMediaQoeWlcSession" in api_client_text, "API client should fetch explicit WLC session details")
    require("createMediaQoeWlcSessionEvent" in media_wlc_sessions_text, "WLC session UI should mark session events")
    require("selectedSessionId" in media_wlc_sessions_text and "getMediaQoeWlcSession" in media_wlc_sessions_text, "WLC session UI should operate on an explicit selected session")
    require("latestRunningSession" not in media_wlc_sessions_text, "WLC session UI must not target the first running session implicitly")
    require("Capture profile" in media_wlc_sessions_text and "Advanced overrides" in media_wlc_sessions_text, "WLC session UI should show a capture profile with explicit override path")
    require("hasCompleteCaptureProfile" in media_wlc_sessions_text and "validMediaStudy" in media_wlc_sessions_text, "WLC session UI should gate creation on valid study ownership and complete profile defaults")
    require("Vocera VLAN" in media_wlc_sessions_text and "Override active-group VLAN reason" in media_wlc_sessions_text, "WLC session UI should preserve VLAN authority and require override reasons")
    require("Find candidate groups" in media_wlc_sessions_text, "WLC session UI should require explicit active-group selection")
    require("I started the WLC capture" in media_wlc_sessions_text and "I confirmed SCP export succeeded" in media_wlc_sessions_text, "WLC session UI should label operator-recorded actions clearly")
    require("Create new investigation" in multicast_page_text and "No multicast investigation is selected" in multicast_page_text, "multicast page should start with an investigation empty state")
    require("collector_scp_password" not in media_wlc_sessions_text and "wlc_password" not in media_wlc_sessions_text, "WLC session UI must not include password fields")
    require("listStudyMediaQoeDnacCaptures" in api_client_text, "API client should expose read-only DNAC/iCAP capture listing")
    require("downloadStudyMediaQoeDnacCapture" in api_client_text and "method: 'POST'" in api_client_text, "API client should expose selected DNAC/iCAP download/register")
    require("getProjectMediaQoeSummary" in api_client_text, "API client should expose media project summary")
    require("listProjectMediaQoeCaptures" in api_client_text, "API client should expose media project captures")
    require("listProjectMediaQoeStreams" in api_client_text, "API client should expose media project streams")
    require("listProjectMediaQoeDuplicates" in api_client_text, "API client should expose media duplicate captures")
    require("listStudyMediaQoeCaptures" in api_client_text, "API client should expose media study captures")
    require("listStudyMediaQoeStreams" in api_client_text, "API client should expose media study streams")
    require("listStudyMediaQoeRawFiles" in api_client_text, "API client should expose media raw file scan")
    require("registerStudyMediaQoeCapture" in api_client_text, "API client should expose media capture registration")
    require("executeMediaQoeCapture" in api_client_text, "API client should expose media capture execution")
    require("listMediaQoeCaptureParseRuns" in api_client_text, "API client should expose media parse-run history")
    require("updateMediaQoeStreamReview" in api_client_text and "method: 'PATCH'" in api_client_text, "API client should expose media stream review PATCH")
    for component_name in (
        "MediaQoeSummary.tsx",
        "MediaCaptureList.tsx",
        "MediaStreamList.tsx",
        "MediaStreamReview.tsx",
        "MediaDuplicateCaptures.tsx",
        "MediaRawFileList.tsx",
        "MediaCaptureExecution.tsx",
        "MediaParseRunList.tsx",
        "MediaExecutionStatus.tsx",
        "MediaCaptureFilters.tsx",
        "MediaStreamFilters.tsx",
        "MediaStreamSeverityBadge.tsx",
        "MediaTriageSummary.tsx",
        "MediaDnacStatus.tsx",
        "MediaDnacCaptureSearch.tsx",
        "MediaDnacCaptureList.tsx",
        "mediaQoeSeverity.ts",
    ):
        require((ROOT / "web" / "study-ui" / "src" / "components" / component_name).is_file(), f"missing Media QoE component {component_name}")
    require("DNAC/iCAP readiness" in media_dnac_status_text, "DNAC status UI should show readiness")
    require("credentials and tokens are never returned" in media_dnac_status_text, "DNAC status UI should not expose credentials")
    require("start unavailable" in media_dnac_status_text and "download enabled" in media_dnac_status_text, "DNAC status UI should show read-only start/download state")
    require("ICAP start-capture" in media_dnac_status_text, "DNAC status UI should label start-capture as unavailable")
    require("Client MAC" in media_dnac_search_text and "Capture type" in media_dnac_search_text, "DNAC capture search should include client and capture type controls")
    require("List Captures" in media_dnac_search_text and "Check API" in media_dnac_search_text, "DNAC capture search should expose read-only check/list actions")
    require("Completed ICAP captures" in media_dnac_list_text, "DNAC capture list should render completed capture inventory")
    require("already_downloaded" in media_dnac_list_text and "already_registered" in media_dnac_list_text and "already_parsed" in media_dnac_list_text, "DNAC capture list should show local/study state")
    require("Download + Register" in media_dnac_list_text, "DNAC capture list should expose Download + Register")
    require("Download + Register + Parse" in media_dnac_list_text, "DNAC capture list should expose chained download/register/parse")
    require("Parse Registered Capture" in media_dnac_list_text, "DNAC capture list should parse registered ICAP captures")
    require("Open Registered Capture" in media_dnac_list_text and "Reparse" in media_dnac_list_text, "DNAC capture list should open or reparse parsed registered captures")
    require("onParseRegistered" in media_dnac_list_text and "onOpenRegistered" in media_dnac_list_text, "DNAC capture list should expose registered-capture actions")
    require("Start Capture" not in media_dnac_list_text and "Start Capture" not in media_dnac_search_text, "DNAC capture controls should not expose active start-capture action")
    require("Scan Raw Directory" in media_raw_file_text, "raw file UI should include scan action")
    require("Register Selected" in media_raw_file_text, "raw file UI should include selected registration")
    require("Register" in media_raw_file_text, "raw file UI should include register action")
    require("Parse" in media_raw_file_text, "raw file UI should include parse action")
    require("Capture Execution History" in media_execution_text, "execution UI should show parse-run history")
    require("Media QoE Execution Guardrails" in media_execution_status_text, "execution status UI should show guardrail status")
    require("archive_enabled" in media_execution_status_text and "raw_dir_readable" in media_execution_status_text, "execution status UI should show archive and raw-dir safety")
    require("parse running" in media_execution_status_text and "Active parse run" in media_execution_status_text, "execution status UI should show active parse lock state")
    require("most_dscp_mismatches" in media_capture_filters_text, "capture filters should include DSCP mismatch sorting")
    require("selectedCaptureOnly" in media_stream_filters_text, "stream filters should support selected-capture filtering")
    require("selectedCaptureFilterActive" in media_stream_filters_text and "Select a capture to filter streams" in media_stream_filters_text, "stream filters should not show selected-capture-only as active without a selected capture")
    require("jitter_warning" in media_stream_filters_text and "interarrival_warning" in media_stream_filters_text, "stream filters should include QoE warning filters")
    require("isTrustedRtpStream" in media_stream_filters_text and "isAdvancedMediaStream" in media_stream_filters_text, "stream filters should expose trusted RTP and advanced stream split helpers")
    require("sortTrustedRtpStreams" in media_stream_filters_text and "loss_ratio" in media_stream_filters_text and "packet_count" in media_stream_filters_text, "trusted RTP streams should have QoE-focused ordering")
    require("measurement_mode').toLowerCase() === 'rtp'" in media_stream_filters_text, "trusted RTP stream split should use measurement_mode rtp")
    require("MEDIA_QOE_THRESHOLDS" in media_severity_helper_text, "stream severity thresholds should be centralized")
    require("getMediaStreamSeverity" in media_severity_helper_text, "stream severity helper should be exported")
    require("getMediaStreamDscpContext" in media_severity_helper_text, "media QoE helper should expose DSCP mismatch context")
    require("Trusted RTP DSCP mismatch" in media_severity_helper_text, "trusted RTP DSCP mismatch label should exist")
    require("Non-RTP DSCP mismatch" in media_severity_helper_text, "non-RTP DSCP mismatch label should exist")
    require("measurementMode === 'rtp'" in media_severity_helper_text, "DSCP context should distinguish trusted RTP from non-RTP streams")
    require("dscp_mismatch" in media_severity_helper_text and "dscpContext.label" in media_severity_helper_text, "stream severity should use contextual DSCP labels")
    require("getCaptureTrustedRtpBadge" in media_severity_helper_text, "capture usefulness helper should expose trusted RTP interpretation")
    require("Trusted RTP found" in media_severity_helper_text and "No trusted RTP detected" in media_severity_helper_text, "capture usefulness helper should expose RTP usefulness labels")
    require("capture.capture_status || '').toLowerCase() !== 'complete'" in media_severity_helper_text and "!isTruthy(capture.parse_success)" in media_severity_helper_text, "capture usefulness helper should only label successful complete parses")
    require("getCaptureUsefulnessSummary" in media_severity_helper_text and "getCaptureConcernBadges" in media_severity_helper_text, "capture usefulness helper should expose summary and concern badges")
    for label in ("Useful RTP capture", "Needs review", "No usable RTP", "Not parsed", "Parse failed"):
        require(label in media_severity_helper_text, f"capture usefulness helper should include {label}")
    for field_name in ("parse_success", "rtp_qoe_stream_count", "capture_status", "trusted_rtp_dscp_mismatch_stream_count", "non_rtp_dscp_mismatch_stream_count", "dscp_mismatch_stream_count", "loss_p95_ratio", "jitter_p95_ms", "interarrival_p95_ms"):
        require(field_name in media_severity_helper_text, f"capture usefulness helper should consider {field_name}")
    for label in ("Trusted RTP DSCP mismatch found", "Only non-RTP DSCP mismatch found", "DSCP mismatch present"):
        require(label in media_severity_helper_text, f"capture usefulness helper should include {label}")
    require(
        media_severity_helper_text.find("trustedRtpDscpMismatchStreamCount > 0")
        < media_severity_helper_text.find("nonRtpDscpMismatchStreamCount > 0")
        < media_severity_helper_text.find("dscpMismatchStreamCount > 0"),
        "capture DSCP badges should prefer trusted RTP split, then non-RTP split, then aggregate fallback",
    )
    require("status === 'failed'" in media_severity_helper_text and "parseExitCode !== null && parseExitCode !== 0" in media_severity_helper_text, "capture usefulness helper should detect failed parses before no-RTP cases")
    require("trustedRtpCount <= 0" in media_severity_helper_text and "getCaptureConcernBadges(capture).length" in media_severity_helper_text, "capture usefulness helper should gate no-RTP and needs-review summaries")
    require("getMediaStreamSeverity" in media_severity_text, "severity badge should render computed severity")
    require("Unreviewed streams" in media_triage_summary_text and "Timing warnings" in media_triage_summary_text, "triage summary should expose operator counters")
    require("Accept as Vocera RTP" in media_stream_review_text, "stream review should include one-click Vocera RTP triage")
    require("Mark server -&gt; badge" in media_stream_review_text, "stream review should include server-to-badge quick action")
    require("Exclude as noise" in media_stream_review_text, "stream review should include noise exclusion quick action")
    require("MediaStreamSeverityBadge" in media_stream_list_text and "selectedStreamKey" in media_stream_list_text, "stream list should show severity and selection")
    require("DSCP context" in media_stream_list_text and "No DSCP mismatch" in media_stream_list_text, "stream list should render contextual DSCP mismatch wording")
    require("getMediaStreamDscpContext" in media_stream_list_text, "stream list should use DSCP context helper")
    require("getCaptureTrustedRtpBadge" in media_capture_list_text, "capture cards should show trusted RTP usefulness badges")
    require("getCaptureTrustedRtpBadge" in media_dnac_list_text, "DNAC capture rows should show trusted RTP usefulness badges")
    require("getCaptureTrustedRtpBadge" in media_raw_file_text, "raw file rows should show trusted RTP usefulness badges")
    require("getCaptureUsefulnessSummary" in media_capture_list_text and "getCaptureConcernBadges" in media_capture_list_text, "capture cards should show usefulness summary and concerns")
    require("getCaptureUsefulnessSummary" in media_dnac_list_text and "getCaptureConcernBadges" in media_dnac_list_text, "DNAC capture rows should show usefulness summary and concerns")
    require("getCaptureUsefulnessSummary" in media_raw_file_text and "getCaptureConcernBadges" in media_raw_file_text, "raw capture rows should show usefulness summary and concerns")
    require("Source identity hash" in media_capture_list_text and "Source SHA256" not in media_capture_list_text, "capture UI should not call identity hash a content SHA256")
    require("Source identity hash" in media_duplicate_text and "Source SHA256" not in media_duplicate_text, "duplicate UI should not call identity hash a content SHA256")
    require("Advanced logs" in media_parse_run_text and "Parser message" in media_parse_run_text, "parse run UI should collapse raw logs")
    require("MediaRawFileList" in media_page_text, "Media QoE page should render raw file list")
    require("MediaCaptureExecution" in media_page_text, "Media QoE page should render execution history")
    require("MediaExecutionStatus" in media_page_text, "Media QoE page should render execution guardrails")
    require("Catalyst Center ICAP" in media_page_text, "Media QoE page should render ICAP capture source section")
    require("MediaDnacStatus" in media_page_text and "MediaDnacCaptureSearch" in media_page_text and "MediaDnacCaptureList" in media_page_text, "Media QoE page should render DNAC/iCAP status, search, and list components")
    require("downloadStudyMediaQoeDnacCapture" in media_page_text and "refreshRawFiles" in media_page_text and "refreshDnacCaptures" in media_page_text, "Media QoE page should refresh DNAC/raw/capture state after download/register")
    require("parseAfterRegister" in media_page_text and "executeMediaQoeCapture" in media_page_text, "Media QoE page should chain DNAC download/register into existing parser execution")
    require("parseRegisteredDnacCapture" in media_page_text and "openRegisteredDnacCapture" in media_page_text, "Media QoE page should expose registered ICAP capture parse/open actions")
    require("MediaCaptureFilters" in media_page_text, "Media QoE page should render capture filters")
    require("MediaStreamFilters" in media_page_text, "Media QoE page should render stream filters")
    require("MediaTriageSummary" in media_page_text, "Media QoE page should render triage summary")
    require("Trusted RTP Streams" in media_page_text and "Advanced Streams" in media_page_text, "Media QoE page should split trusted RTP and advanced streams")
    require("trustedRtpStudyStreams" in media_page_text and "advancedStudyStreams" in media_page_text, "Media QoE page should derive split stream lists")
    require("No trusted RTP streams found for the selected capture" in media_page_text, "Media QoE page should explain empty trusted RTP captures")
    require("Rejected candidates, UDP timing, unknown UDP, and control/noise rows" in media_page_text and "defaultOpen={false}" in media_page_text, "advanced streams should be secondary and collapsed by default")
    for variable_name in ("capture_id", "stream_id", "src_ip", "dst_ip", "measurement_mode", "direction"):
        require(variable_name in media_page_text, f"Media Grafana variables should include {variable_name}")
    require("executeMediaQoeCapture" in media_page_text, "Media QoE page should trigger capture execution")
    require("configuredMediaGrafanaPanels.map" in media_page_text, "Media QoE page should render multiple Grafana panels")
    require("mediaQoeCaptureInventory" in media_page_text and "mediaQoeRtpTrouble" in media_page_text, "Media QoE page should include Phase 6 Grafana panels")
    require("MEDIA_QOE_CAPTURE_INVENTORY" in fastapi_text and "MEDIA_QOE_RTP_TROUBLE" in fastapi_text, "Study Web should expose Phase 6 Media QoE Grafana panel config")
    require("--study-id" in batch_text and "VOCERA_MEDIA_QOE_STUDY_ID" in batch_text, "batch parser should support selected study import")
    require("--skip-install-db" in batch_text and "VOCERA_MEDIA_QOE_INSTALL_DB" in batch_text, "batch parser should support skipping DB install during web parse")
    require("study_id: str | None" in history_text and "_capture_insert(payload, study_id=study_id)" in history_text, "SQL importer should apply selected study_id")

    survey_script = (ROOT / "scripts" / "run_vocera_survey_refresh.sh").read_text(encoding="utf-8")
    windows_script = (
        ROOT / "scripts" / "vocera_rf_validation" / "windows" / "Sync-RfValidationDataAndRun.ps1"
    ).read_text(encoding="utf-8")
    require("delete_uploaded_pcaps_for_device" in survey_script, "uploaded PCAP cleanup is missing")
    require("VOCERA_SURVEY_MEDIA_DELETE_UPLOADED_PCAPS" in survey_script, "uploaded PCAP cleanup toggle is missing")
    require("VOCERA_SURVEY_MEDIA_STUDY_ACTION" not in survey_script, "server script should not accept laptop study action env")
    require("MediaStudyAction" not in windows_script, "Windows upload script should not own study lifecycle")

    for dashboard_path in (
        ROOT / "grafana" / "dashboards-prod" / "Platform - Wireless RF" / "vocera-media-pcap-qoe__vocera_media_pcap_qoe.json",
        ROOT / "grafana" / "dashboards-dev" / "Platform - Wireless RF" / "vocera-media-pcap-qoe__vocera_media_pcap_qoe.json",
    ):
        require(
            not dashboard_path.exists(),
            "Media QoE Grafana dashboard should be retired from the final two-dashboard inventory",
        )


def test_dnac_icap_capture_selection_and_filename() -> None:
    """Verify Catalyst Center ICAP helper selects and names client captures."""

    captures = icap.iter_capture_files(
        {
            "response": [
                {
                    "id": "old_full_capture",
                    "fileName": "old-full.pcap",
                    "type": "FULL",
                    "clientMac": "00:09:ef:54:5f:46",
                    "fileCreationTimestamp": 1000,
                },
                {
                    "id": "new_full_capture",
                    "fileName": "new full capture.pcap",
                    "type": "FULL",
                    "clientMac": "0009ef545f46",
                    "fileCreationTimestamp": 2000,
                },
                {
                    "id": "other_client",
                    "fileName": "other.pcap",
                    "type": "FULL",
                    "clientMac": "00:09:ef:54:5f:47",
                    "fileCreationTimestamp": 3000,
                },
            ]
        }
    )
    selected = icap.select_latest_capture(
        icap.filter_capture_files(captures, client_mac="00-09-ef-54-5f-46"),
    )
    require(selected is not None, "expected a selected ICAP capture")
    require(selected["id"] == "new_full_capture", f"wrong ICAP capture selected: {selected}")
    require(
        icap.capture_download_ids(selected) == ["new_full_capture", "new full capture.pcap"],
        f"bad download id candidates: {icap.capture_download_ids(selected)}",
    )
    filename = icap.capture_filename(selected, client_mac="00:09:ef:54:5f:46", capture_type="FULL")
    require(filename.endswith(".pcap"), f"missing pcap suffix: {filename}")
    require("0009ef545f46" in filename, f"filename should include client MAC token: {filename}")
    require(" " not in filename, f"filename should be path-safe: {filename}")


def test_dnac_icap_env_file_defaults() -> None:
    """Verify EnvironmentFile parsing does not perform shell expansion."""

    path = Path(tempfile.NamedTemporaryFile(prefix="vocera-icap-env-", delete=False).name)
    path.write_text(
        "\n".join(
            [
                "DNAC_BASE_URL=https://dnac.example.org",
                "DNAC_USERNAME=api-user",
                "DNAC_PASSWORD='p@ss$word#literal'",
                "VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46",
                "VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES=30",
            ]
        ),
        encoding="utf-8",
    )
    values = icap.load_env_file(str(path))
    require(values["DNAC_PASSWORD"] == "p@ss$word#literal", f"bad password parse: {values['DNAC_PASSWORD']}")

    class Args:
        env_file = str(path)
        base_url = None
        username = None
        client_mac = None
        ap_mac = None
        capture_type = None
        wlc_id = None
        ap_id = None
        post_capture_buffer_seconds = None
        lookback_minutes = None
        limit = None
        out_dir = None
        parsed_dir = None
        insecure = False

    setattr(Args, "pass" + "word", None)
    args = Args()
    saved_env = {
        name: os.environ.pop(name, None)
        for name in (
            "DNAC_BASE_URL",
            "DNAC_USERNAME",
            "DNAC_PASSWORD",
            "VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC",
            "VOCERA_MEDIA_QOE_DNAC_LOOKBACK_MINUTES",
        )
    }
    try:
        icap.apply_env_defaults(args, values)  # type: ignore[arg-type]
    finally:
        for name, value in saved_env.items():
            if value is not None:
                os.environ[name] = value
    require(args.base_url == "https://dnac.example.org", f"bad base URL default: {args.base_url}")
    require(args.client_mac == "00:09:ef:54:5f:46", f"bad client MAC default: {args.client_mac}")
    require(args.lookback_minutes == 30, f"bad lookback default: {args.lookback_minutes}")


def test_dnac_icap_zero_lookback_omits_time_filters() -> None:
    """Verify zero lookback disables ICAP API time filtering."""

    class Args:
        start_time_ms = None
        end_time_ms = None
        lookback_minutes = 0

    require(icap.resolve_time_filters(Args()) == (None, None), "zero lookback should omit ICAP time filters")


def test_dnac_icap_resolves_capture_ids_from_client_detail() -> None:
    """Verify AP and WLC UUIDs are resolved from Catalyst Center client detail."""

    payload = {
        "connectionInfo": {
            "nwDeviceName": "SFB-TSG",
            "nwDeviceMac": "50:5C:88:00:CE:A0",
        },
        "detail": {
            "wlcUuid": "876c2887-037b-40c8-8d8f-8753e2b58cca",
            "wlcName": "SRHC-WLC-40G-SEC.srhc.net",
            "connectedDevice": [
                {
                    "id": "3876644e-5012-4c41-8f07-576feaf40d5c",
                    "name": "SFB-TSG",
                    "type": "AP",
                }
            ],
        },
    }
    resolved = icap.resolve_capture_ids(payload)
    require(resolved["ap_id"] == "3876644e-5012-4c41-8f07-576feaf40d5c", f"bad AP id: {resolved}")
    require(resolved["wlc_id"] == "876c2887-037b-40c8-8d8f-8753e2b58cca", f"bad WLC id: {resolved}")
    require(resolved["ap_name"] == "SFB-TSG", f"bad AP name: {resolved}")


def test_dnac_icap_readiness_checks_read_download_paths() -> None:
    """Verify ICAP readiness checks only client-detail and capture-file list."""

    class FakeClient:
        """Minimal Catalyst Center client stub for ICAP readiness checks."""

        def __init__(self) -> None:
            """Track read/download readiness calls."""

            self.calls: list[str] = []

        def get_client_detail(self, mac_address: str) -> dict:
            """Return enough client detail for the readiness check."""

            self.calls.append(f"get_client_detail:{mac_address}")
            return {"detail": {"wlcUuid": "wlc-1"}}

        def list_icap_capture_files(self, *args, **kwargs) -> dict:
            """Return an empty capture-file page."""

            self.calls.append("list_icap_capture_files")
            return {"response": []}

    class Args:
        client_mac = "00:09:ef:54:5f:46"
        start_time_ms = None
        end_time_ms = None
        lookback_minutes = 60
        capture_type = "FULL"

    client = FakeClient()
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = icap.check_api_readiness(client, Args())  # type: ignore[arg-type]

    payload = json.loads(stdout.getvalue())
    check_names = [item["name"] for item in payload["checks"]]
    require(rc == 0, f"readiness should pass when read/download checks work: {payload}")
    require(check_names == ["client_detail", "icap_capture_files"], f"unexpected readiness checks: {check_names}")
    require(payload["icap_download_ready"] is True, f"download readiness should be true: {payload}")
    require(payload["start_capture_available"] is False, f"start capture should be unavailable: {payload}")
    require(client.calls == ["get_client_detail:00:09:ef:54:5f:46", "list_icap_capture_files"], f"bad readiness calls: {client.calls}")


def test_dnac_icap_study_membership_check() -> None:
    """Verify capture_in_study detects captures already parsed into parsed_dir."""

    with tempfile.TemporaryDirectory() as tmp:
        parsed_dir = Path(tmp)

        capture_a = {"id": "cap-abc123", "fileName": "full-abc123.pcap"}
        capture_b = {"id": "cap-xyz789", "fileName": "full-xyz789.pcap"}

        # Empty parsed_dir: neither capture is in the study.
        require(not icap.capture_in_study(capture_a, parsed_dir), "empty study should not contain capture_a")
        require(not icap.capture_in_study(capture_b, parsed_dir), "empty study should not contain capture_b")

        # Write a cache JSON for capture_a as the batch publisher would.
        cache_json = {
            "source_pcap": {
                "dnac_metadata": {
                    "downloaded_at_seconds": 1000,
                    "capture": {"id": "cap-abc123", "fileName": "full-abc123.pcap"},
                }
            }
        }
        (parsed_dir / "full-abc123.pcap.abcdef01.json").write_text(json.dumps(cache_json), encoding="utf-8")

        # capture_a is now in the study; capture_b is not.
        require(icap.capture_in_study(capture_a, parsed_dir), "capture_a should be in study after cache written")
        require(not icap.capture_in_study(capture_b, parsed_dir), "capture_b should still not be in study")

        # Matching on fileName alone (id missing from cache) should also work.
        require(
            icap.capture_in_study({"fileName": "full-abc123.pcap"}, parsed_dir),
            "capture_in_study should match on fileName when id absent",
        )

        # A cache JSON with no dnac_metadata should be ignored safely.
        (parsed_dir / "no-meta.json").write_text(json.dumps({"source_pcap": {"path": "/raw/x.pcap"}}), encoding="utf-8")
        require(not icap.capture_in_study(capture_b, parsed_dir), "malformed cache should not affect study lookup")


def test_dnac_icap_study_check_skips_download() -> None:
    """Verify command_download exits 0 when the capture is already in the study."""

    with tempfile.TemporaryDirectory() as tmp:
        parsed_dir = Path(tmp) / "captures"
        parsed_dir.mkdir()
        raw_dir = Path(tmp) / "raw"
        raw_dir.mkdir()

        # Pre-populate the study with the capture that DNAC would return.
        cache_json = {
            "source_pcap": {
                "dnac_metadata": {
                    "downloaded_at_seconds": 1000,
                    "capture": {"id": "existing-cap", "fileName": "existing.pcap"},
                }
            }
        }
        (parsed_dir / "existing.pcap.deadbeef.json").write_text(json.dumps(cache_json), encoding="utf-8")

        class FakeClient:
            """Stub client that returns one ICAP capture matching the study entry."""

            def list_icap_capture_files(self, *args, **kwargs) -> dict:
                return {
                    "response": [
                        {"id": "existing-cap", "fileName": "existing.pcap", "clientMac": "00:09:ef:11:22:33", "fileCreationTimestamp": 5000},
                    ]
                }

        import unittest.mock as mock

        with mock.patch("vocera_dnac_icap.CatalystCenterIcapReadClient", return_value=FakeClient()):
            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                rc = icap.command_download(
                    _make_icap_args(
                        client_mac="00:09:ef:11:22:33",
                        out_dir=str(raw_dir),
                        parsed_dir=str(parsed_dir),
                    )
                )

        require(rc == 0, f"expected exit 0 for already-in-study capture, got {rc}")
        require("already in the study" in stderr.getvalue(), f"expected study-skip message, got: {stderr.getvalue()!r}")
        downloaded = list(raw_dir.glob("*.pcap"))
        require(len(downloaded) == 0, f"no pcap should be downloaded when capture is in study: {downloaded}")


def _make_icap_args(**overrides):
    """Build a minimal args namespace for command_download tests."""

    class Args:
        base_url = "https://dnac.example.org"
        username = "user"
        capture_type = "FULL"
        ap_mac = None
        wlc_id = None
        ap_id = None
        check_api = False
        lookback_minutes = 0
        start_time_ms = None
        end_time_ms = None
        limit = 20
        offset = 1
        metadata_out = None
        allow_empty = False
        force = False
        print_path_only = False
        parsed_dir = None
        insecure = False
        env_file = None

        def __init__(self, **kw):
            setattr(self, "pass" + "word", "pw")
            for k, v in kw.items():
                setattr(self, k, v)
            if not hasattr(self, "client_mac"):
                self.client_mac = "00:09:ef:11:22:33"
            if not hasattr(self, "out_dir"):
                self.out_dir = "/tmp"

    return Args(**overrides)


def main() -> int:
    """Run the standalone Vocera media QoE tests."""

    test_rtp_jitter_loss_duplicate_and_out_of_order()
    test_control_test_device_labels()
    test_device_label_falls_back_to_source_mac()
    test_rtp_unknown_clock_rate_is_visible()
    test_strict_plausibility_accepts_clean_rtp()
    test_strict_plausibility_rejects_random_rtp_lookalike()
    test_rtp_debug_cli_output()
    test_rtp_loss_detection()
    test_sparse_rtp_candidate_does_not_emit_qoe()
    test_large_rtp_sequence_jump_is_not_counted_as_loss()
    test_large_rtp_timestamp_jump_does_not_poison_jitter()
    test_udp_interarrival_only()
    test_future_packet_timestamps_are_quarantined()
    test_radiotap_80211_udp()
    test_pcapng_udp()
    test_truncated_pcap_record_rejected()
    test_batch_publisher_parses_only_new_captures()
    test_batch_rejects_dnac_size_mismatch_and_emits_history_sql()
    test_media_study_sql_contract()
    test_dnac_icap_capture_selection_and_filename()
    test_dnac_icap_env_file_defaults()
    test_dnac_icap_zero_lookback_omits_time_filters()
    test_dnac_icap_resolves_capture_ids_from_client_detail()
    test_dnac_icap_readiness_checks_read_download_paths()
    test_dnac_icap_study_membership_check()
    test_dnac_icap_study_check_skips_download()
    print("OK: vocera media QoE parser tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
