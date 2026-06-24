#!/usr/bin/env python3
"""Tests for manual WLC capture-session package creation."""

from __future__ import annotations

import json
import re
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_wlc_session as session  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def test_long_session_package() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        rc = session.main(
            [
                "init",
                "--session-root",
                tmp,
                "--study-id",
                "study_v5000_c1000_multicast",
                "--session-id",
                "20260623T160000-v5000-c1000-session-001",
                "--wlc-name",
                "SRHC-WLC-40G-SEC",
                "--capture-name",
                "VOCERA_C1000_001",
                "--wlc-interface",
                "Port-channel1",
                "--collector-host",
                "10.0.128.107",
                "--collector-scp-username",
                "appsadmin",
                "--sender-mac",
                "00:09:ef:54:5f:46",
                "--sender-ip",
                "10.16.88.228",
                "--receiver-mac",
                "00:09:ef:61:0b:f7",
                "--receiver-ip",
                "10.16.88.230",
                "--ring-file-count",
                "5",
                "--ring-file-size-mb",
                "100",
                "--vocera-vlan",
                "684",
            ]
        )
        require(rc == 0, "session init should succeed")
        target = Path(tmp) / "study_v5000_c1000_multicast" / "20260623T160000-v5000-c1000-session-001"
        payload = json.loads((target / "session.json").read_text(encoding="utf-8"))
        require(payload["session_state"] == "prepared_not_started", f"bad state: {payload}")
        require(payload["ring_total_size_mb"] == 500, f"bad ring total: {payload}")
        require(payload["expected"]["expected_mac_start"] == "01:00:5e:66:00:01", "bad derived start MAC")
        long_cli = (target / "start-long.cli").read_text(encoding="utf-8")
        short_cli = (target / "start-short-validation.cli").read_text(encoding="utf-8")
        stop_cli = (target / "stop-export.cli").read_text(encoding="utf-8")
        cleanup_cli = (target / "cleanup.cli").read_text(encoding="utf-8")
        require("monitor capture VOCERA_C1000_001 interface Port-channel 1 both" in long_cli, "missing Po1 capture attachment")
        require("monitor capture VOCERA_C1000_001 buffer circular file 5 file-size 100" in long_cli, "missing bounded circular ring")
        require("monitor capture VOCERA_C1000_001 limit duration" not in long_cli, "long mode must not force duration")
        require("monitor capture VOCERA_C1000_001 limit duration 90" in short_cli, "short validation mode should have duration")
        require("permit ip any 230.230.0.0 0.0.15.255" in long_cli, "missing Vocera pool destination ACL")
        require("permit igmp any any" in long_cli, "missing IGMP evidence ACL line")
        require("monitor capture VOCERA_C1000_001 inner mac 00:09:ef:54:5f:46 00:09:ef:61:0b:f7" in long_cli, "missing badge identity inner MAC filter")
        require("scp://appsadmin@10.0.128.107//" in stop_cli, "missing password-free SCP export URI")
        require(not re.search(r"scp://[^/@:]+:[^/@]+@", stop_cli), "SCP URI must not embed a credential")
        require((target / "baseline.cli").is_file(), "missing baseline command sheet")
        require((target / "active-event.cli").is_file(), "missing active-event command sheet")
        require((target / "resolved-active-group.cli").is_file(), "missing resolved active-group command sheet")
        require((target / "post-failure.cli").is_file(), "missing post-failure command sheet")
        require((target / "ap-evidence.cli").is_file(), "missing AP evidence command sheet")
        baseline_cli = (target / "baseline.cli").read_text(encoding="utf-8")
        active_cli = (target / "active-event.cli").read_text(encoding="utf-8")
        resolved_cli = (target / "resolved-active-group.cli").read_text(encoding="utf-8")
        ap_cli = (target / "ap-evidence.cli").read_text(encoding="utf-8")
        require(payload["expected"]["configured_vocera_vlan"] == 684, f"configured VLAN should be persisted: {payload}")
        require(payload["configured_vocera_vlan"] == 684, f"top-level configured VLAN should be persisted: {payload}")
        require(payload["vlan_selection_source"] == "default", f"default VLAN source should be recorded: {payload}")
        require("Configured Vocera multicast VLAN: 684" in baseline_cli, "baseline should label configured VLAN")
        require("show ip igmp snooping querier vlan 684" in baseline_cli, "missing IGMP querier baseline command")
        require("show ip igmp snooping wireless mcast-ipc-count" in active_cli, "missing multicast IPC command")
        require("show ip igmp snooping wireless mcast-spi-count" in active_cli, "missing multicast SPI command")
        require("show ip igmp snooping groups vlan 684" in active_cli, "active-event candidate commands should use configured VLAN")
        require("show wireless multicast group <VOCERA_GROUP> vlan 684" not in active_cli, "active-event should not auto-fill group detail commands")
        require("show wireless multicast group <RESOLVED_GROUP_IP> vlan <RESOLVED_GROUP_VLAN>" in resolved_cli, "resolved sheet should use selected group and VLAN")
        require("Configured default VLAN: 684" in resolved_cli, "resolved sheet should preserve configured default")
        require("show capwap mcast mgid clients" in ap_cli, "missing AP MGID client command")
        require("no monitor capture VOCERA_C1000_001" in cleanup_cli, "cleanup must delete EPC session")
        require("no ip access-list extended VOCERA_EPC_VOCERA_C1000_001" in cleanup_cli, "cleanup must delete temporary ACL")

        rc = session.main(["mark", "--session-dir", str(target), "--event-kind", "missed", "--operator", "tester"])
        require(rc == 0, "session mark should succeed")
        events = json.loads((target / "session-events.json").read_text(encoding="utf-8"))
        require(events[-1]["event_kind"] == "missed", f"bad event marker: {events}")


