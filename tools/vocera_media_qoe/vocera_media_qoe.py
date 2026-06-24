#!/usr/bin/env python3
"""Offline Vocera media QoE analyzer for pcap files.

The collector intentionally reports low-cardinality Prometheus snapshot gauges.
Per-stream identifiers such as IPs, ports, SSRC, and stream IDs are written only
to the JSON summary.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import math
import os
import re
import statistics
import struct
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from run_archive import create_run_archive

try:
    from tools.common.config import load_mapping_config
    from tools.common.files import write_text
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.common.config import load_mapping_config
    from tools.common.files import write_text


PCAP_MAGIC = {
    b"\xa1\xb2\xc3\xd4": (">", 1_000_000),
    b"\xd4\xc3\xb2\xa1": ("<", 1_000_000),
    b"\xa1\xb2\x3c\x4d": (">", 1_000_000_000),
    b"\x4d\x3c\xb2\xa1": ("<", 1_000_000_000),
}
PCAPNG_MAGIC = b"\x0a\x0d\x0d\x0a"
PCAPNG_BYTE_ORDER_MAGIC = {
    b"\x1a\x2b\x3c\x4d": ">",
    b"\x4d\x3c\x2b\x1a": "<",
}
PCAPNG_SECTION_HEADER_BLOCK = 0x0A0D0D0A
PCAPNG_INTERFACE_DESCRIPTION_BLOCK = 0x00000001
PCAPNG_ENHANCED_PACKET_BLOCK = 0x00000006
PCAPNG_IF_TSRESOL_OPTION = 9
ETHERNET_LINKTYPE = 1
IEEE802_11_RADIOTAP_LINKTYPE = 127
VLAN_ETHERTYPES = {0x8100, 0x88A8, 0x9100}
IPV4_ETHERTYPE = 0x0800
UDP_PROTOCOL = 17
DEFAULT_RTP_CLOCK_HZ = 8000
DEFAULT_MAX_CAPTURE_FUTURE_SKEW_SECONDS = 300.0
DEFAULT_MIN_RTP_QOE_PACKETS = 20
DEFAULT_MAX_RTP_TRANSIT_DELTA_SECONDS = 1.0
DEFAULT_MIN_RTP_DURATION_SECONDS = 0.25
DEFAULT_MAX_RTP_INTERARRIVAL_MS = 500.0
DEFAULT_MAX_RTP_JITTER_MS = 500.0
DEFAULT_MIN_RTP_SEQUENCE_PROGRESSION_RATIO = 0.80
DEFAULT_MIN_RTP_TIMESTAMP_PROGRESSION_RATIO = 0.80
DEFAULT_MAX_RTP_TIMESTAMP_WALLCLOCK_ERROR_MS = 250.0
DEFAULT_MIN_VOICE_PACKETIZATION_MS = 5.0
DEFAULT_MAX_VOICE_PACKETIZATION_MS = 100.0
DEFAULT_MAX_RTP_LOSS_RATIO_FOR_PLAUSIBILITY = 0.50
DEFAULT_MAX_RTP_DUPLICATE_RATIO_FOR_PLAUSIBILITY = 0.50
DEFAULT_MAX_RTP_OUT_OF_ORDER_RATIO_FOR_PLAUSIBILITY = 0.50
DEFAULT_RTP_DEBUG_PACKET_LIMIT = 20
RTP_SEQ_MOD = 65536
RTP_MAX_DROPOUT = 3000
RTP_MAX_MISORDER = 100
RTP_TS_MOD = 2 ** 32
RTP_TS_HALF_MOD = 2 ** 31
ANALYZER_CACHE_VERSION = 6
LLC_SNAP_HEADER_LEN = 8
UNMAPPED_DEVICE_NAME = "unmapped"
UNMAPPED_DEVICE_ROLE = "unmapped"
UNMAPPED_DEVICE_CONFIG = "unmapped"


@dataclass(frozen=True)
class UdpPacket:
    """One UDP packet parsed from a pcap record."""

    arrival_time: float
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    dscp: int
    payload: bytes
    udp_length: int
    orig_len: int


@dataclass(frozen=True)
class RtpHeader:
    """Visible RTP header fields required for receiver-side QoE math."""

    payload_type: int
    marker: int
    sequence: int
    timestamp: int
    ssrc: int
    header_len: int


@dataclass(frozen=True)
class DeviceProfile:
    """Configured control/test endpoint metadata for comparison reporting."""

    name: str
    role: str
    config: str
    ip: str
    mac: str | None = None


@dataclass
class AnalyzerConfig:
    """Site-specific classification and labeling settings."""

    site: str = "unknown"
    capture_point: str = "unknown"
    expected_dscp: int | None = None
    servers: dict[str, str] = field(default_factory=dict)
    badge_subnets: list[ipaddress._BaseNetwork] = field(default_factory=list)
    devices: dict[str, DeviceProfile] = field(default_factory=dict)
    media_ports: list[tuple[int, int]] = field(default_factory=list)
    payload_clock_rates: dict[int, int] = field(default_factory=dict)
    default_rtp_clock_hz: int = DEFAULT_RTP_CLOCK_HZ
    max_capture_future_skew_seconds: float = DEFAULT_MAX_CAPTURE_FUTURE_SKEW_SECONDS
    min_rtp_qoe_packets: int = DEFAULT_MIN_RTP_QOE_PACKETS
    max_rtp_transit_delta_seconds: float = DEFAULT_MAX_RTP_TRANSIT_DELTA_SECONDS
    strict_rtp_plausibility: bool = True
    require_known_rtp_clock_rate: bool = False
    min_rtp_duration_seconds: float = DEFAULT_MIN_RTP_DURATION_SECONDS
    max_rtp_interarrival_ms: float = DEFAULT_MAX_RTP_INTERARRIVAL_MS
    max_rtp_jitter_ms: float = DEFAULT_MAX_RTP_JITTER_MS
    min_rtp_sequence_progression_ratio: float = DEFAULT_MIN_RTP_SEQUENCE_PROGRESSION_RATIO
    min_rtp_timestamp_progression_ratio: float = DEFAULT_MIN_RTP_TIMESTAMP_PROGRESSION_RATIO
    max_rtp_timestamp_wallclock_error_ms: float = DEFAULT_MAX_RTP_TIMESTAMP_WALLCLOCK_ERROR_MS
    min_voice_packetization_ms: float = DEFAULT_MIN_VOICE_PACKETIZATION_MS
    max_voice_packetization_ms: float = DEFAULT_MAX_VOICE_PACKETIZATION_MS
    max_rtp_loss_ratio_for_plausibility: float = DEFAULT_MAX_RTP_LOSS_RATIO_FOR_PLAUSIBILITY
    max_rtp_duplicate_ratio_for_plausibility: float = DEFAULT_MAX_RTP_DUPLICATE_RATIO_FOR_PLAUSIBILITY
    max_rtp_out_of_order_ratio_for_plausibility: float = DEFAULT_MAX_RTP_OUT_OF_ORDER_RATIO_FOR_PLAUSIBILITY
    rtp_debug_packet_limit: int = DEFAULT_RTP_DEBUG_PACKET_LIMIT

    def server_name_for(self, ip: str) -> str | None:
        """Return the configured server label for an IP, if any."""
        for name, server_ip in self.servers.items():
            if ip == server_ip:
                return name
        return None

    def role_for(self, ip: str) -> str:
        """Classify an IP as server, badge, or unknown."""
        if self.server_name_for(ip):
            return "server"
        address = ipaddress.ip_address(ip)
        if any(address in subnet for subnet in self.badge_subnets):
            return "badge"
        return "unknown"

    def device_profile_for(self, ip: str) -> DeviceProfile | None:
        """Return configured comparison metadata for an endpoint IP, if any."""
        try:
            key = str(ipaddress.ip_address(ip))
        except ValueError:
            key = ip
        return self.devices.get(key)

    def device_profile_for_source_mac(self, value: str) -> DeviceProfile | None:
        """Return configured comparison metadata when source text contains a known MAC."""
        path_mac_text = normalize_mac_hex(value)
        if not path_mac_text:
            return None
        for device in self.devices.values():
            if device.mac and normalize_mac_hex(device.mac) in path_mac_text:
                return device
        return None

    def media_port_matches(self, src_port: int, dst_port: int) -> bool:
        """Return whether either UDP port is in a configured media range."""
        if not self.media_ports:
            return True
        for start, end in self.media_ports:
            if start <= src_port <= end or start <= dst_port <= end:
                return True
        return False

    def rtp_clock_rate(self, payload_type: int) -> tuple[int, bool]:
        """Return (clock_rate_hz, known) where `known` is False when the
        payload type isn't in `payload_clock_rates` and the fallback default
        was used. Operators should treat jitter for unknown-clock streams as
        suspect — a wideband 16 kHz codec on the 8 kHz default reports 2x
        true jitter."""
        if payload_type in self.payload_clock_rates:
            return self.payload_clock_rates[payload_type], True
        return self.default_rtp_clock_hz, False


@dataclass(frozen=True)
class StreamIdentity:
    """High-cardinality stream identity for JSON only."""

    src_ip: str
    src_port: int
    dst_ip: str
    dst_port: int
    ssrc: int | None = None
    payload_type: int | None = None

    @property
    def stream_id(self) -> str:
        """Return a stable high-cardinality stream id for JSON output."""
        parts = [self.src_ip, str(self.src_port), self.dst_ip, str(self.dst_port)]
        if self.ssrc is not None:
            parts.extend([f"ssrc-{self.ssrc:08x}", f"pt-{self.payload_type}"])
        return "_".join(parts)


@dataclass
class RtpPlausibilityResult:
    """RTP stream sanity-check result and bounded diagnostics."""

    is_plausible: bool
    reasons: list[str] = field(default_factory=list)
    packet_count: int = 0
    duration_seconds: float | None = None
    sequence_progression_ratio: float | None = None
    timestamp_progression_ratio: float | None = None
    timestamp_wallclock_error_ms: float | None = None
    interarrival_p50_ms: float | None = None
    interarrival_p95_ms: float | None = None
    interarrival_max_ms: float | None = None
    estimated_packetization_ms: float | None = None
    loss_ratio: float | None = None
    duplicate_ratio: float | None = None
    out_of_order_ratio: float | None = None
    jitter_ms: float | None = None
    clock_rate_known: bool = True
    debug_packets: list[dict[str, float | int | None]] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """Serialize plausibility details for JSON/debug output."""

        return {
            "is_plausible": self.is_plausible,
            "reasons": list(self.reasons),
            "packet_count": self.packet_count,
            "duration_seconds": self.duration_seconds,
            "sequence_progression_ratio": self.sequence_progression_ratio,
            "timestamp_progression_ratio": self.timestamp_progression_ratio,
            "timestamp_wallclock_error_ms": self.timestamp_wallclock_error_ms,
            "interarrival_p50_ms": self.interarrival_p50_ms,
            "interarrival_p95_ms": self.interarrival_p95_ms,
            "interarrival_max_ms": self.interarrival_max_ms,
            "estimated_packetization_ms": self.estimated_packetization_ms,
            "loss_ratio": self.loss_ratio,
            "duplicate_ratio": self.duplicate_ratio,
            "out_of_order_ratio": self.out_of_order_ratio,
            "jitter_ms": self.jitter_ms,
            "clock_rate_known": self.clock_rate_known,
        }


@dataclass
class StreamStats:
    """Per-stream analysis result."""

    identity: StreamIdentity
    measurement_mode: str
    src_role: str
    dst_role: str
    device_name: str
    device_role: str
    device_config: str
    peer_device_name: str
    peer_device_role: str
    peer_device_config: str
    direction: str
    server: str
    site: str
    capture_point: str
    dscp: int
    packet_count: int
    byte_count: int
    first_seen: float
    last_seen: float
    payload_type: int | None = None
    expected_packets: int | None = None
    lost_packets: int | None = None
    loss_ratio: float | None = None
    duplicate_packets: int = 0
    out_of_order_packets: int = 0
    jitter_ms: float | None = None
    interarrival_p50_ms: float | None = None
    interarrival_p95_ms: float | None = None
    interarrival_max_ms: float | None = None
    packet_rate_pps: float | None = None
    dscp_mismatch: bool = False
    clock_rate_known: bool = True
    rtp_plausibility: RtpPlausibilityResult | None = None
    rtp_rejection_reasons: list[str] = field(default_factory=list)

    def prometheus_labels(self) -> dict[str, str]:
        """Return the low-cardinality label set used for Prometheus output."""
        return {
            "server": self.server,
            "site": self.site,
            "capture_point": self.capture_point,
            "direction": self.direction,
            "src_role": self.src_role,
            "dst_role": self.dst_role,
            "device_role": self.device_role,
            "device_config": self.device_config,
            "payload_type": str(self.payload_type) if self.payload_type is not None else "unknown",
            "dscp": str(self.dscp),
            "measurement_mode": self.measurement_mode,
        }

    def to_json(self) -> dict[str, Any]:
        """Serialize stream stats with high-cardinality identity details."""
        return {
            "src_ip": self.identity.src_ip,
            "src_port": self.identity.src_port,
            "dst_ip": self.identity.dst_ip,
            "dst_port": self.identity.dst_port,
            "ssrc": f"{self.identity.ssrc:08x}" if self.identity.ssrc is not None else None,
            "stream_id": self.identity.stream_id,
            "measurement_mode": self.measurement_mode,
            "src_role": self.src_role,
            "dst_role": self.dst_role,
            "device_name": self.device_name,
            "device_role": self.device_role,
            "device_config": self.device_config,
            "peer_device_name": self.peer_device_name,
            "peer_device_role": self.peer_device_role,
            "peer_device_config": self.peer_device_config,
            "direction": self.direction,
            "server": self.server,
            "site": self.site,
            "capture_point": self.capture_point,
            "payload_type": self.payload_type,
            "dscp": self.dscp,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "packet_count": self.packet_count,
            "byte_count": self.byte_count,
            "expected_packets": self.expected_packets,
            "lost_packets": self.lost_packets,
            "loss_ratio": self.loss_ratio,
            "duplicate_packets": self.duplicate_packets,
            "out_of_order_packets": self.out_of_order_packets,
            "jitter_ms": self.jitter_ms,
            "interarrival_p50_ms": self.interarrival_p50_ms,
            "interarrival_p95_ms": self.interarrival_p95_ms,
            "interarrival_max_ms": self.interarrival_max_ms,
            "packet_rate_pps": self.packet_rate_pps,
            "dscp_mismatch": self.dscp_mismatch,
            "clock_rate_known": self.clock_rate_known,
            "rtp_rejection_reasons": self.rtp_rejection_reasons,
            "rtp_plausibility": self.rtp_plausibility.to_json() if self.rtp_plausibility else None,
        }


@dataclass
class AnalysisResult:
    """Whole-pcap analysis result."""

    streams: list[StreamStats]
    packets_read: int
    udp_packets_seen: int
    last_capture_timestamp_seconds: float | None
    parse_success: int
    error: str = ""
    timestamp_outlier_packets: int = 0

    def to_json(self) -> dict[str, Any]:
        """Serialize the whole-pcap analysis result."""
        return {
            "packets_read": self.packets_read,
            "udp_packets_seen": self.udp_packets_seen,
            "last_capture_timestamp_seconds": self.last_capture_timestamp_seconds,
            "parse_success": self.parse_success,
            "error": self.error,
            "timestamp_outlier_packets": self.timestamp_outlier_packets,
            "streams": [stream.to_json() for stream in self.streams],
        }

    def to_rtp_debug_json(self) -> dict[str, Any]:
        """Serialize high-cardinality RTP candidate packet diagnostics."""

        candidates = []
        for stream in self.streams:
            if stream.rtp_plausibility is None:
                continue
            candidates.append(
                {
                    "stream_id": stream.identity.stream_id,
                    "src_ip": stream.identity.src_ip,
                    "src_port": stream.identity.src_port,
                    "dst_ip": stream.identity.dst_ip,
                    "dst_port": stream.identity.dst_port,
                    "ssrc": f"{stream.identity.ssrc:08x}" if stream.identity.ssrc is not None else None,
                    "payload_type": stream.payload_type,
                    "measurement_mode": stream.measurement_mode,
                    "rtp_rejection_reasons": stream.rtp_rejection_reasons,
                    "rtp_plausibility": stream.rtp_plausibility.to_json(),
                    "packets": stream.rtp_plausibility.debug_packets,
                }
            )
        return {
            "candidate_count": len(candidates),
            "candidates": candidates,
        }


def percentile(values: list[float], q: float) -> float | None:
    """Return nearest-rank percentile for a small window."""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def parse_port_range(value: object) -> tuple[int, int]:
    """Parse a single UDP port or inclusive port range."""
    text = str(value).strip()
    if "-" in text:
        start_text, end_text = text.split("-", 1)
        start = int(start_text)
        end = int(end_text)
    else:
        start = end = int(text)
    if not (0 <= start <= end <= 65535):
        raise ValueError(f"invalid UDP port range: {value!r}")
    return start, end


def _env_or_value(payload: Mapping[str, Any], key: str) -> Any:
    """Read a config value directly or from the named environment variable."""
    env_name = payload.get(f"{key}_env")
    if env_name:
        return os.environ.get(str(env_name))
    return payload.get(key)


def _comparison_label(value: Any, default: str) -> str:
    """Normalize a dashboard comparison label into a stable simple token."""
    text = str(value or default).strip().lower().replace(" ", "_")
    return text or default


def normalize_mac_hex(value: object) -> str:
    """Collapse MAC-ish text to lowercase hex for source-path matching."""
    return re.sub(r"[^0-9a-f]", "", str(value or "").lower())


def load_config(path: str | Path | None) -> AnalyzerConfig:
    """Load an optional YAML/JSON config file."""

    if not path:
        return AnalyzerConfig()
    payload = load_mapping_config(path, description="Vocera media QoE config")
    return config_from_mapping(payload)


def config_from_mapping(payload: Mapping[str, Any]) -> AnalyzerConfig:
    """Build analyzer config from a Python mapping."""

    servers: dict[str, str] = {}
    for item in payload.get("servers") or []:
        if not isinstance(item, Mapping):
            continue
        name = str(item.get("name") or item.get("ip") or "server")
        ip = _env_or_value(item, "ip")
        if ip:
            servers[name] = str(ip)

    devices: dict[str, DeviceProfile] = {}
    for item in payload.get("devices") or []:
        if not isinstance(item, Mapping):
            continue
        role = _comparison_label(item.get("role"), UNMAPPED_DEVICE_ROLE)
        config_label = _comparison_label(
            item.get("config") or item.get("config_profile") or item.get("profile"),
            UNMAPPED_DEVICE_CONFIG,
        )
        mac = _env_or_value(item, "mac")
        name_hint = str(item.get("name") or item.get("label") or "").strip()
        raw_ips: list[Any] = []
        ip = _env_or_value(item, "ip")
        if ip:
            raw_ips.append(ip)
        extra_ips = item.get("ips") or []
        if isinstance(extra_ips, (str, int)):
            raw_ips.append(extra_ips)
        else:
            for extra_ip in extra_ips:
                raw_ips.append(extra_ip)
        if not raw_ips:
            mac_hex = normalize_mac_hex(mac)
            if mac_hex:
                devices[f"mac:{mac_hex}"] = DeviceProfile(
                    name=name_hint or f"{role}-{mac_hex}",
                    role=role,
                    config=config_label,
                    ip="",
                    mac=str(mac),
                )
            continue
        for raw_ip in raw_ips:
            ip_text = str(ipaddress.ip_address(str(raw_ip)))
            name = name_hint or f"{role}-{ip_text}"
            devices[ip_text] = DeviceProfile(
                name=name or ip_text,
                role=role,
                config=config_label,
                ip=ip_text,
                mac=str(mac) if mac else None,
            )

    badge_subnets = [
        ipaddress.ip_network(str(value), strict=False)
        for value in (payload.get("badge_subnets") or [])
    ]
    media_ports = [
        parse_port_range(value)
        for value in (payload.get("media_ports") or [])
    ]
    raw_clock_rates = payload.get("payload_clock_rates") or {}
    payload_clock_rates: dict[int, int] = {}
    default_clock = DEFAULT_RTP_CLOCK_HZ
    if isinstance(raw_clock_rates, Mapping):
        for key, value in raw_clock_rates.items():
            if str(key).lower() == "default":
                default_clock = int(value)
            else:
                payload_clock_rates[int(key)] = int(value)

    expected_dscp = payload.get("expected_dscp")
    max_future_skew = payload.get("max_capture_future_skew_seconds", DEFAULT_MAX_CAPTURE_FUTURE_SKEW_SECONDS)
    min_rtp_qoe_packets = payload.get("min_rtp_qoe_packets", DEFAULT_MIN_RTP_QOE_PACKETS)
    max_rtp_transit_delta = payload.get("max_rtp_transit_delta_seconds", DEFAULT_MAX_RTP_TRANSIT_DELTA_SECONDS)
    plausibility = payload.get("rtp_plausibility") or {}
    if not isinstance(plausibility, Mapping):
        plausibility = {}
    return AnalyzerConfig(
        site=str(payload.get("site") or "unknown"),
        capture_point=str(payload.get("capture_point") or "unknown"),
        expected_dscp=int(expected_dscp) if expected_dscp is not None else None,
        servers=servers,
        badge_subnets=badge_subnets,
        devices=devices,
        media_ports=media_ports,
        payload_clock_rates=payload_clock_rates,
        default_rtp_clock_hz=default_clock,
        max_capture_future_skew_seconds=float(max_future_skew),
        min_rtp_qoe_packets=int(plausibility.get("min_packets", min_rtp_qoe_packets)),
        max_rtp_transit_delta_seconds=float(max_rtp_transit_delta),
        strict_rtp_plausibility=bool(plausibility.get("strict", payload.get("strict_rtp_plausibility", True))),
        require_known_rtp_clock_rate=bool(
            plausibility.get("require_known_clock_rate", payload.get("require_known_rtp_clock_rate", False))
        ),
        min_rtp_duration_seconds=float(
            plausibility.get("min_duration_seconds", payload.get("min_rtp_duration_seconds", DEFAULT_MIN_RTP_DURATION_SECONDS))
        ),
        max_rtp_interarrival_ms=float(
            plausibility.get("max_interarrival_ms", payload.get("max_rtp_interarrival_ms", DEFAULT_MAX_RTP_INTERARRIVAL_MS))
        ),
        max_rtp_jitter_ms=float(plausibility.get("max_jitter_ms", payload.get("max_rtp_jitter_ms", DEFAULT_MAX_RTP_JITTER_MS))),
        min_rtp_sequence_progression_ratio=float(
            plausibility.get(
                "min_sequence_progression_ratio",
                payload.get("min_rtp_sequence_progression_ratio", DEFAULT_MIN_RTP_SEQUENCE_PROGRESSION_RATIO),
            )
        ),
        min_rtp_timestamp_progression_ratio=float(
            plausibility.get(
                "min_timestamp_progression_ratio",
                payload.get("min_rtp_timestamp_progression_ratio", DEFAULT_MIN_RTP_TIMESTAMP_PROGRESSION_RATIO),
            )
        ),
        max_rtp_timestamp_wallclock_error_ms=float(
            plausibility.get(
                "max_timestamp_wallclock_error_ms",
                payload.get("max_rtp_timestamp_wallclock_error_ms", DEFAULT_MAX_RTP_TIMESTAMP_WALLCLOCK_ERROR_MS),
            )
        ),
        min_voice_packetization_ms=float(
            plausibility.get("min_packetization_ms", payload.get("min_voice_packetization_ms", DEFAULT_MIN_VOICE_PACKETIZATION_MS))
        ),
        max_voice_packetization_ms=float(
            plausibility.get("max_packetization_ms", payload.get("max_voice_packetization_ms", DEFAULT_MAX_VOICE_PACKETIZATION_MS))
        ),
        max_rtp_loss_ratio_for_plausibility=float(
            plausibility.get("max_loss_ratio", payload.get("max_rtp_loss_ratio_for_plausibility", DEFAULT_MAX_RTP_LOSS_RATIO_FOR_PLAUSIBILITY))
        ),
        max_rtp_duplicate_ratio_for_plausibility=float(
            plausibility.get(
                "max_duplicate_ratio",
                payload.get("max_rtp_duplicate_ratio_for_plausibility", DEFAULT_MAX_RTP_DUPLICATE_RATIO_FOR_PLAUSIBILITY),
            )
        ),
        max_rtp_out_of_order_ratio_for_plausibility=float(
            plausibility.get(
                "max_out_of_order_ratio",
                payload.get("max_rtp_out_of_order_ratio_for_plausibility", DEFAULT_MAX_RTP_OUT_OF_ORDER_RATIO_FOR_PLAUSIBILITY),
            )
        ),
        rtp_debug_packet_limit=int(
            plausibility.get("debug_packet_limit", payload.get("rtp_debug_packet_limit", DEFAULT_RTP_DEBUG_PACKET_LIMIT))
        ),
    )


def iter_pcap_udp_packets(path: str | Path) -> tuple[list[UdpPacket], int]:
    """Parse classic pcap/pcapng Ethernet or radiotap 802.11 IPv4/UDP packets."""

    data = Path(path).read_bytes()
    if len(data) < 24:
        raise RuntimeError(f"pcap is too short: {path}")
    magic = data[:4]
    if magic == PCAPNG_MAGIC:
        return iter_pcapng_udp_packets(path, data)
    if magic not in PCAP_MAGIC:
        raise RuntimeError(f"unsupported pcap magic in {path}")
    endian, time_scale = PCAP_MAGIC[magic]
    version_major, version_minor, _tz, _sigfigs, _snaplen, network = struct.unpack(
        f"{endian}HHIIII",
        data[4:24],
    )
    if version_major != 2 or version_minor != 4:
        raise RuntimeError(f"unsupported pcap version {version_major}.{version_minor}: {path}")
    if network not in {ETHERNET_LINKTYPE, IEEE802_11_RADIOTAP_LINKTYPE}:
        raise RuntimeError(f"unsupported pcap linktype {network}; only Ethernet and radiotap 802.11 are supported")

    offset = 24
    packets_read = 0
    udp_packets: list[UdpPacket] = []
    while offset + 16 <= len(data):
        ts_sec, ts_frac, incl_len, orig_len = struct.unpack(f"{endian}IIII", data[offset:offset + 16])
        offset += 16
        if incl_len > len(data) - offset:
            raise RuntimeError(
                "truncated pcap record "
                f"{packets_read + 1} in {path}: incl_len={incl_len} remaining={len(data) - offset}"
            )
        if incl_len > _snaplen:
            raise RuntimeError(
                "invalid pcap record "
                f"{packets_read + 1} in {path}: incl_len={incl_len} snaplen={_snaplen}"
            )
        frame = data[offset:offset + incl_len]
        offset += incl_len
        packets_read += 1
        arrival_time = ts_sec + (ts_frac / time_scale)
        if network == ETHERNET_LINKTYPE:
            packet = parse_ethernet_udp_frame(frame, arrival_time=arrival_time, orig_len=orig_len)
        else:
            packet = parse_radiotap_udp_frame(frame, arrival_time=arrival_time, orig_len=orig_len)
        if packet:
            udp_packets.append(packet)
    return udp_packets, packets_read


def _pcapng_padded_length(length: int) -> int:
    """Return a pcapng option/data length padded to 32-bit alignment."""
    return length + ((4 - (length % 4)) % 4)


def _pcapng_ts_resolution(value: bytes) -> float:
    """Decode a pcapng if_tsresol option into seconds per tick."""
    if not value:
        return 0.000001
    raw = value[0]
    if raw & 0x80:
        return 2 ** -(raw & 0x7F)
    return 10 ** -raw


def _pcapng_options(body: bytes, endian: str) -> Iterable[tuple[int, bytes]]:
    """Iterate pcapng option records from a block body."""
    offset = 0
    while offset + 4 <= len(body):
        code, length = struct.unpack(f"{endian}HH", body[offset:offset + 4])
        offset += 4
        if code == 0:
            break
        if offset + length > len(body):
            break
        value = body[offset:offset + length]
        yield code, value
        offset += _pcapng_padded_length(length)


def iter_pcapng_udp_packets(path: str | Path, data: bytes) -> tuple[list[UdpPacket], int]:
    """Parse pcapng Enhanced Packet Blocks for supported link types."""

    offset = 0
    endian: str | None = None
    interfaces: dict[int, tuple[int, float]] = {}
    packets_read = 0
    udp_packets: list[UdpPacket] = []

    while offset + 12 <= len(data):
        if data[offset:offset + 4] == PCAPNG_MAGIC:
            if offset + 28 > len(data):
                raise RuntimeError(f"truncated pcapng section header in {path}")
            endian = PCAPNG_BYTE_ORDER_MAGIC.get(data[offset + 8:offset + 12])
            if endian is None:
                raise RuntimeError(f"unsupported pcapng byte-order magic in {path}")
            block_type = PCAPNG_SECTION_HEADER_BLOCK
            total_len = struct.unpack(f"{endian}I", data[offset + 4:offset + 8])[0]
            interfaces = {}
        else:
            if endian is None:
                raise RuntimeError(f"pcapng block appeared before section header in {path}")
            block_type, total_len = struct.unpack(f"{endian}II", data[offset:offset + 8])

        if total_len < 12:
            raise RuntimeError(f"invalid pcapng block length {total_len} in {path}")
        if offset + total_len > len(data):
            raise RuntimeError(
                f"truncated pcapng block in {path}: block_len={total_len} remaining={len(data) - offset}"
            )
        trailer_len = struct.unpack(f"{endian}I", data[offset + total_len - 4:offset + total_len])[0]
        if trailer_len != total_len:
            raise RuntimeError(f"pcapng block length trailer mismatch in {path}")

        body = data[offset + 8:offset + total_len - 4]
        if block_type == PCAPNG_INTERFACE_DESCRIPTION_BLOCK:
            if len(body) < 8:
                raise RuntimeError(f"truncated pcapng interface description in {path}")
            linktype, _reserved, _snaplen = struct.unpack(f"{endian}HHI", body[:8])
            ts_resolution = 0.000001
            for code, value in _pcapng_options(body[8:], endian):
                if code == PCAPNG_IF_TSRESOL_OPTION:
                    ts_resolution = _pcapng_ts_resolution(value)
            interfaces[len(interfaces)] = (linktype, ts_resolution)
        elif block_type == PCAPNG_ENHANCED_PACKET_BLOCK:
            if len(body) < 20:
                raise RuntimeError(f"truncated pcapng enhanced packet block in {path}")
            interface_id, ts_high, ts_low, captured_len, packet_len = struct.unpack(f"{endian}IIIII", body[:20])
            if captured_len > len(body) - 20:
                raise RuntimeError(
                    "truncated pcapng packet "
                    f"{packets_read + 1} in {path}: captured_len={captured_len} remaining={len(body) - 20}"
                )
            linktype, ts_resolution = interfaces.get(interface_id, (None, 0.000001))
            if linktype not in {ETHERNET_LINKTYPE, IEEE802_11_RADIOTAP_LINKTYPE}:
                raise RuntimeError(f"unsupported pcapng linktype {linktype}; only Ethernet and radiotap 802.11 are supported")
            packets_read += 1
            timestamp = ((ts_high << 32) | ts_low) * ts_resolution
            frame = body[20:20 + captured_len]
            if linktype == ETHERNET_LINKTYPE:
                packet = parse_ethernet_udp_frame(frame, arrival_time=timestamp, orig_len=packet_len)
            else:
                packet = parse_radiotap_udp_frame(frame, arrival_time=timestamp, orig_len=packet_len)
            if packet:
                udp_packets.append(packet)

        offset += total_len

    return udp_packets, packets_read


def parse_ipv4_udp_packet(packet: bytes, *, arrival_time: float, orig_len: int) -> UdpPacket | None:
    """Parse one IPv4 packet into UDP fields when possible."""

    if len(packet) < 20:
        return None
    first_byte = packet[0]
    version = first_byte >> 4
    ihl = (first_byte & 0x0F) * 4
    if version != 4 or ihl < 20 or len(packet) < ihl:
        return None
    tos = packet[1]
    total_length = struct.unpack("!H", packet[2:4])[0]
    fragment = struct.unpack("!H", packet[6:8])[0]
    protocol = packet[9]
    if protocol != UDP_PROTOCOL or (fragment & 0x1FFF):
        return None
    src_ip = ".".join(str(part) for part in packet[12:16])
    dst_ip = ".".join(str(part) for part in packet[16:20])
    ip_payload_start = ihl
    ip_payload_end = min(total_length, len(packet))
    if ip_payload_end < ip_payload_start + 8:
        return None
    src_port, dst_port, udp_length, _checksum = struct.unpack("!HHHH", packet[ip_payload_start:ip_payload_start + 8])
    if udp_length < 8:
        return None
    payload_end = min(ip_payload_start + udp_length, ip_payload_end)
    payload = packet[ip_payload_start + 8:payload_end]
    return UdpPacket(
        arrival_time=arrival_time,
        src_ip=src_ip,
        dst_ip=dst_ip,
        src_port=src_port,
        dst_port=dst_port,
        dscp=tos >> 2,
        payload=payload,
        udp_length=udp_length,
        orig_len=orig_len,
    )


def parse_ethernet_udp_frame(frame: bytes, *, arrival_time: float, orig_len: int) -> UdpPacket | None:
    """Parse one Ethernet frame into a UDP packet when possible."""

    if len(frame) < 14:
        return None
    ethertype = struct.unpack("!H", frame[12:14])[0]
    cursor = 14
    while ethertype in VLAN_ETHERTYPES:
        if len(frame) < cursor + 4:
            return None
        ethertype = struct.unpack("!H", frame[cursor + 2:cursor + 4])[0]
        cursor += 4
    if ethertype != IPV4_ETHERTYPE:
        return None
    return parse_ipv4_udp_packet(frame[cursor:], arrival_time=arrival_time, orig_len=orig_len)


def parse_radiotap_udp_frame(frame: bytes, *, arrival_time: float, orig_len: int) -> UdpPacket | None:
    """Parse one radiotap 802.11 data frame into a UDP packet when possible."""

    if len(frame) < 8:
        return None
    radiotap_version = frame[0]
    radiotap_len = struct.unpack("<H", frame[2:4])[0]
    if radiotap_version != 0 or radiotap_len < 8 or len(frame) < radiotap_len + 24:
        return None

    cursor = radiotap_len
    frame_control = struct.unpack("<H", frame[cursor:cursor + 2])[0]
    frame_type = (frame_control >> 2) & 0x03
    subtype = (frame_control >> 4) & 0x0F
    protected = bool(frame_control & 0x4000)
    to_ds = bool(frame_control & 0x0100)
    from_ds = bool(frame_control & 0x0200)
    if frame_type != 2 or protected:
        return None

    header_len = 24
    if to_ds and from_ds:
        header_len += 6
    if subtype & 0x08:
        header_len += 2
    llc_start = cursor + header_len
    if len(frame) < llc_start + LLC_SNAP_HEADER_LEN:
        return None

    llc = frame[llc_start:llc_start + LLC_SNAP_HEADER_LEN]
    dsap, ssap, control = llc[0], llc[1], llc[2]
    ethertype = struct.unpack("!H", llc[6:8])[0]
    if (dsap, ssap, control) != (0xAA, 0xAA, 0x03) or ethertype != IPV4_ETHERTYPE:
        return None
    return parse_ipv4_udp_packet(
        frame[llc_start + LLC_SNAP_HEADER_LEN:],
        arrival_time=arrival_time,
        orig_len=orig_len,
    )


def parse_rtp_header(payload: bytes) -> RtpHeader | None:
    """Parse visible RTP header fields using RFC 3550 layout."""

    if len(payload) < 12:
        return None
    first = payload[0]
    version = first >> 6
    padding = (first >> 5) & 1
    extension = (first >> 4) & 1
    csrc_count = first & 0x0F
    if version != 2:
        return None
    header_len = 12 + (4 * csrc_count)
    if len(payload) < header_len:
        return None
    if extension:
        if len(payload) < header_len + 4:
            return None
        ext_words = struct.unpack("!H", payload[header_len + 2:header_len + 4])[0]
        header_len += 4 + (4 * ext_words)
        if len(payload) < header_len:
            return None
    if padding and payload[-1] > len(payload) - header_len:
        return None
    second = payload[1]
    marker = second >> 7
    payload_type = second & 0x7F
    sequence, timestamp, ssrc = struct.unpack("!HII", payload[2:12])
    return RtpHeader(
        payload_type=payload_type,
        marker=marker,
        sequence=sequence,
        timestamp=timestamp,
        ssrc=ssrc,
        header_len=header_len,
    )


def direction_for(src_role: str, dst_role: str) -> str:
    """Build the stream direction label from endpoint roles."""
    if src_role == "badge" and dst_role == "server":
        return "badge_to_server"
    if src_role == "server" and dst_role == "badge":
        return "server_to_badge"
    if src_role == "badge" and dst_role == "badge":
        return "badge_to_badge"
    if src_role == "server" and dst_role == "server":
        return "server_to_server"
    return f"{src_role}_to_{dst_role}"


def server_label(packet: UdpPacket, config: AnalyzerConfig) -> str:
    """Return the configured server label seen on either side of a packet."""
    return (
        config.server_name_for(packet.src_ip)
        or config.server_name_for(packet.dst_ip)
        or "unknown"
    )


def stream_device_labels(identity: StreamIdentity, config: AnalyzerConfig) -> dict[str, str]:
    """Return primary and peer configured device labels for a stream."""
    src_device = config.device_profile_for(identity.src_ip)
    dst_device = config.device_profile_for(identity.dst_ip)

    primary = src_device or dst_device
    peer: DeviceProfile | None = None
    if src_device and dst_device:
        peer = dst_device
    elif primary is dst_device and src_device:
        peer = src_device

    return {
        "device_name": primary.name if primary else UNMAPPED_DEVICE_NAME,
        "device_role": primary.role if primary else UNMAPPED_DEVICE_ROLE,
        "device_config": primary.config if primary else UNMAPPED_DEVICE_CONFIG,
        "peer_device_name": peer.name if peer else UNMAPPED_DEVICE_NAME,
        "peer_device_role": peer.role if peer else UNMAPPED_DEVICE_ROLE,
        "peer_device_config": peer.config if peer else UNMAPPED_DEVICE_CONFIG,
    }


def apply_source_device_fallback(result: AnalysisResult, source_path: str | Path, config: AnalyzerConfig) -> AnalysisResult:
    """Label otherwise-unmapped streams from the configured badge MAC in the pcap path."""
    source_device = config.device_profile_for_source_mac(str(source_path))
    if source_device is None:
        return result
    for stream in result.streams:
        if stream.device_role == UNMAPPED_DEVICE_ROLE:
            stream.device_name = source_device.name
            stream.device_role = source_device.role
            stream.device_config = source_device.config
    return result


def extend_rtp_sequence(sequence: int, highest_ext: int | None) -> int:
    """Map a 16-bit RTP sequence number into an extended sequence space."""

    if highest_ext is None:
        return sequence
    cycle = highest_ext & ~0xFFFF
    candidate = cycle + sequence
    if candidate - highest_ext < -32768:
        candidate += 65536
    elif candidate - highest_ext > 32768:
        candidate -= 65536
    return candidate


def interarrival_stats(arrivals: list[float]) -> tuple[float | None, float | None, float | None]:
    """Return p50, p95, and max packet interarrival gaps in milliseconds."""
    gaps = [
        (current - previous) * 1000
        for previous, current in zip(arrivals, arrivals[1:])
        if current >= previous
    ]
    return percentile(gaps, 0.5), percentile(gaps, 0.95), max(gaps) if gaps else None


def filter_future_timestamp_outliers(
    packets: list[UdpPacket],
    *,
    max_arrival_time: float,
) -> tuple[list[UdpPacket], int]:
    """Drop packets whose pcap timestamp is impossible for this collector run."""
    valid = [packet for packet in packets if packet.arrival_time <= max_arrival_time]
    return valid, len(packets) - len(valid)


def packet_rate(packet_count: int, first_seen: float, last_seen: float) -> float | None:
    """Return packets per second over the observed stream duration."""
    duration = last_seen - first_seen
    if duration <= 0:
        return None
    return packet_count / duration


def rtp_sequence_stats(headers: Iterable[RtpHeader]) -> tuple[int, int, int, int]:
    """Return expected, lost, duplicate, and out-of-order RTP packet counts.

    The sequence validation follows the RFC 3550 Appendix A.1 boundary values:
    small forward gaps count as loss, small backwards movement counts as
    misorder, and large jumps are ignored unless the next packet confirms a
    source restart.
    """

    segment = 0
    highest_ext: int | None = None
    bad_seq: int | None = None
    seen: set[tuple[int, int]] = set()
    missing: set[tuple[int, int]] = set()
    valid_unique = 0
    duplicate_packets = 0
    out_of_order_packets = 0

    for header in headers:
        sequence = header.sequence
        if highest_ext is None:
            highest_ext = sequence
            seen.add((segment, highest_ext))
            valid_unique += 1
            bad_seq = None
            continue

        candidate = extend_rtp_sequence(sequence, highest_ext)
        key = (segment, candidate)
        diff = candidate - highest_ext
        if key in seen:
            duplicate_packets += 1
            continue
        if 0 < diff <= RTP_MAX_DROPOUT:
            for missed in range(highest_ext + 1, candidate):
                missing.add((segment, missed))
            seen.add(key)
            missing.discard(key)
            valid_unique += 1
            highest_ext = candidate
            bad_seq = None
        elif -RTP_MAX_MISORDER <= diff < 0:
            out_of_order_packets += 1
            seen.add(key)
            if key in missing:
                missing.remove(key)
            valid_unique += 1
            bad_seq = None
        elif sequence == bad_seq:
            segment += 1
            highest_ext = sequence
            seen.add((segment, highest_ext))
            valid_unique += 1
            bad_seq = None
        else:
            bad_seq = (sequence + 1) % RTP_SEQ_MOD

    expected_packets = valid_unique + len(missing)
    lost_packets = len(missing)
    return expected_packets, lost_packets, duplicate_packets, out_of_order_packets


def rtp_timestamp_delta(current: int, previous: int) -> int:
    """Return RTP timestamp delta in signed extended 32-bit timestamp space."""

    delta = current - previous
    if delta < -RTP_TS_HALF_MOD:
        delta += RTP_TS_MOD
    elif delta > RTP_TS_HALF_MOD:
        delta -= RTP_TS_MOD
    return delta


def rtp_jitter_ms(
    packets: list[tuple[UdpPacket, RtpHeader]],
    *,
    clock_rate: int,
    max_transit_delta_seconds: float,
) -> float:
    """Calculate RFC 3550 jitter with corrupt transit deltas ignored."""

    jitter_seconds = 0.0
    previous_transit: float | None = None
    for packet, header in packets:
        transit = packet.arrival_time - (header.timestamp / clock_rate)
        if previous_transit is not None:
            delta = transit - previous_transit
            if abs(delta) <= max_transit_delta_seconds:
                jitter_seconds += (abs(delta) - jitter_seconds) / 16
        previous_transit = transit
    return jitter_seconds * 1000


def rtp_debug_packets(
    packets: list[tuple[UdpPacket, RtpHeader]],
    *,
    clock_rate: int,
    limit: int,
) -> list[dict[str, float | int | None]]:
    """Return first-N packet timing details for RTP candidate debug output."""

    rows: list[dict[str, float | int | None]] = []
    previous_packet: UdpPacket | None = None
    previous_header: RtpHeader | None = None
    for packet, header in packets[: max(0, limit)]:
        arrival_delta_ms = None
        rtp_delta_ms = None
        if previous_packet is not None and previous_header is not None:
            arrival_delta_ms = (packet.arrival_time - previous_packet.arrival_time) * 1000
            rtp_delta_ms = (rtp_timestamp_delta(header.timestamp, previous_header.timestamp) / clock_rate) * 1000
        rows.append(
            {
                "arrival_time": packet.arrival_time,
                "seq": header.sequence,
                "timestamp": header.timestamp,
                "arrival_delta_ms": arrival_delta_ms,
                "rtp_delta_ms": rtp_delta_ms,
            }
        )
        previous_packet = packet
        previous_header = header
    return rows


def rtp_plausibility_check(
    items: list[tuple[UdpPacket, RtpHeader]],
    config: AnalyzerConfig,
) -> RtpPlausibilityResult:
    """Decide whether RTP-looking UDP behaves like RTP over time."""

    packets = sorted(items, key=lambda item: item[0].arrival_time)
    packet_count = len(packets)
    payload_type = packets[0][1].payload_type if packets else -1
    clock_rate, clock_rate_known = config.rtp_clock_rate(payload_type)
    arrivals = [packet.arrival_time for packet, _header in packets]
    duration = (arrivals[-1] - arrivals[0]) if len(arrivals) >= 2 else 0.0
    p50_gap, p95_gap, max_gap = interarrival_stats(arrivals)
    expected_packets, lost_packets, duplicate_packets, out_of_order_packets = rtp_sequence_stats(
        header for _packet, header in packets
    )
    loss_ratio = lost_packets / expected_packets if expected_packets else 0.0
    duplicate_ratio = duplicate_packets / packet_count if packet_count else 0.0
    out_of_order_ratio = out_of_order_packets / packet_count if packet_count else 0.0
    jitter = rtp_jitter_ms(
        packets,
        clock_rate=clock_rate,
        max_transit_delta_seconds=config.max_rtp_transit_delta_seconds,
    )

    sequence_forward = 0
    sequence_transitions = max(0, packet_count - 1)
    timestamp_forward = 0
    timestamp_checked = 0
    timestamp_errors_ms: list[float] = []
    packetization_ms_values: list[float] = []
    highest_ext: int | None = None
    previous_packet: UdpPacket | None = None
    previous_header: RtpHeader | None = None

    for packet, header in packets:
        if highest_ext is None:
            highest_ext = header.sequence
            previous_packet = packet
            previous_header = header
            continue
        candidate = extend_rtp_sequence(header.sequence, highest_ext)
        diff = candidate - highest_ext
        if 0 < diff <= RTP_MAX_DROPOUT:
            sequence_forward += 1
            if previous_packet is not None and previous_header is not None:
                ts_delta = rtp_timestamp_delta(header.timestamp, previous_header.timestamp)
                timestamp_checked += 1
                if ts_delta > 0:
                    timestamp_forward += 1
                    rtp_delta_seconds = ts_delta / clock_rate
                    arrival_delta_seconds = packet.arrival_time - previous_packet.arrival_time
                    timestamp_errors_ms.append(abs(arrival_delta_seconds - rtp_delta_seconds) * 1000)
                    packetization_ms_values.append(rtp_delta_seconds * 1000)
            highest_ext = candidate
        previous_packet = packet
        previous_header = header

    sequence_progression_ratio = (
        sequence_forward / sequence_transitions if sequence_transitions else 0.0
    )
    timestamp_progression_ratio = (
        timestamp_forward / timestamp_checked if timestamp_checked else 0.0
    )
    timestamp_wallclock_error_ms = percentile(timestamp_errors_ms, 0.95)
    estimated_packetization_ms = percentile(packetization_ms_values, 0.5)

    reasons: list[str] = []
    if packet_count < config.min_rtp_qoe_packets:
        reasons.append("too_few_packets")
    if duration <= 0 or duration < config.min_rtp_duration_seconds:
        reasons.append("duration_too_short")
    if config.require_known_rtp_clock_rate and not clock_rate_known:
        reasons.append("unknown_clock_rate")
    if sequence_progression_ratio < config.min_rtp_sequence_progression_ratio:
        reasons.append("sequence_not_progressing")
    if timestamp_progression_ratio < config.min_rtp_timestamp_progression_ratio:
        reasons.append("timestamp_not_progressing")
    if (
        timestamp_wallclock_error_ms is not None
        and timestamp_wallclock_error_ms > config.max_rtp_timestamp_wallclock_error_ms
    ):
        reasons.append("timestamp_wallclock_mismatch")
    if estimated_packetization_ms is not None and (
        estimated_packetization_ms < config.min_voice_packetization_ms
        or estimated_packetization_ms > config.max_voice_packetization_ms
    ):
        reasons.append("packetization_implausible")
    if p95_gap is not None and p95_gap > config.max_rtp_interarrival_ms:
        reasons.append("interarrival_gap_too_large")
    if loss_ratio > config.max_rtp_loss_ratio_for_plausibility:
        reasons.append("loss_ratio_implausible")
    if duplicate_ratio > config.max_rtp_duplicate_ratio_for_plausibility:
        reasons.append("duplicate_ratio_implausible")
    if out_of_order_ratio > config.max_rtp_out_of_order_ratio_for_plausibility:
        reasons.append("out_of_order_ratio_implausible")
    if jitter > config.max_rtp_jitter_ms:
        reasons.append("jitter_implausible")

    old_valid = (
        packet_count >= config.min_rtp_qoe_packets
        and len({header.sequence for _packet, header in packets}) >= max(2, config.min_rtp_qoe_packets // 2)
        and len({header.timestamp for _packet, header in packets}) >= 2
    )
    is_plausible = not reasons if config.strict_rtp_plausibility else old_valid
    return RtpPlausibilityResult(
        is_plausible=is_plausible,
        reasons=sorted(set(reasons)),
        packet_count=packet_count,
        duration_seconds=duration,
        sequence_progression_ratio=sequence_progression_ratio,
        timestamp_progression_ratio=timestamp_progression_ratio,
        timestamp_wallclock_error_ms=timestamp_wallclock_error_ms,
        interarrival_p50_ms=p50_gap,
        interarrival_p95_ms=p95_gap,
        interarrival_max_ms=max_gap,
        estimated_packetization_ms=estimated_packetization_ms,
        loss_ratio=loss_ratio,
        duplicate_ratio=duplicate_ratio,
        out_of_order_ratio=out_of_order_ratio,
        jitter_ms=jitter,
        clock_rate_known=clock_rate_known,
        debug_packets=rtp_debug_packets(packets, clock_rate=clock_rate, limit=config.rtp_debug_packet_limit),
    )


def analyze_rtp_stream(
    packets: list[tuple[UdpPacket, RtpHeader]],
    identity: StreamIdentity,
    config: AnalyzerConfig,
    plausibility: RtpPlausibilityResult | None = None,
) -> StreamStats:
    """Calculate RFC 3550 jitter, RTP loss, duplicates, and ordering stats."""

    packets = sorted(packets, key=lambda item: item[0].arrival_time)
    src_role = config.role_for(identity.src_ip)
    dst_role = config.role_for(identity.dst_ip)
    direction = direction_for(src_role, dst_role)
    device_labels = stream_device_labels(identity, config)
    arrivals = [packet.arrival_time for packet, _header in packets]
    first_seen = arrivals[0]
    last_seen = arrivals[-1]
    payload_type = identity.payload_type
    clock_rate, clock_rate_known = config.rtp_clock_rate(payload_type if payload_type is not None else -1)
    jitter = rtp_jitter_ms(
        packets,
        clock_rate=clock_rate,
        max_transit_delta_seconds=config.max_rtp_transit_delta_seconds,
    )

    expected_packets, lost_packets, duplicate_packets, out_of_order_packets = rtp_sequence_stats(
        header for _packet, header in packets
    )
    loss_ratio = lost_packets / expected_packets if expected_packets else 0.0
    p50_gap, p95_gap, max_gap = interarrival_stats(arrivals)
    dscp_values = [packet.dscp for packet, _header in packets]
    dscp = statistics.mode(dscp_values)
    byte_count = sum(packet.udp_length for packet, _header in packets)
    dscp_mismatch = config.expected_dscp is not None and dscp != config.expected_dscp
    return StreamStats(
        identity=identity,
        measurement_mode="rtp",
        src_role=src_role,
        dst_role=dst_role,
        **device_labels,
        direction=direction,
        server=server_label(packets[0][0], config),
        site=config.site,
        capture_point=config.capture_point,
        dscp=dscp,
        packet_count=len(packets),
        byte_count=byte_count,
        first_seen=first_seen,
        last_seen=last_seen,
        payload_type=payload_type,
        expected_packets=expected_packets,
        lost_packets=lost_packets,
        loss_ratio=loss_ratio,
        duplicate_packets=duplicate_packets,
        out_of_order_packets=out_of_order_packets,
        jitter_ms=jitter,
        interarrival_p50_ms=p50_gap,
        interarrival_p95_ms=p95_gap,
        interarrival_max_ms=max_gap,
        packet_rate_pps=packet_rate(len(packets), first_seen, last_seen),
        dscp_mismatch=dscp_mismatch,
        clock_rate_known=clock_rate_known,
        rtp_plausibility=plausibility,
    )


def analyze_udp_stream(
    packets: list[UdpPacket],
    identity: StreamIdentity,
    config: AnalyzerConfig,
    measurement_mode: str = "udp_interarrival_only",
    rtp_plausibility: RtpPlausibilityResult | None = None,
) -> StreamStats:
    """Calculate safe timing-only stats for non-RTP UDP."""

    packets = sorted(packets, key=lambda packet: packet.arrival_time)
    src_role = config.role_for(identity.src_ip)
    dst_role = config.role_for(identity.dst_ip)
    device_labels = stream_device_labels(identity, config)
    arrivals = [packet.arrival_time for packet in packets]
    p50_gap, p95_gap, max_gap = interarrival_stats(arrivals)
    dscp_values = [packet.dscp for packet in packets]
    dscp = statistics.mode(dscp_values)
    dscp_mismatch = config.expected_dscp is not None and dscp != config.expected_dscp
    return StreamStats(
        identity=identity,
        measurement_mode=measurement_mode if len(packets) > 1 or measurement_mode != "udp_interarrival_only" else "unknown_udp",
        src_role=src_role,
        dst_role=dst_role,
        **device_labels,
        direction=direction_for(src_role, dst_role),
        server=server_label(packets[0], config),
        site=config.site,
        capture_point=config.capture_point,
        dscp=dscp,
        packet_count=len(packets),
        byte_count=sum(packet.udp_length for packet in packets),
        first_seen=arrivals[0],
        last_seen=arrivals[-1],
        payload_type=identity.payload_type,
        interarrival_p50_ms=p50_gap,
        interarrival_p95_ms=p95_gap,
        interarrival_max_ms=max_gap,
        packet_rate_pps=packet_rate(len(packets), arrivals[0], arrivals[-1]),
        dscp_mismatch=dscp_mismatch,
        clock_rate_known=rtp_plausibility.clock_rate_known if rtp_plausibility else True,
        rtp_plausibility=rtp_plausibility,
        rtp_rejection_reasons=list(rtp_plausibility.reasons) if rtp_plausibility else [],
    )


def valid_rtp_group(items: list[tuple[UdpPacket, RtpHeader]], config: AnalyzerConfig) -> bool:
    """Require enough sequence evidence before claiming RTP."""

    return rtp_plausibility_check(items, config).is_plausible


def analyze_udp_packets(packets: Iterable[UdpPacket], config: AnalyzerConfig) -> AnalysisResult:
    """Classify UDP packets and calculate per-stream stats."""

    packets = [
        packet
        for packet in packets
        if config.media_port_matches(packet.src_port, packet.dst_port)
    ]
    flows: dict[tuple[str, int, str, int], list[UdpPacket]] = defaultdict(list)
    for packet in packets:
        flows[(packet.src_ip, packet.src_port, packet.dst_ip, packet.dst_port)].append(packet)

    streams: list[StreamStats] = []
    for flow_key, flow_packets in flows.items():
        src_ip, src_port, dst_ip, dst_port = flow_key
        rtp_groups: dict[tuple[int, int], list[tuple[UdpPacket, RtpHeader]]] = defaultdict(list)
        non_rtp_packets: list[UdpPacket] = []
        for packet in flow_packets:
            header = parse_rtp_header(packet.payload)
            if header is None:
                non_rtp_packets.append(packet)
            else:
                rtp_groups[(header.ssrc, header.payload_type)].append((packet, header))

        for (ssrc, payload_type), items in sorted(rtp_groups.items()):
            identity = StreamIdentity(
                src_ip=src_ip,
                src_port=src_port,
                dst_ip=dst_ip,
                dst_port=dst_port,
                ssrc=ssrc,
                payload_type=payload_type,
            )
            plausibility = rtp_plausibility_check(items, config)
            if plausibility.is_plausible:
                streams.append(analyze_rtp_stream(items, identity, config, plausibility=plausibility))
            else:
                streams.append(
                    analyze_udp_stream(
                        [packet for packet, _header in items],
                        identity,
                        config,
                        measurement_mode="rtp_candidate_rejected",
                        rtp_plausibility=plausibility,
                    )
                )

        if non_rtp_packets:
            identity = StreamIdentity(src_ip=src_ip, src_port=src_port, dst_ip=dst_ip, dst_port=dst_port)
            streams.append(analyze_udp_stream(non_rtp_packets, identity, config))

    return AnalysisResult(
        streams=streams,
        packets_read=len(packets),
        udp_packets_seen=len(packets),
        last_capture_timestamp_seconds=max((packet.arrival_time for packet in packets), default=None),
        parse_success=1,
    )


def analyze_pcap(path: str | Path, config: AnalyzerConfig) -> AnalysisResult:
    """Analyze one pcap file."""

    udp_packets, packets_read = iter_pcap_udp_packets(path)
    max_arrival_time = time.time() + config.max_capture_future_skew_seconds
    analyzed_packets, timestamp_outliers = filter_future_timestamp_outliers(
        udp_packets,
        max_arrival_time=max_arrival_time,
    )
    if udp_packets and not analyzed_packets:
        return AnalysisResult(
            streams=[],
            packets_read=packets_read,
            udp_packets_seen=len(udp_packets),
            last_capture_timestamp_seconds=None,
            parse_success=0,
            error=(
                "all UDP packet timestamps are later than collector time plus "
                f"{config.max_capture_future_skew_seconds:g}s tolerance"
            ),
            timestamp_outlier_packets=timestamp_outliers,
        )
    result = analyze_udp_packets(analyzed_packets, config)
    apply_source_device_fallback(result, path, config)
    result.packets_read = packets_read
    result.udp_packets_seen = len(udp_packets)
    result.timestamp_outlier_packets = timestamp_outliers
    return result


def esc_label(value: object) -> str:
    """Escape one Prometheus label value."""
    text = "" if value is None else str(value)
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def label_text(labels: Mapping[str, str]) -> str:
    """Render sorted Prometheus labels for deterministic output."""
    return ",".join(f'{key}="{esc_label(labels[key])}"' for key in sorted(labels))


def emit_metric(name: str, labels: Mapping[str, str], value: float | int | None) -> str:
    """Render one Prometheus sample, omitting absent values."""
    if value is None:
        return ""
    return f"{name}{{{label_text(labels)}}} {value}\n"


def render_prometheus(result: AnalysisResult) -> str:
    """Render low-cardinality Prometheus snapshot gauges."""

    lines = [
        "# HELP vocera_media_active_streams Active media streams observed in the analyzed capture window.\n",
        "# TYPE vocera_media_active_streams gauge\n",
        "# HELP vocera_media_packets_observed UDP packets observed in the analyzed capture window.\n",
        "# TYPE vocera_media_packets_observed gauge\n",
        "# HELP vocera_media_bytes_observed UDP bytes observed in the analyzed capture window.\n",
        "# TYPE vocera_media_bytes_observed gauge\n",
        "# HELP vocera_media_rtp_packets_observed RTP packets observed in streams with visible RTP headers.\n",
        "# TYPE vocera_media_rtp_packets_observed gauge\n",
        "# HELP vocera_media_rtp_lost_packets_estimated Estimated RTP packets lost within the analyzed capture window.\n",
        "# TYPE vocera_media_rtp_lost_packets_estimated gauge\n",
        "# HELP vocera_media_rtp_duplicate_packets RTP duplicate packets observed in the analyzed capture window.\n",
        "# TYPE vocera_media_rtp_duplicate_packets gauge\n",
        "# HELP vocera_media_rtp_out_of_order_packets RTP out-of-order packets observed in the analyzed capture window.\n",
        "# TYPE vocera_media_rtp_out_of_order_packets gauge\n",
        "# HELP vocera_media_rtp_loss_ratio Estimated RTP packet loss ratio over the analyzed capture window.\n",
        "# TYPE vocera_media_rtp_loss_ratio gauge\n",
        "# HELP vocera_media_rtp_jitter_ms RFC 3550 receiver-side RTP interarrival jitter in milliseconds.\n",
        "# TYPE vocera_media_rtp_jitter_ms gauge\n",
        "# HELP vocera_media_interarrival_gap_p50_ms Median observed packet interarrival gap in milliseconds.\n",
        "# TYPE vocera_media_interarrival_gap_p50_ms gauge\n",
        "# HELP vocera_media_interarrival_gap_p95_ms p95 observed packet interarrival gap in milliseconds.\n",
        "# TYPE vocera_media_interarrival_gap_p95_ms gauge\n",
        "# HELP vocera_media_interarrival_gap_max_ms Maximum observed packet interarrival gap in milliseconds.\n",
        "# TYPE vocera_media_interarrival_gap_max_ms gauge\n",
        "# HELP vocera_media_dscp_mismatch_streams Streams whose dominant DSCP does not match configured expected DSCP.\n",
        "# TYPE vocera_media_dscp_mismatch_streams gauge\n",
        "# HELP vocera_media_non_rtp_udp_streams UDP streams without enough visible RTP header evidence.\n",
        "# TYPE vocera_media_non_rtp_udp_streams gauge\n",
        "# HELP vocera_media_rtp_unknown_clock_streams RTP streams whose payload type lacks a configured clock rate. Jitter for these streams uses the fallback default clock and may be wrong (e.g. 2x off for a 16 kHz codec on the 8 kHz default).\n",
        "# TYPE vocera_media_rtp_unknown_clock_streams gauge\n",
        "# HELP vocera_media_rtp_plausible_streams RTP-looking streams that passed plausibility checks and were promoted to trusted RTP QoE.\n",
        "# TYPE vocera_media_rtp_plausible_streams gauge\n",
        "# HELP vocera_media_rtp_candidate_rejected_streams RTP-looking streams rejected by plausibility checks, broken down by controlled reason.\n",
        "# TYPE vocera_media_rtp_candidate_rejected_streams gauge\n",
        "# HELP vocera_media_rtp_candidate_rejected_packets RTP-looking packets rejected by plausibility checks, broken down by controlled reason.\n",
        "# TYPE vocera_media_rtp_candidate_rejected_packets gauge\n",
        "# HELP vocera_media_last_capture_timestamp_seconds Latest packet timestamp seen in the analyzed capture window.\n",
        "# TYPE vocera_media_last_capture_timestamp_seconds gauge\n",
        "# HELP vocera_media_timestamp_outlier_packets UDP packets ignored because their pcap timestamp is later than collector time plus configured tolerance.\n",
        "# TYPE vocera_media_timestamp_outlier_packets gauge\n",
        "# HELP vocera_media_capture_parse_success 1 when the capture parsed successfully, otherwise 0.\n",
        "# TYPE vocera_media_capture_parse_success gauge\n",
    ]

    aggregate: dict[tuple[tuple[str, str], ...], dict[str, float]] = defaultdict(lambda: defaultdict(float))
    jitter_values: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
    gap_p50_values: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
    gap_p95_values: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
    gap_max_values: dict[tuple[tuple[str, str], ...], list[float]] = defaultdict(list)
    rejected_by_reason: dict[tuple[tuple[str, str], ...], dict[str, float]] = defaultdict(lambda: defaultdict(float))

    for stream in result.streams:
        labels = tuple(sorted(stream.prometheus_labels().items()))
        data = aggregate[labels]
        data["active_streams"] += 1
        data["packets_observed"] += stream.packet_count
        data["bytes_observed"] += stream.byte_count
        if stream.measurement_mode == "rtp":
            data["rtp_plausible_streams"] += 1
            data["rtp_packets_observed"] += stream.packet_count
            data["rtp_expected_packets"] += stream.expected_packets or stream.packet_count
            data["rtp_lost_packets_estimated"] += stream.lost_packets or 0
            data["rtp_duplicate_packets"] += stream.duplicate_packets
            data["rtp_out_of_order_packets"] += stream.out_of_order_packets
            if not stream.clock_rate_known:
                data["rtp_unknown_clock_streams"] += 1
            if stream.jitter_ms is not None:
                jitter_values[labels].append(stream.jitter_ms)
        else:
            data["non_rtp_udp_streams"] += 1
            if stream.measurement_mode == "rtp_candidate_rejected":
                reasons = stream.rtp_rejection_reasons or ["unknown_rejection"]
                for reason in reasons:
                    reason_labels = tuple(sorted({**dict(labels), "reason": reason}.items()))
                    rejected_by_reason[reason_labels]["streams"] += 1
                    rejected_by_reason[reason_labels]["packets"] += stream.packet_count
        if stream.dscp_mismatch:
            data["dscp_mismatch_streams"] += 1
        if stream.interarrival_p50_ms is not None:
            gap_p50_values[labels].append(stream.interarrival_p50_ms)
        if stream.interarrival_p95_ms is not None:
            gap_p95_values[labels].append(stream.interarrival_p95_ms)
        if stream.interarrival_max_ms is not None:
            gap_max_values[labels].append(stream.interarrival_max_ms)

    for labels_tuple, data in aggregate.items():
        labels = dict(labels_tuple)
        lines.append(emit_metric("vocera_media_active_streams", labels, data["active_streams"]))
        lines.append(emit_metric("vocera_media_packets_observed", labels, data["packets_observed"]))
        lines.append(emit_metric("vocera_media_bytes_observed", labels, data["bytes_observed"]))
        if data.get("rtp_packets_observed", 0):
            lines.append(emit_metric("vocera_media_rtp_packets_observed", labels, data.get("rtp_packets_observed", 0)))
            lines.append(
                emit_metric(
                    "vocera_media_rtp_lost_packets_estimated",
                    labels,
                    data.get("rtp_lost_packets_estimated", 0),
                )
            )
            lines.append(emit_metric("vocera_media_rtp_duplicate_packets", labels, data.get("rtp_duplicate_packets", 0)))
            lines.append(
                emit_metric(
                    "vocera_media_rtp_out_of_order_packets",
                    labels,
                    data.get("rtp_out_of_order_packets", 0),
                )
            )
            expected = data.get("rtp_expected_packets", 0)
            loss_ratio = (data.get("rtp_lost_packets_estimated", 0) / expected) if expected else None
            lines.append(emit_metric("vocera_media_rtp_loss_ratio", labels, loss_ratio))
            lines.append(emit_metric("vocera_media_rtp_jitter_ms", labels, percentile(jitter_values[labels_tuple], 0.5)))
        lines.append(
            emit_metric(
                "vocera_media_interarrival_gap_p50_ms",
                labels,
                percentile(gap_p50_values[labels_tuple], 0.5),
            )
        )
        lines.append(
            emit_metric(
                "vocera_media_interarrival_gap_p95_ms",
                labels,
                percentile(gap_p95_values[labels_tuple], 0.95),
            )
        )
        lines.append(
            emit_metric(
                "vocera_media_interarrival_gap_max_ms",
                labels,
                max(gap_max_values[labels_tuple]) if gap_max_values[labels_tuple] else None,
            )
        )
        lines.append(emit_metric("vocera_media_dscp_mismatch_streams", labels, data.get("dscp_mismatch_streams", 0)))
        if data.get("non_rtp_udp_streams", 0):
            lines.append(emit_metric("vocera_media_non_rtp_udp_streams", labels, data.get("non_rtp_udp_streams", 0)))
        if data.get("rtp_plausible_streams", 0):
            lines.append(emit_metric("vocera_media_rtp_plausible_streams", labels, data.get("rtp_plausible_streams", 0)))
        if data.get("rtp_unknown_clock_streams", 0):
            lines.append(
                emit_metric(
                    "vocera_media_rtp_unknown_clock_streams",
                    labels,
                    data.get("rtp_unknown_clock_streams", 0),
                )
            )

    for labels_tuple, data in rejected_by_reason.items():
        labels = dict(labels_tuple)
        lines.append(emit_metric("vocera_media_rtp_candidate_rejected_streams", labels, data.get("streams", 0)))
        lines.append(emit_metric("vocera_media_rtp_candidate_rejected_packets", labels, data.get("packets", 0)))

    health_labels = {"capture_point": "unknown", "server": "unknown", "site": "unknown"}
    if result.streams:
        first = result.streams[0]
        health_labels = {
            "capture_point": first.capture_point,
            "server": first.server,
            "site": first.site,
        }
    lines.append(
        emit_metric(
            "vocera_media_last_capture_timestamp_seconds",
            health_labels,
            result.last_capture_timestamp_seconds,
        )
    )
    lines.append(emit_metric("vocera_media_timestamp_outlier_packets", health_labels, result.timestamp_outlier_packets))
    lines.append(emit_metric("vocera_media_capture_parse_success", health_labels, result.parse_success))
    return "".join(line for line in lines if line)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for offline pcap analysis."""
    parser = argparse.ArgumentParser(description="Analyze Vocera media QoE from an offline pcap.")
    parser.add_argument("--pcap", required=True, help="Input classic pcap file.")
    parser.add_argument("--config", help="Optional YAML/JSON analyzer config.")
    parser.add_argument("--prom-out", default="data/vocera-media-qoe/out/vocera_media_qoe.prom")
    parser.add_argument("--json-out", default="data/vocera-media-qoe/out/vocera_media_qoe_summary.json")
    parser.add_argument("--archive-dir", help="Directory for per-run ZIP archives. Defaults beside --json-out.")
    parser.add_argument("--no-archive", action="store_true", help="Disable per-run ZIP archive creation.")
    parser.add_argument("--no-json", action="store_true", help="Do not write a JSON summary.")
    parser.add_argument("--rtp-debug", action="store_true", help="Write detailed RTP candidate debug JSON.")
    parser.add_argument("--rtp-debug-out", help="RTP debug JSON output path. Defaults beside --json-out.")
    parser.add_argument("--print", action="store_true", help="Print Prometheus output to stdout.")
    return parser.parse_args(argv)


