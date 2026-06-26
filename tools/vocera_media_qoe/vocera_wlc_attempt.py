#!/usr/bin/env python3
"""Manual WLC attempt package workflow for Vocera broadcast investigations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import vocera_wlc_evidence as evidence


DEFAULT_ATTEMPT_ROOT = Path("/var/lib/vocera-media-qoe/raw/wlc-attempts")
AUDIO_RESULTS = ("heard", "missed", "partial", "choppy", "unknown", "not_tested")
ALERT_RESULTS = ("true", "false", "unknown", "not_tested")


def normalize_mac(value: str) -> str:
    """Normalize a MAC address to lower-case colon notation."""

    token = re.sub(r"[^0-9A-Fa-f]", "", value)
    if len(token) != 12:
        raise ValueError(f"invalid MAC address: {value}")
    token = token.lower()
    return ":".join(token[index : index + 2] for index in range(0, 12, 2))


def utc_now_iso() -> str:
    """Return a simple UTC timestamp."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def write_text(path: Path, text: str, *, overwrite: bool) -> None:
    """Write text, refusing to overwrite unless requested."""

    if path.exists() and not overwrite:
        raise FileExistsError(f"{path} already exists; pass --force to overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    path.chmod(0o644)


def write_json(path: Path, payload: dict[str, Any], *, overwrite: bool) -> None:
    """Write JSON, refusing to overwrite unless requested."""

    write_text(path, json.dumps(payload, indent=2, sort_keys=True), overwrite=overwrite)


def attempt_dir(root: Path, study_id: str, attempt_id: str) -> Path:
    """Return the canonical attempt directory."""

    return root / study_id / attempt_id


def before_cli(c1000_mac: str, v5000_mac: str) -> str:
    """Return the before-broadcast command sheet."""

    return f"""
terminal length 0
show clock detail
show wireless client mac-address {c1000_mac} detail
show wireless client mac-address {c1000_mac} mobility history
show wireless client mac-address {v5000_mac} detail
show wireless client mac-address {v5000_mac} mobility history
show wireless multicast
show ap multicast mom
show ip igmp snooping
show ip igmp snooping wireless mgid
show wireless multicast group summary
"""


def during_cli(c1000_mac: str, v5000_mac: str, vlan: int) -> str:
    """Return the during-broadcast command sheet."""

    return f"""
terminal length 0
show clock detail
show wireless multicast group summary
! Replace <VOCERA_GROUP> with the active group shown above.
show wireless multicast group <VOCERA_GROUP> vlan {vlan}
show wireless multicast source 0.0.0.0 group <VOCERA_GROUP> vlan {vlan}
show ip igmp snooping groups vlan {vlan}
show ip igmp snooping igmpv2-tracking
show wireless client mac-address {c1000_mac} detail
show wireless client mac-address {v5000_mac} detail
show ap multicast mom
"""


def after_cli(c1000_mac: str) -> str:
    """Return the after-broadcast command sheet."""

    return f"""
terminal length 0
show clock detail
show wireless client mac-address {c1000_mac} detail
show wireless client mac-address {c1000_mac} mobility history
show wireless multicast group summary
show ip igmp snooping igmpv2-tracking
show ap multicast mom
"""


def epc_start_cli(session: str, c1000_mac: str, v5000_mac: str) -> str:
    """Return the EPC start command sheet with operator-verified placeholders."""

    return f"""
terminal length 0
show clock detail
show monitor capture {session}
! Verify exact interface/filter syntax on the WLC with '?' before use.
monitor capture {session} interface <WLC_UPLINK_INTERFACE> both
monitor capture {session} buffer circular size 50
monitor capture {session} match ipv4 any any
! IOS XE 17.12.1+ supports inner MAC filters; verify syntax on this WLC.
monitor capture {session} inner mac {v5000_mac} {c1000_mac}
monitor capture {session} start
show monitor capture {session}
"""


def epc_stop_cli(session: str) -> str:
    """Return the EPC stop/export command sheet."""

    return f"""
terminal length 0
show clock detail
show monitor capture {session}
monitor capture {session} stop
show monitor capture {session}
monitor capture {session} export <APPROVED_TRANSFER_DESTINATION>
! After export is confirmed, remove the capture session.
no monitor capture {session}
show monitor capture {session}
"""


def cleanup_cli(session: str) -> str:
    """Return the EPC cleanup command sheet."""

    return f"""
terminal length 0
show monitor capture {session}
no monitor capture {session}
show monitor capture {session}
"""


def readme_text(study_id: str, attempt_id: str) -> str:
    """Return operator instructions for one attempt package."""

    return f"""
# Manual WLC Evidence Package

Study: `{study_id}`
Attempt: `{attempt_id}`

This folder is intentionally manual. The repo generated command sheets and will
ingest evidence after you move files here, but it will not SSH to the WLC or
change WLC configuration.

1. Enable terminal logging in your WLC terminal.
2. Paste `before.cli` before the V5000 broadcast.
3. Paste `epc-start.cli` after verifying placeholder syntax with `?`.
4. Start the V5000 broadcast.
5. Paste `during.cli`, replacing `<VOCERA_GROUP>` after reading the group summary.
6. Paste `epc-stop-export.cli` and export the EPC PCAP.
7. Paste `after.cli`.
8. Save transcripts as `cli/before.txt`, `cli/during.txt`, and `cli/after.txt`.
9. Move the EPC PCAP to `pcaps/wlc-epc.pcap`.
10. Update `operator-observation.json`.
11. Run `make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=<this directory>`.

Safety:

- Always run `show monitor capture <session>` before start.
- Always run `no monitor capture <session>` after export.
- Never leave EPC running after the attempt.
- Do not treat undecodable or encrypted captures as proof that multicast was absent.
"""


def default_manifest(args: argparse.Namespace, target: Path) -> dict[str, Any]:
    """Build a manifest for one attempt."""

    c1000_mac = normalize_mac(args.c1000_mac)
    v5000_mac = normalize_mac(args.v5000_mac)
    return {
        "schema_version": 1,
        "attempt_id": args.attempt_id,
        "study_id": args.study_id,
        "site": args.site,
        "wlc_name": args.wlc_name,
        "capture_method": "manual_wlc_cli",
        "started_at": args.started_at or utc_now_iso(),
        "ended_at": None,
        "sender": {
            "name": "V5000 Sender",
            "model": "V5000",
            "mac": v5000_mac,
            "ip": args.v5000_ip,
        },
        "receiver": {
            "name": "C1000 Receiver",
            "model": "C1000",
            "mac": c1000_mac,
            "ip": args.c1000_ip,
        },
        "expected": {
            "vocera_vlan": int(args.vocera_vlan),
            "multicast_group": None,
            "expected_dscp": int(args.expected_dscp),
        },
        "artifacts": [
            {
                "type": "wlc_epc",
                "path": "pcaps/wlc-epc.pcap",
                "capture_point": "wlc_epc_uplink",
                "phase": "during",
            },
            {"type": "wlc_cli_snapshot", "path": "cli/before.txt", "phase": "before"},
            {"type": "wlc_cli_snapshot", "path": "cli/during.txt", "phase": "during"},
            {"type": "wlc_cli_snapshot", "path": "cli/after.txt", "phase": "after"},
        ],
        "package_path": str(target),
    }


def default_observation(attempt_id: str, operator: str | None) -> dict[str, Any]:
    """Build an operator observation template."""

    return {
        "attempt_id": attempt_id,
        "c1000_received_alert": None,
        "c1000_received_audio": None,
        "audio_result": "unknown",
        "operator": operator or os.environ.get("USER") or "unknown",
        "observation_time": None,
        "notes": "",
    }


def command_init(args: argparse.Namespace) -> int:
    """Create a new attempt package."""

    target = attempt_dir(Path(args.attempt_root), args.study_id, args.attempt_id)
    for subdir in ("pcaps", "cli", "notes", "validation"):
        (target / subdir).mkdir(parents=True, exist_ok=True)
    manifest = default_manifest(args, target)
    c1000_mac = manifest["receiver"]["mac"]
    v5000_mac = manifest["sender"]["mac"]
    session = args.epc_session
    files = {
        "manifest.json": json.dumps(manifest, indent=2, sort_keys=True),
        "operator-observation.json": json.dumps(default_observation(args.attempt_id, args.operator), indent=2, sort_keys=True),
        "README.md": readme_text(args.study_id, args.attempt_id),
        "before.cli": before_cli(c1000_mac, v5000_mac),
        "during.cli": during_cli(c1000_mac, v5000_mac, int(args.vocera_vlan)),
        "after.cli": after_cli(c1000_mac),
        "epc-start.cli": epc_start_cli(session, c1000_mac, v5000_mac),
        "epc-stop-export.cli": epc_stop_cli(session),
        "cleanup.cli": cleanup_cli(session),
        "notes/operator-notes.md": "# Operator Notes\n",
    }
    for rel_path, text in files.items():
        write_text(target / rel_path, text, overwrite=args.force)
    print(target)
    return 0


def _alert_value(value: str) -> bool | None:
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def command_record(args: argparse.Namespace) -> int:
    """Record or update the operator observation."""

    target = Path(args.attempt_dir)
    path = target / "operator-observation.json"
    payload = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"attempt_id": target.name}
    payload["audio_result"] = args.audio_result
    payload["c1000_received_alert"] = _alert_value(args.alert_result)
    payload["c1000_received_audio"] = args.audio_result == "heard" if args.audio_result in {"heard", "missed"} else None
    payload["operator"] = args.operator or payload.get("operator") or os.environ.get("USER") or "unknown"
    payload["observation_time"] = args.observation_time or utc_now_iso()
    if args.notes is not None:
        payload["notes"] = args.notes
    write_json(path, payload, overwrite=True)
    print(path)
    return 0


