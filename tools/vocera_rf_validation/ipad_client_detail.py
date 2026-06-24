"""Parse and collect iPad WLC client-detail scan reports for RF validation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from tools.common.files import read_text

from .models import (
    BadgeParseResult,
    BadgeScanCandidate,
    BadgeScanEvent,
    derive_band_from_channel,
    normalize_mac,
    parse_float,
    parse_int,
    stable_id,
)


DEFAULT_CLIENT_MODEL = "iPad"
SCAN_REPORT_SOURCE = "wlc_client_scan_report"

ISO_HEADER_RE = re.compile(r"(?im)^#\s*collected_at\s*:\s*(.+?)\s*$")
FIELD_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /_.()-]+?)\s*:\s*(.*?)\s*$")
DBM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*dBm\b", re.IGNORECASE)
SNR_RE = re.compile(r"\bSNR\b\s*[:=]?\s*(-?\d+(?:\.\d+)?)\s*dB\b", re.IGNORECASE)
CHANNEL_RE = re.compile(r"\b(?:channel|chan|ch)\b\s*[:=]?\s*(\d{1,3})\b", re.IGNORECASE)
WLC_SCAN_REPORT_TIME_RE = re.compile(
    r"\b(?:Last\s+Report\s*@|Time)\s*:\s*"
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d{1,2}:\d{2}:\d{2})(?:\s+[A-Z]{2,4})?\b",
    re.IGNORECASE,
)

SECTION_END_RE = re.compile(
    r"^\s*(Nearby AP Statistics|EoGRE|Device Type|Device Name|Protocol Map|Max Client Protocol|Cellular Capability|"
    r"Apple Specific Requests|Advanced Scheduling Requests|Client Statistics|Fabric status)\b",
    re.IGNORECASE,
)


@dataclass
class ParsedScanCandidate:
    """One AP row extracted from the WLC Client Scan Reports section."""

    bssid: str
    channel: int | None = None
    rssi_dbm: float | None = None
    snr_db: float | None = None
    ssid: str | None = None
    score: float | None = None
    source_line: int | None = None


def _field_values(lines: list[str]) -> dict[str, str]:
    """Return lower-case field names parsed from show-client-detail text."""

    values: dict[str, str] = {}
    for line in lines:
        match = FIELD_RE.match(line)
        if not match:
            continue
        key = re.sub(r"\s+", " ", match.group(1).strip().lower())
        values.setdefault(key, match.group(2).strip())
    return values


def _parse_time(text: str, path: Path, timezone: str) -> datetime:
    """Use the explicit collection timestamp, otherwise fall back to file mtime."""

    match = ISO_HEADER_RE.search(text)
    if match:
        raw = match.group(1).strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=ZoneInfo(timezone))
            return parsed
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime, tz=ZoneInfo(timezone))


def _parse_wlc_scan_report_time(value: str, timezone: str) -> datetime | None:
    """Parse Cisco WLC Client Scan Reports timestamps in controller-local time."""

    match = WLC_SCAN_REPORT_TIME_RE.search(value)
    if not match:
        return None
    raw = f"{match.group(1)} {match.group(2)}"
    try:
        parsed = datetime.strptime(raw, "%m/%d/%Y %H:%M:%S")
    except ValueError:
        return None
    return parsed.replace(tzinfo=ZoneInfo(timezone))


def _scan_report_time(lines: list[tuple[int, str]], timezone: str) -> datetime | None:
    """Return the WLC scan-report timestamp, preferring the explicit Last Report field."""

    fallback: datetime | None = None
    for _line_number, line in lines:
        parsed = _parse_wlc_scan_report_time(line, timezone)
        if parsed is None:
            continue
        if re.search(r"\bLast\s+Report\s*@", line, re.IGNORECASE):
            return parsed
        if fallback is None:
            fallback = parsed
    return fallback


def _scan_report_lines(lines: list[str]) -> list[tuple[int, str]]:
    """Return only the WLC Client Scan Reports section, excluding Nearby APs."""

    in_section = False
    selected: list[tuple[int, str]] = []
    for line_number, line in enumerate(lines, start=1):
        if re.search(r"\bClient Scan Reports\b", line, re.IGNORECASE):
            in_section = True
            continue
        if not in_section:
            continue
        if SECTION_END_RE.search(line):
            break
        if line.strip():
            selected.append((line_number, line))
    return selected


def _value_after_colon(line: str) -> str | None:
    """Return the right side of a WLC key/value line if it has one."""

    if ":" not in line:
        return None
    return line.split(":", 1)[1].strip()


def _parse_explicit_channel(line: str) -> int | None:
    """Parse a channel from block-style or table-style WLC output."""

    match = CHANNEL_RE.search(line)
    if match:
        return parse_int(match.group(1))
    value = _value_after_colon(line)
    if value is not None and re.match(r"^\d{1,3}\b", value):
        return parse_int(value.split()[0])
    return None


def _parse_explicit_snr(line: str) -> float | None:
    """Parse SNR dB from a WLC scan-report line."""

    match = SNR_RE.search(line)
    if match:
        return parse_float(match.group(1))
    if re.search(r"\bSNR\b", line, re.IGNORECASE):
        value = _value_after_colon(line)
        if value:
            numeric = re.search(r"-?\d+(?:\.\d+)?", value)
            if numeric:
                return parse_float(numeric.group(0))
    return None


def _parse_explicit_score(line: str) -> float | None:
    """Parse a WLC score field if the scan-report row has one."""

    if not re.search(r"\bscore\b", line, re.IGNORECASE):
        return None
    value = _value_after_colon(line)
    if value:
        numeric = re.search(r"-?\d+(?:\.\d+)?", value)
        if numeric:
            return parse_float(numeric.group(0))
    return None


def _finalize_block_candidate(candidate: dict[str, Any], rows: list[ParsedScanCandidate]) -> None:
    """Append one block-style candidate if it has useful scan-report evidence."""

    bssid = normalize_mac(candidate.get("bssid"))
    if not bssid:
        return
    rows.append(
        ParsedScanCandidate(
            bssid=bssid,
            channel=parse_int(candidate.get("channel")),
            rssi_dbm=parse_float(candidate.get("rssi_dbm")),
            snr_db=parse_float(candidate.get("snr_db")),
            ssid=str(candidate["ssid"]) if candidate.get("ssid") else None,
            score=parse_float(candidate.get("score")),
            source_line=parse_int(candidate.get("source_line")),
        )
    )


def _parse_block_candidates(lines: list[tuple[int, str]]) -> list[ParsedScanCandidate]:
    """Parse scan reports that are formatted as repeated BSSID/key blocks."""

    rows: list[ParsedScanCandidate] = []
    current: dict[str, Any] = {}
    for line_number, line in lines:
        field = FIELD_RE.match(line)
        key = field.group(1).strip().lower() if field else ""
        value = field.group(2).strip() if field else ""
        mac = normalize_mac(value if key == "bssid" else line)
        if key == "bssid" or (mac and not current.get("bssid")):
            if current:
                _finalize_block_candidate(current, rows)
            current = {"bssid": mac, "source_line": line_number}
            if field and key == "bssid":
                remainder = line[field.end() :]
                rssi = DBM_RE.search(remainder)
                if rssi:
                    current["rssi_dbm"] = rssi.group(1)
            continue
        if not current:
            continue
        if "channel" in key:
            current["channel"] = _parse_explicit_channel(line)
        elif key == "ssid" or "network name" in key:
            current["ssid"] = value
        elif "rssi" in key or "signal" in key:
            rssi = DBM_RE.search(line)
            current["rssi_dbm"] = rssi.group(1) if rssi else value
        elif "snr" in key or "noise" in key:
            current["snr_db"] = _parse_explicit_snr(line)
        elif "score" in key:
            current["score"] = _parse_explicit_score(line)
    if current:
        _finalize_block_candidate(current, rows)
    return rows


def _parse_table_candidate(line_number: int, line: str) -> ParsedScanCandidate | None:
    """Parse one table-style scan-report row containing a BSSID and RSSI."""

    mac_match = re.search(
        r"(?i)([0-9a-f]{2}[:.\-]?[0-9a-f]{2}[:.\-]?[0-9a-f]{2}[:.\-]?"
        r"[0-9a-f]{2}[:.\-]?[0-9a-f]{2}[:.\-]?[0-9a-f]{2})",
        line,
    )
    if not mac_match:
        return None
    bssid = normalize_mac(mac_match.group(1))
    if not bssid:
        return None
    rssi_match = DBM_RE.search(line)
    if rssi_match is None:
        return None
    before_rssi = line[: rssi_match.start()]
    channel = _parse_explicit_channel(line)
    if channel is None:
        numeric_before = [int(value) for value in re.findall(r"\b\d{1,3}\b", before_rssi[mac_match.end() :])]
        channel = next((value for value in numeric_before if 1 <= value <= 196), None)
    return ParsedScanCandidate(
        bssid=bssid,
        channel=channel,
        rssi_dbm=parse_float(rssi_match.group(1)),
        snr_db=_parse_explicit_snr(line),
        source_line=line_number,
    )


def _dedupe_candidates(candidates: Iterable[ParsedScanCandidate]) -> list[ParsedScanCandidate]:
    """Keep the strongest row per BSSID/channel pair from one WLC scan report."""

    best: dict[tuple[str, int | None], ParsedScanCandidate] = {}
    for candidate in candidates:
        key = (candidate.bssid, candidate.channel)
        current = best.get(key)
        if current is None:
            best[key] = candidate
            continue
        current_rssi = current.rssi_dbm if current.rssi_dbm is not None else -999
        new_rssi = candidate.rssi_dbm if candidate.rssi_dbm is not None else -999
        if new_rssi > current_rssi:
            best[key] = candidate
    return sorted(best.values(), key=lambda row: (row.channel or 999, row.bssid))


def parse_client_detail_input(
    path: str | Path,
    *,
    test_run_id: str,
    client_mac: str | None = None,
    client_model: str = DEFAULT_CLIENT_MODEL,
    timezone: str = "America/Chicago",
) -> BadgeParseResult:
    """Parse WLC Client Scan Reports from one collected client-detail output."""

    input_path = Path(path)
    text = read_text(input_path, errors="replace")
    lines = text.splitlines()
    fields = _field_values(lines)
    source_id = stable_id(input_path.name, text, prefix="src_")
    resolved_client_mac = normalize_mac(client_mac) or normalize_mac(fields.get("client mac address"))
    connected_bssid = normalize_mac(fields.get("bssid"))
    connected_channel = parse_int(fields.get("channel"))
    connected_band = derive_band_from_channel(connected_channel)
    ssid = fields.get("wireless lan network name (ssid)") or fields.get("ssid")
    collection_time = _parse_time(text, input_path, timezone)
    event_time = collection_time
    warnings: list[str] = []

    section_lines = _scan_report_lines(lines)
    scan_report_time = _scan_report_time(section_lines, timezone)
    if scan_report_time is not None:
        event_time = scan_report_time
        scan_age_seconds = (collection_time - scan_report_time).total_seconds()
        if abs(scan_age_seconds) > 300:
            warnings.append(
                "WLC Client Scan Reports timestamp differs from collection time by "
                f"{scan_age_seconds:.0f} seconds; using scan-report timestamp for matching."
            )
    else:
        warnings.append("No WLC Client Scan Reports timestamp found; using collection time for matching.")
    table_rows = [_parse_table_candidate(line_number, line) for line_number, line in section_lines]
    block_rows = _parse_block_candidates(section_lines)
    scan_rows = _dedupe_candidates([row for row in [*table_rows, *block_rows] if row is not None and row.rssi_dbm is not None])

    if not scan_rows:
        warnings.append(
            "No WLC Client Scan Reports rows with BSSID and RSSI were found. "
            "AP-side Client Statistics RSSI/SNR were intentionally not imported."
        )
        return BadgeParseResult(
            test_run_id=test_run_id,
            source_file_id=source_id,
            source_path=str(input_path),
            parse_success=False,
            events=[],
            warnings=warnings,
            parse_error=warnings[0],
            line_count=len(lines),
        )

    event_id = stable_id(test_run_id, source_id, event_time.isoformat(), resolved_client_mac, prefix="evt_")
    event = BadgeScanEvent(
        event_id=event_id,
        test_run_id=test_run_id,
        source_file_id=source_id,
        event_time=event_time,
        badge_mac=resolved_client_mac,
        badge_model=client_model,
        ssid=ssid,
        roam_reason=SCAN_REPORT_SOURCE,
        total_aps=len(scan_rows),
        roam_candidate_aps=len(scan_rows),
        connected_bssid=connected_bssid,
        connected_channel=connected_channel,
        connected_band=connected_band,
        connected_ssid=ssid,
        connected_ip=fields.get("client ipv4 address") or None,
        source_line=section_lines[0][0] if section_lines else None,
    )
    for index, row in enumerate(scan_rows):
        selected = connected_bssid is not None and row.bssid == connected_bssid
        noise_floor = row.rssi_dbm - row.snr_db if row.rssi_dbm is not None and row.snr_db is not None else None
        event.candidates.append(
            BadgeScanCandidate(
                event_id=event_id,
                candidate_index=index,
                selected=selected,
                bssid=row.bssid,
                channel=row.channel,
                band=derive_band_from_channel(row.channel),
                rssi_dbm=row.rssi_dbm,
                noise_dbm=noise_floor,
                snr_db=row.snr_db,
                snr_source=SCAN_REPORT_SOURCE if row.snr_db is not None else None,
                score=row.score,
                is_roam_candidate=True,
                source_line=row.source_line,
            )
        )

    return BadgeParseResult(
        test_run_id=test_run_id,
        source_file_id=source_id,
        source_path=str(input_path),
        parse_success=True,
        events=[event],
        warnings=warnings,
        line_count=len(lines),
    )


def _expand_input_paths(paths: Iterable[str | Path]) -> list[Path]:
    """Expand files and snapshot directories into a stable parse order."""

    expanded: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_dir():
            expanded.extend(
                child
                for child in sorted(path.rglob("*"))
                if child.is_file() and child.suffix.lower() in {".txt", ".log", ".out"}
            )
        else:
            expanded.append(path)
    return expanded


def parse_client_detail_inputs(
    paths: Iterable[str | Path],
    *,
    test_run_id: str,
    client_mac: str | None = None,
    client_model: str = DEFAULT_CLIENT_MODEL,
    timezone: str = "America/Chicago",
) -> BadgeParseResult:
    """Parse one or more WLC client-detail snapshots into one validation run."""

    input_paths = _expand_input_paths(paths)
    source_id = stable_id(test_run_id, *(str(path) for path in input_paths), prefix="src_")
    events: list[BadgeScanEvent] = []
    warnings: list[str] = []
    line_count = 0
    seen_events: set[tuple[str, tuple[tuple[str, int | None, float | None, float | None], ...]]] = set()
    for input_path in input_paths:
        result = parse_client_detail_input(
            input_path,
            test_run_id=test_run_id,
            client_mac=client_mac,
            client_model=client_model,
            timezone=timezone,
        )
        line_count += result.line_count
        warnings.extend(f"{input_path}: {warning}" for warning in result.warnings)
        for event in result.events:
            candidate_key = tuple(
                sorted((candidate.bssid, candidate.channel, candidate.rssi_dbm, candidate.snr_db) for candidate in event.candidates)
            )
            event_key = (event.event_time.isoformat(), candidate_key)
            if event_key in seen_events:
                continue
            seen_events.add(event_key)
            events.append(event)

    events.sort(key=lambda event: event.event_time)
    if not input_paths:
        warnings.append("No iPad WLC client-detail snapshot files were found.")
    if not events:
        parse_error = "No WLC Client Scan Reports rows with BSSID and RSSI were found in collected snapshots."
        return BadgeParseResult(
            test_run_id=test_run_id,
            source_file_id=source_id,
            source_path=", ".join(str(path) for path in input_paths),
            parse_success=False,
            events=[],
            warnings=warnings,
            parse_error=parse_error,
            line_count=line_count,
        )
    return BadgeParseResult(
        test_run_id=test_run_id,
        source_file_id=source_id,
        source_path=", ".join(str(path) for path in input_paths),
        parse_success=True,
        events=events,
        warnings=warnings,
        line_count=line_count,
    )

