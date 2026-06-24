#!/usr/bin/env python3
"""Emit/load PostgreSQL history for Vocera media QoE capture results."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable


ANALYZER_CACHE_VERSION = 6


def _literal(value: Any) -> str:
    """Render a Python scalar as a PostgreSQL SQL literal."""
    if value is None or value == "":
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


def _timestamptz(seconds: Any) -> str:
    """Render epoch seconds as a PostgreSQL timestamptz expression."""
    if seconds in (None, ""):
        return "null"
    return f"to_timestamp({float(seconds)})"


def _mtime_timestamptz(payload: dict[str, Any]) -> str:
    """Render source mtime_ns as a PostgreSQL timestamptz expression."""
    mtime_ns = _source_state(payload).get("mtime_ns")
    if mtime_ns in (None, ""):
        return "null"
    return f"to_timestamp({float(mtime_ns) / 1_000_000_000.0})"


def _capture_status(payload: dict[str, Any]) -> str:
    """Return the workflow status implied by the parser result."""
    return "complete" if bool(payload.get("parse_success")) else "failed"


def _insert(table: str, columns: list[str], values: list[str]) -> str:
    """Build one insert statement for the offline media history importer."""
    return f"insert into {table} ({', '.join(columns)}) values ({', '.join(values)});"


def _upsert(table: str, columns: list[str], values: list[str], conflict_columns: list[str]) -> str:
    """Build one insert/update statement for idempotent history imports."""
    conflict = ", ".join(conflict_columns)
    updates = [
        f"{column} = excluded.{column}"
        for column in columns
        if column not in set(conflict_columns)
    ]
    return (
        f"insert into {table} ({', '.join(columns)}) values ({', '.join(values)}) "
        f"on conflict ({conflict}) do update set {', '.join(updates)};"
    )


def _source_state(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the source_pcap block from a parsed capture payload."""
    state = payload.get("source_pcap")
    return state if isinstance(state, dict) else {}


def _dnac_capture(state: dict[str, Any]) -> dict[str, Any]:
    """Return Catalyst Center capture metadata from source state."""
    metadata = state.get("dnac_metadata")
    if not isinstance(metadata, dict):
        return {}
    capture = metadata.get("capture")
    return capture if isinstance(capture, dict) else {}


def _analyzer_config(state: dict[str, Any]) -> dict[str, Any]:
    """Return analyzer config embedded in the source state."""
    config = state.get("analyzer_config")
    return config if isinstance(config, dict) else {}


