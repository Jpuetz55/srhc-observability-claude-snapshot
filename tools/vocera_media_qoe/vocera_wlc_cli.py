#!/usr/bin/env python3
"""Parse manually saved Catalyst 9800 WLC multicast evidence snapshots."""

from __future__ import annotations

import re
from typing import Any

import vocera_multicast as multicast


MAC_HEX_RE = re.compile(r"(?i)(?:[0-9a-f]{2}[:.-]?){5}[0-9a-f]{2}|[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
WLC_COMMAND_RE = re.compile(
    r"^\s*(?:[A-Za-z0-9_.:/()-]+[>#]\s*)?"
    r"("
    r"(?:show|monitor\s+capture|no\s+monitor\s+capture|configure\s+terminal|"
    r"ip\s+access-list|no\s+ip\s+access-list|terminal\s+length|end)"
    r"\b.*"
    r")$",
    flags=re.IGNORECASE,
)


def normalize_mac(value: str | None) -> str | None:
    """Normalize a MAC address to lower-case colon notation."""

    if not value:
        return None
    mac_digits = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(mac_digits) != 12:
        return None
    mac_digits = mac_digits.lower()
    return ":".join(mac_digits[index : index + 2] for index in range(0, 12, 2))


def mac_token(value: str | None) -> str | None:
    """Return a compact lower-case MAC token for text matching."""

    normalized = normalize_mac(value)
    return normalized.replace(":", "") if normalized else None


def _first_match(patterns: tuple[str, ...], text: str) -> str | None:
    """Return the first regex capture found in text."""

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1) if match.lastindex else match.group(0)
            return value.strip()
    return None


def _int_or_none(value: Any) -> int | None:
    """Convert a simple integer value when possible."""

    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _is_multicast_group(value: str) -> bool:
    """Return true when an IPv4 address is in multicast range."""

    parts = value.split(".")
    try:
        first = int(parts[0])
    except (IndexError, ValueError):
        return False
    return 224 <= first <= 239


def _command_from_line(line: str) -> str | None:
    """Return a normalized WLC command echoed in a transcript line."""

    match = WLC_COMMAND_RE.match(line)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).strip())


def _show_blocks(text: str) -> list[tuple[str, str]]:
    """Return transcript blocks keyed by their leading `show ...` command."""

    blocks: list[tuple[str, list[str]]] = []
    current_command: str | None = None
    current_lines: list[str] = []
    for line in text.splitlines():
        command = _command_from_line(line)
        if command and command.lower().startswith("show "):
            if current_command is not None:
                blocks.append((current_command, current_lines))
            current_command = command
            current_lines = [line]
        elif current_command is not None:
            current_lines.append(line)
    if current_command is not None:
        blocks.append((current_command, current_lines))
    return [(command, "\n".join(lines)) for command, lines in blocks]


def extract_attempt_ids(text: str) -> list[str]:
    """Return attempt IDs explicitly visible in a transcript.

    Generated resolved-group sheets include an ``! Attempt: ...`` marker. We use
    only explicit markers for high-confidence automatic association; otherwise
    the transcript remains session-level evidence.
    """

    seen: set[str] = set()
    attempts: list[str] = []
    for match in re.finditer(r"(?im)^\s*!\s*Attempt\s*:\s*([A-Za-z0-9_.:-]+)\s*$", text):
        attempt_id = match.group(1).strip()
        if attempt_id and attempt_id != "<unbound>" and attempt_id not in seen:
            attempts.append(attempt_id)
            seen.add(attempt_id)
    return attempts


