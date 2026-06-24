#!/usr/bin/env python3
"""Run path RTT probes and render Prometheus textfile metrics."""

from __future__ import annotations

import argparse
import math
import re
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

try:
    from tools.common.config import load_mapping_config
    from tools.common.files import write_json, write_text
    from tools.common.prometheus import emit_metric, escape_label, format_labels
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.common.config import load_mapping_config
    from tools.common.files import write_json, write_text
    from tools.common.prometheus import emit_metric, escape_label, format_labels


LINUX_PACKET_RE = re.compile(
    r"(?P<sent>\d+)\s+packets transmitted,\s+"
    r"(?P<received>\d+)(?:\s+packets)?\s+received.*?"
    r"(?P<loss>[0-9.]+)%\s+packet loss",
    re.I | re.S,
)
LINUX_TIME_RE = re.compile(r"time[=<]([0-9.]+)\s*ms")
LINUX_SUMMARY_RE = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s+=\s+"
    r"([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s+ms",
    re.I,
)


@dataclass(frozen=True)
class ProbeStats:
    """One completed probe attempt and the values exported for it."""

    sent: int
    received: int
    loss_pct: float
    rtt_min_ms: float | None
    rtt_avg_ms: float | None
    rtt_max_ms: float | None
    rtt_p95_ms: float | None
    rtt_mdev_ms: float | None
    rtt_pdv_p95_ms: float | None
    rtt_pdv_range_ms: float | None
    # Deprecated compatibility field. This is synthetic RTT variation, not RTP
    # interarrival jitter.
    jitter_ms: float | None
    last_run_timestamp_seconds: float
    last_success_timestamp_seconds: float
    error: str = ""

    @property
    def up(self) -> int:
        """Return 1 when at least one probe packet received a response."""

        return 1 if self.received > 0 else 0


@dataclass(frozen=True)
class ProbeTarget:
    """Configuration and labels for one measured path segment."""

    segment: str
    source: str
    target: str
    target_type: str
    address: str
    method: str = "system_ping"
    count: int = 5
    timeout_seconds: int = 2
    interval_seconds: float = 1.0


@dataclass(frozen=True)
class ProbeResult:
    """Rendered result with the target labels kept beside the measurements."""

    target: ProbeTarget
    stats: ProbeStats


def percentile(values: list[float], q: float) -> float | None:
    """Return a nearest-rank percentile for a small in-process sample set."""

    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def parse_linux_ping_output(text: str, *, now: float | None = None) -> ProbeStats:
    """Parse iputils ping output from collector-originated probes."""

    now = time.time() if now is None else now
    packet_match = LINUX_PACKET_RE.search(text)
    sent = int(packet_match.group("sent")) if packet_match else 0
    received = int(packet_match.group("received")) if packet_match else 0
    loss_pct = float(packet_match.group("loss")) if packet_match else 100.0
    samples = [float(value) for value in LINUX_TIME_RE.findall(text)]

    if samples:
        min_ms = min(samples)
        max_ms = max(samples)
        p95_ms = percentile(samples, 0.95)
        mdev_ms = statistics.pstdev(samples) if len(samples) > 1 else 0.0
        pdv_p95_ms = max(0.0, (p95_ms or min_ms) - min_ms)
        pdv_range_ms = max(0.0, max_ms - min_ms)
        return ProbeStats(
            sent=sent or len(samples),
            received=received or len(samples),
            loss_pct=loss_pct,
            rtt_min_ms=min_ms,
            rtt_avg_ms=sum(samples) / len(samples),
            rtt_max_ms=max_ms,
            rtt_p95_ms=p95_ms,
            rtt_mdev_ms=mdev_ms,
            rtt_pdv_p95_ms=pdv_p95_ms,
            rtt_pdv_range_ms=pdv_range_ms,
            jitter_ms=mdev_ms,
            last_run_timestamp_seconds=now,
            last_success_timestamp_seconds=now,
        )

    summary_match = LINUX_SUMMARY_RE.search(text)
    if summary_match and received > 0:
        min_ms, avg_ms, max_ms, jitter_ms = (float(value) for value in summary_match.groups())
        return ProbeStats(
            sent=sent,
            received=received,
            loss_pct=loss_pct,
            rtt_min_ms=min_ms,
            rtt_avg_ms=avg_ms,
            rtt_max_ms=max_ms,
            rtt_p95_ms=max_ms,
            rtt_mdev_ms=jitter_ms if jitter_ms >= 0 else None,
            rtt_pdv_p95_ms=None,
            rtt_pdv_range_ms=max(0.0, max_ms - min_ms),
            jitter_ms=jitter_ms if jitter_ms >= 0 else None,
            last_run_timestamp_seconds=now,
            last_success_timestamp_seconds=now,
        )

    return ProbeStats(
        sent=sent,
        received=received,
        loss_pct=loss_pct,
        rtt_min_ms=None,
        rtt_avg_ms=None,
        rtt_max_ms=None,
        rtt_p95_ms=None,
        rtt_mdev_ms=None,
        rtt_pdv_p95_ms=None,
        rtt_pdv_range_ms=None,
        jitter_ms=None,
        last_run_timestamp_seconds=now,
        last_success_timestamp_seconds=0,
        error="no ping replies parsed",
    )


