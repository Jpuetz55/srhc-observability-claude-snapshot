#!/usr/bin/env python3
"""Tests for WLC capture-session SCP ingest.

Two layers:

1. Unit tests for the pure ingest primitives in ``vocera_wlc_session_ingest`` --
   upload-stability decisions, pcap/pcapng magic-byte validation, hashing,
   atomic promotion, scan scoping, and path-traversal guards. These cover the
   security- and correctness-critical building blocks without a database.
2. Text-contract assertions for the Study-Web-owned orchestration and schema
   that cannot be exercised here (no fastapi/psql): the generic raw-file path
   must keep ignoring WLC sessions, the shared parser executor must be reused,
   the session-artifact table and ingest endpoints must exist, and the systemd
   timer must drive a thin trigger. This mirrors the repo's existing
   contract-test style in test_vocera_media_qoe.py.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "vocera_media_qoe"))

import vocera_wlc_session_ingest as ingest  # noqa: E402
import vocera_media_qoe_batch as batch  # noqa: E402


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _pcap_bytes(magic: bytes = b"\xd4\xc3\xb2\xa1", size: int = 64) -> bytes:
    return magic + b"\x00" * max(0, size - len(magic))


# ---------------------------------------------------------------------------
# Primitive unit tests
# ---------------------------------------------------------------------------

def test_pcap_magic_detection() -> None:
    for magic in (
        b"\xa1\xb2\xc3\xd4",  # pcap BE microsecond
        b"\xd4\xc3\xb2\xa1",  # pcap LE microsecond
        b"\xa1\xb2\x3c\x4d",  # pcap BE nanosecond
        b"\x4d\x3c\xb2\xa1",  # pcap LE nanosecond
        b"\x0a\x0d\x0d\x0a",  # pcapng Section Header Block
    ):
        require(ingest.looks_like_pcap(magic + b"rest"), f"magic {magic!r} should be accepted")
    for bad in (b"PK\x03\x04", b"\x7fELF", b"%PDF", b"", b"\x00\x00", b"abc"):
        require(not ingest.looks_like_pcap(bad), f"non-capture {bad!r} must be rejected")


def test_sha256_file_matches_known_content() -> None:
    import hashlib

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.pcap"
        content = _pcap_bytes(size=4096)
        path.write_bytes(content)
        require(ingest.sha256_file(path) == hashlib.sha256(content).hexdigest(), "sha256_file must stream the real digest")


def test_growing_upload_is_never_ready() -> None:
    """A file still being SCP-written must not be promoted/parsed."""

    now = datetime(2026, 6, 24, 18, 0, 0, tzinfo=timezone.utc)
    first = {"size_bytes": 100, "mtime_ns": 10}
    grown = {"size_bytes": 250, "mtime_ns": 20}
    # First sighting -> wait.
    require(
        ingest.plan_ingest_decision(prev_signature=None, prev_observed_at=None, current_signature=first, now=now, min_gap_seconds=15)
        == ingest.DECISION_WAIT_NEW,
        "first sighting must wait",
    )
    # Size changed since last poll -> still uploading, wait.
    require(
        ingest.plan_ingest_decision(prev_signature=first, prev_observed_at=now - timedelta(seconds=60), current_signature=grown, now=now, min_gap_seconds=15)
        == ingest.DECISION_WAIT_CHANGED,
        "a changed signature must reset the stability clock",
    )
    # Unchanged but not long enough -> wait.
    require(
        ingest.plan_ingest_decision(prev_signature=grown, prev_observed_at=now - timedelta(seconds=5), current_signature=grown, now=now, min_gap_seconds=15)
        == ingest.DECISION_WAIT_TOO_SOON,
        "an unchanged file must age past the gap before it is ready",
    )
    # Unchanged for long enough -> ready.
    require(
        ingest.plan_ingest_decision(prev_signature=grown, prev_observed_at=now - timedelta(seconds=30), current_signature=grown, now=now, min_gap_seconds=15)
        == ingest.DECISION_READY,
        "a file unchanged past the gap must be ready",
    )


def test_is_stable_with_growing_then_settled_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "u.pcap"
        path.write_bytes(b"a" * 10)

        calls = {"n": 0}

        def grow(_delay: float) -> None:
            calls["n"] += 1
            path.write_bytes(b"a" * (10 + calls["n"] * 10))  # changes between polls

        require(not ingest.is_stable(path, polls=2, delay_seconds=0, sleep=grow), "a growing file is not stable")

        def noop(_delay: float) -> None:
            pass

        require(ingest.is_stable(path, polls=3, delay_seconds=0, sleep=noop), "a settled file is stable")


def test_atomic_move_promotes_and_creates_destination() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        src = root / "incoming" / "s.pcap"
        src.parent.mkdir(parents=True)
        src.write_bytes(_pcap_bytes(size=128))
        before = ingest.sha256_file(src)
        dst = root / "pcaps" / "s.pcap"  # destination dir does not exist yet
        moved = ingest.atomic_move(src, dst)
        require(moved == dst and dst.is_file(), "atomic_move must land the file at the destination")
        require(not src.exists(), "atomic_move must remove the source")
        require(ingest.sha256_file(dst) == before, "atomic_move must preserve content")


def test_iter_incoming_pcaps_scope() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        incoming = root / "studyA" / "sess-1" / "incoming"
        pcaps = root / "studyA" / "sess-1" / "pcaps"
        incoming.mkdir(parents=True)
        pcaps.mkdir(parents=True)
        wanted = incoming / "sess-1.pcap"
        wanted.write_bytes(_pcap_bytes())
        (incoming / "notes.txt").write_text("not a capture")  # wrong extension
        (pcaps / "already.pcap").write_bytes(_pcap_bytes())   # already promoted, must be ignored
        (root / "studyA" / "sess-1" / "cli").mkdir()
        (root / "loose.pcap").write_bytes(_pcap_bytes())       # not in a session package
        found = list(ingest.iter_incoming_pcaps(root))
        require(found == [wanted], f"scanner must yield only incoming/ captures, got {found}")


def test_parse_session_rel_and_promoted_path() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        f = root / "studyA" / "sess-1" / "incoming" / "sess-1.pcap"
        f.parent.mkdir(parents=True)
        f.write_bytes(_pcap_bytes())
        info = ingest.parse_session_rel(root, f)
        require(info == {"study_id": "studyA", "session_id": "sess-1", "subdir": "incoming", "name": "sess-1.pcap"}, f"bad decomposition: {info}")
        promoted = ingest.promoted_path(root, f)
        require(promoted == root / "studyA" / "sess-1" / "pcaps" / "sess-1.pcap", f"bad promoted path: {promoted}")
        # Wrong depth and outside-root are rejected.
        require(ingest.parse_session_rel(root, root / "a" / "b" / "c") is None, "shallow path must be rejected")
        require(ingest.parse_session_rel(root, root.parent / "evil" / "x" / "incoming" / "y.pcap") is None, "outside-root path must be rejected")


def test_artifact_id_is_deterministic_and_scoped() -> None:
    a = ingest.artifact_id_for("sess-1", "wlc_epc", "f.pcap")
    require(a == ingest.artifact_id_for("sess-1", "wlc_epc", "f.pcap"), "artifact id must be deterministic")
    require(a != ingest.artifact_id_for("sess-1", "wlc_epc", "g.pcap"), "different files must differ")
    require(a != ingest.artifact_id_for("sess-2", "wlc_epc", "f.pcap"), "different sessions must differ")
    require(a.startswith("wlcart_"), "artifact id should be namespaced")


def test_is_within_traversal_guard() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "root"
        (root).mkdir()
        require(ingest.is_within(root, root / "a" / "b"), "child path is within root")
        require(not ingest.is_within(root, root.parent), "parent path is not within root")
        require(not ingest.is_within(root, root / ".." / "escape"), "traversal escape is not within root")


def test_batch_publisher_excludes_wlc_dirs() -> None:
    """The generic ICAP batch publisher must never discover WLC packages.

    A promoted session EPC lives under wlc-sessions/<study>/<session>/pcaps/; if
    the recursive batch scanner found it, the one-minute textfile path would
    double-parse it and mislabel a WLC EPC as ordinary ICAP evidence.
    """

    require(batch.DEFAULT_EXCLUDED_SCAN_DIRS == ("wlc-sessions", "wlc-attempts"), "batch must exclude WLC package roots by default")
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "icap").mkdir()
        generic = root / "icap" / "server_span.pcap"
        generic.write_bytes(_pcap_bytes())
        (root / "wlc-sessions" / "studyA" / "sess1" / "pcaps").mkdir(parents=True)
        promoted = root / "wlc-sessions" / "studyA" / "sess1" / "pcaps" / "sess1.pcap"
        promoted.write_bytes(_pcap_bytes())
        (root / "wlc-attempts" / "a1").mkdir(parents=True)
        attempt = root / "wlc-attempts" / "a1" / "x.pcap"
        attempt.write_bytes(_pcap_bytes())

        require(batch.discover_pcaps(root) == [generic], "default discovery must skip wlc-sessions and wlc-attempts")
        require(set(batch.discover_pcaps(root, exclude_dirs=())) == {generic, promoted, attempt}, "empty exclude must discover everything")
        require(batch._parse_exclude_dirs("wlc-sessions, wlc-attempts ") == ("wlc-sessions", "wlc-attempts"), "exclude parsing should trim names")
        require(batch._parse_exclude_dirs(None) == batch.DEFAULT_EXCLUDED_SCAN_DIRS, "missing exclude env should default to WLC dirs")


# ---------------------------------------------------------------------------
# Text-contract assertions for the Study-Web-owned orchestration and schema.
# (No fastapi/psql here, so we assert the wiring is present and real.)
# ---------------------------------------------------------------------------

def test_study_web_ingest_contract() -> None:
    main_text = (ROOT / "tools" / "study_web" / "main.py").read_text(encoding="utf-8")
    # Generic raw-file path must keep WLC session AND attempt packages out.
    require('WLC_MANAGED_SCAN_DIRS = ("wlc-sessions", "wlc-attempts")' in main_text, "Study Web must isolate both WLC package roots")
    require("def media_path_under_wlc_managed" in main_text, "Study Web should detect WLC-managed paths")
    require(
        main_text.count("if media_path_under_wlc_managed(resolved):") >= 2,
        "both the raw-file validator and the raw scanner must skip WLC-managed paths",
    )
    # Shared parser executor reused by both the endpoint and the ingest path.
    require("def media_run_capture_parse(" in main_text, "Study Web should extract a shared parser executor")
    require("def media_register_capture_record(" in main_text, "Study Web should extract a shared capture registrar")
    require("return media_run_capture_parse(" in main_text, "the execute endpoint should delegate to the shared parser executor")
    require("media_run_capture_parse(capture_id, study_id, validated" in main_text, "WLC ingest must reuse the shared executor")
    # Session-EPC ingest pipeline and endpoints.
    require('capture_point="wlc_epc"' in main_text, "WLC ingest must register captures as wlc_epc")
    require('@app.post("/api/media-qoe/wlc/sessions/ingest-scan")' in main_text, "Study Web should expose the ingest-scan trigger")
    require('@app.get("/api/media-qoe/wlc/sessions/{session_id}/artifacts")' in main_text, "Study Web should expose session artifact status")
    require("def media_wlc_validate_session_capture(" in main_text, "Study Web should validate session-package captures separately")
    require("wlc_ingest.atomic_move(" in main_text, "ingest must atomically promote incoming/ into pcaps/")
    require("wlc_ingest.looks_like_pcap(" in main_text, "ingest must validate capture containers before import")
    # Hardening: the scan trigger is localhost-only.
    require("def media_require_local_request(" in main_text, "the ingest-scan trigger must enforce local-only callers")
    require("media_require_local_request(request)" in main_text, "the ingest-scan endpoint must call the local-only guard")
    require('"127.0.0.1", "::1"' in main_text, "the local guard must allow only loopback callers")
    # Hardening: stranded post-promotion artifacts are retried automatically.
    require("def media_wlc_retry_promoted_artifacts(" in main_text, "ingest must auto-retry artifacts stranded after promotion")
    require("retried = media_wlc_retry_promoted_artifacts(" in main_text, "the scan must run the retry pass")
    require("ingest_state in ('imported', 'failed')" in main_text, "retry must target imported/failed artifacts with a promoted path")
    # Capture-name collision protection for non-terminal sessions.
    require("is already in use by active session" in main_text, "Study Web must reject reuse of an active capture name")
    require("session_state not in ('imported', 'aborted')" in main_text, "capture-name reuse check must scope to non-terminal sessions")
    # Stays password-free and parser-safe.
    require("sshpass" not in main_text and "collector_scp_password" not in main_text, "ingest must not introduce SCP credentials")


def test_session_artifact_schema_contract() -> None:
    schema = (ROOT / "sql" / "vocera_media_qoe_schema.sql").read_text(encoding="utf-8")
    require("create table if not exists vocera_media_session_artifacts" in schema, "missing session-artifact table")
    require("capture_session_id text not null references vocera_media_capture_sessions(session_id) on delete cascade" in schema, "artifacts must belong to a capture session")
    require("capture_id text references vocera_media_captures(capture_id) on delete set null" in schema, "artifacts should link to the registered capture")
    for kind in ("wlc_epc", "wlc_terminal_output", "wlc_terminal_timing", "wlc_transcript"):
        require(kind in schema, f"artifact_kind {kind} must be allowed")
    for state in ("waiting_for_export", "upload_detected", "validating", "imported", "parsing", "parsed", "failed", "quarantined"):
        require(state in schema, f"ingest_state {state} must be allowed")
    require("uq_vocera_media_session_artifacts_session_sha" in schema, "duplicate content imports must be guarded for idempotency")


def _env_int(text: str, key: str) -> int:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(f"Environment={key}="):
            return int(line.split("=", 2)[2].strip())
        if line.startswith(f"{key}="):
            return int(line.split("=", 1)[1].strip())
    raise AssertionError(f"{key} not found")


def test_systemd_and_trigger_contract() -> None:
    service = (ROOT / "systemd" / "vocera-media-qoe-wlc-session-ingest.service").read_text(encoding="utf-8")
    timer = (ROOT / "systemd" / "vocera-media-qoe-wlc-session-ingest.timer").read_text(encoding="utf-8")
    script = (ROOT / "scripts" / "run_vocera_wlc_session_ingest.sh").read_text(encoding="utf-8")
    study_web = (ROOT / "systemd" / "vocera-rf-validation-study-web.service").read_text(encoding="utf-8")
    require("Type=oneshot" in service, "ingest service should be a oneshot trigger")
    require("run_vocera_wlc_session_ingest.sh" in service, "ingest service should run the trigger script")
    require("OnUnitActiveSec=1min" in timer, "ingest timer should fire about once a minute")
    require("ingest-scan" in script, "trigger script should poke the ingest-scan endpoint")
    require("sshpass" not in script, "trigger must not use sshpass")

    # Timeout ordering: systemd TimeoutStartSec > curl max-time > parser timeout,
    # so a valid large-EPC parse is never killed mid-flight.
    timeout_start = _env_int(service, "TimeoutStartSec")
    ingest_timeout = _env_int(service, "STUDY_WEB_INGEST_TIMEOUT")
    parse_timeout = _env_int(study_web, "STUDY_WEB_MEDIA_QOE_PARSE_TIMEOUT_SECONDS")
    require(
        timeout_start > ingest_timeout > parse_timeout,
        f"timeout ordering must hold: TimeoutStartSec({timeout_start}) > ingest({ingest_timeout}) > parser({parse_timeout})",
    )
    require('STUDY_WEB_INGEST_TIMEOUT:-600' in script, "trigger curl default should match the aligned ingest timeout")


def test_isolation_and_hardening_contract() -> None:
    textfile_script = (ROOT / "scripts" / "run_vocera_media_qoe_textfile.sh").read_text(encoding="utf-8")
    textfile_service = (ROOT / "systemd" / "vocera-media-qoe-textfile.service").read_text(encoding="utf-8")
    config_text = (ROOT / "config" / "vocera-media-qoe.yaml").read_text(encoding="utf-8")
    main_text = (ROOT / "tools" / "study_web" / "main.py").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    media_page = (ROOT / "web" / "study-ui" / "src" / "pages" / "MediaQoeStudy.tsx").read_text(encoding="utf-8")
    # The generic publisher must receive (and pass) the WLC exclusion list.
    require("--exclude-dirs" in textfile_script, "textfile wrapper must pass --exclude-dirs to the batch publisher")
    require("VOCERA_MEDIA_QOE_BATCH_EXCLUDE_DIRS=wlc-sessions,wlc-attempts" in textfile_service, "textfile service must set the WLC exclusion env")
    # Capture name is blank by default; the server generates a unique one.
    require('capture_name: ""' in config_text, "config capture_name must be blank so a unique name is generated")
    require('"capture_name": wlc.get("capture_name") or ""' in main_text, "Study Web defaults must not prefill a static capture name")
    require("WLC_CAPTURE_NAME ?=\n" in makefile or "WLC_CAPTURE_NAME ?= \n" in makefile, "Makefile WLC capture name must default blank")
    require("VOCERA_CAPTURE" not in makefile, "Makefile must not default to a static VOCERA_CAPTURE name")
    require("$(if $(strip $(WLC_CAPTURE_NAME)),--capture-name" in makefile, "Makefile must only pass --capture-name when set")
    # Generic raw-file imports use a neutral capture point, not ICAP.
    require("capture_point: 'Imported PCAP'" in media_page, "manual raw-file imports should register as Imported PCAP")
    require("capture_point: 'ICAP'" not in media_page, "manual raw-file imports must not be mislabeled as ICAP")


def test_ingest_installer_contract() -> None:
    installer = ROOT / "scripts" / "install_vocera_wlc_session_ingest.sh"
    require(installer.is_file(), "missing WLC session-ingest installer script")
    require(installer.stat().st_mode & 0o111, "installer script should be executable")
    text = installer.read_text(encoding="utf-8")
    require('if [[ "$EUID" -ne 0 ]]; then' in text, "installer must require root")
    require("/etc/systemd/system/$SERVICE" in text and "/etc/systemd/system/$TIMER" in text, "installer must install both units into /etc/systemd/system")
    require("SERVICE=vocera-media-qoe-wlc-session-ingest.service" in text, "installer must target the ingest service unit")
    require("TIMER=vocera-media-qoe-wlc-session-ingest.timer" in text, "installer must target the ingest timer unit")
    require("DEFAULT_FILE=/etc/default/vocera-media-qoe-wlc-session-ingest" in text, "installer must manage the EnvironmentFile")
    require('if [[ ! -f "$DEFAULT_FILE" ]]; then' in text, "installer must create the EnvironmentFile only when absent")
    require("systemctl daemon-reload" in text, "installer must reload systemd")
    require('systemctl enable --now "$TIMER"' in text, "installer must enable and start the timer")
    for key in ("STUDY_WEB_INGEST_HOST", "STUDY_WEB_INGEST_PORT", "STUDY_WEB_INGEST_TIMEOUT"):
        require(key in text, f"installer EnvironmentFile must expose {key}")
    require("sshpass" not in text, "installer must not introduce SCP credentials")

    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    require("vocera-media-qoe-wlc-session-ingest-install:" in makefile, "Makefile must expose the ingest install target")
    require("install_vocera_wlc_session_ingest.sh" in makefile, "Makefile target must run the installer script")


def main() -> int:
    test_pcap_magic_detection()
    test_sha256_file_matches_known_content()
    test_growing_upload_is_never_ready()
    test_is_stable_with_growing_then_settled_file()
    test_atomic_move_promotes_and_creates_destination()
    test_iter_incoming_pcaps_scope()
    test_parse_session_rel_and_promoted_path()
    test_artifact_id_is_deterministic_and_scoped()
    test_is_within_traversal_guard()
    test_batch_publisher_excludes_wlc_dirs()
    test_study_web_ingest_contract()
    test_session_artifact_schema_contract()
    test_systemd_and_trigger_contract()
    test_isolation_and_hardening_contract()
    test_ingest_installer_contract()
    print("OK: WLC capture-session ingest tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