def _capture_id(payload: dict[str, Any]) -> str:
    """Create a stable capture id from source path, size, and mtime."""
    state = _source_state(payload)
    identity = {
        "path": state.get("path"),
        "size_bytes": state.get("size_bytes"),
        "mtime_ns": state.get("mtime_ns"),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()[:24]


def _source_sha256(payload: dict[str, Any]) -> str:
    """Create a stable source identity hash for duplicate import detection."""
    state = _source_state(payload)
    identity = {
        "path": state.get("path"),
        "size_bytes": state.get("size_bytes"),
        "mtime_ns": state.get("mtime_ns"),
    }
    return hashlib.sha256(json.dumps(identity, sort_keys=True).encode("utf-8")).hexdigest()


def _current_payload(path: Path) -> dict[str, Any] | None:
    """Load a cached capture only if the source file still matches it."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    state = _source_state(payload)
    source_path = state.get("path")
    if not source_path:
        return None
    pcap = Path(str(source_path))
    if not pcap.is_file():
        return None
    stat = pcap.stat()
    if state.get("analyzer_cache_version") != ANALYZER_CACHE_VERSION:
        return None
    if state.get("size_bytes") != stat.st_size or state.get("mtime_ns") != stat.st_mtime_ns:
        return None
    return payload


def load_current_payloads(parsed_dir: str | Path) -> list[dict[str, Any]]:
    """Load every current parsed-capture payload from a cache directory."""
    root = Path(parsed_dir)
    if not root.is_dir():
        return []
    payloads = [
        payload
        for path in sorted(root.glob("*.json"))
        if (payload := _current_payload(path)) is not None
    ]
    return sorted(payloads, key=lambda item: (_source_state(item).get("mtime_ns") or 0, _source_state(item).get("path") or ""))


def _first_stream_value(payload: dict[str, Any], key: str) -> Any:
    """Return the first non-empty stream value for a label/config fallback."""
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return None
    for item in streams:
        if isinstance(item, dict) and item.get(key) not in (None, ""):
            return item.get(key)
    return None


def _capture_time_seconds(payload: dict[str, Any]) -> float | None:
    """Pick the best available capture timestamp for history samples."""
    value = payload.get("last_capture_timestamp_seconds")
    if value not in (None, ""):
        return float(value)
    capture = _dnac_capture(_source_state(payload))
    for key in ("fileCreationTimestamp", "lastUpdatedTimestamp"):
        raw = capture.get(key)
        if raw not in (None, ""):
            return float(raw) / 1000.0
    mtime_ns = _source_state(payload).get("mtime_ns")
    return (float(mtime_ns) / 1_000_000_000.0) if mtime_ns not in (None, "") else None


def _capture_insert(payload: dict[str, Any], *, study_id: str | None = None) -> str:
    """Render one vocera_media_captures insert statement."""
    state = _source_state(payload)
    columns = [
        "capture_id",
        "source_path",
        "source_name",
        "source_size_bytes",
        "expected_size_bytes",
        "source_sha256",
        "source_mtime",
        "source_mtime_ns",
        "capture_time",
        "parsed_at",
        "site",
        "capture_point",
        "capture_status",
        "parse_success",
        "parse_error",
        "packets_read",
        "udp_packets_seen",
        "stream_count",
        "raw_metadata",
    ]
    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    values = [
        _literal(_capture_id(payload)),
        _literal(state.get("path")),
        _literal(state.get("name")),
        _literal(state.get("size_bytes")),
        _literal(state.get("expected_size_bytes")),
        _literal(_source_sha256(payload)),
        _mtime_timestamptz(payload),
        _literal(state.get("mtime_ns")),
        _timestamptz(_capture_time_seconds(payload)),
        _timestamptz(payload.get("parsed_at_seconds")),
        _literal(_first_stream_value(payload, "site") or _analyzer_config(state).get("site") or "unknown"),
        _literal(_first_stream_value(payload, "capture_point") or _analyzer_config(state).get("capture_point") or "unknown"),
        _literal(_capture_status(payload)),
        _literal(bool(payload.get("parse_success"))),
        _literal(payload.get("error")),
        _literal(payload.get("packets_read")),
        _literal(payload.get("udp_packets_seen")),
        _literal(len(streams)),
        _jsonb({"source_pcap": state}),
    ]
    if study_id:
        columns.insert(1, "study_id")
        values.insert(1, _literal(study_id))
    return _upsert("vocera_media_captures", columns, values, ["capture_id"])


def _stream_inserts(payload: dict[str, Any]) -> Iterable[str]:
    """Render stream-sample insert statements for one capture payload."""
    capture_id = _capture_id(payload)
    streams = payload.get("streams")
    if not isinstance(streams, list):
        return []
    columns = [
        "capture_id",
        "stream_id",
        "sample_time",
        "first_seen",
        "last_seen",
        "site",
        "capture_point",
        "server",
        "direction",
        "measurement_mode",
        "src_role",
        "dst_role",
        "device_name",
        "device_role",
        "device_config",
        "peer_device_name",
        "peer_device_role",
        "peer_device_config",
        "src_ip",
        "src_port",
        "dst_ip",
        "dst_port",
        "ssrc",
        "payload_type",
        "dscp",
        "packet_count",
        "byte_count",
        "expected_packets",
        "lost_packets",
        "loss_ratio",
        "duplicate_packets",
        "out_of_order_packets",
        "jitter_ms",
        "interarrival_p50_ms",
        "interarrival_p95_ms",
        "interarrival_max_ms",
        "packet_rate_pps",
        "dscp_mismatch",
        "raw_stream",
    ]
    rows: list[str] = []
    for index, stream in enumerate(streams):
        if not isinstance(stream, dict):
            continue
        stream_id = stream.get("stream_id") or f"stream_{index}"
        values = [
            _literal(capture_id),
            _literal(stream_id),
            _timestamptz(stream.get("last_seen") or _capture_time_seconds(payload)),
            _timestamptz(stream.get("first_seen")),
            _timestamptz(stream.get("last_seen")),
            _literal(stream.get("site") or "unknown"),
            _literal(stream.get("capture_point") or "unknown"),
            _literal(stream.get("server") or "unknown"),
            _literal(stream.get("direction") or "unknown"),
            _literal(stream.get("measurement_mode") or "unknown"),
            _literal(stream.get("src_role") or "unknown"),
            _literal(stream.get("dst_role") or "unknown"),
            _literal(stream.get("device_name") or "unmapped"),
            _literal(stream.get("device_role") or "unmapped"),
            _literal(stream.get("device_config") or "unmapped"),
            _literal(stream.get("peer_device_name") or "unmapped"),
            _literal(stream.get("peer_device_role") or "unmapped"),
            _literal(stream.get("peer_device_config") or "unmapped"),
            _literal(stream.get("src_ip")),
            _literal(stream.get("src_port")),
            _literal(stream.get("dst_ip")),
            _literal(stream.get("dst_port")),
            _literal(stream.get("ssrc")),
            _literal(stream.get("payload_type")),
            _literal(stream.get("dscp")),
            _literal(stream.get("packet_count")),
            _literal(stream.get("byte_count")),
            _literal(stream.get("expected_packets")),
            _literal(stream.get("lost_packets")),
            _literal(stream.get("loss_ratio")),
            _literal(stream.get("duplicate_packets")),
            _literal(stream.get("out_of_order_packets")),
            _literal(stream.get("jitter_ms")),
            _literal(stream.get("interarrival_p50_ms")),
            _literal(stream.get("interarrival_p95_ms")),
            _literal(stream.get("interarrival_max_ms")),
            _literal(stream.get("packet_rate_pps")),
            _literal(bool(stream.get("dscp_mismatch"))),
            _jsonb(stream),
        ]
        rows.append(_insert("vocera_media_stream_samples", columns, values))
    return rows


def emit_sql(*, parsed_dir: str | Path, study_id: str | None = None) -> str:
    """Emit full PostgreSQL import SQL for current parsed captures."""
    payloads = load_current_payloads(parsed_dir)
    lines: list[str] = ["begin;"]
    for payload in payloads:
        lines.append(f"delete from vocera_media_stream_samples where capture_id = {_literal(_capture_id(payload))};")
        lines.append(_capture_insert(payload, study_id=study_id))
        lines.extend(_stream_inserts(payload))
    lines.append("commit;")
    return "\n".join(lines) + "\n"


def install_schema(*, postgres_url: str, schema_sql: Path, views_sql: Path, psql_bin: str = "psql") -> None:
    """Apply the media QoE schema and views atomically through psql."""

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sql",
        prefix="vocera_media_qoe_install_",
        delete=False,
    ) as combined:
        combined.write(schema_sql.read_text(encoding="utf-8"))
        combined.write("\n\n")
        combined.write(views_sql.read_text(encoding="utf-8"))
        combined_path = Path(combined.name)

    try:
        subprocess.run(
            [
                psql_bin,
                postgres_url,
                "-v",
                "ON_ERROR_STOP=1",
                "--single-transaction",
                "-f",
                str(combined_path),
            ],
            check=True,
        )
    finally:
        combined_path.unlink(missing_ok=True)

def load_sql(*, postgres_url: str, sql_path: Path, psql_bin: str = "psql") -> None:
    """Load generated media QoE import SQL through psql."""
    subprocess.run(
        [psql_bin, postgres_url, "-v", "ON_ERROR_STOP=1", "-f", str(sql_path)],
        check=True,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for schema install and SQL emission."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    emit = subparsers.add_parser("emit-sql", help="Emit PostgreSQL import SQL from cached capture parses")
    emit.add_argument("--parsed-dir", default="data/vocera-media-qoe/out/captures")
    emit.add_argument("--sql-out", required=True)
    emit.add_argument("--study-id", default=None)

    install = subparsers.add_parser("install-db", help="Apply PostgreSQL schema and views")
    install.add_argument("--postgres-url", required=True)
    install.add_argument("--psql-bin", default="psql")
    install.add_argument("--schema-sql", default="sql/vocera_media_qoe_schema.sql")
    install.add_argument("--views-sql", default="sql/vocera_media_qoe_views.sql")

    load = subparsers.add_parser("load-db", help="Load an emitted PostgreSQL import SQL file")
    load.add_argument("--postgres-url", required=True)
    load.add_argument("--sql-out", required=True)
    load.add_argument("--psql-bin", default="psql")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for media QoE SQL helper operations."""
    args = parse_args(argv)
    if args.command == "emit-sql":
        out = Path(args.sql_out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(emit_sql(parsed_dir=args.parsed_dir, study_id=args.study_id), encoding="utf-8")
        print(f"Wrote PostgreSQL import SQL to {out}")
        return 0
    if args.command == "install-db":
        install_schema(
            postgres_url=args.postgres_url,
            schema_sql=Path(args.schema_sql),
            views_sql=Path(args.views_sql),
            psql_bin=args.psql_bin,
        )
        print("Installed Vocera media QoE PostgreSQL schema and views")
        return 0
    if args.command == "load-db":
        load_sql(postgres_url=args.postgres_url, sql_path=Path(args.sql_out), psql_bin=args.psql_bin)
        print(f"Loaded Vocera media QoE PostgreSQL import SQL from {args.sql_out}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