def command_validate(args: argparse.Namespace) -> int:
    """Validate an attempt package and write a report."""

    target = Path(args.attempt_dir)
    report = evidence.build_report(target, write_sidecars=False)
    report_path = Path(args.report_out) if args.report_out else target / "validation" / "ingest-report.json"
    evidence.write_json(report_path, report)
    print(json.dumps({"ok": report["ok"], "report": str(report_path), "verdict": report["verdict"]}, sort_keys=True))
    return 0 if report["ok"] else 1


def command_ingest(args: argparse.Namespace) -> int:
    """Validate, write sidecars and SQL, and optionally load PostgreSQL."""

    report = evidence.ingest_attempt(
        Path(args.attempt_dir),
        report_out=Path(args.report_out) if args.report_out else None,
        sql_out=Path(args.sql_out) if args.sql_out else None,
        postgres_url=args.postgres_url,
        psql_bin=args.psql_bin,
        schema_sql=Path(args.schema_sql),
        views_sql=Path(args.views_sql),
    )
    print(json.dumps({"ok": report["ok"], "report": report["report_path"], "sql": report["sql_path"], "verdict": report["verdict"]}, sort_keys=True))
    return 0 if report["ok"] else 1


def command_report(args: argparse.Namespace) -> int:
    """Print a concise attempt report."""

    path = Path(args.attempt_dir) / "validation" / "ingest-report.json"
    report = evidence.load_json(path) if path.is_file() else evidence.build_report(Path(args.attempt_dir), write_sidecars=False)
    payload = {
        "attempt_id": report.get("attempt_id"),
        "ok": report.get("ok"),
        "errors": report.get("errors"),
        "warnings": report.get("warnings"),
        "verdict": report.get("verdict"),
        "artifact_count": len(report.get("artifacts", [])),
        "snapshot_count": len(report.get("snapshots", [])),
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


def command_list(args: argparse.Namespace) -> int:
    """List attempt directories."""

    root = Path(args.attempt_root)
    study_root = root / args.study_id if args.study_id else root
    for path in sorted(study_root.glob("*/*" if not args.study_id else "*")):
        if path.is_dir() and (path / "manifest.json").is_file():
            print(path)
    return 0


def parse_args(argv: Iterable[str]) -> argparse.Namespace:
    """Parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Manual WLC evidence package toolkit.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create an attempt package and command sheets")
    init.add_argument("--attempt-root", default=str(DEFAULT_ATTEMPT_ROOT))
    init.add_argument("--study-id", required=True)
    init.add_argument("--attempt-id", required=True)
    init.add_argument("--site", default="srhc")
    init.add_argument("--wlc-name", required=True)
    init.add_argument("--v5000-mac", required=True)
    init.add_argument("--v5000-ip", required=True)
    init.add_argument("--c1000-mac", required=True)
    init.add_argument("--c1000-ip", required=True)
    init.add_argument("--vocera-vlan", required=True, type=int)
    init.add_argument("--expected-dscp", default=46, type=int)
    init.add_argument("--started-at")
    init.add_argument("--operator")
    init.add_argument("--epc-session", default="VOCERA_BCAST")
    init.add_argument("--force", action="store_true")
    init.set_defaults(func=command_init)

    record = subparsers.add_parser("record", help="Record the human attempt outcome")
    record.add_argument("--attempt-dir", required=True)
    record.add_argument("--audio-result", required=True, choices=AUDIO_RESULTS)
    record.add_argument("--alert-result", default="unknown", choices=ALERT_RESULTS)
    record.add_argument("--operator")
    record.add_argument("--observation-time")
    record.add_argument("--notes")
    record.set_defaults(func=command_record)

    validate = subparsers.add_parser("validate", help="Validate an attempt package")
    validate.add_argument("--attempt-dir", required=True)
    validate.add_argument("--report-out")
    validate.set_defaults(func=command_validate)

    ingest = subparsers.add_parser("ingest", help="Validate, emit sidecars/report/SQL, and optionally load DB")
    ingest.add_argument("--attempt-dir", required=True)
    ingest.add_argument("--report-out")
    ingest.add_argument("--sql-out")
    ingest.add_argument("--postgres-url")
    ingest.add_argument("--psql-bin", default="psql")
    ingest.add_argument("--schema-sql", default="sql/vocera_media_qoe_schema.sql")
    ingest.add_argument("--views-sql", default="sql/vocera_media_qoe_views.sql")
    ingest.set_defaults(func=command_ingest)

    report = subparsers.add_parser("report", help="Print attempt summary")
    report.add_argument("--attempt-dir", required=True)
    report.set_defaults(func=command_report)

    list_cmd = subparsers.add_parser("list", help="List attempt packages")
    list_cmd.add_argument("--attempt-root", default=str(DEFAULT_ATTEMPT_ROOT))
    list_cmd.add_argument("--study-id")
    list_cmd.set_defaults(func=command_list)
    return parser.parse_args(list(argv))


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entrypoint."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