def test_incoming_staging_dir() -> None:
    """The session package stages SCP uploads in incoming/, not pcaps/.

    Exporting straight into pcaps/ would let a half-written file look like final
    evidence, so the WLC writes the EPC into incoming/ and the collector only
    promotes it into pcaps/ once the upload is complete and validated.
    """

    with tempfile.TemporaryDirectory() as tmp:
        rc = session.main(
            [
                "init",
                "--session-root",
                tmp,
                "--study-id",
                "study_x",
                "--session-id",
                "sess_incoming",
                "--wlc-name",
                "SRHC-WLC-40G-SEC",
                "--wlc-interface",
                "Port-channel1",
                "--collector-host",
                "10.0.128.107",
                "--collector-scp-username",
                "appsadmin",
                "--sender-mac",
                "00:09:ef:54:5f:46",
                "--sender-ip",
                "10.16.88.228",
                "--receiver-mac",
                "00:09:ef:61:0b:f7",
                "--receiver-ip",
                "10.16.88.230",
            ]
        )
        require(rc == 0, "session init should succeed")
        target = Path(tmp) / "study_x" / "sess_incoming"
        require((target / "incoming").is_dir(), "session package must create an incoming/ staging dir")
        require((target / "pcaps").is_dir(), "session package must still create pcaps/")
        export_path = session.default_export_path("sess_incoming", target)
        require(
            export_path.endswith("/incoming/sess_incoming.pcap"),
            f"export should land in incoming/: {export_path}",
        )
        payload = json.loads((target / "session.json").read_text(encoding="utf-8"))
        require("/incoming/" in payload["collector_scp_path"], f"scp path should target incoming/: {payload['collector_scp_path']}")
        require("/incoming/" in payload["export_uri"], f"export URI should target incoming/: {payload['export_uri']}")
        require("/pcaps/" not in payload["export_uri"], "export URI must not target pcaps/ directly")
        stop_cli = (target / "stop-export.cli").read_text(encoding="utf-8")
        require("/incoming/" in stop_cli, "stop-export should export the EPC into incoming/")


