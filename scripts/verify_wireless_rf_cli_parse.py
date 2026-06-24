#!/usr/bin/env python3
"""Compare WLC traffic-distribution CLI evidence with emitted Prometheus metrics."""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from wireless_rf.parser import normalize_access_category
from wireless_rf.parser import normalize_client_generation
from wireless_rf.parser import parse_wlc_rf_dump


PROM_LINE_RE = re.compile(
    r"^(?P<name>[A-Za-z_:][A-Za-z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?|NaN|Inf|-Inf)"
    r"(?:\s+\d+)?$"
)
LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="((?:\\.|[^"\\])*)"')
PACKET_LEVELS = ("good", "medium", "high", "very_high")


@dataclass(frozen=True)
class PromSample:
    """One Prometheus text exposition sample."""

    name: str
    labels: dict[str, str]
    value: float


@dataclass(frozen=True)
class VerificationResult:
    """Raw-vs-Prometheus comparison for one AP/access-category observation."""

    ap_name: str
    slot_id: str
    access_category: str
    client_generation: str
    comparisons: dict[str, tuple[float, float]]


def _unescape_label(value: str) -> str:
    """Unescape a Prometheus label value for comparison."""

    return value.replace(r"\\", "\\").replace(r"\"", '"').replace(r"\n", "\n")


def parse_prometheus_text(text: str) -> list[PromSample]:
    """Parse enough Prometheus textfile format for this verifier."""

    samples: list[PromSample] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = PROM_LINE_RE.match(line)
        if not match:
            continue
        labels = {
            key: _unescape_label(value)
            for key, value in LABEL_RE.findall(match.group("labels") or "")
        }
        samples.append(
            PromSample(
                name=match.group("name"),
                labels=labels,
                value=float(match.group("value")),
            )
        )
    return samples


def _matches(sample: PromSample, metric: str, labels: dict[str, str]) -> bool:
    """Return true when a sample has the requested metric and labels."""

    return sample.name == metric and all(sample.labels.get(key) == value for key, value in labels.items())


def find_prom_value(samples: Iterable[PromSample], metric: str, labels: dict[str, str]) -> float | None:
    """Return a unique Prometheus sample value for metric+labels, or None."""

    matches = [sample.value for sample in samples if _matches(sample, metric, labels)]
    if not matches:
        return None
    if len(matches) > 1:
        label_text = ", ".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
        raise ValueError(f"multiple samples found for {metric}{{{label_text}}}")
    return matches[0]


def _candidate_observations(text: str, wlc: str, band: str):
    """Yield parsed latency observations from raw WLC CLI evidence."""

    snapshots = parse_wlc_rf_dump(text, wlc=wlc, default_band=band)
    for snapshot in sorted(snapshots, key=lambda item: (item.ap_name, item.band)):
        for latency in sorted(
            snapshot.access_category_latencies,
            key=lambda item: (item.slot_id, item.access_category, item.client_generation),
        ):
            yield snapshot, latency


def _filter_matches(value: str, expected: str | None) -> bool:
    """Match helper where None means no selector was requested."""

    return expected is None or value == expected


def _find_observation(
    text: str,
    samples: list[PromSample],
    *,
    wlc: str,
    band: str,
    ap_name: str | None,
    slot_id: str | None,
    access_category: str | None,
    client_generation: str | None,
):
    """Select the raw observation that should be compared to Prometheus."""

    normalized_access_category = normalize_access_category(access_category) if access_category else None
    normalized_generation = normalize_client_generation(client_generation) if client_generation else None
    # Access category defaults to voice for both live and fixture checks, so do
    # not treat it as an explicit selector by itself. Without AP/slot/generation
    # the verifier should auto-select a complete observation from the parse.
    explicit = any([ap_name, slot_id, normalized_generation])

    candidates = []
    for snapshot, latency in _candidate_observations(text, wlc=wlc, band=band):
        if not _filter_matches(snapshot.ap_name, ap_name):
            continue
        if not _filter_matches(latency.slot_id, slot_id):
            continue
        if not _filter_matches(latency.access_category, normalized_access_category):
            continue
        if not _filter_matches(latency.client_generation, normalized_generation):
            continue
        candidates.append((snapshot, latency))

    if not candidates:
        detail = ", ".join(
            part
            for part in [
                f"ap={ap_name}" if ap_name else "",
                f"slot={slot_id}" if slot_id else "",
                f"access_category={normalized_access_category}" if normalized_access_category else "",
                f"client_generation={normalized_generation}" if normalized_generation else "",
            ]
            if part
        )
        raise ValueError(f"no raw traffic-distribution observation matched {detail or 'the input'}")

    if explicit:
        return candidates[0]

    complete = []
    for snapshot, latency in candidates:
        if latency.active_clients is None or latency.avg_latency_us is None:
            continue
        labels = _base_labels(snapshot.ap_name, latency.slot_id, latency.access_category, latency.client_generation)
        if (
            find_prom_value(samples, "wireless_ap_ac_latency_avg_us_cli", labels) is not None
            and find_prom_value(samples, "wireless_ap_ac_latency_active_clients_cli", labels) is not None
        ):
            complete.append((snapshot, latency))
    for snapshot, latency in complete:
        if latency.active_clients > 0 or latency.avg_latency_us > 0:
            return snapshot, latency
    if complete:
        return complete[0]
    return candidates[0]