def load_config(path: str | Path) -> dict[str, Any]:
    """Load the path probe YAML config."""

    config_path = Path(path)
    payload = load_mapping_config(config_path, description="Path probe config")
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise RuntimeError(f"Path probe config must contain a jobs list: {config_path}")
    return payload


def _merge_defaults(job: Mapping[str, Any], target: Mapping[str, Any]) -> dict[str, Any]:
    """Overlay target-specific probe settings on top of job defaults."""

    merged: dict[str, Any] = {}
    defaults = job.get("defaults")
    if isinstance(defaults, Mapping):
        merged.update(defaults)
    merged.update(target)
    return merged


def _target_from_mapping(job: Mapping[str, Any], target: Mapping[str, Any]) -> ProbeTarget:
    """Validate and materialize one configured probe target."""

    merged = _merge_defaults(job, target)
    missing = [key for key in ("segment", "source", "target", "target_type", "address") if not merged.get(key)]
    if missing:
        raise RuntimeError("Path probe target is missing required fields: " + ", ".join(missing))
    return ProbeTarget(
        segment=str(merged["segment"]),
        source=str(merged["source"]),
        target=str(merged["target"]),
        target_type=str(merged["target_type"]),
        address=str(merged["address"]),
        method=str(merged.get("method") or "system_ping"),
        count=int(merged.get("count") or 5),
        timeout_seconds=int(merged.get("timeout_seconds") or 2),
        interval_seconds=float(merged.get("interval_seconds") or 1.0),
    )


def select_targets(config: Mapping[str, Any], job_name: str | None = None) -> list[ProbeTarget]:
    """Return configured probe targets, optionally narrowed to one job."""

    jobs = [job for job in config.get("jobs", []) if isinstance(job, Mapping)]
    if job_name:
        jobs = [job for job in jobs if job.get("name") == job_name]
        if not jobs:
            raise RuntimeError(f"No path probe job named {job_name!r} found in config.")
    targets: list[ProbeTarget] = []
    for job in jobs:
        configured_targets = job.get("targets") or []
        if not isinstance(configured_targets, list):
            raise RuntimeError(f"Path probe job {job.get('name')!r} must contain a targets list.")
        for target in configured_targets:
            if isinstance(target, Mapping):
                targets.append(_target_from_mapping(job, target))
    return targets


def run_system_ping(target: ProbeTarget, *, now: float | None = None) -> ProbeStats:
    """Run a collector-originated Linux ping probe."""

    command = [
        "ping",
        "-n",
        "-c",
        str(target.count),
        "-W",
        str(target.timeout_seconds),
        "-i",
        str(target.interval_seconds),
        target.address,
    ]
    deadline = max(3.0, target.count * (target.timeout_seconds + target.interval_seconds) + 2)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=deadline,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        run_time = time.time() if now is None else now
        return ProbeStats(
            sent=target.count,
            received=0,
            loss_pct=100.0,
            rtt_min_ms=None,
            rtt_avg_ms=None,
            rtt_max_ms=None,
            rtt_p95_ms=None,
            rtt_mdev_ms=None,
            rtt_pdv_p95_ms=None,
            rtt_pdv_range_ms=None,
            jitter_ms=None,
            last_run_timestamp_seconds=run_time,
            last_success_timestamp_seconds=0,
            error=str(exc),
        )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    stats = parse_linux_ping_output(output, now=now)
    if stats.sent == 0 and stats.received == 0:
        return failed_probe_stats(
            target,
            stats.error or f"ping exited {completed.returncode} without parseable statistics",
            now=stats.last_run_timestamp_seconds,
        )
    if completed.returncode != 0 and not stats.error:
        return ProbeStats(
            sent=stats.sent,
            received=stats.received,
            loss_pct=stats.loss_pct,
            rtt_min_ms=stats.rtt_min_ms,
            rtt_avg_ms=stats.rtt_avg_ms,
            rtt_max_ms=stats.rtt_max_ms,
            rtt_p95_ms=stats.rtt_p95_ms,
            rtt_mdev_ms=stats.rtt_mdev_ms,
            rtt_pdv_p95_ms=stats.rtt_pdv_p95_ms,
            rtt_pdv_range_ms=stats.rtt_pdv_range_ms,
            jitter_ms=stats.jitter_ms,
            last_run_timestamp_seconds=stats.last_run_timestamp_seconds,
            last_success_timestamp_seconds=stats.last_success_timestamp_seconds,
            error=f"ping exited {completed.returncode}",
        )
    return stats