def test_operator_vlan_override_package() -> None:
    """Verify operator-selected configured VLAN is persisted without changing the default contract."""

    with tempfile.TemporaryDirectory() as tmp:
        rc = session.main(
            [
                "init",
                "--session-root",
                tmp,
                "--study-id",
                "study_v5000_c1000_multicast",
                "--session-id",
                "20260623T160500-v5000-c1000-session-002",
                "--wlc-name",
                "SRHC-WLC-40G-SEC",
                "--wlc-interface",
                "Port-channel1",
                "--collector-host",
                "10.0.128.107",
                "--collector-scp-username",
                "appsadmin",
                "--sender-mac",
                "00:09:ef:54:5f:46",
                "--sender-ip",
                "10.16.88.228",
                "--receiver-mac",
                "00:09:ef:61:0b:f7",
                "--receiver-ip",
                "10.16.88.230",
                "--vocera-vlan",
                "688",
                "--vlan-selection-source",
                "operator_override",
            ]
        )
        require(rc == 0, "session init with override should succeed")
        target = Path(tmp) / "study_v5000_c1000_multicast" / "20260623T160500-v5000-c1000-session-002"
        payload = json.loads((target / "session.json").read_text(encoding="utf-8"))
        active_cli = (target / "active-event.cli").read_text(encoding="utf-8")
        require(payload["configured_vocera_vlan"] == 688, f"operator override VLAN should persist: {payload}")
        require(payload["vlan_selection_source"] == "operator_override", f"override source should persist: {payload}")
        require("show ip igmp snooping groups vlan 688" in active_cli, "operator-selected VLAN should drive command sheets")


def _init_session(tmp: str, session_id: str = "sess-001", *, vocera_vlan: int = 684) -> Path:
    rc = session.main(
        [
            "init",
            "--session-root",
            tmp,
            "--study-id",
            "study_x",
            "--session-id",
            session_id,
            "--wlc-name",
            "WLC",
            "--wlc-interface",
            "Port-channel1",
            "--collector-host",
            "10.0.128.107",
            "--collector-scp-username",
            "appsadmin",
            "--sender-mac",
            "00:09:ef:54:5f:46",
            "--sender-ip",
            "10.16.88.228",
            "--receiver-mac",
            "00:09:ef:61:0b:f7",
            "--receiver-ip",
            "10.16.88.230",
            "--vocera-vlan",
            str(vocera_vlan),
        ]
    )
    require(rc == 0, "session init should succeed")
    return Path(tmp) / "study_x" / session_id


def test_generated_capture_name_is_unique() -> None:
    name_a = session.generate_capture_name()
    name_b = session.generate_capture_name()
    require(re.fullmatch(r"VOCERA_\d{6}_\d{4}_[0-9A-F]{4}", name_a) is not None, f"bad capture name format: {name_a}")
    require(name_a != name_b, "generated capture names must be unique")
    require(len(name_a) <= 32, "capture name must fit the WLC 32-char limit")


def test_duplicate_session_protection() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _init_session(tmp)
        rc = session.main(
            [
                "init",
                "--session-root",
                tmp,
                "--study-id",
                "study_x",
                "--session-id",
                "sess-001",
                "--wlc-name",
                "WLC",
                "--wlc-interface",
                "Port-channel1",
                "--collector-host",
                "10.0.128.107",
                "--collector-scp-username",
                "appsadmin",
                "--sender-mac",
                "00:09:ef:54:5f:46",
                "--sender-ip",
                "10.16.88.228",
                "--receiver-mac",
                "00:09:ef:61:0b:f7",
                "--receiver-ip",
                "10.16.88.230",
            ]
        )
        require(rc == 2, "re-init of an existing session package must be refused")


