"""Correlation engine for badge scan candidates and manual Ekahau observations."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import fields
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .ekahau_importer import read_manual_observations_csv
from .models import (
    BadgeParseResult,
    BadgeRadioSignalSample,
    BadgeRrmNeighbor,
    BadgeScanCandidate,
    BadgeScanEvent,
    CandidateTemplateRow,
    CorrelatedMatch,
    EkahauParseResult,
    EkahauSurveyPoint,
    ManualObservation,
    derive_band_from_channel,
    dt_from_iso,
    parse_float,
    parse_int,
)
from .stats import annotate_outliers


TEMPLATE_COLUMNS = [
    "test_run_id",
    "survey_point_id",
    "survey_time",
    "ekahau_survey_id",
    "ekahau_survey_name",
    "badge_event_id",
    "badge_candidate_index",
    "badge_time",
    "time_delta_seconds",
    "match_quality",
    "floor",
    "area",
    "x_m",
    "y_m",
    "badge_mac",
    "badge_model",
    "ssid",
    "bssid",
    "ap_name",
    "channel",
    "band",
    "badge_rssi_dbm",
    "badge_radio_signal_level_dbm",
    "badge_snr_db",
    "badge_noise_floor_dbm",
    "badge_snr_source",
    "badge_snr_time",
    "badge_snr_time_delta_seconds",
    "badge_cu_percent",
    "badge_score",
    "badge_selected",
    "ekahau_rssi_dbm",
    "ekahau_snr_db",
    "notes",
]


DEFAULT_MATCH_WINDOW_SECONDS = 1.0
OUTLIER_COLUMNS = ["sample_count", "mean_delta", "stddev_delta", "z_score", "outlier_status"]


def _event_from_dict(payload: dict[str, Any]) -> BadgeScanEvent:
    """Rehydrate a badge scan event and nested candidates from JSON."""
    event = BadgeScanEvent(
        event_id=payload["event_id"],
        test_run_id=payload["test_run_id"],
        source_file_id=payload.get("source_file_id"),
        event_time=dt_from_iso(payload["event_time"]),
        badge_mac=payload.get("badge_mac"),
        badge_model=payload.get("badge_model"),
        ssid=payload.get("ssid"),
        roam_reason=payload.get("roam_reason"),
        total_aps=payload.get("total_aps"),
        roam_candidate_aps=payload.get("roam_candidate_aps"),
        outage_ms=payload.get("outage_ms"),
        total_scan_time_ms=payload.get("total_scan_time_ms"),
        connected_bssid=payload.get("connected_bssid"),
        connected_channel=payload.get("connected_channel"),
        connected_band=payload.get("connected_band"),
        connected_ssid=payload.get("connected_ssid"),
        connected_ip=payload.get("connected_ip"),
        gateway=payload.get("gateway"),
        source_line=payload.get("source_line"),
        warnings=list(payload.get("warnings") or []),
    )
    event.candidates = [BadgeScanCandidate(**candidate) for candidate in payload.get("candidates", [])]
    return event


def _rrm_neighbor_from_dict(payload: dict[str, Any]) -> BadgeRrmNeighbor:
    """Rehydrate one RRM neighbor record from parser JSON."""
    return BadgeRrmNeighbor(
        test_run_id=payload["test_run_id"],
        source_file_id=payload.get("source_file_id"),
        event_time=dt_from_iso(payload["event_time"]),
        badge_mac=payload.get("badge_mac"),
        bssid=payload["bssid"],
        op_class=payload.get("op_class"),
        channel=payload.get("channel"),
        band=payload.get("band"),
        phy_type=payload.get("phy_type"),
        info_hex=payload.get("info_hex"),
        source_line=payload.get("source_line"),
    )


def _radio_signal_from_dict(payload: dict[str, Any]) -> BadgeRadioSignalSample:
    """Rehydrate one associated-link radio-signal sample from parser JSON."""
    return BadgeRadioSignalSample(
        test_run_id=payload["test_run_id"],
        source_file_id=payload.get("source_file_id"),
        event_time=dt_from_iso(payload["event_time"]),
        badge_mac=payload.get("badge_mac"),
        sig_bars=payload.get("sig_bars"),
        noise_dbm=payload.get("noise_dbm"),
        level_dbm=payload.get("level_dbm"),
        snr_db=payload.get("snr_db"),
        channel=payload.get("channel"),
        band=payload.get("band"),
        bandwidth_mhz=payload.get("bandwidth_mhz"),
        powersave=payload.get("powersave"),
        channel_utilization_percent=payload.get("channel_utilization_percent"),
        source_line=payload.get("source_line"),
    )


def load_badge_result(path: str | Path) -> BadgeParseResult:
    """Load badge parser JSON into typed dataclasses for correlation."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return BadgeParseResult(
        test_run_id=payload["test_run_id"],
        source_file_id=payload.get("source_file_id"),
        source_path=payload.get("source_path", ""),
        parse_success=bool(payload.get("parse_success")),
        events=[_event_from_dict(event) for event in payload.get("events", [])],
        rrm_neighbors=[_rrm_neighbor_from_dict(neighbor) for neighbor in payload.get("rrm_neighbors", [])],
        radio_signal_samples=[_radio_signal_from_dict(sample) for sample in payload.get("radio_signal_samples", [])],
        warnings=list(payload.get("warnings") or []),
        parse_error=payload.get("parse_error"),
        line_count=int(payload.get("line_count") or 0),
    )


