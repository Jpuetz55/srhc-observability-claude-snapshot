"""Parsers for Cisco WLC auto-rf and traffic-distribution CLI evidence."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Dict, Iterable, List, Optional, Tuple

from .dfs import is_dfs_channel
from .models import ApAccessCategoryLatency, ApRfSnapshot, ApTags, Neighbor, WirelessRfCollectionStats

MAC_DOTTED_RE = r"[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}\.[0-9a-fA-F]{4}"
MAC_COLON_RE = r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}"
MAC_ANY_RE = rf"(?:{MAC_DOTTED_RE}|{MAC_COLON_RE})"

TAG_WITH_MAC_RE = re.compile(
    rf"^\s*(?P<ap>\S+)\s+(?P<mac>{MAC_ANY_RE})\s+"
    r"(?P<site>\S+)\s+(?P<policy>\S+)\s+(?P<rf>\S+)",
    re.IGNORECASE,
)
TAG_WITHOUT_MAC_RE = re.compile(
    r"^\s*(?P<ap>\S+)\s+(?P<site>\S+)\s+(?P<policy>\S+)\s+(?P<rf>\S+)(?:\s+.*)?$",
    re.IGNORECASE,
)
TAG_SUMMARY_HEADER_RE = re.compile(
    r"\bAP\s+Name\b.*\bSite\s+Tag\s+Name\b.*\bPolicy\s+Tag\s+Name\b.*\bRF\s+Tag\s+Name\b",
    re.IGNORECASE,
)
CMD_AUTO_RF_RE = re.compile(
    r"show\s+ap\s+name\s+(?P<ap>\S+)\s+auto-rf\s+dot11\s+(?P<band>\S+)",
    re.IGNORECASE,
)
CMD_TRAFFIC_DISTRIBUTION_LATENCY_RE = re.compile(
    r"show\s+wireless\s+stats\s+ap\s+name\s+(?P<ap>\S+)\s+"
    r"traffic-distribution\s+slot\s+(?P<slot>\S+)\s+latency\s+"
    r"access-category\s+(?P<access_category>\S+)",
    re.IGNORECASE,
)
TIME_PERIOD_END_RE = re.compile(
    r"Time\s+Period\s*:\s*Ending\s+at\s+"
    r"(?P<timestamp>\d{1,2}/\d{1,2}/\d{4}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?)",
    re.IGNORECASE,
)
AP_NAME_RE = re.compile(r"^\s*(?:AP\s+Name|Cisco\s+AP\s+Name)\s*:\s*(?P<ap>\S+)", re.IGNORECASE)
RADAR_COUNT_RE = re.compile(r"Channel\s+changes\s+due\s+to\s+radar\s*:\s*(?P<count>\d+)", re.IGNORECASE)
CHANNEL_RE = re.compile(r"\b(?:Current\s+)?Channel\s*:?\s*(?P<channel>\d{1,3})(?P<cac>#)?(?=\s|$)", re.IGNORECASE)
WIDTH_RE = re.compile(r"\b(?:Channel\s+)?Width\s*:?\s*(?P<width>\d{2,3})\b", re.IGNORECASE)
UTILIZATION_RE = re.compile(
    r"\b(?P<kind>Receive|Transmit|Channel)\s+Utilization\s*:?\s*(?P<value>\d+(?:\.\d+)?)\s*%?",
    re.IGNORECASE,
)
ZERO_WAIT_RE = re.compile(r"Zero\s+Wait\s+DFS[^:\n]*:\s*(?P<value>enabled|disabled|yes|no|true|false|capable|not capable)", re.IGNORECASE)
GENERATION_TOKEN_RE = re.compile(
    r"Wi[-\s]?Fi\s*7\s*/?\s*Non[-\s]?MLO|Wi[-\s]?Fi\s*7\s*/?\s*MLO|Non[-\s]?Wi[-\s]?Fi\s*6|Wi[-\s]?Fi\s*6",
    re.IGNORECASE,
)

PACKET_LEVEL_PATTERNS = [
    (re.compile(r"^\s*very\s+high\b", re.IGNORECASE), "very_high"),
    (re.compile(r"^\s*high\b", re.IGNORECASE), "high"),
    (re.compile(r"^\s*medium\b", re.IGNORECASE), "medium"),
    (re.compile(r"^\s*good\b", re.IGNORECASE), "good"),
]
COMMAND_FAILURE_RE = re.compile(
    r"\b(?:failure|blacklisted|invalid input|unknown command|command failed|failed|error)\b",
    re.IGNORECASE,
)
COLLECTION_METADATA_RE = re.compile(
    r"^\s*#\s*wireless_rf_collection_(?P<key>[a-z_]+):\s*(?P<value>.+?)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_mac(value: str) -> str:
    """Normalize dotted or colon MAC formats to lowercase colon notation."""

    value = value.strip().lower()
    if re.fullmatch(MAC_DOTTED_RE, value, re.IGNORECASE):
        compact = value.replace(".", "")
        return ":".join(compact[i:i + 2] for i in range(0, 12, 2))
    if re.fullmatch(MAC_COLON_RE, value, re.IGNORECASE):
        return value
    return value


def parse_bool_text(value: str) -> Optional[bool]:
    """Convert controller boolean-ish text to Python booleans when possible."""

    value = value.strip().lower()
    if value in {"enabled", "yes", "true", "capable"}:
        return True
    if value in {"disabled", "no", "false", "not capable"}:
        return False
    return None


def normalize_access_category(value: str) -> str:
    """Normalize access category names for stable Prometheus labels."""

    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "unknown"


def normalize_client_generation(value: str) -> str:
    """Normalize WLC client-generation headings into label-safe values."""

    lowered = value.strip().lower().replace("-", "").replace(" ", "").replace("/", "")
    if lowered == "wifi7mlo":
        return "wifi7_mlo"
    if lowered == "wifi7nonmlo":
        return "wifi7_non_mlo"
    if lowered == "nonwifi6":
        return "non_wifi6"
    if lowered == "wifi6":
        return "wifi6"
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "unknown"


def generation_columns(line: str) -> List[str]:
    """Return normalized client-generation headings found in one WLC table line."""

    return [normalize_client_generation(match.group(0)) for match in GENERATION_TOKEN_RE.finditer(line)]


def numeric_values(line: str) -> List[float]:
    """Return numeric table values while ignoring Wi-Fi generation labels."""

    # Remove generation tokens first so WiFi6 does not contribute a bogus value.
    cleaned = GENERATION_TOKEN_RE.sub("", line)
    return [float(token) for token in re.findall(r"(?<![A-Za-z0-9_.:-])\d+(?:\.\d+)?(?![A-Za-z0-9_.:-])", cleaned)]


def band_from_slot(slot_id: str) -> str:
    """Map Cisco radio slot ids to dashboard band labels."""

    slot = slot_id.strip().lower()
    if slot == "0":
        return "2.4ghz"
    if slot == "1":
        return "5ghz"
    if slot == "2":
        return "6ghz"
    return "unknown"


def parse_time_period_end_timestamp_seconds(block: str) -> Optional[float]:
    """Parse the WLC traffic-distribution sample-end timestamp."""

    match = TIME_PERIOD_END_RE.search(block)
    if not match:
        return None
    value = match.group("timestamp")
    for fmt in ("%m/%d/%Y %H:%M:%S.%f", "%m/%d/%Y %H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    return None


def looks_like_command_echo(line: str) -> bool:
    """Detect WLC command echoes embedded in collected text."""

    stripped = line.strip()
    if stripped.lower().startswith("show "):
        return True
    return bool(re.match(r"^\S+#\s*show\s+", stripped, re.IGNORECASE))


def parse_collection_metadata(text: str) -> dict[str, str]:
    """Parse collector metadata comments embedded at the top of raw evidence."""

    return {
        match.group("key").strip().lower(): match.group("value").strip()
        for match in COLLECTION_METADATA_RE.finditer(text)
    }


def metadata_float(metadata: dict[str, str], key: str) -> float | None:
    """Read a floating-point metadata value when present."""

    try:
        return float(metadata[key])
    except (KeyError, ValueError):
        return None


def metadata_int(metadata: dict[str, str], key: str) -> int | None:
    """Read an integer metadata value when present."""

    try:
        return int(float(metadata[key]))
    except (KeyError, ValueError):
        return None


def parse_ap_tag_summary(text: str) -> Dict[str, ApTags]:
    """Parse the AP tag table used to enrich later per-AP command blocks."""

    tags: Dict[str, ApTags] = {}
    in_tag_table = False
    for line in text.splitlines():
        stripped = line.strip()
        if TAG_SUMMARY_HEADER_RE.search(line):
            in_tag_table = True
            continue
        if not in_tag_table:
            continue
        if not stripped or stripped.endswith("#") or stripped.lower().startswith("show "):
            in_tag_table = False
            continue
        if set(stripped) <= {"-"}:
            continue
        m = TAG_WITH_MAC_RE.match(line)
        has_mac = bool(m)
        if not m:
            m = TAG_WITHOUT_MAC_RE.match(line)
        if not m:
            continue
        ap = m.group("ap").strip()
        # Avoid accidental matches on command echo or separator lines.
        if ap.lower() in {"ap", "ap-name", "name", "show", "number", "total"}:
            continue
        site_tag = m.group("site").strip()
        policy_tag = m.group("policy").strip()
        rf_tag = m.group("rf").strip()
        if site_tag.lower() == "name" or policy_tag.lower() == "tag" or rf_tag.lower() == "name":
            continue
        tags[ap] = ApTags(
            ap_name=ap,
            ap_mac=normalize_mac(m.group("mac")) if has_mac else "",
            site_tag=site_tag,
            policy_tag=policy_tag,
            rf_tag=rf_tag,
        )
    return tags


def iter_auto_rf_blocks(text: str, default_band: str = "5ghz") -> Iterable[Tuple[str, str, str]]:
    """Yield (ap_name, band, block_text) for each per-AP auto-rf command block."""

    matches = list(CMD_AUTO_RF_RE.finditer(text))
    if matches:
        for idx, match in enumerate(matches):
            start = match.start()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
            yield match.group("ap"), match.group("band").lower(), text[start:end]
        return

    if CMD_TRAFFIC_DISTRIBUTION_LATENCY_RE.search(text):
        return

    # Fallback for a single pasted auto-rf output without the command echo.
    ap_name = "unknown"
    band = default_band
    for line in text.splitlines():
        m = AP_NAME_RE.match(line)
        if m:
            ap_name = m.group("ap")
            break
    yield ap_name, band, text


def iter_traffic_distribution_latency_blocks(text: str) -> Iterable[Tuple[str, str, str, str]]:
    """Yield (ap_name, slot_id, access_category, block_text) for traffic-distribution latency output."""

    traffic_matches = list(CMD_TRAFFIC_DISTRIBUTION_LATENCY_RE.finditer(text))
    if not traffic_matches:
        return

    command_starts = sorted(
        [match.start() for match in traffic_matches]
        + [match.start() for match in CMD_AUTO_RF_RE.finditer(text)]
    )
    for match in traffic_matches:
        next_starts = [start for start in command_starts if start > match.start()]
        end = next_starts[0] if next_starts else len(text)
        yield (
            match.group("ap"),
            match.group("slot").strip(),
            normalize_access_category(match.group("access_category")),
            text[match.start():end],
        )


def extract_section(block: str, start_pattern: str, stop_patterns: List[str]) -> str:
    """Return the text between a start heading and the next stop heading."""

    lines = block.splitlines()
    start_idx: Optional[int] = None
    start_re = re.compile(start_pattern, re.IGNORECASE)
    stop_res = [re.compile(pattern, re.IGNORECASE) for pattern in stop_patterns]
    for idx, line in enumerate(lines):
        if start_re.search(line):
            start_idx = idx + 1
            break
    if start_idx is None:
        return ""
    end_idx = len(lines)
    for idx in range(start_idx, len(lines)):
        if any(stop_re.search(lines[idx]) for stop_re in stop_res):
            end_idx = idx
            break
    return "\n".join(lines[start_idx:end_idx])


def first_channel_after_mac(line: str) -> Optional[int]:
    """Find the first plausible channel after a MAC in a neighbor row."""

    mac_match = re.search(MAC_ANY_RE, line, re.IGNORECASE)
    tail = line[mac_match.end():] if mac_match else line
    for token in re.findall(r"(?<!\d)(\d{1,3})(?:#)?(?!\d)", tail):
        channel = int(token)
        if 1 <= channel <= 196:
            return channel
    return None


def first_rssi(line: str) -> Optional[int]:
    """Return the first explicit negative dBm value in a neighbor row."""

    # Prefer explicit negative dBm values. If the platform emits RSSI as a
    # positive absolute value, ignore it rather than risk counting channel or
    # power columns as RSSI.
    for token in re.findall(r"(?<!\d)(-\d{2,3})(?!\d)", line):
        value = int(token)
        if -100 <= value <= -10:
            return value
    return None


def looks_like_neighbor_line(line: str) -> bool:
    """Filter the loose WLC neighbor table variants down to data rows."""

    stripped = line.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if lowered.startswith(("---", "nearby", "ap name", "mac", "slot", "channel", "radar")):
        return False
    if "no nearby" in lowered or "not available" in lowered:
        return False
    if re.search(MAC_ANY_RE, stripped, re.IGNORECASE):
        return True
    # Some WLC tables do not include MACs in every output variant. Require at
    # least an AP-looking first token and an RSSI-looking value to reduce noise.
    first = stripped.split()[0]
    return bool(re.match(r"^[A-Za-z0-9_.:-]+$", first) and first_rssi(stripped) is not None)


def parse_neighbors(block: str) -> List[Neighbor]:
    """Parse Nearby AP rows from an auto-rf block."""

    section = extract_section(
        block,
        r"Nearby\s+APs",
        [r"Radar\s+Information", r"Load\s+Information", r"Profile\s+Information", r"^\S+#\s*show\s+"],
    )
    neighbors: List[Neighbor] = []
    for line in section.splitlines():
        if not looks_like_neighbor_line(line):
            continue
        stripped = line.strip()
        mac_match = re.search(MAC_ANY_RE, stripped, re.IGNORECASE)
        parts = stripped.split()
        neighbor_ap = parts[0] if parts else "unknown"
        neighbor_mac = normalize_mac(mac_match.group(0)) if mac_match else ""
        neighbors.append(
            Neighbor(
                neighbor_ap=neighbor_ap,
                neighbor_mac=neighbor_mac,
                channel=first_channel_after_mac(stripped),
                rssi_dbm=first_rssi(stripped),
                raw_line=stripped,
            )
        )
    return neighbors


def parse_current_channel(block: str) -> tuple[Optional[int], bool]:
    """Return the current channel and whether the WLC marked it with CAC."""

    for m in CHANNEL_RE.finditer(block):
        channel = int(m.group("channel"))
        if 1 <= channel <= 196:
            return channel, bool(m.group("cac"))
    return None, False


def parse_channel_width(block: str) -> Optional[int]:
    """Parse a valid channel width from an auto-rf block."""

    m = WIDTH_RE.search(block)
    if not m:
        return None
    width = int(m.group("width"))
    return width if width in {20, 40, 80, 160, 320} else None


def parse_load_utilization(block: str) -> tuple[Optional[float], Optional[float], Optional[float]]:
    """Parse receive/transmit/channel utilization percentages."""

    values: dict[str, float] = {}
    for match in UTILIZATION_RE.finditer(block):
        value = float(match.group("value"))
        if 0 <= value <= 100:
            values[match.group("kind").lower()] = value
    return values.get("receive"), values.get("transmit"), values.get("channel")


def parse_radar_changes(block: str) -> Optional[int]:
    """Parse the cumulative radar-triggered channel-change count."""

    m = RADAR_COUNT_RE.search(block)
    return int(m.group("count")) if m else None


def parse_zero_wait_dfs(block: str) -> tuple[Optional[bool], Optional[bool]]:
    """Extract Zero Wait DFS capability/enabled state when the platform reports it."""

    capable: Optional[bool] = None
    enabled: Optional[bool] = None
    for line in block.splitlines():
        if "zero" not in line.lower() or "dfs" not in line.lower():
            continue
        value_match = ZERO_WAIT_RE.search(line)
        if not value_match:
            continue
        value = parse_bool_text(value_match.group("value"))
        if "capable" in line.lower():
            capable = value
        else:
            enabled = value
    return capable, enabled


def _traffic_observation(
    observations: Dict[str, ApAccessCategoryLatency],
    generation: str,
    slot_id: str,
    access_category: str,
    sample_end_timestamp_seconds: float | None,
) -> ApAccessCategoryLatency:
    """Return the per-generation latency observation, creating it on demand."""

    generation = normalize_client_generation(generation)
    if generation not in observations:
        observations[generation] = ApAccessCategoryLatency(
            slot_id=slot_id,
            band=band_from_slot(slot_id),
            access_category=access_category,
            client_generation=generation,
            sample_end_timestamp_seconds=sample_end_timestamp_seconds,
        )
    elif observations[generation].sample_end_timestamp_seconds is None:
        observations[generation].sample_end_timestamp_seconds = sample_end_timestamp_seconds
    return observations[generation]


def _assign_traffic_values(
    observations: Dict[str, ApAccessCategoryLatency],
    slot_id: str,
    access_category: str,
    current_generation: str | None,
    header_generations: List[str],
    line_generations: List[str],
    values: List[float],
    metric: str,
    sample_end_timestamp_seconds: float | None,
    latency_level: str | None = None,
) -> None:
    """Map numeric table values onto client-generation observations.

    WLC output varies between one-value-per-line and multi-generation rows, so
    the assignment falls back from line-local generation headings to the last
    seen table header before using an `all` bucket.
    """

    if not values:
        return

    if line_generations and len(values) >= len(line_generations):
        pairs = zip(line_generations, values[-len(line_generations):])
    elif header_generations and len(values) >= len(header_generations):
        pairs = zip(header_generations, values[-len(header_generations):])
    else:
        pairs = [(current_generation or "all", values[-1])]

    for generation, value in pairs:
        observation = _traffic_observation(
            observations,
            generation,
            slot_id,
            access_category,
            sample_end_timestamp_seconds,
        )
        if metric == "avg_latency_us":
            observation.avg_latency_us = value
        elif metric == "active_clients":
            observation.active_clients = int(value)
        elif metric == "packets" and latency_level:
            observation.packets_by_latency_level[latency_level] = int(value)


def parse_traffic_distribution_latency_block(
    block: str,
    slot_id: str,
    access_category: str,
) -> List[ApAccessCategoryLatency]:
    """Parse AP traffic-distribution latency for one command block."""

    observations: Dict[str, ApAccessCategoryLatency] = {}
    current_generation: str | None = None
    header_generations: List[str] = []
    sample_end_timestamp_seconds = parse_time_period_end_timestamp_seconds(block)

    for raw_line in block.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        line_generations = generation_columns(line)
        values = numeric_values(line)
        lowered = line.lower()

        metric: str | None = None
        latency_level: str | None = None
        if "active client" in lowered:
            metric = "active_clients"
        elif "average latency" in lowered:
            metric = "avg_latency_us"
        else:
            for pattern, level in PACKET_LEVEL_PATTERNS:
                if pattern.search(line):
                    metric = "packets"
                    latency_level = level
                    break

        if metric:
            _assign_traffic_values(
                observations,
                slot_id,
                access_category,
                current_generation,
                header_generations,
                line_generations,
                values,
                metric,
                sample_end_timestamp_seconds,
                latency_level=latency_level,
            )
            continue

        if line_generations and not values:
            current_generation = line_generations[0]
            if len(line_generations) > 1:
                header_generations = line_generations

    return list(observations.values())


def looks_like_auto_rf_output(block: str) -> bool:
    """Detect real auto-rf output and skip command failures/empty blocks."""

    lowered = block.lower()
    return bool(
        AP_NAME_RE.search(block)
        or "nearby aps" in lowered
        or "radar information" in lowered
        or "noise information" in lowered
        or "load information" in lowered
    )


def parse_wlc_rf_dump(text: str, wlc: str = "unknown", default_band: str = "5ghz") -> List[ApRfSnapshot]:
    """Parse one raw WLC evidence file into normalized AP snapshots."""

    tags_by_ap = parse_ap_tag_summary(text)
    snapshots: List[ApRfSnapshot] = []
    snapshots_by_ap_band: Dict[tuple[str, str], ApRfSnapshot] = {}
    snapshots_by_ap: Dict[str, ApRfSnapshot] = {}

    for ap_name, band, block in iter_auto_rf_blocks(text, default_band=default_band):
        if not looks_like_auto_rf_output(block):
            continue
        tag = tags_by_ap.get(ap_name, ApTags(ap_name=ap_name))
        current_channel, cac_marker = parse_current_channel(block)
        receive_utilization_pct, transmit_utilization_pct, channel_utilization_pct = parse_load_utilization(block)
        capable, enabled = parse_zero_wait_dfs(block)
        cac_running = cac_marker or ("cac" in block.lower() and "running" in block.lower())
        snapshot = ApRfSnapshot(
            ap_name=ap_name,
            wlc=wlc,
            band=band or default_band,
            site_tag=tag.site_tag,
            policy_tag=tag.policy_tag,
            rf_tag=tag.rf_tag,
            current_channel=current_channel,
            channel_width_mhz=parse_channel_width(block),
            receive_utilization_pct=receive_utilization_pct,
            transmit_utilization_pct=transmit_utilization_pct,
            channel_utilization_pct=channel_utilization_pct,
            is_dfs_channel=is_dfs_channel(current_channel),
            cac_running=cac_running,
            radar_changes_total=parse_radar_changes(block),
            zero_wait_dfs_capable=capable,
            zero_wait_dfs_enabled=enabled,
            neighbors=parse_neighbors(block),
            has_auto_rf=True,
        )
        snapshots.append(snapshot)
        snapshots_by_ap_band[(ap_name, snapshot.band)] = snapshot
        snapshots_by_ap.setdefault(ap_name, snapshot)

    for ap_name, slot_id, access_category, block in iter_traffic_distribution_latency_blocks(text):
        # Traffic-distribution commands do not always travel next to auto-rf
        # commands. Create a latency-only snapshot when no RF snapshot exists.
        band = band_from_slot(slot_id)
        key = (ap_name, band)
        tag = tags_by_ap.get(ap_name, ApTags(ap_name=ap_name))
        latencies = parse_traffic_distribution_latency_block(block, slot_id=slot_id, access_category=access_category)
        if not latencies:
            continue
        snapshot = snapshots_by_ap_band.get(key)
        if snapshot is None:
            snapshot = ApRfSnapshot(
                ap_name=ap_name,
                wlc=wlc,
                band=band,
                site_tag=tag.site_tag,
                policy_tag=tag.policy_tag,
                rf_tag=tag.rf_tag,
            )
            snapshots.append(snapshot)
            snapshots_by_ap_band[key] = snapshot
            snapshots_by_ap.setdefault(ap_name, snapshot)
        snapshot.access_category_latencies.extend(latencies)

    return snapshots


def build_collection_stats(
    text: str,
    snapshots: Iterable[ApRfSnapshot],
    wlc: str = "unknown",
    last_success_timestamp_seconds: float | None = None,
    duration_seconds: float | None = None,
) -> WirelessRfCollectionStats:
    """Build collection health metrics from embedded metadata and parsed data."""

    snapshot_list = list(snapshots)
    metadata = parse_collection_metadata(text)
    commands_total = (
        metadata_int(metadata, "commands_total")
        or sum(1 for line in text.splitlines() if looks_like_command_echo(line))
    )
    commands_failed_total = sum(1 for line in text.splitlines() if COMMAND_FAILURE_RE.search(line))
    latency_samples_total = sum(
        1
        for snapshot in snapshot_list
        for latency in snapshot.access_category_latencies
        if latency.avg_latency_us is not None
    )
    ap_count = len({snapshot.ap_name for snapshot in snapshot_list if snapshot.ap_name != "unknown"})
    metadata_finished_at = metadata_float(metadata, "finished_at_seconds")
    metadata_duration = metadata_float(metadata, "duration_seconds")
    return WirelessRfCollectionStats(
        wlc=wlc,
        last_success_timestamp_seconds=metadata_finished_at or last_success_timestamp_seconds,
        duration_seconds=duration_seconds if duration_seconds is not None else (metadata_duration or 0),
        commands_total=commands_total,
        commands_failed_total=commands_failed_total,
        ap_count=ap_count,
        latency_samples_total=latency_samples_total,
        last_error_reason="dnac_collect_failed" if commands_failed_total else "none",
    )


def apply_filters(
    snapshots: Iterable[ApRfSnapshot],
    site_tag: str | None = None,
    site_tag_regex: str | None = None,
    ap_name_regex: str | None = None,
    band: str | None = None,
    min_neighbors: int | None = None,
) -> List[ApRfSnapshot]:
    """Apply CLI/API filters after parsing so raw evidence can be reused."""

    site_re = re.compile(site_tag_regex) if site_tag_regex else None
    ap_re = re.compile(ap_name_regex) if ap_name_regex else None
    output: List[ApRfSnapshot] = []
    for snapshot in snapshots:
        if site_tag and snapshot.site_tag != site_tag:
            continue
        if site_re and not site_re.search(snapshot.site_tag):
            continue
        if ap_re and not ap_re.search(snapshot.ap_name):
            continue
        if band and snapshot.band.lower() != band.lower():
            continue
        if min_neighbors is not None and snapshot.neighbor_count < min_neighbors:
            continue
        output.append(snapshot)
    return output