def test_attempt_lifecycle_one_open_per_session() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = _init_session(tmp)
        require(session.main(["start-attempt", "--session-dir", str(target), "--operator", "t1"]) == 0, "start should succeed")
        attempts = json.loads((target / "attempts" / "index.json").read_text(encoding="utf-8"))
        require(len(attempts) == 1 and attempts[0]["attempt_state"] == "open", f"one open attempt expected: {attempts}")
        # A second open attempt is refused while one is already open.
        require(session.main(["start-attempt", "--session-dir", str(target)]) == 2, "second open attempt must be refused")
        # Outcome closes the open attempt without creating a new row.
        require(session.main(["outcome", "--session-dir", str(target), "--audio-result", "heard"]) == 0, "outcome should succeed")
        attempts = json.loads((target / "attempts" / "index.json").read_text(encoding="utf-8"))
        require(len(attempts) == 1, f"outcome must reuse the open attempt: {attempts}")
        require(attempts[0]["attempt_state"] == "completed", f"attempt should be completed: {attempts}")
        require(attempts[0]["audio_result"] == "heard", f"attempt outcome should persist: {attempts}")
        # Starting again is allowed once the prior attempt is closed.
        require(session.main(["start-attempt", "--session-dir", str(target)]) == 0, "new attempt after close should succeed")
        attempts = json.loads((target / "attempts" / "index.json").read_text(encoding="utf-8"))
        require(len(attempts) == 2, f"a new broadcast should open a new attempt: {attempts}")


def test_resolve_group_persists_and_enforces_vlan() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        target = _init_session(tmp)
        require(session.main(["start-attempt", "--session-dir", str(target)]) == 0, "start should succeed")
        attempt_id = json.loads((target / "attempts" / "index.json").read_text(encoding="utf-8"))[0]["attempt_id"]
        summary = "show wireless multicast group summary\nMGID  Group        Vlan\n4160  230.230.0.5  684\n"
        rc = session.main(
            [
                "resolve-group",
                "--session-dir",
                str(target),
                "--group-ip",
                "230.230.0.5",
                "--group-vlan",
                "684",
                "--mgid",
                "4160",
                "--summary-text",
                summary,
                "--operator",
                "t1",
            ]
        )
        require(rc == 0, "matching-VLAN group resolution should succeed")
        resolved_cli = (target / "cli" / f"attempt-{attempt_id}-resolved-group.cli").read_text(encoding="utf-8")
        require("show wireless multicast group 230.230.0.5 vlan 684" in resolved_cli, "resolved sheet must use concrete group/VLAN")
        require("<RESOLVED_GROUP_IP>" not in resolved_cli, "resolved sheet must not keep placeholders")
        selection = json.loads((target / "notes" / f"attempt-{attempt_id}-group-selection.json").read_text(encoding="utf-8"))
        require(selection["group_ip"] == "230.230.0.5" and selection["group_vlan"] == 684, f"selection must persist: {selection}")
        require(selection["selected_row"] == "4160  230.230.0.5  684", f"raw selected row must persist: {selection}")
        require((target / "cli" / f"attempt-{attempt_id}-active-group-summary.txt").is_file(), "raw summary must persist")
        # A VLAN mismatch without an override reason is rejected.
        rc = session.main(
            [
                "resolve-group",
                "--session-dir",
                str(target),
                "--group-ip",
                "230.230.0.6",
                "--group-vlan",
                "688",
                "--selection-source",
                "observed_confirmation",
            ]
        )
        require(rc == 2, "mismatched VLAN without override must be refused")
        # A VLAN mismatch with an operator override and reason is accepted.
        rc = session.main(
            [
                "resolve-group",
                "--session-dir",
                str(target),
                "--group-ip",
                "230.230.0.6",
                "--group-vlan",
                "688",
                "--selection-source",
                "operator_override",
                "--override-reason",
                "live broadcast on 688",
            ]
        )
        require(rc == 0, "explained VLAN override must be accepted")
        attempts = json.loads((target / "attempts" / "index.json").read_text(encoding="utf-8"))
        require(attempts[0]["resolved_group_vlan"] == 688, f"override VLAN must persist on attempt: {attempts}")
        require(attempts[0]["vlan_override_reason"] == "live broadcast on 688", f"override reason must persist: {attempts}")


def main() -> int:
    test_long_session_package()
    test_incoming_staging_dir()
    test_operator_vlan_override_package()
    test_generated_capture_name_is_unique()
    test_duplicate_session_protection()
    test_attempt_lifecycle_one_open_per_session()
    test_resolve_group_persists_and_enforces_vlan()
    print("OK: WLC capture-session package tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
