#!/usr/bin/env python3
"""Vocera dynamic multicast pool helpers."""

from __future__ import annotations

import ipaddress
import re
from typing import Any


DEFAULT_VOCERA_MULTICAST_CIDR = "230.230.0.0/20"
DEFAULT_FIRST_USABLE = "230.230.0.1"
DEFAULT_LAST_USABLE = "230.230.15.254"
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def normalize_mac(value: str | None) -> str | None:
    """Normalize a MAC address to lower-case colon notation."""

    if not value:
        return None
    token = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(token) != 12:
        return None
    token = token.lower()
    return ":".join(token[index : index + 2] for index in range(0, 12, 2))


def _pool(cidr: str = DEFAULT_VOCERA_MULTICAST_CIDR) -> ipaddress.IPv4Network:
    return ipaddress.IPv4Network(cidr, strict=False)


def _ip(value: str) -> ipaddress.IPv4Address:
    return ipaddress.IPv4Address(value)


def is_vocera_multicast_ip(ip: str, cidr: str = DEFAULT_VOCERA_MULTICAST_CIDR) -> bool:
    """Return true when an IPv4 address is inside the configured Vocera pool."""

    try:
        address = _ip(ip)
    except ipaddress.AddressValueError:
        return False
    return address in _pool(cidr)


def ipv4_multicast_to_mac(ip: str) -> str:
    """Map an IPv4 multicast address to its RFC 1112 Ethernet multicast MAC."""

    address = _ip(ip)
    if not address.is_multicast:
        raise ValueError(f"not an IPv4 multicast address: {ip}")
    lower_23 = int(address) & 0x7FFFFF
    octets = [
        0x01,
        0x00,
        0x5E,
        (lower_23 >> 16) & 0x7F,
        (lower_23 >> 8) & 0xFF,
        lower_23 & 0xFF,
    ]
    return ":".join(f"{octet:02x}" for octet in octets)


def _mac_int(value: str) -> int | None:
    normalized = normalize_mac(value)
    if not normalized:
        return None
    return int(normalized.replace(":", ""), 16)


def is_vocera_multicast_mac(mac: str, cidr: str = DEFAULT_VOCERA_MULTICAST_CIDR) -> bool:
    """Return true when a MAC is in the derived Vocera multicast MAC range."""

    value = _mac_int(mac)
    if value is None:
        return False
    network = _pool(cidr)
    hosts = list(network.hosts())
    if not hosts:
        return False
    start = _mac_int(ipv4_multicast_to_mac(str(hosts[0])))
    end = _mac_int(ipv4_multicast_to_mac(str(hosts[-1])))
    return start is not None and end is not None and start <= value <= end


def validate_ip_mac_mapping(ip: str, mac: str) -> bool:
    """Return true when the MAC is the RFC 1112 mapping for the IP."""

    normalized = normalize_mac(mac)
    if not normalized:
        return False
    try:
        return normalized == ipv4_multicast_to_mac(ip)
    except (ipaddress.AddressValueError, ValueError):
        return False


def vocera_group_metadata(ip: str, cidr: str = DEFAULT_VOCERA_MULTICAST_CIDR) -> dict[str, Any]:
    """Return deterministic metadata for a possible Vocera multicast group."""

    in_pool = is_vocera_multicast_ip(ip, cidr)
    try:
        derived_mac = ipv4_multicast_to_mac(ip)
    except (ipaddress.AddressValueError, ValueError):
        derived_mac = None
    return {
        "vocera_dynamic_group_ip": ip if in_pool else None,
        "vocera_dynamic_group_mac": derived_mac if in_pool else None,
        "vocera_multicast_pool": cidr,
        "vocera_group_evidence_confidence": "exact_ip" if in_pool else "not_vocera_pool",
    }


def find_vocera_multicast_ips(text: str, cidr: str = DEFAULT_VOCERA_MULTICAST_CIDR) -> list[str]:
    """Return unique Vocera multicast IPs seen in text, preserving order."""

    found: list[str] = []
    seen: set[str] = set()
    for match in IPV4_RE.finditer(text):
        value = match.group(0)
        if value in seen or not is_vocera_multicast_ip(value, cidr):
            continue
        seen.add(value)
        found.append(value)
    return found


class VlanSelectionError(ValueError):
    """Raised when an active-group VLAN selection violates the override policy."""


def enforce_vlan_selection(
    configured_vlan: int | None,
    selected_vlan: int | None,
    *,
    selection_source: str | None,
    override_reason: str | None,
) -> str:
    """Validate an active-group VLAN selection against the configured default.

    A Vocera broadcast's live multicast-group VLAN is authoritative, but selecting
    a VLAN that differs from the configured default must be a deliberate operator
    decision. This enforces, independent of any UI:

      - a selected VLAN equal to the configured VLAN is always allowed;
      - a selected VLAN that differs requires ``selection_source`` to be
        ``"operator_override"`` and a non-empty ``override_reason``.

    Returns the effective selection source. Raises :class:`VlanSelectionError`
    when the override policy is not satisfied.
    """

    reason = (override_reason or "").strip()
    if selected_vlan is None:
        return selection_source or "default"
    if configured_vlan is None or int(selected_vlan) == int(configured_vlan):
        return selection_source or "observed_confirmation"
    if selection_source != "operator_override":
        raise VlanSelectionError(
            "Selecting an active-group VLAN that differs from the configured Vocera "
            "VLAN requires selection_source='operator_override'."
        )
    if not reason:
        raise VlanSelectionError(
            "A non-empty vlan_override_reason is required when the selected "
            "active-group VLAN differs from the configured Vocera VLAN."
        )
    return "operator_override"


class SessionResolutionError(ValueError):
    """Raised when active-group resolution is written at the capture-session level."""


# Active-group resolution fields that belong on a broadcast attempt, never on a
# capture session. The matching columns on vocera_media_capture_sessions are kept
# only for backward compatibility with legacy rows.
SESSION_LEVEL_RESOLUTION_FIELDS = (
    "resolved_group_ip",
    "resolved_group_vlan",
    "resolved_mgid",
    "resolved_at",
)


def reject_session_level_resolution(**fields: Any) -> None:
    """Reject any attempt to resolve the active multicast group on a session.

    A Vocera broadcast's dynamic multicast group is transient evidence tied to one
    broadcast attempt, not durable session metadata: membership, group address, and
    VLAN can differ between attempts within the same capture. Capture sessions
    therefore own only the configured baseline; the resolved group/VLAN/MGID must
    always be attached to a specific attempt. Enforcing this independently of any UI
    or transport keeps the legacy session-level columns from becoming a second,
    conflicting source of truth.

    Only the names in :data:`SESSION_LEVEL_RESOLUTION_FIELDS` are policed, so callers
    can pass an unfiltered payload. Raises :class:`SessionResolutionError` when any
    such field carries a non-null value.
    """

    offending = sorted(
        name
        for name, value in fields.items()
        if name in SESSION_LEVEL_RESOLUTION_FIELDS and value is not None
    )
    if offending:
        raise SessionResolutionError(
            "Active multicast group resolution must be attached to a broadcast "
            "attempt, not a capture session (offending fields: "
            + ", ".join(offending)
            + ")."
        )
