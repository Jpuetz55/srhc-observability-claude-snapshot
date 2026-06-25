#!/usr/bin/env python3
"""Manual long-running WLC EPC capture-session workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import vocera_multicast as multicast


DEFAULT_SESSION_ROOT = Path("/var/lib/vocera-media-qoe/raw/wlc-sessions")
SESSION_STATES = ("prepared_not_started", "running", "stopped", "exported", "imported", "aborted")
EVENT_KINDS = ("broadcast_started", "heard", "missed", "partial", "choppy", "alert_only", "session_end", "note")
AUDIO_RESULTS = ("heard", "missed", "partial", "choppy", "unknown", "not_tested")
OUTCOME_RESULTS = ("heard", "missed", "partial", "choppy")
ATTEMPT_STATES = ("open", "completed", "cancelled", "incomplete")
GROUP_SELECTION_SOURCES = ("default", "operator_override", "observed_confirmation")


def utc_now_iso() -> str:
    """Return a UTC ISO timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text(path: Path, text: str, *, overwrite: bool) -> None:
    """Write text, refusing to overwrite unless requested."""

    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    path.chmod(0o644)


def write_json(path: Path, payload: Any, *, overwrite: bool = True) -> None:
    """Write JSON with stable formatting."""

    write_text(path, json.dumps(payload, indent=2, sort_keys=True), overwrite=overwrite)


def read_json(path: Path, default: Any) -> Any:
    """Read JSON or return a default value."""

    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def safe_name(value: str, *, fallback: str = "VOCERA_EPC") -> str:
    """Return a WLC-friendly capture or ACL name."""

    text = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return (text or fallback)[:32]


def generate_capture_name(prefix: str = "VOCERA", *, now: datetime | None = None) -> str:
    """Return a short, unique WLC-friendly capture name.

    Format ``PREFIX_YYMMDD_HHMM_XXXX`` (for example ``VOCERA_260624_1512_A7D3``).
    Static defaults such as ``VOCERA_C1000_001`` eventually collide on the
    controller; the random suffix keeps each capture-session name unique while
    staying within the WLC 32-character capture-name limit.
    """

    moment = now or datetime.now(timezone.utc)
    stamp = moment.strftime("%y%m%d_%H%M")
    suffix = uuid.uuid4().hex[:4].upper()
    return safe_name(f"{prefix}_{stamp}_{suffix}", fallback="VOCERA_BCAST")


def generate_attempt_id(session_id: str, *, now: datetime | None = None) -> str:
    """Return a unique attempt identifier scoped to a capture session."""

    moment = now or datetime.now(timezone.utc)
    stamp = moment.strftime("%Y%m%dT%H%M%S")
    suffix = uuid.uuid4().hex[:6]
    return f"{session_id}-attempt-{stamp}-{suffix}"[:96]


def attempts_index_path(session_dir: Path) -> Path:
    """Return the path to the per-session attempt index."""

    return session_dir / "attempts" / "index.json"


def read_attempts(session_dir: Path) -> list[dict[str, Any]]:
    """Return the recorded broadcast attempts for a session package."""

    data = read_json(attempts_index_path(session_dir), [])
    return data if isinstance(data, list) else []


def write_attempts(session_dir: Path, attempts: list[dict[str, Any]]) -> None:
    """Persist the broadcast attempt index for a session package."""

    write_json(attempts_index_path(session_dir), attempts, overwrite=True)