def _base_labels(ap_name: str, slot_id: str, access_category: str, client_generation: str) -> dict[str, str]:
    """Build the metric label set shared by AP latency samples."""

    return {
        "ap_name": ap_name,
        "slot_id": slot_id,
        "access_category": access_category,
        "client_generation": client_generation,
    }


def _compare_metric(
    comparisons: dict[str, tuple[float, float]],
    samples: list[PromSample],
    *,
    name: str,
    prom_metric: str,
    labels: dict[str, str],
    raw_value: float | int | None,
) -> None:
    """Compare one raw value with its Prometheus sample and record the pair."""

    if raw_value is None:
        raise ValueError(f"raw value is missing for {name}")
    prom_value = find_prom_value(samples, prom_metric, labels)
    if prom_value is None:
        label_text = ", ".join(f'{key}="{value}"' for key, value in sorted(labels.items()))
        raise ValueError(f"Prometheus metric missing for {name}: {prom_metric}{{{label_text}}}")
    raw_float = float(raw_value)
    if not math.isclose(raw_float, prom_value, rel_tol=0, abs_tol=1e-9):
        raise ValueError(f"{name} mismatch: raw={raw_float:g} prom={prom_value:g}")
    comparisons[name] = (raw_float, prom_value)


def verify_cli_parse(
    input_path: Path,
    prom_path: Path,
    *,
    wlc: str = "unknown",
    band: str = "5ghz",
    ap_name: str | None = None,
    slot_id: str | None = None,
    access_category: str | None = "voice",
    client_generation: str | None = None,
) -> VerificationResult:
    """Compare one raw traffic-distribution observation with emitted metrics."""

    text = input_path.read_text(encoding="utf-8")
    samples = parse_prometheus_text(prom_path.read_text(encoding="utf-8"))
    snapshot, latency = _find_observation(
        text,
        samples,
        wlc=wlc,
        band=band,
        ap_name=ap_name,
        slot_id=slot_id,
        access_category=access_category,
        client_generation=client_generation,
    )

    labels = _base_labels(
        snapshot.ap_name,
        latency.slot_id,
        latency.access_category,
        latency.client_generation,
    )
    comparisons: dict[str, tuple[float, float]] = {}
    _compare_metric(
        comparisons,
        samples,
        name="active_clients",
        prom_metric="wireless_ap_ac_latency_active_clients_cli",
        labels=labels,
        raw_value=latency.active_clients,
    )
    _compare_metric(
        comparisons,
        samples,
        name="avg_latency_us",
        prom_metric="wireless_ap_ac_latency_avg_us_cli",
        labels=labels,
        raw_value=latency.avg_latency_us,
    )
    for level in PACKET_LEVELS:
        if level not in latency.packets_by_latency_level:
            continue
        packet_labels = {**labels, "latency_level": level}
        _compare_metric(
            comparisons,
            samples,
            name=f"{level}_packets",
            prom_metric="wireless_ap_ac_latency_packets_cli",
            labels=packet_labels,
            raw_value=latency.packets_by_latency_level[level],
        )

    return VerificationResult(
        ap_name=snapshot.ap_name,
        slot_id=latency.slot_id,
        access_category=latency.access_category,
        client_generation=latency.client_generation,
        comparisons=comparisons,
    )


def _format_number(value: float) -> str:
    """Format comparison values without unnecessary decimal places."""

    return str(int(value)) if value.is_integer() else f"{value:g}"


def print_result(result: VerificationResult) -> None:
    """Print a compact human-readable verification result."""

    print(
        "PASS "
        f"AP={result.ap_name} slot={result.slot_id} "
        f"access_category={result.access_category} generation={result.client_generation}"
    )
    for name in ["active_clients", "avg_latency_us", *[f"{level}_packets" for level in PACKET_LEVELS]]:
        if name not in result.comparisons:
            continue
        raw_value, prom_value = result.comparisons[name]
        print(f"  {name}: raw={_format_number(raw_value)} prom={_format_number(prom_value)}")


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for raw-vs-Prometheus verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Raw WLC CLI evidence file")
    parser.add_argument("--prom", required=True, type=Path, help="Generated Prometheus textfile output")
    parser.add_argument("--wlc", default="unknown", help="WLC label value used while parsing raw evidence")
    parser.add_argument("--band", default="5ghz", help="Default band for raw evidence without slot-derived band")
    parser.add_argument("--ap", dest="ap_name", help="AP name to verify; omitted selects the first matching observation")
    parser.add_argument("--slot", dest="slot_id", help="Slot ID to verify")
    parser.add_argument("--access-category", default="voice", help="Access category to verify")
    parser.add_argument("--client-generation", help="Client generation to verify, for example non_wifi6")
    return parser.parse_args()


def main() -> int:
    """CLI entrypoint for the wireless RF parser verifier."""

    args = parse_args()
    try:
        result = verify_cli_parse(
            args.input,
            args.prom,
            wlc=args.wlc,
            band=args.band,
            ap_name=args.ap_name,
            slot_id=args.slot_id,
            access_category=args.access_category,
            client_generation=args.client_generation,
        )
    except Exception as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
