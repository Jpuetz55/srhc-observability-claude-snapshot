"""Pure AP-OTA preflight gate evaluation for the C1000 receiver workflow.

This module is deliberately framework-free so the gate derivation can be unit
tested without importing the Study Web FastAPI application. The web layer is
responsible for authentication, MAC normalization, evidence storage, and
database persistence; this module only derives the gate state and blockers from
already-normalized observed facts.

Cisco AP client packet capture is not a generic "capture anywhere" feature: the
target client must be associated to an AP whose AP join profile / site-tag chain
maps an AP packet-capture profile, only one client capture is allowed per site,
and static mode pins the capture to a specific AP/radio at a point in time. The
gate state is always derived here, never accepted from the client, so a stale or
unsuitable observation cannot be hand-waved into ``ready_to_prepare``.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Mapping

# AP packet-capture profile packet classes. For the Vocera multicast problem all
# seven must be explicitly enabled: a profile can have broadcast on while
# multicast/UDP are off, so "a profile exists" cannot imply suitability.
REQUIRED_CLASSIFIERS: tuple[str, ...] = (
    "control",
    "management",
    "data",
    "ip",
    "udp",
    "broadcast",
    "multicast",
)

# Static AP capture targets a specific AP/radio; after this window the serving AP
# may have changed (badge roamed), so a stale preflight must not authorize a leg.
MAX_AGE_SECONDS = 120

CAPTURE_CAPABILITIES: tuple[str, ...] = (
    "unknown",
    "profile_unmapped",
    "profile_mapped_unverified",
    "validated",
)
EVALUATION_STATES: tuple[str, ...] = (
    "blocked",
    "ready_for_profile_change",
    "ready_for_ftp_validation",
    "ready_to_prepare",
)
EVIDENCE_SOURCES: tuple[str, ...] = ("manual_cli_import", "future_wlc_api")


def evaluate(
    facts: Mapping[str, Any],
    *,
    observed_at: datetime,
    now: datetime,
    ftp_intake_ready: bool,
    max_age_seconds: int = MAX_AGE_SECONDS,
) -> dict[str, Any]:
    """Derive the AP-OTA preflight gate state from observed evidence.

    ``facts`` are already-normalized observed values. ``ftp_intake_ready`` is the
    live collector drop-zone health (the web layer supplies it). Returns a dict
    with the derived classifiers, capability, gate state, freshness, and a
    human-readable blocker for every unmet condition.
    """

    classifiers = {
        name: bool(facts.get("classifiers", {}).get(name, False))
        for name in REQUIRED_CLASSIFIERS
    }
    missing_classifiers = [name for name, ok in classifiers.items() if not ok]

    associated = bool(facts.get("target_client_associated"))
    serving_ap = str(facts.get("serving_ap_name") or "").strip()
    site_verified = bool(facts.get("site_capture_status_verified"))
    existing_active = bool(facts.get("existing_site_capture_active"))
    site_tag = str(facts.get("site_tag") or "").strip()
    ap_join = str(facts.get("ap_join_profile") or "").strip()
    pcap_profile = str(facts.get("packet_capture_profile") or "").strip()
    ftp_host = str(facts.get("ftp_server_host") or "").strip()
    ftp_path = str(facts.get("ftp_path") or "").strip()
    ftp_user = str(facts.get("ftp_username") or "").strip()

    expires_at = observed_at + timedelta(seconds=max_age_seconds)
    age_seconds = max(0.0, (now - observed_at).total_seconds())
    fresh = now <= expires_at

    profile_mapped = bool(pcap_profile and site_tag and ap_join)
    classifiers_ok = not missing_classifiers
    ftp_endpoint_ok = bool(ftp_host and ftp_path and ftp_user)
    ftp_ready = bool(ftp_endpoint_ok and ftp_intake_ready)

    if not profile_mapped:
        capability = "profile_unmapped"
    elif not classifiers_ok:
        capability = "profile_mapped_unverified"
    else:
        capability = "validated"

    target_mac = str(facts.get("target_client_mac") or "").strip() or "client"
    blockers: list[str] = []
    if not associated:
        blockers.append(f"Target client {target_mac} is not associated to any AP in the imported evidence.")
    if not serving_ap:
        blockers.append("No serving AP was resolved for static AP capture mode.")
    if not site_verified:
        blockers.append("Site-wide AP client-capture lock was not verified (show ap status packet-capture).")
    if existing_active:
        blockers.append("Another site-wide AP client capture is active; Cisco allows only one client capture per site.")
    if not fresh:
        blockers.append(
            f"Preflight evidence is older than {max_age_seconds}s; re-run discovery before preparing a leg."
        )
    if not profile_mapped:
        blockers.append("No AP packet-capture profile is mapped through the site-tag / AP join profile chain.")
    if missing_classifiers:
        blockers.append("Required packet classifiers are not confirmed: " + ", ".join(missing_classifiers) + ".")
    if not ftp_endpoint_ok:
        blockers.append("FTP endpoint host/path/user are not all confirmed from the profile detail.")
    if not ftp_intake_ready:
        blockers.append("AP-OTA FTP collector drop zone is not ready.")

    base_ok = associated and bool(serving_ap) and site_verified and not existing_active and fresh
    if not base_ok:
        state = "blocked"
    elif not profile_mapped:
        # Expected initial state: client/AP/site evidence is good but no profile
        # has been attached through the AP join / site-tag chain yet.
        state = "ready_for_profile_change"
    elif not classifiers_ok:
        # A profile is attached but is unsafe (missing required classifiers);
        # capturing with it would yield misleading evidence, so hard-block.
        state = "blocked"
    elif not ftp_ready:
        state = "ready_for_ftp_validation"
    else:
        state = "ready_to_prepare"

    return {
        "classifiers": classifiers,
        "missing_classifiers": missing_classifiers,
        "capture_capability": capability,
        "profile_mapped": profile_mapped,
        "classifiers_ok": classifiers_ok,
        "ftp_endpoint_ok": ftp_endpoint_ok,
        "ftp_ready": ftp_ready,
        "ftp_intake_ready": bool(ftp_intake_ready),
        "fresh": fresh,
        "age_seconds": age_seconds,
        "expires_at": expires_at,
        "evaluation_state": state,
        "blockers": blockers,
        "can_create_companion_leg": state == "ready_to_prepare",
    }