def infer_transcript_phase(text: str) -> str:
    """Classify a terminal transcript by the WLC evidence commands it contains."""

    lowered = text.lower()
    if "no monitor capture" in lowered or "no ip access-list extended" in lowered:
        return "cleanup"
    if "monitor capture" in lowered and " export " in lowered:
        return "capture_stop_export"
    if "monitor capture" in lowered and " start" in lowered:
        return "capture_start"
    if re.search(r"show\s+capwap\s+mcast\s+mgid", text, flags=re.IGNORECASE):
        return "ap_evidence"
    has_group_detail = re.search(
        r"show\s+wireless\s+multicast\s+(?:group|source)\s+(?!summary\b)",
        text,
        flags=re.IGNORECASE,
    )
    if has_group_detail:
        return "resolved_group"
    if re.search(r"show\s+wireless\s+multicast\s+group\s+summary", text, flags=re.IGNORECASE):
        if re.search(r"mobility\s+history", text, flags=re.IGNORECASE) and re.search(
            r"show\s+monitor\s+capture\s+\S+\s+buffer\s+brief", text, flags=re.IGNORECASE
        ):
            return "post_failure"
        if re.search(r"show\s+monitor\s+capture\s+\S+\s+buffer\s+brief", text, flags=re.IGNORECASE):
            return "active_event"
        if re.search(r"mobility\s+history|show\s+ap\s+multicast\s+mom", text, flags=re.IGNORECASE):
            return "baseline"
    if re.search(r"mobility\s+history", text, flags=re.IGNORECASE):
        return "post_failure"
    return "unassigned"


def transcript_command_blocks(text: str) -> list[dict[str, Any]]:
    """Split one output-only terminal log into generated-sheet command blocks.

    Generated WLC command sheets start with ``terminal length 0``. Use that
    operator-visible boundary to keep baseline, active-event, resolved-group,
    stop/export, post-failure, and cleanup evidence separate while still
    preserving the original terminal transcript as one artifact.
    """

    blocks: list[dict[str, Any]] = []
    current_lines: list[str] = []
    commands: list[str] = []

    def flush() -> None:
        nonlocal current_lines, commands
        if not commands:
            current_lines = []
            return
        block_text = "\n".join(current_lines).strip()
        if not block_text:
            current_lines = []
            commands = []
            return
        block_index = len(blocks)
        phase = infer_transcript_phase(block_text)
        blocks.append(
            {
                "block_index": block_index,
                "block_id": f"block-{block_index:04d}",
                "phase": phase,
                "commands": list(commands),
                "attempt_ids": extract_attempt_ids(block_text),
                "text": block_text,
            }
        )
        current_lines = []
        commands = []

    for line in text.splitlines():
        command = _command_from_line(line)
        if command and re.match(r"terminal\s+length\s+0\b", command, flags=re.IGNORECASE):
            flush()
            current_lines = [line]
            commands = [command]
            continue
        if command:
            if not current_lines:
                current_lines = [line]
            else:
                current_lines.append(line)
            commands.append(command)
            continue
        if current_lines:
            current_lines.append(line)
    flush()
    return blocks


def _group_detail_blocks(text: str) -> list[str]:
    """Return multicast group/source detail blocks, excluding the summary table."""

    blocks: list[str] = []
    for command, block in _show_blocks(text):
        if re.search(r"\bshow\s+wireless\s+multicast\s+group\s+summary\b", command, flags=re.IGNORECASE):
            continue
        if re.search(r"\bshow\s+wireless\s+multicast\s+(?:group|source)\b", command, flags=re.IGNORECASE):
            blocks.append(block)
    return blocks


def _client_detail_block(text: str, client_mac: str | None) -> str:
    """Return one client-detail command block for the requested MAC."""

    wanted = normalize_mac(client_mac)
    for command, block in _show_blocks(text):
        if not re.search(r"\bshow\s+wireless\s+client\s+mac-address\b", command, flags=re.IGNORECASE):
            continue
        if not re.search(r"\bdetail\b", command, flags=re.IGNORECASE):
            continue
        command_mac = normalize_mac(MAC_HEX_RE.search(command).group(0)) if MAC_HEX_RE.search(command) else None
        if wanted is None or command_mac == wanted:
            return block
    return ""


def _extract_client_vlans(text: str, client_mac: str | None) -> dict[str, int | None]:
    """Extract client-side VLAN fields without treating them as group VLANs."""

    block = _client_detail_block(text, client_mac)
    return {
        "client_vlan": _int_or_none(_first_match((r"^\s*VLAN(?:\s+ID)?\s*[:=]\s*(\d+)\s*$",), block)),
        "multicast_vlan": _int_or_none(_first_match((r"^\s*Multicast\s+VLAN\s*[:=]\s*(\d+)\s*$",), block)),
    }


