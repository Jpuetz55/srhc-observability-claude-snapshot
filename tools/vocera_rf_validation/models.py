"""Shared data models and normalization helpers for RF validation."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


MAC_RE = re.compile(r"(?i)([0-9a-f]{2})[:.\-]?([0-9a-f]{2})[:.\-]?([0-9a-f]{2})[:.\-]?([0-9a-f]{2})[:.\-]?([0-9a-f]{2})[:.\-]?([0-9a-f]{2})")


def stable_id(*parts: object, prefix: str = "") -> str:
    """Return a deterministic short id for parsed rows and source files."""
    payload = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}{digest}" if prefix else digest


def normalize_mac(value: str | None) -> str | None:
    """Normalize common MAC address spellings to lower-case colon notation."""
    if value is None:
        return None
    match = MAC_RE.search(str(value).strip())
    if not match:
        return None
    return ":".join(part.lower() for part in match.groups())


def derive_band_from_frequency(frequency_mhz: int | None) -> str | None:
    """Map a frequency in MHz to the dashboard band label."""
    if frequency_mhz is None:
        return None
    if 2400 <= frequency_mhz < 2500:
        return "2.4GHz"
    if 4900 <= frequency_mhz < 5925:
        return "5GHz"
    if 5925 <= frequency_mhz <= 7125:
        return "6GHz"
    return None


def derive_band_from_channel(channel: int | None, op_class: int | None = None) -> str | None:
    """Infer a Wi-Fi band from channel and optional regulatory op class."""
    if channel is None:
        return None
    if op_class is not None and 131 <= op_class <= 137:
        return "6GHz"
    if 1 <= channel <= 14:
        return "2.4GHz"
    if 32 <= channel <= 177:
        return "5GHz"
    return None


def parse_int(value: Any) -> int | None:
    """Parse an optional integer field from CSV/JSON input."""
    if value is None or value == "":
        return None
    try:
        return int(str(value).strip())
    except ValueError:
        return None


def parse_float(value: Any) -> float | None:
    """Parse an optional float field from CSV/JSON input."""
    if value is None or value == "":
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def dt_to_iso(value: datetime) -> str:
    """Serialize timezone-aware datetimes consistently for JSON/CSV output."""
    return value.isoformat()


def dt_from_iso(value: str) -> datetime:
    """Parse ISO datetimes, accepting the common trailing Z UTC form."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass
class BadgeScanCandidate:
    event_id: str
    candidate_index: int
    selected: bool
    bssid: str
    channel: int | None = None
    band: str | None = None
    rssi_dbm: float | None = None
    noise_dbm: float | None = None
    snr_db: float | None = None
    snr_source: str | None = None
    channel_utilization_percent: float | None = None
    score: float | None = None
    is_roam_candidate: bool | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize a scan candidate without transforming scalar fields."""
        return self.__dict__.copy()


@dataclass
class BadgeScanEvent:
    event_id: str
    test_run_id: str
    source_file_id: str | None
    event_time: datetime
    badge_mac: str | None = None
    badge_model: str | None = None
    ssid: str | None = None
    roam_reason: str | None = None
    total_aps: int | None = None
    roam_candidate_aps: int | None = None
    outage_ms: int | None = None
    total_scan_time_ms: int | None = None
    connected_bssid: str | None = None
    connected_channel: int | None = None
    connected_band: str | None = None
    connected_ssid: str | None = None
    connected_ip: str | None = None
    gateway: str | None = None
    source_line: int | None = None
    warnings: list[str] = field(default_factory=list)
    candidates: list[BadgeScanCandidate] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize an event and nested scan candidates for JSON output."""
        payload = self.__dict__.copy()
        payload["event_time"] = dt_to_iso(self.event_time)
        payload["candidates"] = [candidate.to_dict() for candidate in self.candidates]
        return payload


@dataclass
class BadgeRrmNeighbor:
    test_run_id: str
    source_file_id: str | None
    event_time: datetime
    bssid: str
    badge_mac: str | None = None
    op_class: int | None = None
    channel: int | None = None
    band: str | None = None
    phy_type: int | None = None
    info_hex: str | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize an RRM neighbor with an ISO timestamp."""
        payload = self.__dict__.copy()
        payload["event_time"] = dt_to_iso(self.event_time)
        return payload


@dataclass
class BadgeRadioSignalSample:
    test_run_id: str
    source_file_id: str | None
    event_time: datetime
    badge_mac: str | None = None
    sig_bars: int | None = None
    noise_dbm: float | None = None
    level_dbm: float | None = None
    snr_db: float | None = None
    channel: int | None = None
    band: str | None = None
    bandwidth_mhz: int | None = None
    powersave: int | None = None
    channel_utilization_percent: float | None = None
    source_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize an associated-link radio-signal sample."""
        payload = self.__dict__.copy()
        payload["event_time"] = dt_to_iso(self.event_time)
        return payload