def open_attempt(attempts: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the single open attempt, if one exists."""

    for attempt in attempts:
        if attempt.get("attempt_state") == "open":
            return attempt
    return None


def append_event(session_dir: Path, event: dict[str, Any]) -> None:
    """Append an immutable operator event to the session timeline files."""

    for rel_path in ("session-events.json", "attempts/attempt-markers.json"):
        events_path = session_dir / rel_path
        events = read_json(events_path, [])
        events = events if isinstance(events, list) else []
        events.append(event)
        write_json(events_path, events, overwrite=True)


def session_dir(root: Path, study_id: str, session_id: str) -> Path:
    """Return the canonical session package directory."""

    return root / study_id / session_id


def acl_name(capture_name: str) -> str:
    """Return the temporary capture ACL name."""

    return safe_name(f"VOCERA_EPC_{capture_name}", fallback="VOCERA_EPC_TMP")


def wlc_interface_cli(value: str) -> str:
    """Return a WLC CLI-friendly interface token."""

    text = (value or "").strip()
    match = re.fullmatch(r"(?i)(port-channel)\s*(\d+)", text)
    if match:
        return f"Port-channel {match.group(2)}"
    return text


def scp_export_uri(username: str, host: str, path: str, port: int | None = None) -> str:
    """Return a password-free SCP URI for WLC export."""

    authority = f"{username}@{host}"
    if port and port != 22:
        authority = f"{authority}:{port}"
    absolute_path = path if path.startswith("/") else f"/{path}"
    return f"scp://{authority}/{absolute_path}"


def default_export_path(session_id: str, package_dir: Path) -> str:
    """Return the suggested collector-side SCP upload path for final export.

    The WLC SCP-pushes the exported EPC into ``incoming/`` so the collector can
    detect a *completed* upload, validate and hash it, and only then promote it
    into ``pcaps/`` as stable session evidence. Exporting straight into
    ``pcaps/`` would let a half-written file look like final evidence and could
    be picked up mid-transfer.
    """

    return str((package_dir / "incoming" / f"{session_id}.pcap").resolve(strict=False))


def wildcard_for_cidr(cidr: str) -> tuple[str, str]:
    """Return IOS ACL network and wildcard strings for an IPv4 network."""

    import ipaddress

    network = ipaddress.IPv4Network(cidr, strict=False)
    wildcard = ipaddress.IPv4Address(int(network.hostmask))
    return str(network.network_address), str(wildcard)


def session_payload(args: argparse.Namespace, target: Path) -> dict[str, Any]:
    """Build a capture-session manifest."""

    session_id = args.session_id
    capture_name = safe_name(args.capture_name, fallback="VOCERA_BCAST") if args.capture_name else generate_capture_name()
    ring_file_count = int(args.ring_file_count)
    ring_file_size_mb = int(args.ring_file_size_mb)
    export_path = args.collector_scp_path or default_export_path(session_id, target)
    vocera_pool = args.vocera_multicast_pool or multicast.DEFAULT_VOCERA_MULTICAST_CIDR
    first_usable = args.vocera_first_usable or multicast.DEFAULT_FIRST_USABLE
    last_usable = args.vocera_last_usable or multicast.DEFAULT_LAST_USABLE
    return {
        "schema_version": 1,
        "session_id": session_id,
        "study_id": args.study_id,
        "site": args.site,
        "wlc_name": args.wlc_name,
        "capture_method": "manual_wlc_epc",
        "capture_name": capture_name,
        "wlc_interface": args.wlc_interface,
        "capture_filter_mode": args.capture_filter_mode,
        "capture_mode": args.capture_mode,
        "short_validation_duration_seconds": int(args.short_validation_duration_seconds),
        "collector_host": args.collector_host,
        "collector_scp_username": args.collector_scp_username,
        "collector_scp_port": int(args.collector_scp_port) if args.collector_scp_port else 22,
        "collector_scp_path": export_path,
        "export_uri": scp_export_uri(args.collector_scp_username, args.collector_host, export_path, args.collector_scp_port),
        "ring_file_count": ring_file_count,
        "ring_file_size_mb": ring_file_size_mb,
        "ring_total_size_mb": ring_file_count * ring_file_size_mb,
        "continuous_export_enabled": bool(args.continuous_export_enabled),
        "session_state": args.session_state,
        "created_by": args.operator or os.environ.get("USER") or "unknown",
        "created_at": args.created_at or utc_now_iso(),
        "updated_at": args.created_at or utc_now_iso(),
        "sender": {
            "name": args.sender_name,
            "model": args.sender_model,
            "mac": multicast.normalize_mac(args.sender_mac),
            "ip": args.sender_ip,
        },
        "receiver": {
            "name": args.receiver_name,
            "model": args.receiver_model,
            "mac": multicast.normalize_mac(args.receiver_mac),
            "ip": args.receiver_ip,
        },
        "expected": {
            "expected_dscp": int(args.expected_dscp),
            "configured_vocera_vlan": int(args.vocera_vlan) if args.vocera_vlan else 684,
            "vocera_vlan": int(args.vocera_vlan) if args.vocera_vlan else None,
            "vocera_multicast_pool": vocera_pool,
            "vocera_first_usable": first_usable,
            "vocera_last_usable": last_usable,
            "expected_mac_start": multicast.ipv4_multicast_to_mac(first_usable),
            "expected_mac_end": multicast.ipv4_multicast_to_mac(last_usable),
        },
        "configured_vocera_vlan": int(args.vocera_vlan) if args.vocera_vlan else 684,
        "resolved_group_ip": args.resolved_group_ip,
        "resolved_group_vlan": int(args.resolved_group_vlan) if args.resolved_group_vlan else None,
        "resolved_mgid": int(args.resolved_mgid) if args.resolved_mgid else None,
        "resolved_at": args.resolved_at,
        "vlan_selection_source": args.vlan_selection_source,
        "vlan_context_state": "configured_only",
        "temporary_acl_name": acl_name(capture_name),
        "package_path": str(target),
        "notes": args.notes or "",
    }


def clock_check_cli(session: dict[str, Any]) -> str:
    """Return clock-alignment commands."""

    return f"""
terminal length 0
show clock detail
show monitor capture {session['capture_name']}
"""


def snapshot_cli(session: dict[str, Any]) -> str:
    """Return legacy active-state transcript commands for the session."""

    return active_event_cli(session)


def configured_vlan_token(session: dict[str, Any]) -> str:
    """Return the configured Vocera VLAN or a visible placeholder."""

    return str(
        session.get("configured_vocera_vlan")
        or session.get("expected", {}).get("configured_vocera_vlan")
        or session.get("expected", {}).get("vocera_vlan")
        or "<VOCERA_VLAN>"
    )


def resolved_vlan_token(session: dict[str, Any]) -> str:
    """Return the resolved active-group VLAN or a visible placeholder."""

    return str(session.get("resolved_group_vlan") or "<RESOLVED_GROUP_VLAN>")


def resolved_group_token(session: dict[str, Any]) -> str:
    """Return the resolved active-group IP or a visible placeholder."""

    return str(session.get("resolved_group_ip") or "<RESOLVED_GROUP_IP>")


def baseline_cli(session: dict[str, Any]) -> str:
    """Return baseline multicast state commands for the session."""

    receiver = session["receiver"]
    sender = session["sender"]
    vlan = configured_vlan_token(session)
    return f"""
terminal length 0
! Configured Vocera multicast VLAN: {vlan}
! Badge client VLAN observations must not overwrite this configured value.
show clock detail
show wireless client mac-address {receiver['mac']} detail
show wireless client mac-address {receiver['mac']} mobility history
show wireless client mac-address {sender['mac']} detail
show wireless client mac-address {sender['mac']} mobility history
show wireless multicast
show ap multicast mom
show ip igmp snooping
show ip igmp snooping querier vlan {vlan}
show ip igmp snooping wireless mgid
show ip igmp snooping wireless mcast-ipc-count
show ip igmp snooping wireless mcast-spi-count
show wireless multicast group summary
show wireless stats multicast global
show monitor capture {session['capture_name']}
"""


def active_event_cli(session: dict[str, Any]) -> str:
    """Return commands for an active broadcast after the dynamic group is known."""

    receiver = session["receiver"]
    sender = session["sender"]
    vlan = configured_vlan_token(session)
    return f"""
terminal length 0
! Configured default VLAN: {vlan}
! Resolved active group VLAN: unresolved
! Use this sheet to collect candidate dynamic Vocera groups before selecting one.
show clock detail
show wireless client mac-address {receiver['mac']} detail
show wireless client mac-address {sender['mac']} detail
show wireless multicast group summary
show ip igmp snooping groups vlan {vlan}
show ip igmp snooping igmpv2-tracking
show ip igmp snooping wireless mgid
show ip igmp snooping wireless mcast-ipc-count
show ip igmp snooping wireless mcast-spi-count
show monitor capture {session['capture_name']} buffer brief
"""


def render_resolved_active_group(
    capture_name: str,
    configured_vlan: Any,
    resolved_group: Any,
    resolved_vlan: Any,
    *,
    attempt_id: str | None = None,
) -> str:
    """Return resolved-group commands for explicit group/VLAN values.

    The capture-session package ships a placeholder sheet, but once the operator
    selects the live dynamic group for an attempt the backend rewrites this sheet
    with concrete values so the resolved evidence path is never lost on refresh
    or operator handoff.
    """

    attempt_line = f"! Attempt: {attempt_id}" if attempt_id else "! Attempt: <unbound>"
    return f"""
terminal length 0
{attempt_line}
! Configured default VLAN: {configured_vlan}
! Resolved active group VLAN: {resolved_vlan}
! Run this only after selecting the active 230.230.x.x group row from the summary.
show clock detail
show wireless multicast group {resolved_group} vlan {resolved_vlan}
show wireless multicast source 0.0.0.0 group {resolved_group} vlan {resolved_vlan}
show ip igmp snooping groups vlan {resolved_vlan}
show ip igmp snooping igmpv2-tracking
show ip igmp snooping wireless mgid
show ip igmp snooping wireless mcast-ipc-count
show ip igmp snooping wireless mcast-spi-count
show monitor capture {capture_name} buffer brief
"""


def resolved_active_group_cli(session: dict[str, Any]) -> str:
    """Return the placeholder resolved-group sheet shipped with the package."""

    return render_resolved_active_group(
        session["capture_name"],
        configured_vlan_token(session),
        resolved_group_token(session),
        resolved_vlan_token(session),
    )


def post_failure_cli(session: dict[str, Any]) -> str:
    """Return post-failure state commands."""

    receiver = session["receiver"]
    sender = session["sender"]
    return f"""
terminal length 0
show clock detail
show wireless client mac-address {receiver['mac']} detail
show wireless client mac-address {receiver['mac']} mobility history
show wireless client mac-address {sender['mac']} detail
show wireless multicast group summary
show ip igmp snooping igmpv2-tracking
show ip igmp snooping wireless mgid
show ip igmp snooping wireless mcast-ipc-count
show ip igmp snooping wireless mcast-spi-count
show ap multicast mom
show monitor capture {session['capture_name']} buffer brief
"""


def ap_evidence_cli(session: dict[str, Any]) -> str:
    """Return optional AP-side multicast evidence commands."""

    return """
terminal length 0
! Optional AP shell evidence. Use only when AP shell access is authorized.
show capwap mcast mgid clients
show capwap mcast mgid all
"""


def acl_cli(session: dict[str, Any]) -> str:
    """Return temporary ACL commands for the session filter."""

    network, wildcard = wildcard_for_cidr(session["expected"]["vocera_multicast_pool"])
    sender_ip = session["sender"].get("ip")
    receiver_ip = session["receiver"].get("ip")
    lines = [
        "configure terminal",
        f"ip access-list extended {session['temporary_acl_name']}",
        " remark Temporary Vocera EPC filter. Remove with cleanup.cli after export.",
        f" permit ip any {network} {wildcard}",
        f" permit ip {network} {wildcard} any",
        " permit igmp any any",
    ]
    if sender_ip:
        lines.extend([f" permit ip host {sender_ip} any", f" permit ip any host {sender_ip}"])
    if receiver_ip:
        lines.extend([f" permit ip host {receiver_ip} any", f" permit ip any host {receiver_ip}"])
    lines.append("end")
    return "\n".join(lines)


def start_cli(session: dict[str, Any], *, short: bool) -> str:
    """Return WLC EPC start commands."""

    capture_name = session["capture_name"]
    sender_mac = session["sender"].get("mac")
    receiver_mac = session["receiver"].get("mac")
    duration_line = (
        f"monitor capture {capture_name} limit duration {session['short_validation_duration_seconds']}"
        if short
        else "! Long reproduction mode: no duration limit. Stop manually immediately after failure reproduction."
    )
    continuous_line = ""
    if session.get("continuous_export_enabled"):
        continuous_line = (
            f"monitor capture {capture_name} continuous-capture "
            f"{session['export_uri'].rsplit('/', 1)[0]}/{capture_name}_continuous.pcap"
        )
    else:
        continuous_line = "! Continuous export disabled. Final export occurs in stop-export.cli."
    return f"""
terminal length 0
show clock detail
show monitor capture {capture_name}
{acl_cli(session)}
monitor capture {capture_name} interface {wlc_interface_cli(session['wlc_interface'])} both
monitor capture {capture_name} buffer circular file {session['ring_file_count']} file-size {session['ring_file_size_mb']}
monitor capture {capture_name} access-list {session['temporary_acl_name']}
monitor capture {capture_name} match ipv4
monitor capture {capture_name} inner mac {sender_mac} {receiver_mac}
{duration_line}
{continuous_line}
monitor capture {capture_name} start
show monitor capture {capture_name}
"""


def stop_export_cli(session: dict[str, Any]) -> str:
    """Return WLC EPC stop/export commands."""

    capture_name = session["capture_name"]
    return f"""
terminal length 0
show clock detail
show monitor capture {capture_name}
monitor capture {capture_name} stop
show monitor capture {capture_name}
monitor capture {capture_name} export {session['export_uri']}
! The WLC prompts interactively for the collector account password during SCP export.
! This repo and web app do not store or transmit that password.
"""


def cleanup_cli(session: dict[str, Any]) -> str:
    """Return WLC cleanup commands."""

    capture_name = session["capture_name"]
    acl = session["temporary_acl_name"]
    return f"""
terminal length 0
show monitor capture {capture_name}
no monitor capture {capture_name}
show monitor capture {capture_name}
configure terminal
no ip access-list extended {acl}
end
show monitor capture {capture_name}
"""


def readme_text(session: dict[str, Any]) -> str:
    """Return operator instructions for the session package."""

    return f"""
# Manual WLC Capture Session

Study: `{session['study_id']}`
Session: `{session['session_id']}`
Capture name: `{session['capture_name']}`

This package is manual by design. It generates command sheets, records operator
markers, and imports evidence after files are moved here. It does not SSH to
the WLC and it does not collect WLC or SCP passwords.

Long reproduction workflow:

1. Run `clock-check.cli` while terminal logging is enabled.
2. Run `start-long.cli`.
3. For each broadcast, mark "Broadcast Started" in Study Web (opens one attempt).
4. Perform the V5000 to C1000 broadcast.
5. Mark the outcome (heard / missed / partial / choppy / alert only). This closes that attempt.
6. On a missed/partial/choppy/alert-only outcome, gather live group evidence BEFORE stopping EPC:
   a. Keep the V5000 broadcast active a few more seconds if operationally possible.
   b. Run `active-event.cli` (group summary, IGMP state, client details).
   c. Paste the group summary into Study Web and select the active 230.230.x.x group for that attempt.
   d. Run the regenerated `attempt-<attempt-id>-resolved-group.cli` (group detail, source detail, IGMP snooping).
7. Only then run `stop-export.cli` to stop and export the PCAP. The WLC
   SCP-pushes it into `incoming/`; the collector detects the completed upload,
   validates and hashes it, promotes it into `pcaps/`, and parses it
   automatically. No manual move, hash, register, or parse step is required.
8. Run `post-failure.cli` and save output under `cli/`.
9. After export is confirmed, run `cleanup.cli`.

A dynamic Vocera multicast group can disappear quickly once a broadcast ends, so
the live group-summary and group-detail evidence must be collected for the
attempt BEFORE EPC stop/export, never after.

Ring buffer:

- Files: {session['ring_file_count']}
- Per-file size: {session['ring_file_size_mb']} MB
- Total bounded ring: {session['ring_total_size_mb']} MB
- Interface: {session['wlc_interface']}
- Filter mode: {session['capture_filter_mode']}
- Vocera pool: {session['expected']['vocera_multicast_pool']}
- Configured Vocera multicast VLAN: {session['configured_vocera_vlan']}
- Resolved active group VLAN: {session.get('resolved_group_vlan') or 'unresolved'}

Do not infer a fixed retention time from the ring size. Retention depends on
packet rate during the reproduction window.
"""


def create_session_package(session: dict[str, Any], target: Path, *, force: bool = False) -> dict[str, Any]:
    """Create a session package and return its manifest."""

    for subdir in ("incoming", "pcaps", "cli", "notes", "validation", "attempts"):
        (target / subdir).mkdir(parents=True, exist_ok=True)
    files = {
        "session.json": json.dumps(session, indent=2, sort_keys=True),
        "README.md": readme_text(session),
        "clock-check.cli": clock_check_cli(session),
        "baseline.cli": baseline_cli(session),
        "start-long.cli": start_cli(session, short=False),
        "start-short-validation.cli": start_cli(session, short=True),
        "stop-export.cli": stop_export_cli(session),
        "active-event.cli": active_event_cli(session),
        "resolved-active-group.cli": resolved_active_group_cli(session),
        "post-failure.cli": post_failure_cli(session),
        "ap-evidence.cli": ap_evidence_cli(session),
        "active-state-snapshot.cli": snapshot_cli(session),
        "cleanup.cli": cleanup_cli(session),
        "session-events.json": "[]",
        "attempts/attempt-markers.json": "[]",
        "notes/operator-notes.md": "# Operator Notes\n",
    }
    for rel_path, text in files.items():
        write_text(target / rel_path, text, overwrite=force)
    return session


def command_init(args: argparse.Namespace) -> int:
    """Create a manual WLC capture session package."""

    target = session_dir(Path(args.session_root), args.study_id, args.session_id)
    if (target / "session.json").exists() and not args.force:
        print(
            f"error: capture-session package already exists at {target}; "
            "choose a new --session-id or pass --force to overwrite.",
            file=sys.stderr,
        )
        return 2
    session = session_payload(args, target)
    create_session_package(session, target, force=args.force)
    print(target)
    return 0


def command_mark(args: argparse.Namespace) -> int:
    """Append an immutable operator marker to a session package."""

    target = Path(args.session_dir)
    session = read_json(target / "session.json", {})
    session_id = str(session.get("session_id") or target.name)
    event = {
        "event_id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}",
        "session_id": session_id,
        "attempt_id": args.attempt_id,
        "event_kind": args.event_kind,
        "event_time": args.event_time or utc_now_iso(),
        "browser_event_time": args.browser_event_time,
        "operator": args.operator or os.environ.get("USER") or "unknown",
        "audio_result": args.audio_result,
        "alert_received": args.alert_received,
        "audio_received": args.audio_received,
        "notes": args.notes or "",
    }
    append_event(target, event)
    print(json.dumps(event, sort_keys=True))
    return 0


def command_start_attempt(args: argparse.Namespace) -> int:
    """Open exactly one broadcast attempt for a capture session."""

    target = Path(args.session_dir)
    session = read_json(target / "session.json", {})
    session_id = str(session.get("session_id") or target.name)
    attempts = read_attempts(target)
    existing = open_attempt(attempts)
    if existing is not None:
        print(
            f"error: capture session {session_id} already has an open attempt "
            f"({existing.get('attempt_id')}); record its outcome before starting another.",
            file=sys.stderr,
        )
        return 2
    started_at = args.event_time or utc_now_iso()
    operator = args.operator or os.environ.get("USER") or "unknown"
    attempt_id = args.attempt_id or generate_attempt_id(session_id)
    attempt = {
        "attempt_id": attempt_id,
        "session_id": session_id,
        "attempt_state": "open",
        "attempt_started_at": started_at,
        "attempt_ended_at": None,
        "audio_result": None,
        "alert_received": None,
        "audio_received": None,
        "operator": operator,
        "resolved_group_ip": None,
        "resolved_group_vlan": None,
        "resolved_mgid": None,
        "group_selection_source": None,
        "vlan_override_reason": None,
        "active_group_selected_at": None,
        "notes": args.notes or "",
    }
    attempts.append(attempt)
    write_attempts(target, attempts)
    append_event(
        target,
        {
            "event_id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}",
            "session_id": session_id,
            "attempt_id": attempt_id,
            "event_kind": "broadcast_started",
            "event_time": started_at,
            "operator": operator,
            "notes": args.notes or "",
        },
    )
    print(attempt_id)
    return 0


def command_outcome(args: argparse.Namespace) -> int:
    """Record the audio outcome for an attempt and close it."""

    target = Path(args.session_dir)
    session = read_json(target / "session.json", {})
    session_id = str(session.get("session_id") or target.name)
    attempts = read_attempts(target)
    ended_at = args.event_time or utc_now_iso()
    operator = args.operator or os.environ.get("USER") or "unknown"
    attempt: dict[str, Any] | None = None
    if args.attempt_id:
        attempt = next((item for item in attempts if item.get("attempt_id") == args.attempt_id), None)
        if attempt is None:
            print(f"error: attempt {args.attempt_id} not found in {session_id}.", file=sys.stderr)
            return 2
    else:
        attempt = open_attempt(attempts)
    if attempt is None:
        # A bare outcome with no prior start still yields one completed attempt.
        attempt = {
            "attempt_id": generate_attempt_id(session_id),
            "session_id": session_id,
            "attempt_started_at": ended_at,
            "resolved_group_ip": None,
            "resolved_group_vlan": None,
            "resolved_mgid": None,
            "group_selection_source": None,
            "vlan_override_reason": None,
            "active_group_selected_at": None,
        }
        attempts.append(attempt)
    alert = _result_bool(args.alert_received)
    audio = _result_bool(args.audio_received)
    if args.audio_result == "heard":
        alert = True if alert is None else alert
        audio = True if audio is None else audio
    elif args.audio_result in {"missed", "partial", "choppy"}:
        audio = False if audio is None and args.audio_result == "missed" else audio
    attempt.update(
        {
            "attempt_state": "completed",
            "attempt_ended_at": ended_at,
            "audio_result": args.audio_result,
            "alert_received": alert,
            "audio_received": audio,
            "operator": operator,
        }
    )
    if args.notes is not None:
        attempt["notes"] = args.notes
    write_attempts(target, attempts)
    append_event(
        target,
        {
            "event_id": f"evt_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}",
            "session_id": session_id,
            "attempt_id": attempt["attempt_id"],
            "event_kind": args.audio_result,
            "event_time": ended_at,
            "operator": operator,
            "audio_result": args.audio_result,
            "alert_received": alert,
            "audio_received": audio,
            "notes": args.notes or "",
        },
    )
    print(attempt["attempt_id"])
    return 0


def command_resolve_group(args: argparse.Namespace) -> int:
    """Attach the live dynamic Vocera group to an attempt and persist evidence."""

    target = Path(args.session_dir)
    session = read_json(target / "session.json", {})
    session_id = str(session.get("session_id") or target.name)
    configured_vlan = (
        session.get("configured_vocera_vlan")
        or session.get("expected", {}).get("configured_vocera_vlan")
        or 684
    )
    attempts = read_attempts(target)
    if args.attempt_id:
        attempt = next((item for item in attempts if item.get("attempt_id") == args.attempt_id), None)
    else:
        attempt = open_attempt(attempts)
    if attempt is None:
        print(
            "error: active-group resolution requires an existing attempt; start an "
            "attempt or pass --attempt-id.",
            file=sys.stderr,
        )
        return 2

    selected_vlan = int(args.group_vlan)
    try:
        selection_source = multicast.enforce_vlan_selection(
            int(configured_vlan),
            selected_vlan,
            selection_source=args.selection_source,
            override_reason=args.override_reason,
        )
    except multicast.VlanSelectionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    summary_text = ""
    if args.summary_file:
        summary_text = Path(args.summary_file).read_text(encoding="utf-8")
    elif args.summary_text:
        summary_text = args.summary_text
    selected_row = _select_summary_row(summary_text, args.group_ip)
    selected_at = args.event_time or utc_now_iso()
    operator = args.operator or os.environ.get("USER") or "unknown"
    mgid = int(args.mgid) if args.mgid is not None else None

    attempt.update(
        {
            "resolved_group_ip": args.group_ip,
            "resolved_group_vlan": selected_vlan,
            "resolved_mgid": mgid,
            "group_selection_source": selection_source,
            "vlan_override_reason": (args.override_reason or "").strip() or None,
            "active_group_selected_at": selected_at,
        }
    )
    write_attempts(target, attempts)

    attempt_id = str(attempt["attempt_id"])
    capture_name = session.get("capture_name") or "VOCERA_BCAST"
    resolved_sheet = render_resolved_active_group(
        capture_name, configured_vlan, args.group_ip, selected_vlan, attempt_id=attempt_id
    )
    write_text(target / "cli" / f"attempt-{attempt_id}-resolved-group.cli", resolved_sheet, overwrite=True)
    if summary_text.strip():
        write_text(
            target / "cli" / f"attempt-{attempt_id}-active-group-summary.txt",
            summary_text,
            overwrite=True,
        )
    selection = {
        "attempt_id": attempt_id,
        "session_id": session_id,
        "group_ip": args.group_ip,
        "group_vlan": selected_vlan,
        "mgid": mgid,
        "configured_vocera_vlan": int(configured_vlan),
        "selection_source": selection_source,
        "vlan_override_reason": (args.override_reason or "").strip() or None,
        "selected_row": selected_row,
        "selected_at": selected_at,
        "operator": operator,
    }
    write_json(target / "notes" / f"attempt-{attempt_id}-group-selection.json", selection, overwrite=True)
    print(json.dumps(selection, sort_keys=True))
    return 0


def _result_bool(value: str | None) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _select_summary_row(summary_text: str, group_ip: str) -> str | None:
    """Return the raw group-summary line for the selected group, if present."""

    for line in summary_text.splitlines():
        if group_ip in line:
            return line.strip()
    return None


def command_report(args: argparse.Namespace) -> int:
    """Print a concise session package report."""

    target = Path(args.session_dir)
    session = read_json(target / "session.json", {})
    events = read_json(target / "session-events.json", [])
    payload = {
        "session_id": session.get("session_id") or target.name,
        "study_id": session.get("study_id"),
        "session_state": session.get("session_state"),
        "capture_name": session.get("capture_name"),
        "ring_total_size_mb": session.get("ring_total_size_mb"),
        "event_count": len(events) if isinstance(events, list) else 0,
        "package_path": str(target),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_list(args: argparse.Namespace) -> int:
    """List capture session directories."""

    root = Path(args.session_root)
    study_root = root / args.study_id if args.study_id else root
    for path in sorted(study_root.glob("*/*" if not args.study_id else "*")):
        if path.is_dir() and (path / "session.json").is_file():
            print(path)
    return 0


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Manual WLC capture-session package toolkit.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create a capture-session package")
    init.add_argument("--session-root", default=str(DEFAULT_SESSION_ROOT))
    init.add_argument("--study-id", required=True)
    init.add_argument("--session-id", required=True)
    init.add_argument("--site", default="srhc")
    init.add_argument("--wlc-name", required=True)
    init.add_argument("--capture-name")
    init.add_argument("--wlc-interface", required=True)
    init.add_argument("--capture-filter-mode", default="vocera_pool_control")
    init.add_argument("--capture-mode", choices=("long_reproduction", "short_validation"), default="long_reproduction")
    init.add_argument("--short-validation-duration-seconds", type=int, default=90)
    init.add_argument("--collector-host", required=True)
    init.add_argument("--collector-scp-username", required=True)
    init.add_argument("--collector-scp-port", type=int, default=22)
    init.add_argument("--collector-scp-path")
    init.add_argument("--ring-file-count", type=int, default=5)
    init.add_argument("--ring-file-size-mb", type=int, default=100)
    init.add_argument("--continuous-export-enabled", action="store_true")
    init.add_argument("--session-state", choices=SESSION_STATES, default="prepared_not_started")
    init.add_argument("--sender-name", default="V5000 Sender")
    init.add_argument("--sender-model", default="V5000")
    init.add_argument("--sender-mac", required=True)
    init.add_argument("--sender-ip", required=True)
    init.add_argument("--receiver-name", default="C1000 Receiver")
    init.add_argument("--receiver-model", default="C1000")
    init.add_argument("--receiver-mac", required=True)
    init.add_argument("--receiver-ip", required=True)
    init.add_argument("--expected-dscp", type=int, default=46)
    init.add_argument("--vocera-vlan", type=int, default=684)
    init.add_argument("--resolved-group-ip")
    init.add_argument("--resolved-group-vlan", type=int)
    init.add_argument("--resolved-mgid", type=int)
    init.add_argument("--resolved-at")
    init.add_argument("--vlan-selection-source", choices=("default", "operator_override", "observed_confirmation"), default="default")
    init.add_argument("--vocera-multicast-pool", default=multicast.DEFAULT_VOCERA_MULTICAST_CIDR)
    init.add_argument("--vocera-first-usable", default=multicast.DEFAULT_FIRST_USABLE)
    init.add_argument("--vocera-last-usable", default=multicast.DEFAULT_LAST_USABLE)
    init.add_argument("--operator")
    init.add_argument("--created-at")
    init.add_argument("--notes")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    mark = subparsers.add_parser("mark", help="Record an operator event marker")
    mark.add_argument("--session-dir", required=True)
    mark.add_argument("--event-kind", required=True, choices=EVENT_KINDS)
    mark.add_argument("--attempt-id")
    mark.add_argument("--event-time")
    mark.add_argument("--browser-event-time")
    mark.add_argument("--operator")
    mark.add_argument("--audio-result", choices=AUDIO_RESULTS)
    mark.add_argument("--alert-received", choices=("true", "false", "unknown"))
    mark.add_argument("--audio-received", choices=("true", "false", "unknown"))
    mark.add_argument("--notes")
    mark.set_defaults(func=command_mark)

    start_attempt = subparsers.add_parser("start-attempt", help="Open one broadcast attempt")
    start_attempt.add_argument("--session-dir", required=True)
    start_attempt.add_argument("--attempt-id")
    start_attempt.add_argument("--event-time")
    start_attempt.add_argument("--operator")
    start_attempt.add_argument("--notes")
    start_attempt.set_defaults(func=command_start_attempt)

    outcome = subparsers.add_parser("outcome", help="Record an attempt outcome and close it")
    outcome.add_argument("--session-dir", required=True)
    outcome.add_argument("--audio-result", required=True, choices=OUTCOME_RESULTS)
    outcome.add_argument("--attempt-id")
    outcome.add_argument("--event-time")
    outcome.add_argument("--operator")
    outcome.add_argument("--alert-received", choices=("true", "false", "unknown"))
    outcome.add_argument("--audio-received", choices=("true", "false", "unknown"))
    outcome.add_argument("--notes")
    outcome.set_defaults(func=command_outcome)

    resolve_group = subparsers.add_parser("resolve-group", help="Attach the live dynamic group to an attempt")
    resolve_group.add_argument("--session-dir", required=True)
    resolve_group.add_argument("--group-ip", required=True)
    resolve_group.add_argument("--group-vlan", required=True, type=int)
    resolve_group.add_argument("--mgid", type=int)
    resolve_group.add_argument("--attempt-id")
    resolve_group.add_argument("--selection-source", choices=GROUP_SELECTION_SOURCES, default="observed_confirmation")
    resolve_group.add_argument("--override-reason")
    resolve_group.add_argument("--summary-file")
    resolve_group.add_argument("--summary-text")
    resolve_group.add_argument("--event-time")
    resolve_group.add_argument("--operator")
    resolve_group.set_defaults(func=command_resolve_group)

    report = subparsers.add_parser("report", help="Print capture-session summary")
    report.add_argument("--session-dir", required=True)
    report.set_defaults(func=command_report)

    list_cmd = subparsers.add_parser("list", help="List capture-session packages")
    list_cmd.add_argument("--session-root", default=str(DEFAULT_SESSION_ROOT))
    list_cmd.add_argument("--study-id")
    list_cmd.set_defaults(func=command_list)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
