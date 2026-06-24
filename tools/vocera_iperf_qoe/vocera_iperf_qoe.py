#!/usr/bin/env python3
"""Convert uploaded Vocera iperf3 JSON results into Prometheus textfile metrics."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import socket
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from tools.common.config import load_mapping_config
    from tools.common.files import write_text
    from tools.common.prometheus import emit_metric as common_emit_metric
    from tools.common.prometheus import escape_label, format_labels
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.common.config import load_mapping_config
    from tools.common.files import write_text
    from tools.common.prometheus import emit_metric as common_emit_metric
    from tools.common.prometheus import escape_label, format_labels


DEFAULT_INCOMING_ROOT = "/var/lib/vocera-iperf-qoe/incoming"
TEMP_IPERF_SUFFIX = ".iperf.json"
RESULT_FILENAME_RE = re.compile(r"^(?P<direction>.+)-\d{8}-\d{6}$")


@dataclass(frozen=True)
class IperfResult:
    """One parsed iperf3 result and its safe Prometheus labels."""

    path: str
    device: str
    site: str
    ssid: str
    role: str
    mode: str
    direction: str
    target: str
    target_name: str
    target_port: str
    protocol: str
    reverse: str
    tos: str
    timestamp_seconds: float
    up: int
    seconds: float | None
    bytes: float | None
    bits_per_second: float | None
    jitter_ms: float | None
    lost_packets: float | None
    packets: float | None
    lost_percent: float | None
    raw_latency_seconds: float | None
    configured_duration_seconds: float | None
    configured_bitrate_bits_per_second: float | None
    payload_bytes: float | None
    error: str = ""

    @property
    def labels(self) -> dict[str, str]:
        """Return the stable Prometheus label set for this result series."""

        return {
            "device": self.device,
            "site": self.site,
            "ssid": self.ssid,
            "role": self.role,
            "mode": self.mode,
            "direction": self.direction,
            "target": self.target,
            "target_name": self.target_name,
            "target_port": self.target_port,
            "protocol": self.protocol,
            "reverse": self.reverse,
            "tos": self.tos,
        }

    @property
    def series_key(self) -> tuple[tuple[str, str], ...]:
        """Return the de-duplication key used to keep only the newest series sample."""

        return tuple(sorted(self.labels.items()))

    @property
    def last_success_timestamp_seconds(self) -> float:
        """Return the run timestamp only for successful iperf results."""

        return self.timestamp_seconds if self.up else 0.0

    def to_json(self) -> dict[str, Any]:
        """Serialize the parsed result for the debug JSON summary."""

        return {
            "path": self.path,
            "device": self.device,
            "site": self.site,
            "ssid": self.ssid,
            "role": self.role,
            "mode": self.mode,
            "direction": self.direction,
            "target": self.target,
            "target_name": self.target_name,
            "target_port": self.target_port,
            "protocol": self.protocol,
            "reverse": self.reverse,
            "tos": self.tos,
            "timestamp_seconds": self.timestamp_seconds,
            "up": self.up,
            "seconds": self.seconds,
            "bytes": self.bytes,
            "bits_per_second": self.bits_per_second,
            "jitter_ms": self.jitter_ms,
            "lost_packets": self.lost_packets,
            "packets": self.packets,
            "lost_percent": self.lost_percent,
            "raw_latency_seconds": self.raw_latency_seconds,
            "configured_duration_seconds": self.configured_duration_seconds,
            "configured_bitrate_bits_per_second": self.configured_bitrate_bits_per_second,
            "payload_bytes": self.payload_bytes,
            "error": self.error,
        }


@dataclass(frozen=True)
class ScanResult:
    """Whole incoming-directory scan result."""

    incoming_root: str
    collector: str
    scan_timestamp_seconds: float
    files_seen: int
    parsed_files: int
    ignored_temp_files: int
    parse_errors: int
    latest_results: list[IperfResult]

    def to_json(self) -> dict[str, Any]:
        """Serialize the whole scan result for operator inspection."""

        return {
            "incoming_root": self.incoming_root,
            "collector": self.collector,
            "scan_timestamp_seconds": self.scan_timestamp_seconds,
            "files_seen": self.files_seen,
            "parsed_files": self.parsed_files,
            "ignored_temp_files": self.ignored_temp_files,
            "parse_errors": self.parse_errors,
            "latest_results": [result.to_json() for result in self.latest_results],
        }


def load_config(path: str | Path | None) -> dict[str, Any]:
    """Load an optional YAML/JSON config file."""

    return load_mapping_config(
        path,
        allow_missing=True,
        description="Vocera iperf QoE config",
    )


def esc_label(value: object) -> str:
    """Escape a value for Prometheus label syntax."""

    return escape_label(value, none_value="unknown", empty_value="unknown")


def label_text(labels: Mapping[str, str]) -> str:
    """Render sorted Prometheus labels so output is deterministic."""

    return format_labels(labels, sort=True, none_value="unknown", empty_value="unknown")


def emit_metric(name: str, labels: Mapping[str, str], value: float | int | None) -> str:
    """Render one Prometheus metric sample, omitting unavailable values."""

    return common_emit_metric(
        name,
        labels,
        value,
        sort_labels=True,
        none_label_value="unknown",
        empty_label_value="unknown",
    )


def divide(value: float | None, divisor: float) -> float | None:
    """Safely divide an optional metric value for unit conversion."""

    if value is None:
        return None
    return value / divisor


def as_mapping(value: object) -> Mapping[str, Any]:
    """Return a mapping value or an empty mapping for loose JSON traversal."""

    return value if isinstance(value, Mapping) else {}


def first_mapping(items: object) -> Mapping[str, Any]:
    """Return the first mapping in an iperf array field."""

    if isinstance(items, list) and items and isinstance(items[0], Mapping):
        return items[0]
    return {}


def number(value: object) -> float | None:
    """Parse a JSON scalar into a float when possible."""

    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def text_value(value: object, default: str = "unknown") -> str:
    """Return non-empty text or a caller-provided label default."""

    if value is None or value == "":
        return default
    return str(value)


def parse_rate_bits_per_second(value: object) -> float | None:
    """Parse iperf-style bitrate strings such as 64K or 1.5M as bits/s."""

    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    multiplier = 1.0
    suffix = text[-1].lower()
    if suffix in {"k", "m", "g"}:
        text = text[:-1]
        multiplier = {"k": 1_000.0, "m": 1_000_000.0, "g": 1_000_000_000.0}[suffix]
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def latency_seconds_from_metadata(metadata: Mapping[str, Any]) -> float | None:
    """Return raw latency/RTT seconds when the laptop wrapper provides it."""

    second_keys = (
        "raw_latency_seconds",
        "latency_seconds",
        "rtt_seconds",
        "ping_rtt_seconds",
    )
    millisecond_keys = (
        "raw_latency_ms",
        "latency_ms",
        "rtt_ms",
        "ping_rtt_ms",
        "ping_avg_ms",
        "ping_rtt_avg_ms",
    )
    for key in second_keys:
        value = number(metadata.get(key))
        if value is not None:
            return value
    for key in millisecond_keys:
        value = number(metadata.get(key))
        if value is not None:
            return value / 1000.0
    return None


def direction_from_filename(path: Path) -> str:
    """Infer direction from wrapper filenames like upstream-YYYYMMDD-HHMMSS.json."""

    name = path.name
    if name.endswith(".json"):
        name = name[:-5]
    match = RESULT_FILENAME_RE.match(name)
    if match:
        return match.group("direction")
    return "unknown"


def device_from_path(path: Path, incoming_root: Path) -> str:
    """Infer device id from the incoming DEVICE/raw/*.json layout."""

    try:
        rel = path.relative_to(incoming_root)
    except ValueError:
        rel = path
    if len(rel.parts) >= 3 and rel.parts[1] == "raw":
        return rel.parts[0]
    if len(path.parents) >= 2:
        return path.parent.parent.name
    return "unknown"


def timestamp_from_filename(path: Path) -> float | None:
    """Parse wrapper timestamps from filenames as local-time epoch seconds."""

    stem = path.name[:-5] if path.name.endswith(".json") else path.stem
    if "-" not in stem:
        return None
    value = stem.rsplit("-", 1)[1]
    try:
        parsed = dt.datetime.strptime(value, "%Y%m%d-%H%M%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=dt.datetime.now().astimezone().tzinfo).timestamp()


def target_config(config: Mapping[str, Any], target: str, target_port: str) -> Mapping[str, Any]:
    """Return optional target metadata by host:port, then by host."""

    targets = as_mapping(config.get("targets"))
    endpoint_keys = [f"{target}:{target_port}", target]
    for key in endpoint_keys:
        value = targets.get(key)
        if isinstance(value, Mapping):
            return value
        if isinstance(value, str):
            return {"name": value}
    return {}


def device_config(config: Mapping[str, Any], device: str) -> Mapping[str, Any]:
    """Return optional per-device label defaults from config."""

    return as_mapping(as_mapping(config.get("devices")).get(device))


def parse_iperf_result(path: Path, incoming_root: Path, config: Mapping[str, Any]) -> IperfResult:
    """Parse one completed iperf JSON result."""

    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, Mapping):
        raise RuntimeError("top-level JSON payload is not an object")

    iperf = as_mapping(payload.get("iperf3")) or payload
    metadata = as_mapping(payload.get("metadata"))
    start = as_mapping(iperf.get("start"))
    end = as_mapping(iperf.get("end"))
    connected = first_mapping(start.get("connected"))
    test_start = as_mapping(start.get("test_start"))
    connecting_to = as_mapping(start.get("connecting_to"))
    # For UDP `iperf3 -J --reverse`, jitter_ms and lost_packets live only in
    # `sum_received` (the receiver side); `sum_sent` lacks them. Prefer
    # `sum_received` over `sum` so reverse runs report real jitter/loss rather
    # than the sender-side roll-up.
    summary = (
        as_mapping(end.get("sum_received"))
        or as_mapping(end.get("sum"))
        or as_mapping(end.get("sum_sent"))
    )

    device = text_value(metadata.get("device"), device_from_path(path, incoming_root))
    dev_cfg = device_config(config, device)
    target = text_value(metadata.get("target"), text_value(connecting_to.get("host"), text_value(connected.get("remote_host"))))
    target_port = text_value(metadata.get("target_port"), text_value(connecting_to.get("port"), text_value(connected.get("remote_port"))))
    tgt_cfg = target_config(config, target, target_port)

    timestamp = number(as_mapping(start.get("timestamp")).get("timesecs"))
    if timestamp is None:
        timestamp = timestamp_from_filename(path)
    if timestamp is None:
        timestamp = path.stat().st_mtime

    error = text_value(iperf.get("error") or payload.get("error"), "")
    up = 1 if not error and summary else 0
    protocol = text_value(test_start.get("protocol"))
    reverse = "1" if int(number(test_start.get("reverse")) or 0) else "0"

    return IperfResult(
        path=str(path),
        device=device,
        site=text_value(metadata.get("site"), text_value(dev_cfg.get("site"))),
        ssid=text_value(metadata.get("ssid"), text_value(dev_cfg.get("ssid"))),
        role=text_value(metadata.get("role"), text_value(dev_cfg.get("role"))),
        mode=text_value(metadata.get("mode"), text_value(dev_cfg.get("mode"))),
        direction=text_value(metadata.get("direction"), direction_from_filename(path)),
        target=target,
        target_name=text_value(metadata.get("target_name"), text_value(tgt_cfg.get("name"), target)),
        target_port=target_port,
        protocol=protocol,
        reverse=reverse,
        tos=text_value(metadata.get("tos"), text_value(dev_cfg.get("tos"))),
        timestamp_seconds=timestamp,
        up=up,
        seconds=number(summary.get("seconds") or summary.get("end")),
        bytes=number(summary.get("bytes")),
        bits_per_second=number(summary.get("bits_per_second")),
        jitter_ms=number(summary.get("jitter_ms")),
        lost_packets=number(summary.get("lost_packets")),
        packets=number(summary.get("packets")),
        lost_percent=number(summary.get("lost_percent")),
        raw_latency_seconds=latency_seconds_from_metadata(metadata),
        configured_duration_seconds=number(metadata.get("duration_seconds") or test_start.get("duration")),
        configured_bitrate_bits_per_second=parse_rate_bits_per_second(metadata.get("bitrate")),
        payload_bytes=number(metadata.get("payload_bytes") or test_start.get("blksize")),
        error=error,
    )


def candidate_files(incoming_root: Path) -> Iterable[Path]:
    """Return completed JSON files under the incoming root."""

    if not incoming_root.exists():
        return []
    return sorted(path for path in incoming_root.rglob("*.json") if path.is_file())


def scan_incoming(
    incoming_root: str | Path,
    config: Mapping[str, Any],
    *,
    now: float | None = None,
) -> ScanResult:
    """Scan uploaded JSON and keep the newest parsed result for each series."""

    root = Path(incoming_root)
    scan_time = time.time() if now is None else now
    latest: dict[tuple[tuple[str, str], ...], IperfResult] = {}
    files_seen = 0
    parsed_files = 0
    ignored_temp_files = 0
    parse_errors = 0

    for path in candidate_files(root):
        files_seen += 1
        if path.name.endswith(TEMP_IPERF_SUFFIX):
            ignored_temp_files += 1
            continue
        try:
            result = parse_iperf_result(path, root, config)
        except Exception:
            parse_errors += 1
            continue
        parsed_files += 1
        previous = latest.get(result.series_key)
        if previous is None or result.timestamp_seconds >= previous.timestamp_seconds:
            latest[result.series_key] = result

    collector = text_value(config.get("collector"), socket.gethostname())
    return ScanResult(
        incoming_root=str(root),
        collector=collector,
        scan_timestamp_seconds=scan_time,
        files_seen=files_seen,
        parsed_files=parsed_files,
        ignored_temp_files=ignored_temp_files,
        parse_errors=parse_errors,
        latest_results=sorted(latest.values(), key=lambda item: item.series_key),
    )


def render_prometheus(scan: ScanResult) -> str:
    """Render latest iperf results into node-exporter textfile format."""

    lines = [
        "# HELP vocera_iperf_up 1 when the latest iperf result completed successfully.\n",
        "# TYPE vocera_iperf_up gauge\n",
        "# HELP vocera_iperf_throughput_bytes_per_second Measured throughput from the latest iperf summary.\n",
        "# TYPE vocera_iperf_throughput_bytes_per_second gauge\n",
        "# HELP vocera_iperf_jitter_seconds UDP jitter in seconds from the latest iperf summary.\n",
        "# TYPE vocera_iperf_jitter_seconds gauge\n",
        "# HELP vocera_iperf_raw_latency_seconds Raw latency or RTT in seconds from companion laptop-side measurement.\n",
        "# TYPE vocera_iperf_raw_latency_seconds gauge\n",
        "# HELP vocera_iperf_lost_packets UDP packets lost in the latest iperf summary.\n",
        "# TYPE vocera_iperf_lost_packets gauge\n",
        "# HELP vocera_iperf_packets UDP packets reported in the latest iperf summary.\n",
        "# TYPE vocera_iperf_packets gauge\n",
        "# HELP vocera_iperf_loss_ratio UDP packet loss ratio from the latest iperf summary.\n",
        "# TYPE vocera_iperf_loss_ratio gauge\n",
        "# HELP vocera_iperf_transferred_bytes Bytes transferred in the latest iperf summary.\n",
        "# TYPE vocera_iperf_transferred_bytes gauge\n",
        "# HELP vocera_iperf_duration_seconds Measured duration in seconds from the latest iperf summary.\n",
        "# TYPE vocera_iperf_duration_seconds gauge\n",
        "# HELP vocera_iperf_configured_duration_seconds Configured iperf test duration in seconds.\n",
        "# TYPE vocera_iperf_configured_duration_seconds gauge\n",
        "# HELP vocera_iperf_configured_bitrate_bytes_per_second Configured iperf target bitrate in bytes per second.\n",
        "# TYPE vocera_iperf_configured_bitrate_bytes_per_second gauge\n",
        "# HELP vocera_iperf_payload_bytes Configured UDP payload size in bytes.\n",
        "# TYPE vocera_iperf_payload_bytes gauge\n",
        "# HELP vocera_iperf_last_run_timestamp_seconds Unix timestamp for the latest iperf run.\n",
        "# TYPE vocera_iperf_last_run_timestamp_seconds gauge\n",
        "# HELP vocera_iperf_last_success_timestamp_seconds Unix timestamp for the latest successful iperf run.\n",
        "# TYPE vocera_iperf_last_success_timestamp_seconds gauge\n",
        "# HELP vocera_iperf_result_age_seconds Age in seconds of the latest iperf result at exporter scan time.\n",
        "# TYPE vocera_iperf_result_age_seconds gauge\n",
        "# HELP vocera_iperf_scan_files_seen Completed and temporary JSON files seen during the scan.\n",
        "# TYPE vocera_iperf_scan_files_seen gauge\n",
        "# HELP vocera_iperf_scan_parsed_files Completed JSON files parsed during the scan.\n",
        "# TYPE vocera_iperf_scan_parsed_files gauge\n",
        "# HELP vocera_iperf_scan_ignored_temp_files Temporary .iperf.json files ignored during the scan.\n",
        "# TYPE vocera_iperf_scan_ignored_temp_files gauge\n",
        "# HELP vocera_iperf_scan_parse_errors JSON files that could not be parsed during the scan.\n",
        "# TYPE vocera_iperf_scan_parse_errors gauge\n",
        "# HELP vocera_iperf_scan_latest_results Latest result series published by this scan.\n",
        "# TYPE vocera_iperf_scan_latest_results gauge\n",
        "# HELP vocera_iperf_scan_timestamp_seconds Unix timestamp for this exporter scan.\n",
        "# TYPE vocera_iperf_scan_timestamp_seconds gauge\n",
    ]

    for result in scan.latest_results:
        labels = result.labels
        lines.append(emit_metric("vocera_iperf_up", labels, result.up))
        lines.append(emit_metric("vocera_iperf_throughput_bytes_per_second", labels, divide(result.bits_per_second, 8.0)))
        lines.append(emit_metric("vocera_iperf_jitter_seconds", labels, divide(result.jitter_ms, 1000.0)))
        lines.append(emit_metric("vocera_iperf_raw_latency_seconds", labels, result.raw_latency_seconds))
        lines.append(emit_metric("vocera_iperf_lost_packets", labels, result.lost_packets))
        lines.append(emit_metric("vocera_iperf_packets", labels, result.packets))
        lines.append(emit_metric("vocera_iperf_loss_ratio", labels, divide(result.lost_percent, 100.0)))
        lines.append(emit_metric("vocera_iperf_transferred_bytes", labels, result.bytes))
        lines.append(emit_metric("vocera_iperf_duration_seconds", labels, result.seconds))
        lines.append(emit_metric("vocera_iperf_configured_duration_seconds", labels, result.configured_duration_seconds))
        lines.append(
            emit_metric(
                "vocera_iperf_configured_bitrate_bytes_per_second",
                labels,
                divide(result.configured_bitrate_bits_per_second, 8.0),
            )
        )
        lines.append(emit_metric("vocera_iperf_payload_bytes", labels, result.payload_bytes))
        lines.append(emit_metric("vocera_iperf_last_run_timestamp_seconds", labels, result.timestamp_seconds))
        lines.append(
            emit_metric(
                "vocera_iperf_last_success_timestamp_seconds",
                labels,
                result.last_success_timestamp_seconds,
            )
        )
        lines.append(
            emit_metric(
                "vocera_iperf_result_age_seconds",
                labels,
                max(0.0, scan.scan_timestamp_seconds - result.timestamp_seconds),
            )
        )

    scan_labels = {"collector": scan.collector}
    lines.append(emit_metric("vocera_iperf_scan_files_seen", scan_labels, scan.files_seen))
    lines.append(emit_metric("vocera_iperf_scan_parsed_files", scan_labels, scan.parsed_files))
    lines.append(emit_metric("vocera_iperf_scan_ignored_temp_files", scan_labels, scan.ignored_temp_files))
    lines.append(emit_metric("vocera_iperf_scan_parse_errors", scan_labels, scan.parse_errors))
    lines.append(emit_metric("vocera_iperf_scan_latest_results", scan_labels, len(scan.latest_results)))
    lines.append(emit_metric("vocera_iperf_scan_timestamp_seconds", scan_labels, scan.scan_timestamp_seconds))
    return "".join(line for line in lines if line)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse Vocera iperf QoE exporter CLI arguments."""

    parser = argparse.ArgumentParser(description="Publish Vocera iperf QoE JSON uploads as Prometheus textfile metrics.")
    parser.add_argument("--config", default="config/vocera-iperf-qoe.example.yaml", help="Optional YAML/JSON config.")
    parser.add_argument("--incoming-root", default=DEFAULT_INCOMING_ROOT, help="Root containing DEVICE/raw/*.json uploads.")
    parser.add_argument("--prom-out", default="data/vocera-iperf-qoe/out/vocera_iperf_qoe.prom")
    parser.add_argument("--json-out", default="data/vocera-iperf-qoe/out/vocera_iperf_qoe_summary.json")
    parser.add_argument("--no-json", action="store_true", help="Do not write a JSON scan summary.")
    parser.add_argument("--print", action="store_true", help="Also print Prometheus output to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Scan uploaded iperf JSON files and publish Prometheus/JSON outputs."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        config = load_config(args.config)
        scan = scan_incoming(args.incoming_root, config)
    except Exception as exc:
        print(f"Failed to scan Vocera iperf QoE results: {exc}", file=sys.stderr)
        return 1

    prom = render_prometheus(scan)
    write_text(args.prom_out, prom)
    if not args.no_json:
        write_text(args.json_out, json.dumps(scan.to_json(), indent=2, sort_keys=True))
    if args.print:
        print(prom, end="")

    print(f"Published {len(scan.latest_results)} latest iperf result series from {scan.parsed_files} parsed files")
    print(f"Prom: {args.prom_out}")
    if not args.no_json:
        print(f"JSON: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