def run_probe(
    target: ProbeTarget,
    *,
    now: float | None = None,
) -> ProbeResult:
    """Run the probe method configured for one target."""

    if target.method == "system_ping":
        return ProbeResult(target=target, stats=run_system_ping(target, now=now))
    raise RuntimeError(f"Unsupported path probe method: {target.method}")


def failed_probe_stats(target: ProbeTarget, error: str, *, now: float | None = None) -> ProbeStats:
    """Represent a probe setup/runtime failure as an exported down sample."""

    run_time = time.time() if now is None else now
    return ProbeStats(
        sent=target.count,
        received=0,
        loss_pct=100.0,
        rtt_min_ms=None,
        rtt_avg_ms=None,
        rtt_max_ms=None,
        rtt_p95_ms=None,
        rtt_mdev_ms=None,
        rtt_pdv_p95_ms=None,
        rtt_pdv_range_ms=None,
        jitter_ms=None,
        last_run_timestamp_seconds=run_time,
        last_success_timestamp_seconds=0,
        error=error,
    )


esc_label = escape_label


def label_text(target: ProbeTarget) -> str:
    """Render the stable path-probe label set."""

    pairs = {
        "segment": target.segment,
        "source": target.source,
        "target": target.target,
        "target_type": target.target_type,
        "method": target.method,
    }
    return format_labels(pairs)


