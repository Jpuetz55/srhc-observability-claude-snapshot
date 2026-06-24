#!/usr/bin/env python3
"""Tests for manual WLC multicast CLI evidence parsing."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_wlc_cli as wlc_cli  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise a concise test failure."""

    if not condition:
        raise AssertionError(message)


def test_multicast_membership_present() -> None:
    """Parse a healthy multicast group detail transcript."""

    text = """
show wireless multicast
Multicast: Enabled
AP CAPWAP Multicast: Multicast
AP CAPWAP IPv4 Multicast group Address: 239.3.2.1

show ap multicast mom
AP Name                  MOM-IP     TYPE MOM- STATUS
----------------------------------------------------
SFB-TSG                  IPv4            Up

show wireless multicast group summary
MGID        Group             Vlan
-----------------------------------------
4160        230.230.0.1       684

show wireless multicast group 230.230.0.1 vlan 684
Group  : 230.230.0.1
Vlan   : 684
MGID   : 4160
Client List
-------------
Client MAC             Client IP         Status
---------------------------------------------------------------
0009.ef54.5f46         10.16.1.44        MC_ONLY

show ip igmp snooping igmpv2-tracking
IGMPv2 Tracking Table

show ip igmp snooping wireless mgid
MGID  Group          Vlan
4160  230.230.0.1    684

show wireless client mac-address 00:09:ef:54:5f:46 detail
AP Name : SFB-TSG
BSSID : aa:bb:cc:dd:ee:ff
Channel : 36
VLAN : 684
Multicast VLAN : 688
RSSI : -58
SNR : 31
Policy Manager State : RUN
"""
    parsed = wlc_cli.parse_wlc_snapshot(text, phase="during", receiver_mac="00:09:ef:54:5f:46", expected_vlan=684)
    require(parsed["vocera_group"] == "230.230.0.1", f"bad group: {parsed}")
    require(parsed["vocera_dynamic_group_ip"] == "230.230.0.1", f"bad dynamic group: {parsed}")
    require(parsed["vocera_dynamic_group_mac"] == "01:00:5e:66:00:01", f"bad dynamic MAC: {parsed}")
    require(parsed["vocera_vlan"] == 684, f"bad vlan: {parsed}")
    require(parsed["configured_vocera_vlan"] == 684, f"configured VLAN should remain 684: {parsed}")
    require(parsed["receiver_multicast_vlan"] == 688, f"client multicast VLAN should be separate evidence: {parsed}")
    require(parsed["resolved_group_vlan"] == 684, f"resolved group VLAN should come from group detail: {parsed}")
    require(parsed["vlan_context_state"] == "resolved_confirmed", f"bad VLAN context: {parsed}")
    require(parsed["mgid"] == 4160, f"bad mgid: {parsed}")
    require(parsed["c1000_group_member"] is True, f"member should be present: {parsed}")
    require(parsed["receiver_ap"] == "SFB-TSG", f"bad AP: {parsed}")
    require(parsed["receiver_channel"] == 36, f"bad channel: {parsed}")
    require(parsed["ap_mom_status"] == "up", f"bad MOM status: {parsed}")
    require(parsed["multicast_enabled"] is True, f"bad multicast status: {parsed}")
    require(parsed["igmp_version"] == "v2", f"bad IGMP version: {parsed}")
    observations = parsed["multicast_observations"]
    require(observations and observations[0]["vocera_group_ip"] == "230.230.0.1", f"missing group observation: {parsed}")
    require(observations[0]["wlc_capwap_group"] == "239.3.2.1", f"missing CAPWAP group: {observations}")
    require(observations[0]["receiver_member"] is True, f"missing receiver membership observation: {observations}")