@dataclass
class BadgeParseResult:
    test_run_id: str
    source_file_id: str | None
    source_path: str
    parse_success: bool
    events: list[BadgeScanEvent] = field(default_factory=list)
    rrm_neighbors: list[BadgeRrmNeighbor] = field(default_factory=list)
    radio_signal_samples: list[BadgeRadioSignalSample] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_error: str | None = None
    line_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete badge parser result."""
        return {
            "test_run_id": self.test_run_id,
            "source_file_id": self.source_file_id,
            "source_path": self.source_path,
            "parse_success": self.parse_success,
            "events": [event.to_dict() for event in self.events],
            "rrm_neighbors": [neighbor.to_dict() for neighbor in self.rrm_neighbors],
            "radio_signal_samples": [sample.to_dict() for sample in self.radio_signal_samples],
            "warnings": self.warnings,
            "parse_error": self.parse_error,
            "line_count": self.line_count,
        }


@dataclass
class EkahauSurveyPoint:
    survey_point_id: str
    test_run_id: str
    measured_at: datetime
    source_file_id: str | None = None
    floor: str | None = None
    area: str | None = None
    x_m: float | None = None
    y_m: float | None = None
    source_json_path: str | None = None
    raw_context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize an Ekahau survey point with an ISO timestamp."""
        payload = self.__dict__.copy()
        payload["measured_at"] = dt_to_iso(self.measured_at)
        return payload


@dataclass
class EkahauParseResult:
    test_run_id: str
    source_file_id: str | None
    source_path: str
    parse_success: bool
    survey_points: list[EkahauSurveyPoint] = field(default_factory=list)
    ap_name_by_bssid: dict[str, str] = field(default_factory=dict)
    timestamp_keys_seen: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    parse_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete Ekahau parser result."""
        return {
            "test_run_id": self.test_run_id,
            "source_file_id": self.source_file_id,
            "source_path": self.source_path,
            "parse_success": self.parse_success,
            "survey_points": [point.to_dict() for point in self.survey_points],
            "ap_name_by_bssid": self.ap_name_by_bssid,
            "timestamp_keys_seen": self.timestamp_keys_seen,
            "warnings": self.warnings,
            "parse_error": self.parse_error,
        }


@dataclass
class ManualObservation:
    test_run_id: str
    survey_point_id: str | None
    measured_at: datetime
    bssid: str
    rssi_dbm: float
    snr_db: float | None = None
    floor: str | None = None
    area: str | None = None
    x_m: float | None = None
    y_m: float | None = None
    ssid: str | None = None
    channel: int | None = None
    frequency_mhz: int | None = None
    band: str | None = None
    source_row: int | None = None
    notes: str | None = None


@dataclass
class CandidateTemplateRow:
    test_run_id: str
    survey_point_id: str
    survey_time: datetime
    ekahau_survey_id: str | None
    ekahau_survey_name: str | None
    badge_event_id: str
    badge_candidate_index: int
    badge_time: datetime
    time_delta_seconds: float
    match_quality: str
    badge_mac: str | None
    badge_model: str | None
    floor: str | None
    area: str | None
    x_m: float | None
    y_m: float | None
    ssid: str | None
    bssid: str
    ap_name: str | None
    channel: int | None
    band: str | None
    badge_rssi_dbm: float | None
    badge_cu_percent: float | None
    badge_score: float | None
    badge_selected: bool
    badge_noise_floor_dbm: float | None = None
    badge_snr_db: float | None = None
    badge_snr_source: str | None = None
    badge_snr_time: datetime | None = None
    badge_snr_time_delta_seconds: float | None = None
    badge_radio_signal_level_dbm: float | None = None
    ekahau_rssi_dbm: float | None = None
    ekahau_snr_db: float | None = None
    notes: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize a template row for CSV or JSON emission."""
        payload = self.__dict__.copy()
        payload["survey_time"] = dt_to_iso(self.survey_time)
        payload["badge_time"] = dt_to_iso(self.badge_time)
        payload["badge_snr_time"] = dt_to_iso(self.badge_snr_time) if self.badge_snr_time else None
        return payload


@dataclass
class CorrelatedMatch:
    test_run_id: str
    survey_point_id: str | None
    badge_event_id: str
    badge_candidate_index: int
    badge_time: datetime
    ekahau_time: datetime
    ekahau_survey_id: str | None
    ekahau_survey_name: str | None
    time_delta_seconds: float
    badge_mac: str | None
    badge_model: str | None
    ssid: str | None
    bssid: str
    ap_name: str | None
    channel: int | None
    band: str | None
    badge_rssi_dbm: float | None
    badge_noise_floor_dbm: float | None
    badge_snr_db: float | None
    badge_snr_source: str | None
    badge_snr_time: datetime | None
    badge_snr_time_delta_seconds: float | None
    badge_radio_signal_level_dbm: float | None
    ekahau_rssi_dbm: float | None
    ekahau_snr_db: float | None
    vendor_offset_db: float | None
    expected_badge_rssi_dbm: float | None
    raw_delta_db: float | None
    calibrated_delta_db: float | None
    absolute_calibrated_delta_db: float | None
    badge_cu_percent: float | None
    badge_score: float | None
    badge_selected: bool
    floor: str | None
    area: str | None
    x_m: float | None
    y_m: float | None
    match_quality: str
    manual_entry_status: str

    def to_dict(self) -> dict[str, Any]:
        """Serialize a completed or pending badge/Ekahau correlation row."""
        payload = self.__dict__.copy()
        payload["badge_time"] = dt_to_iso(self.badge_time)
        payload["ekahau_time"] = dt_to_iso(self.ekahau_time)
        payload["badge_snr_time"] = dt_to_iso(self.badge_snr_time) if self.badge_snr_time else None
        return payload