def _archive_offline_run(args: argparse.Namespace, result: AnalysisResult) -> Path | None:
    """Archive an offline single-pcap parser run unless disabled."""
    if args.no_archive:
        return None
    archive_dir = Path(args.archive_dir) if args.archive_dir else Path(args.json_out).parent / "archives"
    inputs: list[Path] = [Path(args.pcap)]
    if args.config:
        inputs.append(Path(args.config))
    outputs: list[Path] = [Path(args.prom_out)]
    if not args.no_json:
        outputs.append(Path(args.json_out))
    if args.rtp_debug:
        outputs.append(Path(args.rtp_debug_out) if args.rtp_debug_out else Path(args.json_out).with_name("vocera_media_qoe_rtp_debug.json"))
    log_lines = [
        "Vocera media QoE offline parser run",
        f"pcap={args.pcap}",
        f"config={args.config or '<default>'}",
        f"prom_out={args.prom_out}",
        f"json_out={'<disabled>' if args.no_json else args.json_out}",
        f"rtp_debug_out={args.rtp_debug_out or '<disabled>'}",
        f"parse_success={result.parse_success}",
        f"packets_read={result.packets_read}",
        f"udp_packets_seen={result.udp_packets_seen}",
        f"stream_count={len(result.streams)}",
    ]
    if result.error:
        log_lines.append(f"error={result.error}")
    return create_run_archive(
        archive_dir=archive_dir,
        workflow="vocera_media_qoe_icap_offline",
        command="vocera_media_qoe",
        inputs=inputs,
        outputs=outputs,
        metadata={
            "parse_success": result.parse_success,
            "packets_read": result.packets_read,
            "udp_packets_seen": result.udp_packets_seen,
            "timestamp_outlier_packets": result.timestamp_outlier_packets,
            "stream_count": len(result.streams),
        },
        log_lines=log_lines,
        label=Path(args.pcap).stem,
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for offline single-pcap media analysis."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config(args.config)
        result = analyze_pcap(args.pcap, config)
    except Exception as exc:
        result = AnalysisResult(
            streams=[],
            packets_read=0,
            udp_packets_seen=0,
            last_capture_timestamp_seconds=None,
            parse_success=0,
            error=str(exc),
        )

    prom = render_prometheus(result)
    write_text(args.prom_out, prom)
    if not args.no_json:
        write_text(args.json_out, json.dumps(result.to_json(), indent=2, sort_keys=True))
    if args.rtp_debug:
        debug_out = Path(args.rtp_debug_out) if args.rtp_debug_out else Path(args.json_out).with_name("vocera_media_qoe_rtp_debug.json")
        write_text(debug_out, json.dumps(result.to_rtp_debug_json(), indent=2, sort_keys=True))
    archive_path = _archive_offline_run(args, result)
    if archive_path is not None:
        print(f"Archived parser inputs and outputs to {archive_path}", file=sys.stderr)
    if args.print:
        print(prom, end="")
    if result.parse_success:
        print(f"Analyzed {len(result.streams)} media streams from {args.pcap}")
        return 0
    print(f"Failed to analyze {args.pcap}: {result.error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