def _vlan_context_state(configured_vlan: int | None, resolved_group_vlan: int | None, group_ip: str | None) -> str:
    """Classify whether the active group VLAN is known and aligned."""

    if group_ip and resolved_group_vlan is not None and configured_vlan is not None:
        return "resolved_confirmed" if resolved_group_vlan == configured_vlan else "configured_group_mismatch"
    if group_ip and resolved_group_vlan is not None:
        return "resolved_confirmed"
    return "configured_only" if configured_vlan is not None else "unresolved"


def _extract_group_summary(text: str) -> list[dict[str, Any]]:
    """Parse `show wireless multicast group summary` rows."""

    groups: list[dict[str, Any]] = []
    seen: set[tuple[int | None, str, int | None]] = set()
    for line in text.splitlines():
        match = re.search(r"^\s*(\d+)\s+((?:\d{1,3}\.){3}\d{1,3})\s+(\d+)\s*$", line)
        if not match or not _is_multicast_group(match.group(2)):
            continue
        row = {
            "mgid": _int_or_none(match.group(1)),
            "group": match.group(2),
            "vlan": _int_or_none(match.group(3)),
        }
        key = (row["mgid"], row["group"], row["vlan"])
        if key not in seen:
            groups.append(row)
            seen.add(key)
    return groups


def _extract_receiver_membership(text: str, receiver_mac: str | None) -> tuple[bool | None, str | None]:
    """Detect receiver membership in a multicast group detail output."""

    receiver_mac_digits = mac_token(receiver_mac)
    if not receiver_mac_digits:
        return None, None
    for line in text.splitlines():
        compact = re.sub(r"[^0-9A-Fa-f]", "", line).lower()
        if receiver_mac_digits not in compact:
            continue
        words = line.split()
        status = words[-1] if words else None
        return True, status
    if "Client MAC" in text or "Client List" in text:
        return False, None
    return None, None


def _extract_ap_mom_status(text: str) -> str | None:
    """Summarize AP multicast-over-multicast status from command output."""

    statuses: set[str] = set()
    for line in text.splitlines():
        if re.search(r"\b(up|down|unknown)\b", line, flags=re.IGNORECASE):
            if re.search(r"\bdown\b", line, flags=re.IGNORECASE):
                statuses.add("down")
            elif re.search(r"\bup\b", line, flags=re.IGNORECASE):
                statuses.add("up")
            elif re.search(r"\bunknown\b", line, flags=re.IGNORECASE):
                statuses.add("unknown")
    if "down" in statuses:
        return "down"
    if "up" in statuses:
        return "up"
    if "unknown" in statuses:
        return "unknown"
    return None


def _extract_igmp_version(text: str) -> str | None:
    """Return the most specific IGMP version visible in a transcript."""

    if re.search(r"\bigmpv?3\b|\bigmp\s+version\s+3\b", text, flags=re.IGNORECASE):
        return "v3"
    if re.search(r"\bigmpv?2\b|\bigmp\s+version\s+2\b", text, flags=re.IGNORECASE):
        return "v2"
    if re.search(r"\bigmp\b", text, flags=re.IGNORECASE):
        return "unknown"
    return None


def _extract_ap_mgid_clients(text: str) -> list[dict[str, Any]]:
    """Parse AP-side MGID client rows when an AP shell transcript is present."""

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str | None, int | None, str | None]] = set()
    for line in text.splitlines():
        mac_match = MAC_HEX_RE.search(line)
        if not mac_match:
            continue
        mode_match = re.search(r"\b(mc_only|mc2uc|multicast|unicast)\b", line, flags=re.IGNORECASE)
        if not mode_match:
            continue
        integers = [int(value) for value in re.findall(r"\b\d+\b", line)]
        mgid = integers[0] if integers else None
        row = {
            "mgid": mgid,
            "receiver_mac": normalize_mac(mac_match.group(0)),
            "ap_delivery_mode": mode_match.group(1).lower(),
            "ap_slot": _first_match((r"\bslot\s*[:=]?\s*(\d+)",), line),
            "raw_line": line.strip(),
        }
        key = (row["receiver_mac"], row["mgid"], row["ap_delivery_mode"])
        if key not in seen:
            rows.append(row)
            seen.add(key)
    return rows


