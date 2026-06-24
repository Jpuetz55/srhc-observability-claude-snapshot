#!/usr/bin/env python3
"""Fixture-based smoke tests for WLC RF and badge client parsers."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "wireless_rf"))

from wireless_rf.client_parser import parse_badge_client_raw  # noqa: E402
from wireless_rf.client_prometheus import render_badge_prometheus  # noqa: E402
from wireless_rf.parser import parse_ap_tag_summary  # noqa: E402
from wireless_rf.parser import parse_wlc_rf_dump  # noqa: E402
from wireless_rf.prometheus import render_prometheus  # noqa: E402
from verify_wireless_rf_cli_parse import verify_cli_parse  # noqa: E402


FIXTURES = ROOT / "tests" / "fixtures" / "wireless_rf"


def require(condition: bool, message: str) -> None:
    """Raise AssertionError with a concise fixture-specific failure message."""

    if not condition:
        raise AssertionError(message)


def test_wlc_rf_fixture() -> None:
    """Verify representative WLC RF output parses into expected snapshots."""

    text = (FIXTURES / "wlc_rf_sample.txt").read_text(encoding="utf-8")
    tags = parse_ap_tag_summary(text)
    require(tags["AP-ALPHA"].site_tag == "ST_MAIN", "tag parser should ignore later dot11 summary rows")
    require(tags["AP-CHARLIE"].site_tag == "ST_CLI_ONLY", "failed to parse tag summary row without AP MAC")
    require(tags["AP-CHARLIE"].ap_mac == "", "AP MAC should be empty when tag summary omits it")

    snapshots = parse_wlc_rf_dump(text, wlc="SRHC-WLC-SEC", default_band="5ghz")
    require(len(snapshots) == 4, f"expected 4 AP snapshots, got {len(snapshots)}")

    alpha = next(snapshot for snapshot in snapshots if snapshot.ap_name == "AP-ALPHA")
    bravo = next(snapshot for snapshot in snapshots if snapshot.ap_name == "AP-BRAVO" and snapshot.band == "5ghz")
    bravo_voice = next(snapshot for snapshot in snapshots if snapshot.ap_name == "AP-BRAVO" and snapshot.band == "2.4ghz")
    charlie = next(snapshot for snapshot in snapshots if snapshot.ap_name == "AP-CHARLIE")

    require(alpha.site_tag == "ST_MAIN", f"unexpected alpha site_tag: {alpha.site_tag}")
    require(alpha.policy_tag == "POL_VOICE", f"unexpected alpha policy_tag: {alpha.policy_tag}")
    require(alpha.rf_tag == "RF_VOICE", f"unexpected alpha rf_tag: {alpha.rf_tag}")
    require(alpha.neighbor_count == 2, f"unexpected alpha neighbor_count: {alpha.neighbor_count}")
    require(alpha.is_dfs_channel is True, "alpha should be on a DFS channel")
    require(alpha.radar_changes_total == 3, f"unexpected alpha radar count: {alpha.radar_changes_total}")
    require(alpha.receive_utilization_pct == 7, f"unexpected alpha receive utilization: {alpha.receive_utilization_pct}")
    require(alpha.transmit_utilization_pct == 11, f"unexpected alpha transmit utilization: {alpha.transmit_utilization_pct}")
    require(alpha.channel_utilization_pct == 23, f"unexpected alpha channel utilization: {alpha.channel_utilization_pct}")
    require(alpha.zero_wait_dfs_capable is True, "alpha should be zero-wait DFS capable")
    require(alpha.zero_wait_dfs_enabled is True, "alpha should have zero-wait DFS enabled")
    require(len(alpha.access_category_latencies) == 1, "alpha should have one traffic-distribution latency observation")
    alpha_voice = alpha.access_category_latencies[0]
    require(alpha_voice.slot_id == "1", f"unexpected alpha slot: {alpha_voice.slot_id}")
    require(alpha_voice.band == "5ghz", f"unexpected alpha voice band: {alpha_voice.band}")
    require(alpha_voice.access_category == "voice", f"unexpected alpha access category: {alpha_voice.access_category}")
    require(alpha_voice.client_generation == "non_wifi6", f"unexpected alpha client generation: {alpha_voice.client_generation}")
    require(alpha_voice.active_clients == 1, f"unexpected alpha voice active clients: {alpha_voice.active_clients}")
    require(alpha_voice.avg_latency_us == 121347, f"unexpected alpha voice latency: {alpha_voice.avg_latency_us}")
    require(alpha_voice.packets_by_latency_level["very_high"] == 1, "alpha should have one very-high voice packet")
    require(alpha_voice.sample_end_timestamp_seconds is not None, "alpha should parse traffic sample end timestamp")

    require(bravo.site_tag == "ST_BACK", f"unexpected bravo site_tag: {bravo.site_tag}")
    require(bravo.current_channel == 44, f"unexpected bravo current_channel: {bravo.current_channel}")
    require(bravo.channel_utilization_pct == 6, f"unexpected bravo channel utilization: {bravo.channel_utilization_pct}")
    require(bravo.is_dfs_channel is False, "bravo should not be on a DFS channel")
    bravo_non_wifi6 = next(
        latency for latency in bravo_voice.access_category_latencies
        if latency.client_generation == "non_wifi6"
    )
    require(bravo_non_wifi6.slot_id == "0", f"unexpected bravo slot: {bravo_non_wifi6.slot_id}")
    require(bravo_non_wifi6.band == "2.4ghz", f"unexpected bravo voice band: {bravo_non_wifi6.band}")
    require(bravo_non_wifi6.active_clients == 16, f"unexpected bravo voice active clients: {bravo_non_wifi6.active_clients}")
    require(bravo_non_wifi6.avg_latency_us == 7197, f"unexpected bravo voice latency: {bravo_non_wifi6.avg_latency_us}")
    require(bravo_non_wifi6.packets_by_latency_level["good"] == 788, "bravo should have 788 good voice packets")
    require(bravo_non_wifi6.packets_by_latency_level["very_high"] == 2, "bravo should have two very-high voice packets")

    require(charlie.site_tag == "ST_CLI_ONLY", f"unexpected charlie site_tag: {charlie.site_tag}")
    require(charlie.band == "5ghz", f"unexpected charlie snapshot band: {charlie.band}")
    charlie_wifi6 = next(
        latency for latency in charlie.access_category_latencies
        if latency.client_generation == "wifi6"
    )
    charlie_non_wifi6 = next(
        latency for latency in charlie.access_category_latencies
        if latency.client_generation == "non_wifi6"
    )
    require(charlie_wifi6.active_clients == 1, "charlie WiFi6 active client count should parse from live table")
    require(charlie_wifi6.avg_latency_us == 3906, "charlie WiFi6 latency should parse from live table")
    require(charlie_wifi6.packets_by_latency_level["good"] == 3, "charlie WiFi6 good packets should parse")
    require(charlie_non_wifi6.active_clients == 17, "charlie non-WiFi6 active client count should parse")
    require(charlie_non_wifi6.avg_latency_us == 67587, "charlie non-WiFi6 latency should parse")
    require(charlie_non_wifi6.packets_by_latency_level["very_high"] == 6, "charlie non-WiFi6 very-high packets should parse")

    prom = render_prometheus(snapshots, now=(alpha_voice.sample_end_timestamp_seconds or 0) + 30)
    require("wireless_rf_collection_last_success_timestamp_seconds" in prom, "missing collection success timestamp")
    require("wireless_rf_collection_commands_total" in prom, "missing collection command count")
    require("wireless_rf_collection_latency_samples_total" in prom, "missing collection latency sample count")
    require('wireless_ap_neighbor_count_cli{wlc="SRHC-WLC-SEC",ap_name="AP-ALPHA"' in prom, "missing AP neighbor count metric line")
    require('site_tag="ST_MAIN"' in prom, "missing AP site tag label")
    require('policy_tag="POL_VOICE"' in prom, "missing AP policy tag label")
    require('rf_tag="RF_VOICE"' in prom, "missing AP rf tag label")
    require('channel_family="UNII-2e DFS"' in prom, "missing DFS channel family label")
    require('threshold_dbm="-65"' in prom, "missing RSSI threshold label")
    require("wireless_ap_channel_utilization_pct_cli" in prom, "missing AP channel utilization metric")
    require("wireless_ap_receive_utilization_pct_cli" in prom, "missing AP receive utilization metric")
    require("wireless_ap_transmit_utilization_pct_cli" in prom, "missing AP transmit utilization metric")
    require("wireless_ap_ac_latency_avg_us_cli" in prom, "missing AP access-category latency metric")
    require("wireless_ap_ac_latency_sample_end_timestamp_seconds" in prom, "missing AP latency sample timestamp")
    require("wireless_ap_ac_latency_sample_age_seconds" in prom, "missing AP latency sample age")
    require('source="traffic_distribution_cli"' in prom, "missing traffic-distribution source label")
    require('slot_id="1"' in prom, "missing slot label")
    require('access_category="voice"' in prom, "missing access-category label")
    require('client_generation="non_wifi6"' in prom, "missing client-generation label")
    require('latency_level="very_high"' in prom, "missing latency-level label")
    require("} 121347" in prom, "missing alpha voice latency value")
    require("} 30.0" in prom, "missing deterministic alpha sample age value")

    with tempfile.TemporaryDirectory() as tmpdir:
        prom_path = Path(tmpdir) / "wlc_rf.prom"
        prom_path.write_text(prom, encoding="utf-8")
        result = verify_cli_parse(
            FIXTURES / "wlc_rf_sample.txt",
            prom_path,
            wlc="SRHC-WLC-SEC",
            ap_name="AP-CHARLIE",
            slot_id="1",
            access_category="voice",
            client_generation="non_wifi6",
        )
    require(result.comparisons["active_clients"] == (17.0, 17.0), "verifier should match active clients")
    require(result.comparisons["avg_latency_us"] == (67587.0, 67587.0), "verifier should match latency")
    require(result.comparisons["very_high_packets"] == (6.0, 6.0), "verifier should match very-high packets")


def test_badge_fixture() -> None:
    """Verify representative badge client JSON parses into stable metrics."""

    payload = json.loads((FIXTURES / "badge_client_sample.json").read_text(encoding="utf-8"))
    snapshots = parse_badge_client_raw(payload)
    require(len(snapshots) == 2, f"expected 2 badge snapshots, got {len(snapshots)}")

    ft = next(snapshot for snapshot in snapshots if snapshot.client_mac == "aa:bb:cc:dd:ee:01")
    non_ft = next(snapshot for snapshot in snapshots if snapshot.client_mac == "aa:bb:cc:dd:ee:02")

    require(ft.ft_state == "ft", f"unexpected ft state: {ft.ft_state}")
    require(non_ft.ft_state == "non_ft", f"unexpected non-ft state: {non_ft.ft_state}")
    require(ft.site_tag == "ST_MAIN", f"unexpected badge site tag: {ft.site_tag}")
    require(ft.policy_tag == "POL_VOICE", f"unexpected badge policy tag: {ft.policy_tag}")
    require(ft.rf_tag == "RF_VOICE", f"unexpected badge rf tag: {ft.rf_tag}")

    prom = render_badge_prometheus(snapshots)
    require("wireless_badge_client_present_cc" in prom, "missing raw badge cc metric")
    require("wireless_badge_client_rx_retry_pct_cc" in prom, "missing retry cc metric")
    require("wireless_badge_client_latency_voice_us_cc" in prom, "missing voice latency cc metric")
    require("wireless_badge_client_latency_be_us_cc" in prom, "missing best effort latency cc metric")
    require("wireless_badge_client_average_auth_duration_ms_cc" in prom, "missing auth duration cc metric")
    require("wireless_badge_client_average_assoc_duration_ms_cc" in prom, "missing assoc duration cc metric")
    require("wireless_badge_client_average_dhcp_duration_ms_cc" in prom, "missing dhcp duration cc metric")
    require("wireless_badge_client_session_duration_s_cc" in prom, "missing session duration cc metric")
    require("wireless_badge_client_onboarding_attempts_cc" in prom, "missing onboarding attempts cc metric")
    require("wireless_badge_client_ft_state_cc" in prom, "missing ft state cc metric")
    require("wireless_badge_client_current_ap_info_cc" in prom, "missing current ap cc metric")
    require("wireless_badge_client_present{" not in prom, "found legacy raw badge metric name")
    require("wireless_badge_client_rx_retry_pct{" not in prom, "found legacy retry metric name")
    require('ap_name="AP-ALPHA"' in prom, "missing AP name label in badge prom output")
    require('policy_tag="POL_VOICE"' in prom, "missing policy tag label in badge prom output")
    require('rf_tag="RF_VOICE"' in prom, "missing rf tag label in badge prom output")


def main() -> int:
    """Run all parser smoke tests without requiring pytest."""

    test_wlc_rf_fixture()
    test_badge_fixture()
    print("OK: wireless RF parser fixtures passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