def render_prometheus(results: Iterable[ProbeResult]) -> str:
    """Render probe results into node-exporter textfile exposition format."""

    lines = [
        "# HELP wireless_path_probe_up 1 when the latest path probe received at least one response.\n",
        "# TYPE wireless_path_probe_up gauge\n",
        "# HELP wireless_path_probe_rtt_min_ms Minimum round-trip time in milliseconds for the latest path probe.\n",
        "# TYPE wireless_path_probe_rtt_min_ms gauge\n",
        "# HELP wireless_path_probe_rtt_avg_ms Average round-trip time in milliseconds for the latest path probe.\n",
        "# TYPE wireless_path_probe_rtt_avg_ms gauge\n",
        "# HELP wireless_path_probe_rtt_max_ms Maximum round-trip time in milliseconds for the latest path probe.\n",
        "# TYPE wireless_path_probe_rtt_max_ms gauge\n",
        "# HELP wireless_path_probe_rtt_p95_ms p95 round-trip time in milliseconds for the latest path probe.\n",
        "# TYPE wireless_path_probe_rtt_p95_ms gauge\n",
        "# HELP wireless_path_probe_rtt_mdev_ms Population standard deviation of round-trip samples in milliseconds when individual samples are available.\n",
        "# TYPE wireless_path_probe_rtt_mdev_ms gauge\n",
        "# HELP wireless_path_probe_rtt_pdv_p95_ms RFC 5481-style RTT packet delay variation p95 in milliseconds, calculated as RTT p95 minus minimum RTT when individual samples are available.\n",
        "# TYPE wireless_path_probe_rtt_pdv_p95_ms gauge\n",
        "# HELP wireless_path_probe_rtt_pdv_range_ms RTT packet delay variation range in milliseconds, calculated as max RTT minus min RTT.\n",
        "# TYPE wireless_path_probe_rtt_pdv_range_ms gauge\n",
        "# HELP wireless_path_probe_jitter_ms Deprecated compatibility alias for synthetic RTT variation; not RTP interarrival jitter.\n",
        "# TYPE wireless_path_probe_jitter_ms gauge\n",
        "# HELP wireless_path_probe_packet_loss_pct Packet loss percentage for the latest path probe.\n",
        "# TYPE wireless_path_probe_packet_loss_pct gauge\n",
        "# HELP wireless_path_probe_last_success_timestamp_seconds Unix timestamp for the latest path probe with at least one response.\n",
        "# TYPE wireless_path_probe_last_success_timestamp_seconds gauge\n",
        "# HELP wireless_path_probe_last_run_timestamp_seconds Unix timestamp for the latest path probe run, successful or not.\n",
        "# TYPE wireless_path_probe_last_run_timestamp_seconds gauge\n",
    ]
    for result in results:
        labels = label_text(result.target)
        stats = result.stats
        lines.append(emit_metric("wireless_path_probe_up", labels, stats.up))
        lines.append(emit_metric("wireless_path_probe_rtt_min_ms", labels, stats.rtt_min_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_avg_ms", labels, stats.rtt_avg_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_max_ms", labels, stats.rtt_max_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_p95_ms", labels, stats.rtt_p95_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_mdev_ms", labels, stats.rtt_mdev_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_pdv_p95_ms", labels, stats.rtt_pdv_p95_ms))
        lines.append(emit_metric("wireless_path_probe_rtt_pdv_range_ms", labels, stats.rtt_pdv_range_ms))
        lines.append(emit_metric("wireless_path_probe_jitter_ms", labels, stats.jitter_ms))
        lines.append(emit_metric("wireless_path_probe_packet_loss_pct", labels, stats.loss_pct))
        lines.append(
            emit_metric(
                "wireless_path_probe_last_success_timestamp_seconds",
                labels,
                stats.last_success_timestamp_seconds,
            )
        )
        lines.append(
            emit_metric(
                "wireless_path_probe_last_run_timestamp_seconds",
                labels,
                stats.last_run_timestamp_seconds,
            )
        )
    return "".join(line for line in lines if line)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse path-probe CLI arguments."""

    parser = argparse.ArgumentParser(description="Run path RTT probes and write Prometheus textfile metrics.")
    parser.add_argument("--config", default="config/path-probe.example.yaml")
    parser.add_argument("--job", help="Only run the named config job.")
    parser.add_argument("--prom-out", default="data/path-probe/out/path_probe.prom")
    parser.add_argument("--json-out", default="data/path-probe/out/path_probe_summary.json")
    parser.add_argument("--no-json", action="store_true", help="Do not write a JSON run summary.")
    parser.add_argument("--print", action="store_true", help="Also print Prometheus output to stdout.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run configured path probes and write Prometheus/JSON outputs."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    config = load_config(args.config)
    targets = select_targets(config, job_name=args.job)
    results: list[ProbeResult] = []
    for target in targets:
        try:
            results.append(run_probe(target))
        except Exception as exc:
            # Textfile collection should still publish fresh "down" samples for
            # targets whose probe setup failed, otherwise dashboards cannot
            # distinguish missing service runs from path failures.
            results.append(ProbeResult(target=target, stats=failed_probe_stats(target, str(exc))))
    prom = render_prometheus(results)

    write_text(args.prom_out, prom)
    if args.print:
        print(prom, end="")

    if not args.no_json:
        write_json(
            args.json_out,
            {
                "config": args.config,
                "job": args.job,
                "prometheus": args.prom_out,
                "targets": [
                    {
                        "segment": result.target.segment,
                        "source": result.target.source,
                        "target": result.target.target,
                        "target_type": result.target.target_type,
                        "address": result.target.address,
                        "method": result.target.method,
                        "sent": result.stats.sent,
                        "received": result.stats.received,
                        "packet_loss_pct": result.stats.loss_pct,
                        "rtt_min_ms": result.stats.rtt_min_ms,
                        "rtt_avg_ms": result.stats.rtt_avg_ms,
                        "rtt_max_ms": result.stats.rtt_max_ms,
                        "rtt_p95_ms": result.stats.rtt_p95_ms,
                        "rtt_mdev_ms": result.stats.rtt_mdev_ms,
                        "rtt_pdv_p95_ms": result.stats.rtt_pdv_p95_ms,
                        "rtt_pdv_range_ms": result.stats.rtt_pdv_range_ms,
                        "jitter_ms": result.stats.jitter_ms,
                        "up": result.stats.up,
                        "error": result.stats.error,
                    }
                    for result in results
                ],
            },
        )

    print(f"Probed {len(results)} path targets")
    print(f"Prom: {args.prom_out}")
    if not args.no_json:
        print(f"JSON: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
