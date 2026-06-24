#!/usr/bin/env python3
"""Tests for manual WLC attempt package creation and ingest."""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_wlc_attempt as attempt  # noqa: E402
import vocera_wlc_evidence as evidence  # noqa: E402


def require(condition: bool, message: str) -> None:
    """Raise a concise test failure."""

    if not condition:
        raise AssertionError(message)


def write_minimal_pcap(path: Path) -> None:
    """Write a tiny structurally valid pcap."""

    global_header = struct.pack("<IHHIIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    packet = b"test"
    record_header = struct.pack("<IIII", 1, 0, len(packet), len(packet))
    path.write_bytes(global_header + record_header + packet)


def test_attempt_init_and_ingest_membership_failure() -> None:
    """Create, populate, and ingest a failed manual WLC attempt."""

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        rc = attempt.main(
            [
                "init",
                "--attempt-root",
                str(root),
                "--study-id",
                "study_v5000_c1000_multicast",
                "--attempt-id",
                "20260623T143015-attempt-002",
                "--wlc-name",
                "SRHC-WLC-40G-SEC",
                "--v5000-mac",
                "aa:bb:cc:dd:ee:ff",
                "--v5000-ip",
                "10.16.1.10",
                "--c1000-mac",
                "00:09:ef:54:5f:46",
                "--c1000-ip",
                "10.16.1.44",
                "--vocera-vlan",
                "684",
                "--started-at",
                "2026-06-23T14:30:15-05:00",
            ]
        )
        require(rc == 0, "attempt init should succeed")
        attempt_dir = root / "study_v5000_c1000_multicast" / "20260623T143015-attempt-002"
        for rel_path in (
            "manifest.json",
            "operator-observation.json",
            "before.cli",
            "during.cli",
            "after.cli",
            "epc-start.cli",
            "epc-stop-export.cli",
            "cleanup.cli",
            "README.md",
        ):
            require((attempt_dir / rel_path).is_file(), f"missing generated file {rel_path}")
        command_text = "\n".join((attempt_dir / name).read_text(encoding="utf-8") for name in ("before.cli", "during.cli", "epc-start.cli"))
        require("show wireless multicast group summary" in command_text, "missing multicast command")
        require("netmiko" not in command_text.lower() and "ssh" not in command_text.lower(), "command sheets must remain manual")

        (attempt_dir / "cli" / "before.txt").write_text("show wireless multicast\nMulticast: Enabled\n", encoding="utf-8")
        (attempt_dir / "cli" / "during.txt").write_text(
            """
show wireless multicast group summary
MGID        Group             Vlan
-----------------------------------------
4160        230.230.0.1       684

show wireless multicast
AP CAPWAP Multicast: Multicast
AP CAPWAP IPv4 Multicast group Address: 239.3.2.1

show wireless multicast group 230.230.0.1 vlan 684
Group  : 230.230.0.1
Vlan   : 684
MGID   : 4160
Client List
-------------
Client MAC             Client IP         Status
---------------------------------------------------------------
aabb.ccdd.eeff         10.16.1.10        MC_ONLY
""",
            encoding="utf-8",
        )
        (attempt_dir / "cli" / "after.txt").write_text("show clock detail\n", encoding="utf-8")
        write_minimal_pcap(attempt_dir / "pcaps" / "wlc-epc.pcap")
        rc = attempt.main(
            [
                "record",
                "--attempt-dir",
                str(attempt_dir),
                "--audio-result",
                "missed",
                "--alert-result",
                "true",
                "--operator",
                "tester",
                "--notes",
                "Alert arrived but voice did not play.",
            ]
        )
        require(rc == 0, "record should succeed")

        report = evidence.ingest_attempt(attempt_dir)
        require(report["ok"] is True, f"ingest should validate: {report}")
        require(report["verdict"]["verdict"] == "membership_failure", f"bad verdict: {report['verdict']}")
        require((attempt_dir / "pcaps" / "wlc-epc.pcap.json").is_file(), "missing PCAP sidecar")
        sidecar = json.loads((attempt_dir / "pcaps" / "wlc-epc.pcap.json").read_text(encoding="utf-8"))
        require(sidecar["capture_source"] == "wlc_epc", f"bad sidecar: {sidecar}")
        sql = (attempt_dir / "validation" / "attempt-import.sql").read_text(encoding="utf-8")
        require("vocera_media_broadcast_attempts" in sql, "missing attempt SQL")
        require("vocera_media_multicast_observations" in sql, "missing multicast observation SQL")
        require("230.230.0.1" in sql and "01:00:5e:66:00:01" in sql, "missing normalized group IP/MAC SQL")
        require("239.3.2.1" in sql, "missing separate CAPWAP multicast group SQL")
        require("membership_failure" in sql, "missing verdict SQL")


def main() -> int:
    """Run standalone tests."""

    test_attempt_init_and_ingest_membership_failure()
    print("OK: WLC attempt package tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