def _extract_ap_mgid_counters(text: str) -> list[dict[str, Any]]:
    """Parse AP-side MGID counter rows when visible."""

    rows: list[dict[str, Any]] = []
    for line in text.splitlines():
        if MAC_HEX_RE.search(line):
            continue
        mode_match = re.search(r"\b(mc_only|mc2uc)\b", line, flags=re.IGNORECASE)
        if not mode_match and not re.search(r"\bmgid\b|\bmcast\b", line, flags=re.IGNORECASE):
            continue
        integers = [int(value) for value in re.findall(r"\b\d+\b", line)]
        if len(integers) < 2:
            continue
        row = {
            "ap_mgid": integers[0],
            "ap_rx_packets": integers[-2] if len(integers) >= 3 else None,
            "ap_tx_packets": integers[-1],
            "ap_delivery_mode": mode_match.group(1).lower() if mode_match else None,
            "raw_line": line.strip(),
        }
        rows.append(row)
    return rows


def parse_wlc_snapshot(
    text: str,
    *,
    phase: str = "unknown",
    receiver_mac: str | None = None,
    sender_mac: str | None = None,
    expected_vlan: int | None = None,
) -> dict[str, Any]:
    """Parse one saved WLC CLI snapshot into conservative structured evidence."""

    groups = _extract_group_summary(text)
    group_detail_text = "\n".join(_group_detail_blocks(text))
    group_detail_available = bool(group_detail_text.strip())
    group = _first_match((r"^\s*Group\s*:\s*((?:\d{1,3}\.){3}\d{1,3})\s*$",), group_detail_text)
    vlan = _int_or_none(_first_match((r"^\s*Vlan\s*:\s*(\d+)\s*$",), group_detail_text))
    mgid = _int_or_none(_first_match((r"^\s*MGID\s*:\s*(\d+)\s*$",), group_detail_text))
    command_group = _first_match(
        (
            r"\bshow\s+wireless\s+multicast\s+group\s+((?:\d{1,3}\.){3}\d{1,3})\s+vlan\s+\d+",
            r"\bshow\s+wireless\s+multicast\s+source\s+\S+\s+group\s+((?:\d{1,3}\.){3}\d{1,3})\s+vlan\s+\d+",
        ),
        group_detail_text,
    )
    command_vlan = _int_or_none(
        _first_match(
            (
                r"\bshow\s+wireless\s+multicast\s+group\s+(?:\d{1,3}\.){3}\d{1,3}\s+vlan\s+(\d+)",
                r"\bshow\s+wireless\s+multicast\s+source\s+\S+\s+group\s+(?:\d{1,3}\.){3}\d{1,3}\s+vlan\s+(\d+)",
            ),
            group_detail_text,
        )
    )
    group = group or command_group
    vlan = vlan if vlan is not None else command_vlan
    if not group and groups:
        candidates = [item for item in groups if expected_vlan is None or item.get("vlan") == expected_vlan]
        selected = candidates[0] if candidates else groups[0]
        group = str(selected.get("group") or "")
        vlan = _int_or_none(selected.get("vlan")) if vlan is None else vlan
        mgid = _int_or_none(selected.get("mgid")) if mgid is None else mgid

    member, member_status = _extract_receiver_membership(group_detail_text, receiver_mac) if group_detail_available else (None, None)
    dynamic_group_ips = multicast.find_vocera_multicast_ips(text)
    dynamic_group_ip = group if group and multicast.is_vocera_multicast_ip(group) else (dynamic_group_ips[0] if dynamic_group_ips else None)
    dynamic_group_mac = multicast.ipv4_multicast_to_mac(dynamic_group_ip) if dynamic_group_ip else None
    receiver_ap = _first_match(
        (
            r"\b(?:AP Name|AP name|Current AP|Associated AP)\s*[:=]\s*([^\r\n,]+)",
            r"\bAP\s*:\s*([^\r\n,]+)",
        ),
        text,
    )
    receiver_bssid = normalize_mac(_first_match((r"\bBSSID\s*[:=]\s*([0-9A-Fa-f:.-]+)",), text))
    receiver_channel = _int_or_none(_first_match((r"\bChannel\s*[:=]\s*(\d+)",), text))
    receiver_band = _first_match((r"\b(?:Band|Radio Type|Radio)\s*[:=]\s*([^\r\n,]+)",), text)
    sender_vlans = _extract_client_vlans(text, sender_mac)
    receiver_vlans = _extract_client_vlans(text, receiver_mac)
    receiver_vlan = receiver_vlans["client_vlan"]
    receiver_rssi = _int_or_none(_first_match((r"\bRSSI\s*[:=]\s*(-?\d+)",), text))
    receiver_snr = _int_or_none(_first_match((r"\bSNR\s*[:=]\s*(-?\d+)",), text))
    receiver_state = _first_match((r"\b(?:Policy Manager State|Client State|State)\s*[:=]\s*([^\r\n,]+)",), text)

    multicast_enabled = None
    if re.search(r"\bMulticast\s*:\s*Enabled\b", text, flags=re.IGNORECASE):
        multicast_enabled = True
    elif re.search(r"\bMulticast\s*:\s*Disabled\b", text, flags=re.IGNORECASE):
        multicast_enabled = False

    igmp_snooping_enabled = None
    if re.search(r"\bIGMP snooping\s*:\s*Enabled\b", text, flags=re.IGNORECASE):
        igmp_snooping_enabled = True
    elif re.search(r"\bIGMP snooping\s*:\s*Disabled\b", text, flags=re.IGNORECASE):
        igmp_snooping_enabled = False

    igmp_querier_enabled = None
    if re.search(r"\bquerier\b.*\benabled\b", text, flags=re.IGNORECASE):
        igmp_querier_enabled = True
    elif re.search(r"\bquerier\b.*\bdisabled\b", text, flags=re.IGNORECASE):
        igmp_querier_enabled = False

    receiver_token = mac_token(receiver_mac)
    receiver_blocklisted = bool(receiver_token and receiver_token in re.sub(r"[^0-9A-Fa-f]", "", text).lower() and re.search(r"\bblock", text, flags=re.IGNORECASE))
    ap_mgid_clients = _extract_ap_mgid_clients(text)
    ap_mgid_counters = _extract_ap_mgid_counters(text)
    resolved_group_ip = dynamic_group_ip if group_detail_available else None
    resolved_group_vlan = vlan if group_detail_available and dynamic_group_ip else None
    vlan_context_state = _vlan_context_state(expected_vlan, resolved_group_vlan, resolved_group_ip)
    observations: list[dict[str, Any]] = []
    for item in groups or ([{"group": dynamic_group_ip, "vlan": vlan, "mgid": mgid}] if dynamic_group_ip else []):
        group_ip = item.get("group")
        if not group_ip or not multicast.is_vocera_multicast_ip(str(group_ip)):
            continue
        item_vlan = item.get("vlan") or vlan
        item_is_resolved_detail = bool(group_detail_available and str(group_ip) == str(dynamic_group_ip) and (vlan is None or item_vlan == vlan))
        observations.append(
            {
                "phase": phase,
                "evidence_source": "wlc_cli",
                "vocera_group_ip": str(group_ip),
                "vocera_group_mac": multicast.ipv4_multicast_to_mac(str(group_ip)),
                "vocera_vlan": item_vlan,
                "configured_vocera_vlan": expected_vlan,
                "resolved_group_vlan": vlan if item_is_resolved_detail else None,
                "vlan_context_state": _vlan_context_state(expected_vlan, vlan if item_is_resolved_detail else None, str(group_ip) if item_is_resolved_detail else None),
                "igmp_version": _extract_igmp_version(text),
                "mgid": item.get("mgid") or mgid,
                "receiver_mac": normalize_mac(receiver_mac),
                "receiver_member": member if item_is_resolved_detail else None,
                "receiver_blocklisted": receiver_blocklisted,
                "receiver_membership_mode": member_status if item_is_resolved_detail else None,
                "wlc_capwap_group": _first_match((r"\bAP CAPWAP IPv4 Multicast group Address\s*:\s*((?:\d{1,3}\.){3}\d{1,3})",), text),
                "wlc_capwap_mode": _first_match((r"\bAP CAPWAP Multicast\s*:\s*([^\r\n]+)",), text),
                "ap_name": receiver_ap,
                "ap_mom_status": _extract_ap_mom_status(text),
                "capture_confidence": "cli_group_observed",
            }
        )
    for item in ap_mgid_clients:
        observations.append(
            {
                "phase": phase,
                "evidence_source": "ap_mgid_snapshot",
                "mgid": item.get("mgid"),
                "receiver_mac": item.get("receiver_mac"),
                "receiver_member": True,
                "receiver_membership_mode": item.get("ap_delivery_mode"),
                "ap_mgid": item.get("mgid"),
                "ap_delivery_mode": item.get("ap_delivery_mode"),
                "ap_slot": item.get("ap_slot"),
                "capture_confidence": "ap_mgid_client_observed",
                "raw_line": item.get("raw_line"),
            }
        )
    for item in ap_mgid_counters:
        observations.append(
            {
                "phase": phase,
                "evidence_source": "ap_mgid_counter",
                "ap_mgid": item.get("ap_mgid"),
                "ap_delivery_mode": item.get("ap_delivery_mode"),
                "ap_rx_packets": item.get("ap_rx_packets"),
                "ap_tx_packets": item.get("ap_tx_packets"),
                "capture_confidence": "ap_counter_observed",
                "raw_line": item.get("raw_line"),
            }
        )
    return {
        "phase": phase,
        "snapshot_time": _first_match((r"^\s*(?:\*?\d{1,2}:\d{2}:\d{2}[^\r\n]*)$",), text),
        "receiver_mac": normalize_mac(receiver_mac),
        "receiver_ap": receiver_ap,
        "receiver_bssid": receiver_bssid,
        "receiver_channel": receiver_channel,
        "receiver_band": receiver_band,
        "receiver_vlan": receiver_vlan,
        "sender_client_vlan": sender_vlans["client_vlan"],
        "sender_multicast_vlan": sender_vlans["multicast_vlan"],
        "receiver_client_vlan": receiver_vlans["client_vlan"],
        "receiver_multicast_vlan": receiver_vlans["multicast_vlan"],
        "receiver_rssi": receiver_rssi,
        "receiver_snr": receiver_snr,
        "receiver_state": receiver_state,
        "receiver_roam_detected": bool(re.search(r"\broam", text, flags=re.IGNORECASE)),
        "multicast_enabled": multicast_enabled,
        "capwap_multicast_mode": _first_match((r"\bAP CAPWAP Multicast\s*:\s*([^\r\n]+)",), text),
        "capwap_multicast_group": _first_match((r"\bAP CAPWAP IPv4 Multicast group Address\s*:\s*((?:\d{1,3}\.){3}\d{1,3})",), text),
        "ap_mom_status": _extract_ap_mom_status(text),
        "igmp_snooping_enabled": igmp_snooping_enabled,
        "igmp_querier_enabled": igmp_querier_enabled,
        "vocera_group": group or None,
        "vocera_dynamic_group_ip": dynamic_group_ip,
        "vocera_dynamic_group_mac": dynamic_group_mac,
        "vocera_group_evidence_confidence": "exact_dynamic_pool_ip" if dynamic_group_ip else "not_seen",
        "vocera_dynamic_groups": [
            multicast.vocera_group_metadata(value)
            for value in dynamic_group_ips
        ],
        "vocera_vlan": vlan,
        "configured_vocera_vlan": expected_vlan,
        "resolved_group_vlan": resolved_group_vlan,
        "group_vlan": vlan,
        "vlan_context_state": vlan_context_state,
        "mgid": mgid,
        "multicast_groups": groups,
        "c1000_group_member": member,
        "c1000_member_status": member_status,
        "c1000_blocklisted": receiver_blocklisted,
        "igmp_tracking_present": bool(re.search(r"\bigmpv?2?-?tracking\b|\btracking\b", text, flags=re.IGNORECASE)),
        "igmp_version": _extract_igmp_version(text),
        "ap_mgid_clients": ap_mgid_clients,
        "ap_mgid_counters": ap_mgid_counters,
        "multicast_observations": observations,
        "raw_snapshot": text,
    }
