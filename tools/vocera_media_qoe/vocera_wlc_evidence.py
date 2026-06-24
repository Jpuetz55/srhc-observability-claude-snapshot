#!/usr/bin/env python3
"""Validate and summarize manual WLC evidence packages for Vocera media QoE."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from pathlib import Path
from typing import Any

import vocera_wlc_cli as wlc_cli


AUDIO_RESULTS = {"heard", "missed", "partial", "choppy", "unknown", "not_tested"}
PCAP_SUFFIXES = {".pcap", ".cap", ".pcapng"}


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object from disk."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    """Write a stable JSON document."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o644)


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of a file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _literal(value: Any) -> str:
    """Render a scalar as a PostgreSQL literal."""

    if value in (None, ""):
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _jsonb(value: Any) -> str:
    """Render a JSON-serializable value as a PostgreSQL jsonb literal."""

    return _literal(json.dumps(value or {}, sort_keys=True)) + "::jsonb"


def _timestamptz(value: Any) -> str:
    """Render an ISO-ish timestamp string as timestamptz."""

    if value in (None, ""):
        return "null"
    return _literal(value) + "::timestamptz"


def _upsert(table: str, columns: list[str], values: list[str], conflict_columns: list[str]) -> str:
    """Build an upsert statement."""

    updates = [
        f"{column} = excluded.{column}"
        for column in columns
        if column not in set(conflict_columns)
    ]
    return (
        f"insert into {table} ({', '.join(columns)}) values ({', '.join(values)}) "
        f"on conflict ({', '.join(conflict_columns)}) do update set {', '.join(updates)};"
    )


def pcap_summary(path: Path) -> dict[str, Any]:
    """Return structural PCAP details without decoding packet payloads."""

    size = path.stat().st_size
    result: dict[str, Any] = {
        "format": "unknown",
        "size_bytes": size,
        "valid_container": False,
        "linktype": None,
        "packet_records_possible": False,
        "evidence_mode": "unsupported_or_inconclusive",
    }
    if size < 4:
        return result
    header = path.read_bytes()[:24]
    magic = header[:4]
    if magic in {b"\xd4\xc3\xb2\xa1", b"M<\xb2\xa1"} and len(header) >= 24:
        result["format"] = "pcap"
        result["valid_container"] = True
        result["linktype"] = int.from_bytes(header[20:24], "little")
        result["packet_records_possible"] = size > 24
    elif magic in {b"\xa1\xb2\xc3\xd4", b"\xa1\xb2<\x4d"} and len(header) >= 24:
        result["format"] = "pcap"
        result["valid_container"] = True
        result["linktype"] = int.from_bytes(header[20:24], "big")
        result["packet_records_possible"] = size > 24
    elif magic == b"\x0a\x0d\x0d\x0a":
        result["format"] = "pcapng"
        result["valid_container"] = True
        result["packet_records_possible"] = size > 28
    if result["valid_container"]:
        result["evidence_mode"] = "capture_container_valid_payload_not_decoded"
    return result


