"""Ekahau JSON timestamp importer and manual observation CSV helpers."""

from __future__ import annotations

import csv
import binascii
import hashlib
import json
import struct
import zipfile
import zlib
from datetime import timedelta
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from .models import (
    EkahauParseResult,
    EkahauSurveyPoint,
    ManualObservation,
    derive_band_from_channel,
    derive_band_from_frequency,
    normalize_mac,
    parse_float,
    parse_int,
    stable_id,
)


def _source_file_id(test_run_id: str, path: Path, payload: bytes) -> str:
    """Create a stable source id for an Ekahau input file or directory."""
    return stable_id(test_run_id, path, hashlib.sha256(payload).hexdigest(), prefix="src_")


def _json_sources(input_path: Path) -> list[tuple[str, bytes]]:
    """Return JSON member payloads that can contribute survey/AP data."""
    # Ekahau .esx files are ZIP containers. We intentionally load lookup JSON
    # files before survey JSON files so floor/AP mappings are available while
    # later parsing route points.
    lookup_names = {"floorPlans.json", "accessPoints.json", "measuredRadios.json", "accessPointMeasurements.json"}
    if input_path.is_dir():
        lookup_files = [
            path
            for path in sorted(input_path.rglob("*.json"))
            if path.is_file() and path.name in lookup_names
        ]
        sources = [
            (str(path), path.read_bytes())
            for path in sorted(input_path.rglob("survey-*.json"))
            if path.is_file()
        ]
        return [(str(path), path.read_bytes()) for path in lookup_files] + sources
    if zipfile.is_zipfile(input_path):
        with zipfile.ZipFile(input_path) as archive:
            names = sorted(name for name in archive.namelist() if not name.endswith("/"))
            selected = [name for name in names if Path(name).name in lookup_names]
            selected.extend(name for name in names if Path(name).name.startswith("survey-") and Path(name).suffix == ".json")
            if not selected and input_path.suffix.lower() == ".json":
                selected = [name for name in names if Path(name).suffix == ".json"]
            return [(name, archive.read(name)) for name in selected]
    if input_path.is_file():
        raw = input_path.read_bytes()
        if raw.startswith(b"PK\x03\x04"):
            sources = _streaming_zip_json_sources(raw)
            if sources:
                return sources
    return [(str(input_path), input_path.read_bytes())]


def _streaming_zip_json_sources(payload: bytes) -> list[tuple[str, bytes]]:
    """Read JSON files from ZIP streams that are missing a central directory."""

    lookup_names = {"floorPlans.json", "accessPoints.json", "measuredRadios.json", "accessPointMeasurements.json"}
    local_header = b"PK\x03\x04"
    data_descriptor = b"PK\x07\x08"
    offsets: list[int] = []
    offset = payload.find(local_header)
    while offset != -1:
        offsets.append(offset)
        offset = payload.find(local_header, offset + 4)

    sources: list[tuple[str, bytes]] = []
    for index, header_offset in enumerate(offsets):
        if header_offset + 30 > len(payload):
            continue
        try:
            (
                signature,
                _version_needed,
                flags,
                compression_method,
                _mtime,
                _mdate,
                expected_crc,
                compressed_size,
                _uncompressed_size,
                name_length,
                extra_length,
            ) = struct.unpack_from("<IHHHHHIIIHH", payload, header_offset)
        except struct.error:
            continue
        if signature != 0x04034B50:
            continue

        name_start = header_offset + 30
        name_end = name_start + name_length
        data_start = name_end + extra_length
        if name_end > len(payload) or data_start > len(payload):
            continue
        try:
            name = payload[name_start:name_end].decode("utf-8")
        except UnicodeDecodeError:
            continue
        base_name = Path(name).name
        if base_name not in lookup_names and not (base_name.startswith("survey-") and base_name.endswith(".json")):
            continue

        next_header = offsets[index + 1] if index + 1 < len(offsets) else len(payload)
        data_end = data_start + compressed_size if compressed_size else next_header
        if flags & 0x08:
            descriptor_at = next_header - 16
            if descriptor_at >= data_start and payload[descriptor_at:descriptor_at + 4] == data_descriptor:
                data_end = descriptor_at
            else:
                descriptor_at = payload.rfind(data_descriptor, data_start, next_header)
                if descriptor_at != -1:
                    data_end = descriptor_at
        if data_end < data_start or data_end > len(payload):
            continue

        compressed = payload[data_start:data_end]
        try:
            if compression_method == 0:
                raw = compressed
            elif compression_method == 8:
                raw = zlib.decompress(compressed, -zlib.MAX_WBITS)
            else:
                continue
        except zlib.error:
            continue
        if expected_crc and binascii.crc32(raw) & 0xFFFFFFFF != expected_crc:
            continue
        sources.append((name, raw))
    return sources