def test_multicast_membership_missing() -> None:
    """Parse a failed group detail where the C1000 is absent."""

    text = """
show wireless multicast group summary
MGID        Group             Vlan
-----------------------------------------
4160        230.230.0.1       684

show wireless multicast group 230.230.0.1 vlan 684
Group  : 230.230.0.1
Vlan   : 684
MGID   : 4160
Client List
-------------
Client MAC             Client IP         Status
---------------------------------------------------------------
aabb.ccdd.eeff         10.16.1.10        MC_ONLY

show wireless client mac-address 00:09:ef:54:5f:46 detail
VLAN : 684
Multicast VLAN : 688
Policy Manager State : RUN
"""
    parsed = wlc_cli.parse_wlc_snapshot(text, phase="during", receiver_mac="00:09:ef:54:5f:46", expected_vlan=684)
    require(parsed["c1000_group_member"] is False, f"member should be absent: {parsed}")
    require(parsed["vocera_group"] == "230.230.0.1", f"bad group: {parsed}")
    require(parsed["receiver_multicast_vlan"] == 688, f"client multicast VLAN should not overwrite configured VLAN: {parsed}")
    require(parsed["configured_vocera_vlan"] == 684, f"configured VLAN should remain 684: {parsed}")


def test_vlan_context_mismatch_does_not_overwrite_configured_vlan() -> None:
    """Preserve configured VLAN when an active group is observed elsewhere."""

    text = """
show wireless multicast group summary
MGID        Group             Vlan
-----------------------------------------
4161        230.230.0.2       688

show wireless multicast group 230.230.0.2 vlan 688
Group  : 230.230.0.2
Vlan   : 688
MGID   : 4161
Client List
-------------
Client MAC             Client IP         Status
---------------------------------------------------------------
0009.ef61.0bf7         10.16.88.230      MC_ONLY

show wireless client mac-address 00:09:ef:61:0b:f7 detail
VLAN : 688
Multicast VLAN : 688
Policy Manager State : RUN
"""
    parsed = wlc_cli.parse_wlc_snapshot(text, phase="during", receiver_mac="00:09:ef:61:0b:f7", expected_vlan=684)
    require(parsed["configured_vocera_vlan"] == 684, f"configured VLAN should remain 684: {parsed}")
    require(parsed["receiver_vlan"] == 688, f"receiver client VLAN should be observed separately: {parsed}")
    require(parsed["resolved_group_vlan"] == 688, f"resolved group VLAN should follow selected group detail: {parsed}")
    require(parsed["vlan_context_state"] == "configured_group_mismatch", f"bad VLAN context: {parsed}")
    require(parsed["c1000_group_member"] is True, f"membership should be scoped to group detail: {parsed}")


def test_ap_mgid_snapshot() -> None:
    """Parse optional AP MGID client and counter evidence."""

    text = """
show capwap mcast mgid clients
MGID   Client MAC        Slot  Mode
4160   0009.ef61.0bf7    0     mc_only

show capwap mcast mgid all
MGID   Mode     RX Packets   TX Packets
4160   mc_only  10           12
"""
    parsed = wlc_cli.parse_wlc_snapshot(text, phase="during", receiver_mac="00:09:ef:61:0b:f7", expected_vlan=684)
    require(parsed["ap_mgid_clients"][0]["receiver_mac"] == "00:09:ef:61:0b:f7", f"bad AP MGID client: {parsed}")
    require(parsed["ap_mgid_clients"][0]["ap_delivery_mode"] == "mc_only", f"bad AP mode: {parsed}")
    require(parsed["ap_mgid_counters"][0]["ap_tx_packets"] == 12, f"bad AP TX counter: {parsed}")
    observations = parsed["multicast_observations"]
    require(any(item["evidence_source"] == "ap_mgid_snapshot" for item in observations), f"missing AP MGID observation: {parsed}")
    require(any(item["evidence_source"] == "ap_mgid_counter" for item in observations), f"missing AP counter observation: {parsed}")


def main() -> int:
    """Run standalone tests."""

    test_multicast_membership_present()
    test_multicast_membership_missing()
    test_vlan_context_mismatch_does_not_overwrite_configured_vlan()
    test_ap_mgid_snapshot()
    print("OK: WLC CLI evidence parser tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