def _artifact_id(attempt_id: str, path: str, artifact_type: str) -> str:
    """Create a stable artifact identifier."""

    raw = json.dumps({"attempt_id": attempt_id, "path": path, "type": artifact_type}, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _load_manifest(attempt_dir: Path) -> tuple[dict[str, Any], list[str]]:
    """Load and minimally validate the attempt manifest."""

    errors: list[str] = []
    manifest_path = attempt_dir / "manifest.json"
    if not manifest_path.is_file():
        return {}, [f"missing {manifest_path.name}"]
    try:
        manifest = load_json(manifest_path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, [f"invalid manifest.json: {exc}"]
    for key in ("attempt_id", "study_id", "wlc_name", "sender", "receiver", "artifacts"):
        if key not in manifest:
            errors.append(f"manifest missing {key}")
    if not isinstance(manifest.get("artifacts"), list):
        errors.append("manifest artifacts must be a list")
    return manifest, errors


def _load_observation(attempt_dir: Path, attempt_id: str | None) -> tuple[dict[str, Any], list[str]]:
    """Load and validate the human observation template."""

    path = attempt_dir / "operator-observation.json"
    if not path.is_file():
        return {}, [f"missing {path.name}"]
    try:
        observation = load_json(path)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return {}, [f"invalid operator-observation.json: {exc}"]
    errors: list[str] = []
    if attempt_id and observation.get("attempt_id") not in (attempt_id, None, ""):
        errors.append("operator observation attempt_id does not match manifest")
    if observation.get("audio_result") not in AUDIO_RESULTS:
        errors.append("operator observation audio_result is not allowed")
    return observation, errors


def _artifact_rows(attempt_dir: Path, manifest: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Return artifact validation rows, warnings, and errors."""

    attempt_id = str(manifest.get("attempt_id") or "unknown")
    rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    errors: list[str] = []
    artifacts = manifest.get("artifacts") if isinstance(manifest.get("artifacts"), list) else []
    for item in artifacts:
        if not isinstance(item, dict):
            warnings.append("manifest contains a non-object artifact entry")
            continue
        rel_path = str(item.get("path") or "")
        artifact_type = str(item.get("type") or "unknown")
        artifact_path = attempt_dir / rel_path
        exists = artifact_path.is_file()
        row: dict[str, Any] = {
            "artifact_id": _artifact_id(attempt_id, rel_path, artifact_type),
            "attempt_id": attempt_id,
            "artifact_type": artifact_type,
            "phase": item.get("phase"),
            "source_path": str(artifact_path),
            "relative_path": rel_path,
            "exists": exists,
            "sha256": sha256_file(artifact_path) if exists else None,
            "size_bytes": artifact_path.stat().st_size if exists else None,
            "capture_id": None,
            "metadata": dict(item),
        }
        if artifact_path.suffix.lower() in PCAP_SUFFIXES and exists:
            row["pcap_summary"] = pcap_summary(artifact_path)
        rows.append(row)
        if not exists:
            errors.append(f"missing artifact {rel_path}")
    return rows, warnings, errors


def _snapshot_rows(attempt_dir: Path, manifest: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse WLC CLI snapshot artifacts."""

    receiver = manifest.get("receiver") if isinstance(manifest.get("receiver"), dict) else {}
    sender = manifest.get("sender") if isinstance(manifest.get("sender"), dict) else {}
    expected = manifest.get("expected") if isinstance(manifest.get("expected"), dict) else {}
    receiver_mac = str(receiver.get("mac") or "")
    sender_mac = str(sender.get("mac") or "")
    vlan = expected.get("vocera_vlan")
    snapshots: list[dict[str, Any]] = []
    for artifact in artifacts:
        if not artifact.get("exists") or not str(artifact.get("artifact_type", "")).startswith("wlc_cli"):
            continue
        path = Path(str(artifact["source_path"]))
        text = path.read_text(encoding="utf-8", errors="replace")
        parsed = wlc_cli.parse_wlc_snapshot(
            text,
            phase=str(artifact.get("phase") or "unknown"),
            receiver_mac=receiver_mac,
            sender_mac=sender_mac,
            expected_vlan=int(vlan) if str(vlan or "").isdigit() else None,
        )
        parsed["snapshot_id"] = artifact["artifact_id"]
        parsed["attempt_id"] = manifest.get("attempt_id")
        parsed["artifact_id"] = artifact["artifact_id"]
        snapshots.append(parsed)
    return snapshots


def _best_snapshot(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Select the during snapshot when present, otherwise the richest snapshot."""

    during = [item for item in snapshots if item.get("phase") == "during"]
    candidates = during or snapshots
    if not candidates:
        return {}
    return max(candidates, key=lambda item: sum(1 for value in item.values() if value not in (None, "", [], {})))


def _observation_id(attempt_id: str, snapshot_id: str, index: int, item: dict[str, Any]) -> str:
    """Create a stable multicast observation ID."""

    raw = json.dumps(
        {
            "attempt_id": attempt_id,
            "snapshot_id": snapshot_id,
            "index": index,
            "evidence_source": item.get("evidence_source"),
            "group": item.get("vocera_group_ip"),
            "mgid": item.get("mgid") or item.get("ap_mgid"),
            "receiver": item.get("receiver_mac"),
        },
        sort_keys=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _multicast_observation_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized multicast observations from parsed snapshots."""

    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    observation = report.get("operator_observation") if isinstance(report.get("operator_observation"), dict) else {}
    receiver = manifest.get("receiver") if isinstance(manifest.get("receiver"), dict) else {}
    attempt_id = str(report.get("attempt_id") or manifest.get("attempt_id") or "")
    capture_session = manifest.get("capture_session") if isinstance(manifest.get("capture_session"), dict) else {}
    capture_session_id = manifest.get("capture_session_id") or manifest.get("session_id") or capture_session.get("session_id")
    rows: list[dict[str, Any]] = []
    for snapshot in report.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        snapshot_id = str(snapshot.get("snapshot_id") or "")
        for index, item in enumerate(snapshot.get("multicast_observations") or []):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            row["observation_id"] = _observation_id(attempt_id, snapshot_id, index, row)
            row["capture_session_id"] = capture_session_id
            row["attempt_id"] = attempt_id
            row["observed_at"] = observation.get("observation_time") or manifest.get("attempt_marked_at") or manifest.get("started_at")
            row["phase"] = row.get("phase") or snapshot.get("phase")
            row["receiver_ip"] = row.get("receiver_ip") or receiver.get("ip")
            row["raw_evidence"] = {
                "snapshot_id": snapshot_id,
                "artifact_id": snapshot.get("artifact_id"),
                "raw_line": row.get("raw_line"),
                "source_snapshot_phase": snapshot.get("phase"),
            }
            rows.append(row)
    return rows


def _finding(finding_type: str, severity: str, confidence: str, message: str, source: str, raw: Any = None) -> dict[str, Any]:
    """Build one machine-generated finding row."""

    return {
        "finding_id": hashlib.sha256(json.dumps([finding_type, message, source], sort_keys=True).encode("utf-8")).hexdigest()[:24],
        "finding_type": finding_type,
        "severity": severity,
        "confidence": confidence,
        "evidence_source": source,
        "message": message,
        "raw_evidence": raw or {},
    }


def compute_verdict(
    *,
    manifest: dict[str, Any],
    observation: dict[str, Any],
    artifacts: list[dict[str, Any]],
    snapshots: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Return a cautious attempt-level verdict and supporting findings."""

    audio_result = str(observation.get("audio_result") or "unknown")
    snapshot = _best_snapshot(snapshots)
    group = snapshot.get("vocera_group")
    member = snapshot.get("c1000_group_member")
    pcap_valid = any(
        artifact.get("pcap_summary", {}).get("valid_container")
        for artifact in artifacts
        if artifact.get("exists")
    )
    findings: list[dict[str, Any]] = []
    if member is False:
        findings.append(_finding("membership_missing", "critical", "high", "C1000 was not listed in the parsed multicast client list.", "wlc_cli", snapshot))
    elif member is True:
        findings.append(_finding("membership_present", "info", "medium", "C1000 was listed in the parsed multicast client list.", "wlc_cli", snapshot))
    if pcap_valid:
        findings.append(_finding("capture_container_valid", "info", "low", "At least one PCAP container is structurally valid; payload decode is a later phase.", "pcap", {}))

    verdict = {
        "verdict": "inconclusive",
        "verdict_confidence": "low",
        "verdict_explanation": "Evidence is incomplete or not yet decoded enough for a stronger conclusion.",
    }
    if audio_result == "heard":
        verdict = {
            "verdict": "baseline_success",
            "verdict_confidence": "medium",
            "verdict_explanation": "Operator reported that audio was heard. Network evidence remains available for baseline comparison.",
        }
    elif audio_result == "missed" and group and member is False:
        verdict = {
            "verdict": "membership_failure",
            "verdict_confidence": "high",
            "verdict_explanation": "C1000 was not confirmed as a receiver for the active Vocera multicast group.",
        }
    elif audio_result == "missed" and not group:
        verdict = {
            "verdict": "inconclusive",
            "verdict_confidence": "low",
            "verdict_explanation": "Audio was missed, but the active Vocera multicast group was not identified in parsed WLC evidence.",
        }
    elif audio_result in {"partial", "choppy"} and pcap_valid:
        verdict = {
            "verdict": "media_degraded",
            "verdict_confidence": "low",
            "verdict_explanation": "Operator reported degraded audio and a PCAP container is present; RTP/CAPWAP decode is required for packet-quality claims.",
        }
    elif audio_result == "missed" and member is True and pcap_valid:
        verdict = {
            "verdict": "inconclusive",
            "verdict_confidence": "medium",
            "verdict_explanation": "Membership and a PCAP container are present, but this phase has not decoded forwarding or media payload evidence.",
        }
    return verdict, findings


def write_pcap_sidecars(attempt_dir: Path, manifest: dict[str, Any], artifacts: list[dict[str, Any]], observation: dict[str, Any]) -> list[Path]:
    """Write capture metadata sidecars beside PCAP artifacts."""

    written: list[Path] = []
    for artifact in artifacts:
        if not artifact.get("exists"):
            continue
        path = Path(str(artifact["source_path"]))
        if path.suffix.lower() not in PCAP_SUFFIXES:
            continue
        payload = {
            "capture_source": artifact.get("artifact_type"),
            "capture_method": manifest.get("capture_method", "manual_wlc_cli"),
            "capture_point": artifact.get("metadata", {}).get("capture_point"),
            "capture_phase": artifact.get("phase"),
            "capture_session_id": manifest.get("capture_session_id") or manifest.get("session_id"),
            "attempt_id": manifest.get("attempt_id"),
            "study_id": manifest.get("study_id"),
            "site": manifest.get("site"),
            "wlc_name": manifest.get("wlc_name"),
            "operator": observation.get("operator"),
            "audio_result": observation.get("audio_result"),
            "alert_result": observation.get("c1000_received_alert"),
            "sender": manifest.get("sender"),
            "receiver": manifest.get("receiver"),
            "expected": manifest.get("expected"),
            "artifact": artifact,
            "created_at_seconds": int(time.time()),
        }
        sidecar = path.with_suffix(path.suffix + ".json")
        write_json(sidecar, payload)
        written.append(sidecar)
    return written


def build_report(attempt_dir: Path, *, write_sidecars: bool = False) -> dict[str, Any]:
    """Validate one attempt directory and return an evidence report."""

    manifest, manifest_errors = _load_manifest(attempt_dir)
    attempt_id = str(manifest.get("attempt_id") or attempt_dir.name)
    observation, observation_errors = _load_observation(attempt_dir, attempt_id)
    artifacts, artifact_warnings, artifact_errors = _artifact_rows(attempt_dir, manifest) if manifest else ([], [], [])
    snapshots = _snapshot_rows(attempt_dir, manifest, artifacts) if manifest else []
    verdict, findings = compute_verdict(manifest=manifest, observation=observation, artifacts=artifacts, snapshots=snapshots)
    sidecars = write_pcap_sidecars(attempt_dir, manifest, artifacts, observation) if write_sidecars and manifest else []
    errors = manifest_errors + observation_errors + artifact_errors
    report = {
        "ok": not errors,
        "attempt_dir": str(attempt_dir),
        "attempt_id": attempt_id,
        "study_id": manifest.get("study_id"),
        "errors": errors,
        "warnings": artifact_warnings,
        "manifest": manifest,
        "operator_observation": observation,
        "artifacts": artifacts,
        "snapshots": snapshots,
        "verdict": verdict,
        "findings": findings,
        "sidecars_written": [str(path) for path in sidecars],
        "generated_at_seconds": int(time.time()),
    }
    return report


def emit_attempt_sql(report: dict[str, Any]) -> str:
    """Emit PostgreSQL SQL for one attempt report."""

    manifest = report.get("manifest") if isinstance(report.get("manifest"), dict) else {}
    observation = report.get("operator_observation") if isinstance(report.get("operator_observation"), dict) else {}
    verdict = report.get("verdict") if isinstance(report.get("verdict"), dict) else {}
    sender = manifest.get("sender") if isinstance(manifest.get("sender"), dict) else {}
    receiver = manifest.get("receiver") if isinstance(manifest.get("receiver"), dict) else {}
    expected = manifest.get("expected") if isinstance(manifest.get("expected"), dict) else {}
    capture_session = manifest.get("capture_session") if isinstance(manifest.get("capture_session"), dict) else {}
    capture_session_id = manifest.get("capture_session_id") or manifest.get("session_id") or capture_session.get("session_id")
    columns = [
        "attempt_id",
        "study_id",
        "capture_session_id",
        "site",
        "wlc_name",
        "started_at",
        "ended_at",
        "attempt_started_at",
        "attempt_marked_at",
        "attempt_ended_at",
        "sender_name",
        "sender_model",
        "sender_mac",
        "sender_ip",
        "receiver_name",
        "receiver_model",
        "receiver_mac",
        "receiver_ip",
        "vocera_group",
        "dynamic_multicast_ip",
        "dynamic_multicast_mac",
        "multicast_group_detected_at",
        "configured_vocera_vlan",
        "resolved_group_ip",
        "resolved_group_vlan",
        "resolved_mgid",
        "vlan_selection_source",
        "vlan_context_state",
        "vocera_vlan",
        "operator_name",
        "audio_result",
        "alert_result",
        "alert_received",
        "audio_received",
        "sender_confirmed",
        "receiver_group_member",
        "failure_marker_type",
        "capture_window_before_seconds",
        "capture_window_after_seconds",
        "operator_notes",
        "verdict",
        "verdict_confidence",
        "verdict_explanation",
        "raw_context",
        "updated_at",
    ]
    best_snapshot = _best_snapshot(report.get("snapshots", []))
    values = [
        _literal(report.get("attempt_id")),
        _literal(report.get("study_id")),
        _literal(capture_session_id),
        _literal(manifest.get("site")),
        _literal(manifest.get("wlc_name")),
        _timestamptz(manifest.get("started_at")),
        _timestamptz(manifest.get("ended_at")),
        _timestamptz(manifest.get("attempt_started_at") or manifest.get("started_at")),
        _timestamptz(observation.get("observation_time") or manifest.get("attempt_marked_at")),
        _timestamptz(manifest.get("attempt_ended_at") or manifest.get("ended_at")),
        _literal(sender.get("name")),
        _literal(sender.get("model")),
        _literal(sender.get("mac")),
        _literal(sender.get("ip")),
        _literal(receiver.get("name")),
        _literal(receiver.get("model")),
        _literal(receiver.get("mac")),
        _literal(receiver.get("ip")),
        _literal(best_snapshot.get("vocera_group") or expected.get("multicast_group")),
        _literal(best_snapshot.get("vocera_dynamic_group_ip") or best_snapshot.get("vocera_group") or expected.get("multicast_group")),
        _literal(best_snapshot.get("vocera_dynamic_group_mac")),
        _timestamptz(observation.get("observation_time") or manifest.get("multicast_group_detected_at")),
        _literal(expected.get("configured_vocera_vlan") or expected.get("vocera_vlan")),
        _literal(best_snapshot.get("vocera_dynamic_group_ip") if best_snapshot.get("resolved_group_vlan") else None),
        _literal(best_snapshot.get("resolved_group_vlan")),
        _literal(best_snapshot.get("mgid") if best_snapshot.get("resolved_group_vlan") else None),
        _literal(manifest.get("vlan_selection_source") or "default"),
        _literal(best_snapshot.get("vlan_context_state") or "configured_only"),
        _literal(best_snapshot.get("vocera_vlan") or expected.get("vocera_vlan")),
        _literal(observation.get("operator")),
        _literal(observation.get("audio_result")),
        _literal(observation.get("c1000_received_alert")),
        _literal(observation.get("c1000_received_alert")),
        _literal(observation.get("c1000_received_audio")),
        _literal(best_snapshot.get("vocera_group") is not None),
        _literal(best_snapshot.get("c1000_group_member")),
        _literal(observation.get("audio_result") if observation.get("audio_result") in {"missed", "partial", "choppy"} else None),
        _literal(manifest.get("capture_window_before_seconds") or 30),
        _literal(manifest.get("capture_window_after_seconds") or 30),
        _literal(observation.get("notes")),
        _literal(verdict.get("verdict")),
        _literal(verdict.get("verdict_confidence")),
        _literal(verdict.get("verdict_explanation")),
        _jsonb(report),
        "now()",
    ]
    lines = ["begin;", _upsert("vocera_media_broadcast_attempts", columns, values, ["attempt_id"])]
    attempt_id = str(report.get("attempt_id") or "")
    lines.append(f"delete from vocera_media_attempt_artifacts where attempt_id = {_literal(attempt_id)};")
    for artifact in report.get("artifacts", []):
        if not isinstance(artifact, dict):
            continue
        lines.append(
            "insert into vocera_media_attempt_artifacts "
            "(artifact_id, attempt_id, artifact_type, phase, source_path, sha256, size_bytes, capture_id, ingested_at, metadata) "
            f"values ({_literal(artifact.get('artifact_id'))}, {_literal(attempt_id)}, {_literal(artifact.get('artifact_type'))}, "
            f"{_literal(artifact.get('phase'))}, {_literal(artifact.get('source_path'))}, {_literal(artifact.get('sha256'))}, "
            f"{_literal(artifact.get('size_bytes'))}, {_literal(artifact.get('capture_id'))}, now(), {_jsonb(artifact)});"
        )
    lines.append(f"delete from vocera_media_wlc_snapshots where attempt_id = {_literal(attempt_id)};")
    for snapshot in report.get("snapshots", []):
        if not isinstance(snapshot, dict):
            continue
        lines.append(
            "insert into vocera_media_wlc_snapshots "
            "(snapshot_id, attempt_id, phase, snapshot_time, receiver_ap, receiver_bssid, receiver_channel, receiver_band, "
            "receiver_rssi, receiver_snr, receiver_vlan, sender_client_vlan, sender_multicast_vlan, receiver_client_vlan, "
            "receiver_multicast_vlan, receiver_group_member, receiver_group_status, vocera_group, "
            "vocera_dynamic_group_ip, vocera_dynamic_group_mac, vocera_group_evidence_confidence, vocera_vlan, "
            "configured_vocera_vlan, resolved_group_vlan, group_vlan, vlan_context_state, mgid, "
            "multicast_enabled, capwap_multicast_mode, ap_mom_status, igmp_snooping_enabled, "
            "igmp_querier_enabled, raw_snapshot) "
            f"values ({_literal(snapshot.get('snapshot_id'))}, {_literal(attempt_id)}, {_literal(snapshot.get('phase'))}, "
            f"{_literal(snapshot.get('snapshot_time'))}, {_literal(snapshot.get('receiver_ap'))}, {_literal(snapshot.get('receiver_bssid'))}, "
            f"{_literal(snapshot.get('receiver_channel'))}, {_literal(snapshot.get('receiver_band'))}, {_literal(snapshot.get('receiver_rssi'))}, "
            f"{_literal(snapshot.get('receiver_snr'))}, {_literal(snapshot.get('receiver_vlan'))}, "
            f"{_literal(snapshot.get('sender_client_vlan'))}, {_literal(snapshot.get('sender_multicast_vlan'))}, "
            f"{_literal(snapshot.get('receiver_client_vlan'))}, {_literal(snapshot.get('receiver_multicast_vlan'))}, "
            f"{_literal(snapshot.get('c1000_group_member'))}, "
            f"{_literal(snapshot.get('c1000_member_status'))}, {_literal(snapshot.get('vocera_group'))}, "
            f"{_literal(snapshot.get('vocera_dynamic_group_ip'))}, {_literal(snapshot.get('vocera_dynamic_group_mac'))}, "
            f"{_literal(snapshot.get('vocera_group_evidence_confidence'))}, {_literal(snapshot.get('vocera_vlan'))}, "
            f"{_literal(snapshot.get('configured_vocera_vlan'))}, {_literal(snapshot.get('resolved_group_vlan'))}, "
            f"{_literal(snapshot.get('group_vlan'))}, {_literal(snapshot.get('vlan_context_state'))}, {_literal(snapshot.get('mgid'))}, "
            f"{_literal(snapshot.get('multicast_enabled'))}, {_literal(snapshot.get('capwap_multicast_mode'))}, "
            f"{_literal(snapshot.get('ap_mom_status'))}, {_literal(snapshot.get('igmp_snooping_enabled'))}, {_literal(snapshot.get('igmp_querier_enabled'))}, "
            f"{_literal(snapshot.get('raw_snapshot'))});"
        )
    lines.append(f"delete from vocera_media_multicast_observations where attempt_id = {_literal(attempt_id)};")
    for observation in _multicast_observation_rows(report):
        lines.append(
            "insert into vocera_media_multicast_observations "
            "(observation_id, capture_session_id, attempt_id, observed_at, phase, evidence_source, "
            "vocera_group_ip, vocera_group_mac, vocera_vlan, source_ip, source_mac, igmp_version, mgid, "
            "receiver_mac, receiver_ip, receiver_member, receiver_blocklisted, receiver_membership_mode, "
            "wlc_capwap_group, wlc_capwap_mode, ap_name, ap_mom_status, ap_mgid, ap_delivery_mode, "
            "ap_rx_packets, ap_tx_packets, ap_slot, capture_confidence, raw_evidence, created_at) "
            f"values ({_literal(observation.get('observation_id'))}, {_literal(observation.get('capture_session_id'))}, "
            f"{_literal(observation.get('attempt_id'))}, {_timestamptz(observation.get('observed_at'))}, "
            f"{_literal(observation.get('phase'))}, {_literal(observation.get('evidence_source'))}, "
            f"{_literal(observation.get('vocera_group_ip'))}, {_literal(observation.get('vocera_group_mac'))}, "
            f"{_literal(observation.get('vocera_vlan'))}, {_literal(observation.get('source_ip'))}, "
            f"{_literal(observation.get('source_mac'))}, {_literal(observation.get('igmp_version'))}, "
            f"{_literal(observation.get('mgid'))}, {_literal(observation.get('receiver_mac'))}, "
            f"{_literal(observation.get('receiver_ip'))}, {_literal(observation.get('receiver_member'))}, "
            f"{_literal(observation.get('receiver_blocklisted'))}, {_literal(observation.get('receiver_membership_mode'))}, "
            f"{_literal(observation.get('wlc_capwap_group'))}, {_literal(observation.get('wlc_capwap_mode'))}, "
            f"{_literal(observation.get('ap_name'))}, {_literal(observation.get('ap_mom_status'))}, "
            f"{_literal(observation.get('ap_mgid'))}, {_literal(observation.get('ap_delivery_mode'))}, "
            f"{_literal(observation.get('ap_rx_packets'))}, {_literal(observation.get('ap_tx_packets'))}, "
            f"{_literal(observation.get('ap_slot'))}, {_literal(observation.get('capture_confidence'))}, "
            f"{_jsonb(observation.get('raw_evidence'))}, now());"
        )
    lines.append(f"delete from vocera_media_attempt_findings where attempt_id = {_literal(attempt_id)};")
    for finding in report.get("findings", []):
        if not isinstance(finding, dict):
            continue
        lines.append(
            "insert into vocera_media_attempt_findings "
            "(finding_id, attempt_id, finding_type, severity, confidence, evidence_source, message, raw_evidence, created_at) "
            f"values ({_literal(finding.get('finding_id'))}, {_literal(attempt_id)}, {_literal(finding.get('finding_type'))}, "
            f"{_literal(finding.get('severity'))}, {_literal(finding.get('confidence'))}, {_literal(finding.get('evidence_source'))}, "
            f"{_literal(finding.get('message'))}, {_jsonb(finding.get('raw_evidence'))}, now());"
        )
    lines.append("commit;")
    return "\n".join(lines) + "\n"


def ingest_attempt(
    attempt_dir: Path,
    *,
    report_out: Path | None = None,
    sql_out: Path | None = None,
    postgres_url: str | None = None,
    psql_bin: str = "psql",
    schema_sql: Path = Path("sql/vocera_media_qoe_schema.sql"),
    views_sql: Path = Path("sql/vocera_media_qoe_views.sql"),
) -> dict[str, Any]:
    """Validate, write sidecars/report/SQL, and optionally load PostgreSQL."""

    report = build_report(attempt_dir, write_sidecars=True)
    validation_dir = attempt_dir / "validation"
    report_path = report_out or validation_dir / "ingest-report.json"
    write_json(report_path, report)
    report["report_path"] = str(report_path)
    sql_path = sql_out or validation_dir / "attempt-import.sql"
    sql_path.parent.mkdir(parents=True, exist_ok=True)
    sql_path.write_text(emit_attempt_sql(report), encoding="utf-8")
    sql_path.chmod(0o644)
    report["sql_path"] = str(sql_path)
    if postgres_url:
        for path in (schema_sql, views_sql, sql_path):
            subprocess.run([psql_bin, postgres_url, "-v", "ON_ERROR_STOP=1", "-f", str(path)], check=True)
        report["db_loaded"] = True
    else:
        report["db_loaded"] = False
    write_json(report_path, report)
    return report