def parse_datetime_value(value: Any, timezone: str) -> datetime | None:
    """Parse Ekahau timestamp variants into the configured timezone."""
    if value is None or value == "":
        return None
    tzinfo = ZoneInfo(timezone)
    if isinstance(value, (int, float)):
        epoch = float(value)
        if epoch > 10_000_000_000:
            epoch = epoch / 1000.0
        return datetime.fromtimestamp(epoch, tzinfo)
    text = str(value).strip()
    if not text:
        return None
    try:
        normalized = text.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tzinfo)
        return parsed.astimezone(tzinfo)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%m/%d/%y %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=tzinfo)
        except ValueError:
            continue
    return None


def _first_value(payload: dict[str, Any], keys: Iterable[str]) -> Any:
    """Return the first present key, matching case-insensitively as fallback."""
    lower_map = {str(key).lower(): value for key, value in payload.items()}
    for key in keys:
        if key in payload:
            return payload[key]
        value = lower_map.get(key.lower())
        if value is not None:
            return value
    return None


def _walk_json(payload: Any, path: str = "$") -> Iterable[tuple[str, dict[str, Any]]]:
    """Yield every JSON object with a simple path for diagnostics."""
    if isinstance(payload, dict):
        yield path, payload
        for key, value in payload.items():
            child_path = f"{path}.{key}"
            yield from _walk_json(value, child_path)
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            yield from _walk_json(value, f"{path}[{index}]")


def _floor_plan_names(sources: list[tuple[str, bytes]]) -> dict[str, str]:
    """Build an Ekahau floor-plan id to display-name lookup."""
    names: dict[str, str] = {}
    for source_name, raw in sources:
        if Path(source_name).name != "floorPlans.json":
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        for floor in payload.get("floorPlans", []):
            if isinstance(floor, dict) and floor.get("id"):
                names[str(floor["id"])] = str(floor.get("name") or floor["id"])
    return names


def _ap_name_lookup(sources: list[tuple[str, bytes]]) -> dict[str, str]:
    """Build a normalized BSSID to AP display-name lookup."""
    # AP names are not stored directly on every route point. Ekahau spreads the
    # relationship across accessPoints, measuredRadios, and
    # accessPointMeasurements; this collapses that graph to BSSID -> AP name for
    # the manual CSV.
    access_points: dict[str, str] = {}
    measurement_macs: dict[str, str] = {}
    radio_measurements: list[dict[str, Any]] = []

    for source_name, raw in sources:
        name = Path(source_name).name
        if name not in {"accessPoints.json", "accessPointMeasurements.json", "measuredRadios.json"}:
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if name == "accessPoints.json":
            for ap in payload.get("accessPoints", []):
                if isinstance(ap, dict) and ap.get("id") and ap.get("name"):
                    access_points[str(ap["id"])] = str(ap["name"])
        elif name == "accessPointMeasurements.json":
            for measurement in payload.get("accessPointMeasurements", []):
                if isinstance(measurement, dict) and measurement.get("id") and measurement.get("mac"):
                    mac = normalize_mac(str(measurement["mac"]))
                    if mac:
                        measurement_macs[str(measurement["id"])] = mac
        elif name == "measuredRadios.json":
            radio_measurements.extend(item for item in payload.get("measuredRadios", []) if isinstance(item, dict))

    lookup: dict[str, str] = {}
    for radio in radio_measurements:
        ap_name = access_points.get(str(radio.get("accessPointId")))
        if not ap_name:
            continue
        for measurement_id in radio.get("accessPointMeasurementIds", []):
            mac = measurement_macs.get(str(measurement_id))
            if mac:
                lookup[mac] = ap_name
    return lookup


