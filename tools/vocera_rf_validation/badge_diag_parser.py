"""Parser for Vocera client diagnostic sys files and brcmfmac scan tables."""

from __future__ import annotations

import hashlib
import re
import tarfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from .models import (
    BadgeParseResult,
    BadgeRadioSignalSample,
    BadgeRrmNeighbor,
    BadgeScanCandidate,
    BadgeScanEvent,
    derive_band_from_channel,
    normalize_mac,
    stable_id,
)


ROAM_REASON_RE = re.compile(r"roam_reason\s*=\s*([^\r\n]+)")
FOUND_APS_RE = re.compile(r"Found\s+(\d+)\s+total APs\s+and\s+(\d+)\s+roam candidate APs", re.IGNORECASE)
OUTAGE_RE = re.compile(r"outage time\s*=\s*(\d+)\s*ms,\s*total_scan_time\s*=\s*(\d+)\s*ms", re.IGNORECASE)
CANDIDATE_RE = re.compile(
    r"\[(\d+)(\*)?\]\s+\[([0-9a-fA-F:.\-]{12,17})\]\s+\[Channel:\s*(\d+)\]\s+"
    r"\[RSSI\s*=\s*(-?\d+(?:\.\d+)?)\]\s+\[CU\s*=\s*(\d+(?:\.\d+)?)%\]\s+\[Score\s*=\s*(-?\d+(?:\.\d+)?)\]"
)
CONNECTED_RE = re.compile(
    r"Connected to network,\s*channel=(\d+),\s*bssid=([0-9a-fA-F:.\-]{12,17}),\s*ssid='([^']*)'",
    re.IGNORECASE,
)
RRM_RE = re.compile(
    r"RRM-NEIGHBOR-REP-RECEIVED\s+bssid=([0-9a-fA-F:.\-]{12,17})"
    r"(?:\s+info=(0x[0-9a-fA-F]+))?"
    r"(?:\s+op_class=(\d+))?"
    r"(?:\s+chan=(\d+))?"
    r"(?:\s+phy_type=(\d+))?",
    re.IGNORECASE,
)
RADIO_SIGNAL_RE = re.compile(
    r"NCI\s*:\s*Radio signal info,"
    r"sig_bars=(\d+),noise=(-?\d+(?:\.\d+)?),level=(-?\d+(?:\.\d+)?),snr=(-?\d+(?:\.\d+)?),"
    r"channel=(\d+),bandwidth=(\d+),powersave=(\d+),cu=(\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
ISO_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")
VOCERA_TS_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?\b")
SYSLOG_TS_RE = re.compile(r"\b([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{2}:\d{2}:\d{2})(?:\.\d+)?\b")
MONTHS = {name: idx for idx, name in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def _parse_line_time(line: str, timezone: str, default_year: int | None, fallback: datetime | None) -> datetime | None:
    """Extract the best timestamp available on a diagnostic log line."""
    tzinfo = ZoneInfo(timezone)
    match = VOCERA_TS_RE.search(line)
    if match:
        month, day, year, hour, minute, second = (int(part) for part in match.groups()[:6])
        micros = int(((match.group(7) or "") + "000000")[:6])
        year += 2000 if year < 70 else 1900
        return datetime(year, month, day, hour, minute, second, micros, tzinfo=tzinfo)
    match = ISO_TS_RE.search(line)
    if match:
        value = match.group(1).replace("Z", "+00:00")
        value = re.sub(
            r"\.(\d+)(?=(?:[+-]\d{2}:?\d{2})?$)",
            lambda frac: "." + (frac.group(1) + "000000")[:6],
            value,
        )
        if re.search(r"[+-]\d{2}:?\d{2}$", value):
            if re.search(r"[+-]\d{4}$", value):
                value = value[:-2] + ":" + value[-2:]
            return datetime.fromisoformat(value).astimezone(tzinfo)
        return datetime.fromisoformat(value).replace(tzinfo=tzinfo)
    match = SYSLOG_TS_RE.search(line)
    if match:
        year = default_year or datetime.now(tzinfo).year
        month = MONTHS[match.group(1)]
        day = int(match.group(2))
        hour, minute, second = (int(part) for part in match.group(3).split(":"))
        return datetime(year, month, day, hour, minute, second, tzinfo=tzinfo)
    return fallback


def _read_sources(input_path: Path) -> Iterable[tuple[str, bytes]]:
    """Yield named byte streams from raw files, directories, tarballs, or zips."""
    if input_path.is_dir():
        for path in sorted(item for item in input_path.rglob("*") if item.is_file()):
            yield str(path), path.read_bytes()
        return
    lower = input_path.name.lower()
    if lower.endswith((".tar.gz", ".tgz", ".tar")) or tarfile.is_tarfile(input_path):
        with tarfile.open(input_path) as archive:
            for member in archive.getmembers():
                if member.isfile():
                    handle = archive.extractfile(member)
                    if handle is not None:
                        yield member.name, handle.read()
        return
    if lower.endswith(".zip"):
        with zipfile.ZipFile(input_path) as archive:
            for name in archive.namelist():
                if not name.endswith("/"):
                    yield name, archive.read(name)
        return
    yield str(input_path), input_path.read_bytes()


def _source_file_id(test_run_id: str, source_name: str, content: bytes) -> str:
    """Build the stable source id stored beside parsed rows."""
    digest = hashlib.sha256(content).hexdigest()
    return stable_id(test_run_id, source_name, digest, prefix="src_")


def _new_event(
    *,
    test_run_id: str,
    source_file_id: str | None,
    event_time: datetime,
    badge_mac: str | None,
    badge_model: str | None,
    source_line: int,
) -> BadgeScanEvent:
    """Create a new roam-scan event shell before candidate lines are attached."""
    event_id = stable_id(test_run_id, source_file_id, event_time.isoformat(), source_line, prefix="bev_")
    return BadgeScanEvent(
        event_id=event_id,
        test_run_id=test_run_id,
        source_file_id=source_file_id,
        event_time=event_time,
        badge_mac=normalize_mac(badge_mac),
        badge_model=badge_model,
        source_line=source_line,
    )


def _validate_event(event: BadgeScanEvent) -> None:
    """Attach parser warnings for internally inconsistent scan events."""
    selected = [candidate for candidate in event.candidates if candidate.selected]
    if len(selected) != 1 and event.candidates:
        event.warnings.append(f"selected_candidate_count={len(selected)}")
    if event.total_aps is not None and len(event.candidates) > event.total_aps:
        event.warnings.append(f"candidate rows parsed {len(event.candidates)} exceeds total_aps {event.total_aps}")
    if event.total_aps is not None and event.candidates and len(event.candidates) < event.total_aps:
        event.warnings.append(f"candidate rows parsed {len(event.candidates)} less than total_aps {event.total_aps}")
    if event.connected_bssid and selected and selected[0].bssid != event.connected_bssid:
        event.warnings.append(f"connected_bssid {event.connected_bssid} differs from selected candidate {selected[0].bssid}")


def parse_badge_input(
    input_path: str | Path,
    *,
    test_run_id: str,
    badge_mac: str | None = None,
    badge_model: str | None = None,
    timezone: str = "America/Chicago",
    default_year: int | None = None,
) -> BadgeParseResult:
    """Parse Vocera diagnostic input into roam events and related RF evidence."""
    path = Path(input_path)
    if not path.exists():
        return BadgeParseResult(
            test_run_id=test_run_id,
            source_file_id=None,
            source_path=str(path),
            parse_success=False,
            warnings=[],
            parse_error=f"badge diagnostic input not found: {path}",
        )

    all_events: list[BadgeScanEvent] = []
    all_neighbors: list[BadgeRrmNeighbor] = []
    all_radio_samples: list[BadgeRadioSignalSample] = []
    warnings: list[str] = []
    source_ids: list[str] = []
    total_lines = 0

    for source_name, content in _read_sources(path):
        source_file_id = _source_file_id(test_run_id, source_name, content)
        source_ids.append(source_file_id)
        current: BadgeScanEvent | None = None
        last_time: datetime | None = None
        lines = content.decode("utf-8", errors="replace").splitlines()
        total_lines += len(lines)
        for line_number, line in enumerate(lines, start=1):
            line_time = _parse_line_time(line, timezone, default_year, last_time)
            if line_time is not None:
                last_time = line_time

            roam_match = ROAM_REASON_RE.search(line)
            found_match = FOUND_APS_RE.search(line)
            outage_match = OUTAGE_RE.search(line)
            candidate_match = CANDIDATE_RE.search(line)
            connected_match = CONNECTED_RE.search(line)
            rrm_match = RRM_RE.search(line)
            radio_match = RADIO_SIGNAL_RE.search(line)

            starts_new = bool(roam_match) or bool(found_match and current and (current.total_aps is not None or current.candidates))
            if starts_new:
                # A new roam_reason or second Found-APs block starts a new
                # logical scan event; validate the previous event before moving
                # on so malformed blocks are still retained with warnings.
                if current is not None:
                    _validate_event(current)
                event_time = line_time or last_time
                if event_time is None:
                    warnings.append(f"{source_name}:{line_number}: skipped event without parseable timestamp")
                    current = None
                else:
                    current = _new_event(
                        test_run_id=test_run_id,
                        source_file_id=source_file_id,
                        event_time=event_time,
                        badge_mac=badge_mac,
                        badge_model=badge_model,
                        source_line=line_number,
                    )
                    all_events.append(current)

            if found_match and current is None and line_time is not None:
                current = _new_event(
                    test_run_id=test_run_id,
                    source_file_id=source_file_id,
                    event_time=line_time,
                    badge_mac=badge_mac,
                    badge_model=badge_model,
                    source_line=line_number,
                )
                all_events.append(current)

            if roam_match and current is not None:
                current.roam_reason = roam_match.group(1).strip()
            if found_match and current is not None:
                current.total_aps = int(found_match.group(1))
                current.roam_candidate_aps = int(found_match.group(2))
            if outage_match and current is not None:
                current.outage_ms = int(outage_match.group(1))
                current.total_scan_time_ms = int(outage_match.group(2))
            if candidate_match:
                if current is None and line_time is not None:
                    current = _new_event(
                        test_run_id=test_run_id,
                        source_file_id=source_file_id,
                        event_time=line_time,
                        badge_mac=badge_mac,
                        badge_model=badge_model,
                        source_line=line_number,
                    )
                    all_events.append(current)
                if current is not None:
                    channel = int(candidate_match.group(4))
                    candidate = BadgeScanCandidate(
                        event_id=current.event_id,
                        candidate_index=int(candidate_match.group(1)),
                        selected=bool(candidate_match.group(2)),
                        bssid=normalize_mac(candidate_match.group(3)) or candidate_match.group(3).lower(),
                        channel=channel,
                        band=derive_band_from_channel(channel),
                        rssi_dbm=float(candidate_match.group(5)),
                        channel_utilization_percent=float(candidate_match.group(6)),
                        score=float(candidate_match.group(7)),
                        source_line=line_number,
                    )
                    current.candidates.append(candidate)
            if connected_match and current is not None:
                channel = int(connected_match.group(1))
                current.connected_channel = channel
                current.connected_band = derive_band_from_channel(channel)
                current.connected_bssid = normalize_mac(connected_match.group(2))
                current.connected_ssid = connected_match.group(3)
                current.ssid = current.connected_ssid
            if rrm_match and line_time is not None:
                channel = int(rrm_match.group(4)) if rrm_match.group(4) else None
                op_class = int(rrm_match.group(3)) if rrm_match.group(3) else None
                neighbor = BadgeRrmNeighbor(
                    test_run_id=test_run_id,
                    source_file_id=source_file_id,
                    event_time=line_time,
                    badge_mac=normalize_mac(badge_mac),
                    bssid=normalize_mac(rrm_match.group(1)) or rrm_match.group(1).lower(),
                    op_class=op_class,
                    channel=channel,
                    band=derive_band_from_channel(channel, op_class),
                    phy_type=int(rrm_match.group(5)) if rrm_match.group(5) else None,
                    info_hex=rrm_match.group(2),
                    source_line=line_number,
                )
                all_neighbors.append(neighbor)
            if radio_match and line_time is not None:
                channel = int(radio_match.group(5))
                all_radio_samples.append(
                    BadgeRadioSignalSample(
                        test_run_id=test_run_id,
                        source_file_id=source_file_id,
                        event_time=line_time,
                        badge_mac=normalize_mac(badge_mac),
                        sig_bars=int(radio_match.group(1)),
                        noise_dbm=float(radio_match.group(2)),
                        level_dbm=float(radio_match.group(3)),
                        snr_db=float(radio_match.group(4)),
                        channel=channel,
                        band=derive_band_from_channel(channel),
                        bandwidth_mhz=int(radio_match.group(6)),
                        powersave=int(radio_match.group(7)),
                        channel_utilization_percent=float(radio_match.group(8)),
                        source_line=line_number,
                    )
                )

        if current is not None:
            _validate_event(current)

    if not all_events:
        warnings.append("no badge scan events parsed")

    return BadgeParseResult(
        test_run_id=test_run_id,
        source_file_id=source_ids[0] if len(source_ids) == 1 else None,
        source_path=str(path),
        parse_success=bool(all_events),
        events=all_events,
        rrm_neighbors=all_neighbors,
        radio_signal_samples=all_radio_samples,
        warnings=warnings,
        line_count=total_lines,
    )
