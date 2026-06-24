#!/usr/bin/env python3
"""Tests for Vocera multicast IP/MAC helpers."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_multicast as multicast  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_vocera_pool_mapping() -> None:
    require(multicast.is_vocera_multicast_ip("230.230.0.1"), "pool start should match")
    require(multicast.is_vocera_multicast_ip("230.230.15.254"), "pool end should match")
    require(not multicast.is_vocera_multicast_ip("230.230.16.1"), "outside pool should not match")
    require(multicast.ipv4_multicast_to_mac("230.230.0.1") == "01:00:5e:66:00:01", "bad pool start MAC")
    require(multicast.ipv4_multicast_to_mac("230.230.15.254") == "01:00:5e:66:0f:fe", "bad pool end MAC")
    require(multicast.is_vocera_multicast_mac("01:00:5e:66:00:01"), "derived MAC should match pool")
    require(multicast.validate_ip_mac_mapping("230.230.0.1", "0100.5e66.0001"), "mapping validation failed")


def test_text_discovery() -> None:
    text = "Group 230.230.0.1 appears before 230.230.15.254 but 239.1.1.1 is not Vocera."
    require(multicast.find_vocera_multicast_ips(text) == ["230.230.0.1", "230.230.15.254"], "bad text discovery")


def test_vlan_selection_enforcement() -> None:
    # Aligned VLAN is always allowed and keeps an observed-confirmation source.
    require(
        multicast.enforce_vlan_selection(684, 684, selection_source="observed_confirmation", override_reason=None)
        == "observed_confirmation",
        "matching VLAN should be accepted",
    )
    # No selected VLAN is a no-op default.
    require(
        multicast.enforce_vlan_selection(684, None, selection_source=None, override_reason=None) == "default",
        "absent VLAN should default",
    )
    # A mismatched VLAN without an override is rejected.
    rejected = False
    try:
        multicast.enforce_vlan_selection(684, 688, selection_source="observed_confirmation", override_reason=None)
    except multicast.VlanSelectionError:
        rejected = True
    require(rejected, "mismatched VLAN without override must raise")
    # A mismatched VLAN flagged as override but with an empty reason is rejected.
    rejected_blank = False
    try:
        multicast.enforce_vlan_selection(684, 688, selection_source="operator_override", override_reason="   ")
    except multicast.VlanSelectionError:
        rejected_blank = True
    require(rejected_blank, "mismatched VLAN with blank reason must raise")
    # A mismatched VLAN with override + reason is accepted.
    require(
        multicast.enforce_vlan_selection(684, 688, selection_source="operator_override", override_reason="live group on 688")
        == "operator_override",
        "explained override should be accepted",
    )


def test_session_resolution_rejection() -> None:
    # A patch that carries no active-group resolution fields is always allowed,
    # even when it sets unrelated session fields.
    multicast.reject_session_level_resolution()
    multicast.reject_session_level_resolution(
        resolved_group_ip=None,
        resolved_group_vlan=None,
        resolved_mgid=None,
        resolved_at=None,
        session_state="running",
    )
    # Each resolution field, on its own, must be rejected at the session level.
    for field, value in (
        ("resolved_group_ip", "230.230.0.5"),
        ("resolved_group_vlan", 684),
        ("resolved_mgid", 4160),
        ("resolved_at", "2026-06-24T00:00:00+00:00"),
    ):
        rejected = False
        try:
            multicast.reject_session_level_resolution(**{field: value})
        except multicast.SessionResolutionError as exc:
            rejected = True
            require(field in str(exc), f"rejection message should name {field}")
        require(rejected, f"session-level {field} must be rejected")
    # The error names every offending field when several are supplied together.
    combined = False
    try:
        multicast.reject_session_level_resolution(
            resolved_group_ip="230.230.0.9", resolved_group_vlan=688
        )
    except multicast.SessionResolutionError as exc:
        combined = True
        require(
            "resolved_group_ip" in str(exc) and "resolved_group_vlan" in str(exc),
            "combined rejection should name all offending fields",
        )
    require(combined, "combined session-level resolution must be rejected")


def main() -> int:
    test_vocera_pool_mapping()
    test_text_discovery()
    test_vlan_selection_enforcement()
    test_session_resolution_rejection()
    print("OK: Vocera multicast helper tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