def _flatten_route_points(value: Any) -> Iterable[dict[str, Any]]:
    """Yield nested route-point objects from Ekahau survey JSON."""
    if isinstance(value, dict):
        if "time" in value and "location" in value:
            yield value
        for child in value.values():
            yield from _flatten_route_points(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten_route_points(child)


# Ekahau .esx route-point times are stored relative to survey.startTime, but
# the unit varies by exporter build (older versions use nanoseconds, newer ones
# use milliseconds). Auto-detect per survey from the magnitude of the largest
# offset: a surveyor's longest walk in ms peaks well below 1e9 (1e9 ms = 11+
# days); ns values for even a few-second walk easily exceed 1e9.
_NS_DETECTION_THRESHOLD = 1_000_000_000.0


def _route_point_scale(times: list[float]) -> float:
    """Return the divisor that converts route-point time values to seconds."""
    if not times:
        return _NS_DETECTION_THRESHOLD
    max_abs = max(abs(t) for t in times)
    if max_abs >= _NS_DETECTION_THRESHOLD:
        return _NS_DETECTION_THRESHOLD
    if max_abs >= 1.0:
        return 1_000.0
    return 1.0


def _parse_survey_points_from_ekahau_survey_file(
    *,
    payload: dict[str, Any],
    source_name: str,
    source_file_id: str,
    test_run_id: str,
    timezone: str,
    floor_plan_names: dict[str, str],
) -> list[EkahauSurveyPoint]:
    """Parse native Ekahau survey route-point offsets into timestamps."""
    points: list[EkahauSurveyPoint] = []
    surveys = payload.get("surveys")
    if not isinstance(surveys, list):
        return points
    for survey_index, survey in enumerate(surveys):
        if not isinstance(survey, dict):
            continue
        start_time = parse_datetime_value(survey.get("startTime"), timezone)
        if start_time is None:
            continue
        survey_id = str(survey.get("id") or stable_id(test_run_id, source_name, survey_index, prefix="survey_"))
        floor_plan_id = str(survey.get("floorPlanId") or "")
        floor = floor_plan_names.get(floor_plan_id) or floor_plan_id or None
        route_points = list(_flatten_route_points(survey.get("routePoints", [])))
        raw_times = [parse_float(rp.get("time")) for rp in route_points]
        scale = _route_point_scale([t for t in raw_times if t is not None])
        for point_index, route_point in enumerate(route_points):
            raw_time = raw_times[point_index]
            if raw_time is None:
                continue
            offset_seconds = raw_time / scale
            location = route_point.get("location") if isinstance(route_point.get("location"), dict) else {}
            measured_at = start_time + timedelta(seconds=offset_seconds)
            points.append(
                EkahauSurveyPoint(
                    survey_point_id=stable_id(test_run_id, survey_id, point_index, prefix="esp_"),
                    test_run_id=test_run_id,
                    source_file_id=source_file_id,
                    measured_at=measured_at,
                    floor=floor,
                    area=None,
                    x_m=parse_float(location.get("x")),
                    y_m=parse_float(location.get("y")),
                    source_json_path=f"{source_name}:$.surveys[{survey_index}].routePoints[{point_index}]",
                    raw_context={
                        "survey_id": survey_id,
                        "survey_name": survey.get("name"),
                        "floorPlanId": floor_plan_id or None,
                        "route_point_time": route_point.get("time"),
                    },
                )
            )
    return points


def parse_ekahau_json(
    input_path: str | Path,
    *,
    test_run_id: str,
    config: dict[str, Any],
) -> EkahauParseResult:
    """Parse an Ekahau export into timestamped survey points and AP lookup data."""
    path = Path(input_path)
    if not path.exists():
        return EkahauParseResult(
            test_run_id=test_run_id,
            source_file_id=None,
            source_path=str(path),
            parse_success=False,
            parse_error=f"Ekahau input not found: {path}",
        )
    input_raw = path.read_bytes() if path.is_file() else str(path).encode("utf-8")
    source_file_id = _source_file_id(test_run_id, path, input_raw)
    sources = _json_sources(path)
    floor_plan_names = _floor_plan_names(sources)
    ap_name_by_bssid = _ap_name_lookup(sources)
    ekahau_cfg = config.get("ekahau_json", {})
    timestamp_keys = ekahau_cfg.get("timestamp_keys", [])
    id_keys = ekahau_cfg.get("id_keys", [])
    floor_keys = ekahau_cfg.get("floor_keys", [])
    area_keys = ekahau_cfg.get("area_keys", [])
    x_keys = ekahau_cfg.get("x_keys", [])
    y_keys = ekahau_cfg.get("y_keys", [])
    timezone = config.get("timezone", "America/Chicago")

    points: list[EkahauSurveyPoint] = []
    keys_seen: set[str] = set()
    seen_ids: set[str] = set()
    warnings: list[str] = []
    for source_name, raw in sources:
        if Path(source_name).name in {"floorPlans.json", "accessPoints.json", "measuredRadios.json", "accessPointMeasurements.json"}:
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            warnings.append(f"{source_name}: invalid JSON ({exc})")
            continue

        survey_points = _parse_survey_points_from_ekahau_survey_file(
            payload=payload,
            source_name=source_name,
            source_file_id=source_file_id,
            test_run_id=test_run_id,
            timezone=timezone,
            floor_plan_names=floor_plan_names,
        )
        if survey_points:
            # Native Ekahau survey files use relative route-point offsets. When
            # that path succeeds, skip the generic timestamp-key walk to avoid
            # duplicate points from the same source.
            points.extend(survey_points)
            keys_seen.add("survey.routePoints.time")
            continue

        for json_path, obj in _walk_json(payload):
            timestamp_key = next((key for key in timestamp_keys if _first_value(obj, [key]) is not None), None)
            if timestamp_key is None:
                continue
            measured_at = parse_datetime_value(_first_value(obj, [timestamp_key]), timezone)
            if measured_at is None:
                warnings.append(f"{source_name}:{json_path}: timestamp key {timestamp_key} was not parseable")
                continue
            keys_seen.add(timestamp_key)
            raw_id = _first_value(obj, id_keys)
            survey_point_id = str(raw_id) if raw_id not in (None, "") else stable_id(test_run_id, source_name, json_path, measured_at.isoformat(), prefix="esp_")
            survey_point_id = survey_point_id.strip()
            if survey_point_id in seen_ids:
                survey_point_id = stable_id(test_run_id, source_name, json_path, survey_point_id, measured_at.isoformat(), prefix="esp_")
            seen_ids.add(survey_point_id)
            point = EkahauSurveyPoint(
                survey_point_id=survey_point_id,
                test_run_id=test_run_id,
                source_file_id=source_file_id,
                measured_at=measured_at,
                floor=str(_first_value(obj, floor_keys)) if _first_value(obj, floor_keys) is not None else None,
                area=str(_first_value(obj, area_keys)) if _first_value(obj, area_keys) is not None else None,
                x_m=parse_float(_first_value(obj, x_keys)),
                y_m=parse_float(_first_value(obj, y_keys)),
                source_json_path=f"{source_name}:{json_path}",
                raw_context={key: value for key, value in obj.items() if isinstance(value, (str, int, float, bool)) or value is None},
            )
            points.append(point)

    return EkahauParseResult(
        test_run_id=test_run_id,
        source_file_id=source_file_id,
        source_path=str(path),
        parse_success=bool(points),
        survey_points=sorted(points, key=lambda item: item.measured_at),
        ap_name_by_bssid=ap_name_by_bssid,
        timestamp_keys_seen=sorted(keys_seen),
        warnings=warnings,
    )


def read_manual_observations_csv(path: str | Path, *, timezone: str = "America/Chicago") -> list[ManualObservation]:
    """Load operator-entered Ekahau RSSI/SNR rows from CSV."""
    observations: list[ManualObservation] = []
    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row_number, row in enumerate(reader, start=2):
            rssi = parse_float(row.get("ekahau_rssi_dbm"))
            bssid = normalize_mac(row.get("bssid"))
            measured_at = parse_datetime_value(row.get("survey_time") or row.get("measured_at"), timezone)
            if rssi is None or bssid is None or measured_at is None:
                continue
            frequency_mhz = parse_int(row.get("frequency_mhz"))
            channel = parse_int(row.get("channel"))
            band = row.get("band") or derive_band_from_frequency(frequency_mhz) or derive_band_from_channel(channel)
            observations.append(
                ManualObservation(
                    test_run_id=row.get("test_run_id", "").strip(),
                    survey_point_id=(row.get("survey_point_id") or "").strip() or None,
                    measured_at=measured_at,
                    bssid=bssid,
                    rssi_dbm=rssi,
                    snr_db=parse_float(row.get("ekahau_snr_db") or row.get("snr_db")),
                    floor=(row.get("floor") or "").strip() or None,
                    area=(row.get("area") or "").strip() or None,
                    x_m=parse_float(row.get("x_m")),
                    y_m=parse_float(row.get("y_m")),
                    ssid=(row.get("ssid") or "").strip() or None,
                    channel=channel,
                    frequency_mhz=frequency_mhz,
                    band=band,
                    source_row=row_number,
                    notes=(row.get("notes") or "").strip() or None,
                )
            )
    return observations


def inspect_ekahau_json(input_path: str | Path, *, config: dict[str, Any]) -> dict[str, Any]:
    """Return timestamp/AP mapping diagnostics without writing parser output."""
    path = Path(input_path)
    sources = _json_sources(path)
    ap_lookup = _ap_name_lookup(sources)
    timestamp_keys = config.get("ekahau_json", {}).get("timestamp_keys", [])
    found: dict[str, int] = {}
    object_count = 0
    survey_file_count = 0
    route_point_count = 0
    for source_name, raw in sources:
        if Path(source_name).name in {"floorPlans.json", "accessPoints.json", "measuredRadios.json", "accessPointMeasurements.json"}:
            continue
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("surveys"), list):
            survey_file_count += 1
            source_route_points = 0
            for survey in payload.get("surveys", []):
                if isinstance(survey, dict):
                    source_route_points += len(list(_flatten_route_points(survey.get("routePoints", []))))
            route_point_count += source_route_points
            found["survey.routePoints.time"] = found.get("survey.routePoints.time", 0) + source_route_points
            continue
        for _, obj in _walk_json(payload):
            object_count += 1
            for key in timestamp_keys:
                if _first_value(obj, [key]) is not None:
                    found[key] = found.get(key, 0) + 1
    return {
        "path": str(path),
        "json_sources": [name for name, _ in sources],
        "survey_json_files": survey_file_count,
        "route_points": route_point_count,
        "ap_name_mappings": len(ap_lookup),
        "objects_scanned": object_count,
        "timestamp_keys": found,
    }