def load_ekahau_result(path: str | Path) -> EkahauParseResult:
    """Load Ekahau parser JSON into typed dataclasses for correlation."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    points = [
        EkahauSurveyPoint(
            survey_point_id=item["survey_point_id"],
            test_run_id=item["test_run_id"],
            source_file_id=item.get("source_file_id"),
            measured_at=dt_from_iso(item["measured_at"]),
            floor=item.get("floor"),
            area=item.get("area"),
            x_m=item.get("x_m"),
            y_m=item.get("y_m"),
            source_json_path=item.get("source_json_path"),
            raw_context=item.get("raw_context") or {},
        )
        for item in payload.get("survey_points", [])
    ]
    return EkahauParseResult(
        test_run_id=payload["test_run_id"],
        source_file_id=payload.get("source_file_id"),
        source_path=payload.get("source_path", ""),
        parse_success=bool(payload.get("parse_success")),
        survey_points=points,
        ap_name_by_bssid=dict(payload.get("ap_name_by_bssid") or {}),
        timestamp_keys_seen=list(payload.get("timestamp_keys_seen") or []),
        warnings=list(payload.get("warnings") or []),
        parse_error=payload.get("parse_error"),
    )


def match_quality(delta_seconds: float, config: dict[str, Any]) -> str | None:
    """Classify a badge/Ekahau timestamp delta into a quality bucket."""
    if not _within_match_window(delta_seconds, config):
        return None
    abs_delta = abs(delta_seconds)
    if abs_delta <= 1.0:
        return "exact_1s"
    if abs_delta <= 5.0:
        return "close_5s"
    return "within_window"


def _match_window_seconds(config: dict[str, Any]) -> float:
    """Return the inclusive badge/Ekahau timestamp match window."""
    return float(config.get("default_match_window_seconds", DEFAULT_MATCH_WINDOW_SECONDS))


def _within_match_window(delta_seconds: float, config: dict[str, Any]) -> bool:
    """Return true when the absolute delta is inside the configured window."""
    return abs(delta_seconds) <= _match_window_seconds(config)


def _require_same_measurement_date(config: dict[str, Any]) -> bool:
    """Return whether local measurement date must match before correlation."""
    return bool(config.get("require_same_measurement_date", True))


def _same_measurement_date(left: datetime, right: datetime, config: dict[str, Any]) -> bool:
    """Compare badge and Ekahau timestamps on configured local date."""
    if not _require_same_measurement_date(config):
        return True
    timezone = ZoneInfo(config.get("timezone", "America/Chicago"))
    # Clock times alone are not enough. A badge diagnostic from one day can look
    # close to an Ekahau route point from another day, so same local date is the
    # default guardrail before applying the sub-second match window.
    return left.astimezone(timezone).date() == right.astimezone(timezone).date()


def _time_range(values: list[datetime]) -> dict[str, str | None]:
    """Return first/last timestamps for operator diagnostics."""
    if not values:
        return {"first": None, "last": None}
    ordered = sorted(values)
    return {"first": ordered[0].isoformat(), "last": ordered[-1].isoformat()}


def _measurement_date_counts(values: list[datetime], config: dict[str, Any]) -> dict[str, int]:
    """Count parsed events by local measurement date."""
    timezone = ZoneInfo(config.get("timezone", "America/Chicago"))
    counts = Counter(value.astimezone(timezone).date().isoformat() for value in values)
    return dict(sorted(counts.items()))


def _nearest_delta_any_date(left: list[datetime], right: list[datetime]) -> float | None:
    """Find nearest timestamp delta without the same-date guardrail."""
    if not left or not right:
        return None
    return min(abs((left_value - right_value).total_seconds()) for left_value in left for right_value in right)


def summarize_match_alignment(
    badge_result: BadgeParseResult,
    ekahau_result: EkahauParseResult,
    *,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Return operator-facing diagnostics for badge/Ekahau time alignment."""
    event_times = [event.event_time for event in badge_result.events]
    point_times = [point.measured_at for point in ekahau_result.survey_points]
    badge_dates = _measurement_date_counts(event_times, config)
    ekahau_dates = _measurement_date_counts(point_times, config)
    same_dates = sorted(set(badge_dates) & set(ekahau_dates))
    nearest_deltas: list[float] = []
    if event_times and point_times:
        for point_time in point_times:
            comparable_events = [
                event_time for event_time in event_times if _same_measurement_date(event_time, point_time, config)
            ]
            if not comparable_events:
                continue
            nearest = min(comparable_events, key=lambda event_time: abs((event_time - point_time).total_seconds()))
            nearest_deltas.append(abs((nearest - point_time).total_seconds()))
    nearest_deltas.sort()
    matched_points = sum(1 for delta in nearest_deltas if _within_match_window(delta, config))
    nearest_any_date = _nearest_delta_any_date(event_times, point_times)
    unmatched_reason = None
    if matched_points == 0:
        if not event_times:
            unmatched_reason = "no_badge_events"
        elif not point_times:
            unmatched_reason = "no_ekahau_points"
        elif _require_same_measurement_date(config) and not same_dates:
            unmatched_reason = "no_same_date_overlap"
        elif nearest_deltas:
            unmatched_reason = "outside_match_window"
        else:
            unmatched_reason = "no_comparable_points"
    return {
        "badge_event_count": len(event_times),
        "ekahau_survey_point_count": len(point_times),
        "configured_match_window_seconds": _match_window_seconds(config),
        "matched_survey_point_count": matched_points,
        "unmatched_reason": unmatched_reason,
        "badge_time_range": _time_range(event_times),
        "ekahau_time_range": _time_range(point_times),
        "badge_measurement_dates": badge_dates,
        "ekahau_measurement_dates": ekahau_dates,
        "same_measurement_dates": same_dates,
        "nearest_delta_min_seconds": nearest_deltas[0] if nearest_deltas else None,
        "nearest_delta_p50_seconds": nearest_deltas[len(nearest_deltas) // 2] if nearest_deltas else None,
        "nearest_delta_p90_seconds": nearest_deltas[int(len(nearest_deltas) * 0.9)] if nearest_deltas else None,
        "nearest_delta_any_date_seconds": nearest_any_date,
    }


def resolve_vendor_offset(config: dict[str, Any], badge_model: str | None, band: str | None) -> float | None:
    """Resolve the Ekahau-to-badge RSSI offset by model, then by band."""
    if not band:
        return None
    offsets = config.get("rssi_offsets", {})
    if badge_model:
        by_model = offsets.get("by_model", {})
        model_offsets = by_model.get(badge_model) or by_model.get(str(badge_model).upper())
        if isinstance(model_offsets, dict) and band in model_offsets:
            value = model_offsets[band]
            return float(value) if value is not None else None
    value = offsets.get("by_band", {}).get(band)
    return float(value) if value is not None else None


def _nearest_radio_signal_sample(
    samples: list[BadgeRadioSignalSample],
    *,
    target_time: datetime,
    channel: int | None = None,
    max_seconds: float,
    require_same_channel: bool = False,
) -> BadgeRadioSignalSample | None:
    """Find the nearest associated-link radio sample.

    Vocera ``Radio signal info`` lines describe the badge's associated radio link at
    that moment. They are not per-candidate AP measurements, but they are still
    the badge-side SNR available for a survey timestamp. Prefer a same-channel
    sample when available; otherwise allow the caller to use the nearest
    event-level associated-link sample and record the source separately.
    """
    candidates = []
    for sample in samples:
        if sample.snr_db is None:
            continue
        if abs((sample.event_time - target_time).total_seconds()) > max_seconds:
            continue
        if require_same_channel:
            if sample.channel is None or channel is None or sample.channel != channel:
                continue
        candidates.append(sample)
    if not candidates:
        return None
    return min(candidates, key=lambda sample: abs((sample.event_time - target_time).total_seconds()))


def _badge_snr_fields(
    *,
    event: BadgeScanEvent,
    candidate: BadgeScanCandidate,
    badge_result: BadgeParseResult,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Attach associated-link SNR/noise-floor fields when evidence exists."""
    radio_config = config.get("badge_radio_signal", {})
    radio_window = float(radio_config.get("associated_sample_match_window_seconds", 300))
    fields: dict[str, Any] = {
        "badge_noise_floor_dbm": None,
        "badge_snr_db": None,
        "badge_snr_source": "unavailable_not_associated_ap",
        "badge_snr_time": None,
        "badge_snr_time_delta_seconds": None,
        "badge_radio_signal_level_dbm": None,
    }
    if candidate.snr_db is not None or candidate.noise_dbm is not None:
        fields.update(
            {
                "badge_noise_floor_dbm": candidate.noise_dbm,
                "badge_snr_db": candidate.snr_db,
                "badge_snr_source": candidate.snr_source or "scan_candidate_report",
                "badge_snr_time": event.event_time,
                "badge_snr_time_delta_seconds": 0,
                "badge_radio_signal_level_dbm": candidate.rssi_dbm,
            }
        )
        return fields
    connected_bssid = event.connected_bssid
    is_associated = candidate.selected or (connected_bssid is not None and candidate.bssid == connected_bssid)

    # Badge radio-signal samples describe the badge's associated link, not a
    # per-candidate AP link. Still, for manual survey entry the useful badge-side
    # SNR is the SNR observed by the badge at the scan/survey timestamp. Prefer a
    # same-channel associated sample, then fall back to the nearest event-level
    # associated sample so the UI does not incorrectly show SNR as missing.
    sample = _nearest_radio_signal_sample(
        badge_result.radio_signal_samples,
        target_time=event.event_time,
        channel=candidate.channel or event.connected_channel,
        max_seconds=radio_window,
        require_same_channel=True,
    )
    source = "associated_radio_signal_level_minus_snr"

    if sample is None:
        sample = _nearest_radio_signal_sample(
            badge_result.radio_signal_samples,
            target_time=event.event_time,
            max_seconds=radio_window,
            require_same_channel=False,
        )
        source = "associated_radio_signal_event_level"

    if sample is None:
        fields["badge_snr_source"] = (
            "unavailable_no_associated_radio_signal_sample"
            if is_associated
            else "unavailable_not_associated_ap_no_radio_signal_sample"
        )
        return fields

    rssi_for_noise = sample.level_dbm if sample.level_dbm is not None else candidate.rssi_dbm
    noise_floor = rssi_for_noise - sample.snr_db if rssi_for_noise is not None and sample.snr_db is not None else None
    fields.update(
        {
            "badge_noise_floor_dbm": noise_floor,
            "badge_snr_db": sample.snr_db,
            "badge_snr_source": source,
            "badge_snr_time": sample.event_time,
            "badge_snr_time_delta_seconds": (sample.event_time - event.event_time).total_seconds(),
            "badge_radio_signal_level_dbm": sample.level_dbm,
        }
    )
    return fields


def build_manual_entry_template(
    badge_result: BadgeParseResult,
    ekahau_result: EkahauParseResult,
    *,
    config: dict[str, Any],
) -> list[CandidateTemplateRow]:
    """Build the operator CSV that joins Ekahau timestamps to badge scans.

    The generated rows preserve badge-side measurements and leave Ekahau RSSI
    fields blank, because the available Ekahau export gives us timestamp and AP
    identity context but not trustworthy direct RSSI/SNR values.
    """
    rows: list[CandidateTemplateRow] = []
    if not badge_result.events or not ekahau_result.survey_points:
        return rows
    for point in ekahau_result.survey_points:
        raw_context = point.raw_context or {}
        ekahau_survey_id = raw_context.get("survey_id")
        ekahau_survey_name = raw_context.get("survey_name")
        comparable_events = [
            event for event in badge_result.events if _same_measurement_date(event.event_time, point.measured_at, config)
        ]
        if not comparable_events:
            continue
        nearest = min(
            comparable_events,
            key=lambda event: abs((event.event_time - point.measured_at).total_seconds()),
        )
        delta = (nearest.event_time - point.measured_at).total_seconds()
        if not _within_match_window(delta, config):
            continue
        quality = match_quality(delta, config)
        for candidate in nearest.candidates:
            ap_name = ekahau_result.ap_name_by_bssid.get(candidate.bssid)
            snr_fields = _badge_snr_fields(
                event=nearest,
                candidate=candidate,
                badge_result=badge_result,
                config=config,
            )
            rows.append(
                CandidateTemplateRow(
                    test_run_id=badge_result.test_run_id,
                    survey_point_id=point.survey_point_id,
                    survey_time=point.measured_at,
                    ekahau_survey_id=str(ekahau_survey_id) if ekahau_survey_id not in (None, "") else None,
                    ekahau_survey_name=str(ekahau_survey_name) if ekahau_survey_name not in (None, "") else None,
                    badge_event_id=nearest.event_id,
                    badge_candidate_index=candidate.candidate_index,
                    badge_time=nearest.event_time,
                    time_delta_seconds=delta,
                    match_quality=quality or "unmatched",
                    badge_mac=nearest.badge_mac,
                    badge_model=nearest.badge_model,
                    floor=point.floor,
                    area=point.area,
                    x_m=point.x_m,
                    y_m=point.y_m,
                    ssid=nearest.ssid,
                    bssid=candidate.bssid,
                    ap_name=ap_name,
                    channel=candidate.channel,
                    band=candidate.band or derive_band_from_channel(candidate.channel),
                    badge_rssi_dbm=candidate.rssi_dbm,
                    badge_cu_percent=candidate.channel_utilization_percent,
                    badge_score=candidate.score,
                    badge_selected=candidate.selected,
                    badge_noise_floor_dbm=snr_fields["badge_noise_floor_dbm"],
                    badge_snr_db=snr_fields["badge_snr_db"],
                    badge_snr_source=snr_fields["badge_snr_source"],
                    badge_snr_time=snr_fields["badge_snr_time"],
                    badge_snr_time_delta_seconds=snr_fields["badge_snr_time_delta_seconds"],
                    badge_radio_signal_level_dbm=snr_fields["badge_radio_signal_level_dbm"],
                )
            )
    return rows


def write_template_csv(rows: list[CandidateTemplateRow], path: str | Path) -> None:
    """Write candidate template rows in the stable manual-entry column order."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=TEMPLATE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.to_dict().get(key) for key in TEMPLATE_COLUMNS})


def read_template_rows(path: str | Path) -> list[CandidateTemplateRow]:
    """Read generated manual-entry template rows back into dataclasses."""
    rows: list[CandidateTemplateRow] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not row.get("badge_event_id") or not row.get("bssid"):
                continue
            rows.append(
                CandidateTemplateRow(
                    test_run_id=row["test_run_id"],
                    survey_point_id=row["survey_point_id"],
                    survey_time=dt_from_iso(row["survey_time"]),
                    ekahau_survey_id=row.get("ekahau_survey_id") or None,
                    ekahau_survey_name=row.get("ekahau_survey_name") or None,
                    badge_event_id=row["badge_event_id"],
                    badge_candidate_index=int(row["badge_candidate_index"]),
                    badge_time=dt_from_iso(row["badge_time"]),
                    time_delta_seconds=float(row["time_delta_seconds"]),
                    match_quality=row["match_quality"],
                    badge_mac=row.get("badge_mac") or None,
                    badge_model=row.get("badge_model") or None,
                    floor=row.get("floor") or None,
                    area=row.get("area") or None,
                    x_m=parse_float(row.get("x_m")),
                    y_m=parse_float(row.get("y_m")),
                    ssid=row.get("ssid") or None,
                    bssid=row["bssid"],
                    ap_name=row.get("ap_name") or None,
                    channel=parse_int(row.get("channel")),
                    band=row.get("band") or None,
                    badge_rssi_dbm=parse_float(row.get("badge_rssi_dbm")),
                    badge_cu_percent=parse_float(row.get("badge_cu_percent")),
                    badge_score=parse_float(row.get("badge_score")),
                    badge_selected=str(row.get("badge_selected", "")).lower() in {"1", "true", "yes"},
                    badge_noise_floor_dbm=parse_float(row.get("badge_noise_floor_dbm")),
                    badge_snr_db=parse_float(row.get("badge_snr_db")),
                    badge_snr_source=row.get("badge_snr_source") or None,
                    badge_snr_time=dt_from_iso(row["badge_snr_time"]) if row.get("badge_snr_time") else None,
                    badge_snr_time_delta_seconds=parse_float(row.get("badge_snr_time_delta_seconds")),
                    badge_radio_signal_level_dbm=parse_float(row.get("badge_radio_signal_level_dbm")),
                    ekahau_rssi_dbm=parse_float(row.get("ekahau_rssi_dbm")),
                    ekahau_snr_db=parse_float(row.get("ekahau_snr_db")),
                    notes=row.get("notes") or None,
                )
            )
    return rows


def _manual_by_template_key(observations: list[ManualObservation]) -> dict[tuple[str | None, str, str], ManualObservation]:
    """Index manual observations by the generated template row identity."""
    indexed: dict[tuple[str | None, str, str], ManualObservation] = {}
    for observation in observations:
        key = (observation.survey_point_id, observation.bssid, observation.measured_at.isoformat())
        indexed[key] = observation
    return indexed


def correlate_template_rows(
    rows: list[CandidateTemplateRow],
    *,
    config: dict[str, Any],
    manual_observations: list[ManualObservation] | None = None,
) -> list[CorrelatedMatch]:
    """Apply manual Ekahau observations and compute badge-vs-Ekahau deltas."""
    manual_index = _manual_by_template_key(manual_observations or [])
    matches: list[CorrelatedMatch] = []
    for row in rows:
        if not _same_measurement_date(row.badge_time, row.survey_time, config):
            continue
        if not _within_match_window(row.time_delta_seconds, config):
            continue
        manual = manual_index.get((row.survey_point_id, row.bssid, row.survey_time.isoformat()))
        ekahau_rssi = row.ekahau_rssi_dbm if row.ekahau_rssi_dbm is not None else (manual.rssi_dbm if manual else None)
        ekahau_snr = row.ekahau_snr_db if row.ekahau_snr_db is not None else (manual.snr_db if manual else None)
        band = row.band or (manual.band if manual else None)
        vendor_offset = resolve_vendor_offset(config, row.badge_model, band)
        expected = ekahau_rssi + vendor_offset if ekahau_rssi is not None and vendor_offset is not None else None
        raw_delta = row.badge_rssi_dbm - ekahau_rssi if row.badge_rssi_dbm is not None and ekahau_rssi is not None else None
        calibrated_delta = row.badge_rssi_dbm - expected if row.badge_rssi_dbm is not None and expected is not None else None
        status = "complete" if ekahau_rssi is not None else "pending_manual_entry"
        if ekahau_rssi is not None and vendor_offset is None:
            status = "missing_vendor_offset"
        matches.append(
            CorrelatedMatch(
                test_run_id=row.test_run_id,
                survey_point_id=row.survey_point_id,
                badge_event_id=row.badge_event_id,
                badge_candidate_index=row.badge_candidate_index,
                badge_time=row.badge_time,
                ekahau_time=row.survey_time,
                ekahau_survey_id=row.ekahau_survey_id,
                ekahau_survey_name=row.ekahau_survey_name,
                time_delta_seconds=row.time_delta_seconds,
                badge_mac=row.badge_mac,
                badge_model=row.badge_model,
                ssid=row.ssid,
                bssid=row.bssid,
                ap_name=row.ap_name,
                channel=row.channel,
                band=band,
                badge_rssi_dbm=row.badge_rssi_dbm,
                badge_noise_floor_dbm=row.badge_noise_floor_dbm,
                badge_snr_db=row.badge_snr_db,
                badge_snr_source=row.badge_snr_source,
                badge_snr_time=row.badge_snr_time,
                badge_snr_time_delta_seconds=row.badge_snr_time_delta_seconds,
                badge_radio_signal_level_dbm=row.badge_radio_signal_level_dbm,
                ekahau_rssi_dbm=ekahau_rssi,
                ekahau_snr_db=ekahau_snr,
                vendor_offset_db=vendor_offset,
                expected_badge_rssi_dbm=expected,
                raw_delta_db=raw_delta,
                calibrated_delta_db=calibrated_delta,
                absolute_calibrated_delta_db=abs(calibrated_delta) if calibrated_delta is not None else None,
                badge_cu_percent=row.badge_cu_percent,
                badge_score=row.badge_score,
                badge_selected=row.badge_selected,
                floor=row.floor,
                area=row.area,
                x_m=row.x_m,
                y_m=row.y_m,
                match_quality=row.match_quality,
                manual_entry_status=status,
            )
        )
    return matches


def correlate_template_csv(
    template_csv: str | Path,
    *,
    config: dict[str, Any],
    manual_csv: str | Path | None = None,
) -> list[CorrelatedMatch]:
    """Load a template/manual CSV pair and return correlated match rows."""
    rows = read_template_rows(template_csv)
    observations = read_manual_observations_csv(manual_csv, timezone=config.get("timezone", "America/Chicago")) if manual_csv else []
    return correlate_template_rows(rows, config=config, manual_observations=observations)


def write_matches_json(matches: list[CorrelatedMatch], path: str | Path) -> None:
    """Write correlated matches as structured JSON for SQL export."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"matches": [match.to_dict() for match in matches]}, indent=2, sort_keys=True), encoding="utf-8")


def write_matches_csv(
    matches: list[CorrelatedMatch],
    path: str | Path,
    *,
    minimum_samples: int = 30,
    z_score_threshold: float = 2.0,
) -> None:
    """Write correlated matches as CSV with optional outlier annotations."""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [field.name for field in fields(CorrelatedMatch)] + OUTLIER_COLUMNS
    annotated = {
        (
            row.get("test_run_id"),
            row.get("survey_point_id"),
            row.get("badge_event_id"),
            row.get("badge_candidate_index"),
            row.get("bssid"),
            row.get("ekahau_time"),
        ): row
        for row in annotate_outliers(matches, minimum_samples=minimum_samples, z_score_threshold=z_score_threshold)
    }
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for match in matches:
            row = match.to_dict()
            annotation = annotated.get(
                (
                    row.get("test_run_id"),
                    row.get("survey_point_id"),
                    row.get("badge_event_id"),
                    row.get("badge_candidate_index"),
                    row.get("bssid"),
                    row.get("ekahau_time"),
                )
            )
            for column in OUTLIER_COLUMNS:
                row[column] = annotation.get(column) if annotation else None
            writer.writerow(row)
