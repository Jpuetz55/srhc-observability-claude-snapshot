#!/usr/bin/env python3
"""Tests for the framework-free AP-OTA preflight gate evaluation.

These exercise the gate-state derivation that backs the Study Web AP-OTA
preflight endpoints without importing the FastAPI app, mirroring the backend
acceptance scenarios in the AP-OTA implementation slice.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_ap_ota_preflight as preflight  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)
TARGET = "00:09:ef:61:0b:f7"


def all_classifiers(enabled: bool = True) -> dict[str, bool]:
    return {name: enabled for name in preflight.REQUIRED_CLASSIFIERS}


def fully_valid_facts() -> dict:
    return {
        "target_client_mac": TARGET,
        "target_client_associated": True,
        "serving_ap_name": "AP-3F-NORTH",
        "site_capture_status_verified": True,
        "existing_site_capture_active": False,
        "site_tag": "ST-3F",
        "ap_join_profile": "JP-DEFAULT",
        "packet_capture_profile": "PCAP-VOCERA",
        "classifiers": all_classifiers(True),
        "ftp_server_host": "10.0.128.107",
        "ftp_path": "/var/lib/vocera-media-qoe/ap-ota-drop",
        "ftp_username": "appsadmin",
    }


def evaluate(facts: dict, *, observed_at=None, now=NOW, ftp_intake_ready=True) -> dict:
    return preflight.evaluate(
        facts,
        observed_at=observed_at or now,
        now=now,
        ftp_intake_ready=ftp_intake_ready,
    )


def test_unassociated_is_blocked() -> None:
    facts = fully_valid_facts()
    facts["target_client_associated"] = False
    result = evaluate(facts)
    require(result["evaluation_state"] == "blocked", f"unassociated must block: {result['evaluation_state']}")
    require(any("not associated" in b for b in result["blockers"]), "missing association blocker")


def test_active_site_capture_is_blocked() -> None:
    facts = fully_valid_facts()
    facts["existing_site_capture_active"] = True
    result = evaluate(facts)
    require(result["evaluation_state"] == "blocked", "active site capture must block")
    require(any("only one client capture per site" in b for b in result["blockers"]), "missing site-lock blocker")


def test_profile_missing_multicast_udp_is_blocked() -> None:
    facts = fully_valid_facts()
    classifiers = all_classifiers(True)
    classifiers["multicast"] = False
    classifiers["udp"] = False
    facts["classifiers"] = classifiers
    result = evaluate(facts)
    require(result["evaluation_state"] == "blocked", f"missing classifiers must block: {result['evaluation_state']}")
    require(result["capture_capability"] == "profile_mapped_unverified", "mapped-but-bad profile capability")
    require("multicast" in result["missing_classifiers"] and "udp" in result["missing_classifiers"], "must list missing classifiers")


def test_unmapped_profile_is_ready_for_profile_change() -> None:
    facts = fully_valid_facts()
    facts["packet_capture_profile"] = ""
    facts["classifiers"] = all_classifiers(False)
    result = evaluate(facts)
    require(
        result["evaluation_state"] == "ready_for_profile_change",
        f"unmapped profile should be ready_for_profile_change: {result['evaluation_state']}",
    )
    require(result["capture_capability"] == "profile_unmapped", "unmapped capability expected")


def test_ftp_unavailable_is_ready_for_ftp_validation() -> None:
    facts = fully_valid_facts()
    result = evaluate(facts, ftp_intake_ready=False)
    require(
        result["evaluation_state"] == "ready_for_ftp_validation",
        f"FTP not ready should be ready_for_ftp_validation: {result['evaluation_state']}",
    )
    require(not result["can_create_companion_leg"], "must not allow leg without FTP")


def test_fully_valid_is_ready_to_prepare() -> None:
    result = evaluate(fully_valid_facts())
    require(result["evaluation_state"] == "ready_to_prepare", f"fully valid should be ready_to_prepare: {result}")
    require(result["blockers"] == [], f"ready_to_prepare must have no blockers: {result['blockers']}")
    require(result["can_create_companion_leg"], "ready_to_prepare must allow leg creation")
    require(result["capture_capability"] == "validated", "validated capability expected")


def test_expired_preflight_is_blocked() -> None:
    facts = fully_valid_facts()
    observed = NOW - timedelta(seconds=preflight.MAX_AGE_SECONDS + 1)
    result = evaluate(facts, observed_at=observed)
    require(not result["fresh"], "stale evidence must not be fresh")
    require(result["evaluation_state"] == "blocked", f"expired preflight must block: {result['evaluation_state']}")
    require(any("older than" in b for b in result["blockers"]), "missing freshness blocker")


def test_freshness_boundary_is_inclusive() -> None:
    facts = fully_valid_facts()
    observed = NOW - timedelta(seconds=preflight.MAX_AGE_SECONDS)
    result = evaluate(facts, observed_at=observed)
    require(result["fresh"], "evidence exactly at the freshness limit should still be usable")
    require(result["evaluation_state"] == "ready_to_prepare", "boundary-fresh valid evidence should be ready")


def main() -> int:
    test_unassociated_is_blocked()
    test_active_site_capture_is_blocked()
    test_profile_missing_multicast_udp_is_blocked()
    test_unmapped_profile_is_ready_for_profile_change()
    test_ftp_unavailable_is_ready_for_ftp_validation()
    test_fully_valid_is_ready_to_prepare()
    test_expired_preflight_is_blocked()
    test_freshness_boundary_is_inclusive()
    print("OK: AP-OTA preflight gate tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
