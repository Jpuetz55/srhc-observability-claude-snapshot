#!/usr/bin/env python3
"""Batch publisher for local Vocera media ICAP pcaps."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import vocera_media_qoe as qoe
import vocera_media_qoe_sql as history
from run_archive import create_run_archive


PCAP_SUFFIXES = {".pcap", ".cap", ".pcapng"}


@dataclass
class BatchPublishResult:
    discovered: list[Path] = field(default_factory=list)
    parsed: list[Path] = field(default_factory=list)
    skipped: list[Path] = field(default_factory=list)
    published_pcap: Path | None = None
    published_json: Path | None = None
    published_prom: Path | None = None
    history_sql: Path | None = None
    db_loaded: bool = False
    archive_zip: Path | None = None


def sidecar_metadata(path: Path) -> dict[str, Any] | None:
    """Load repo-owned capture metadata sidecar beside a pcap, when present."""
    sidecar = path.with_suffix(path.suffix + ".json")
    if not sidecar.is_file():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def expected_capture_size(metadata: dict[str, Any] | None) -> int | None:
    """Extract the expected pcap size from Catalyst Center metadata."""
    if not metadata:
        return None
    capture = metadata.get("capture")
    if not isinstance(capture, dict):
        return None
    value = capture.get("fileSize")
    try:
        expected = int(value)
    except (TypeError, ValueError):
        return None
    return expected if expected > 0 else None


def capture_state(path: Path) -> dict[str, Any]:
    """Return the source identity used to decide whether a cache is current."""
    # The cache key is intentionally more than filename. A pcap is current only
    # when its resolved path, size, mtime, sidecar metadata, and analyzer config
    # still match the JSON cache record.
    stat = path.stat()
    metadata = sidecar_metadata(path)
    expected_size = expected_capture_size(metadata)
    return {
        "path": str(path.resolve()),
        "name": path.name,
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "expected_size_bytes": expected_size,
        "size_matches_expected": expected_size is None or stat.st_size == expected_size,
        "capture_metadata": metadata,
        "dnac_metadata": metadata if isinstance(metadata, dict) and "capture" in metadata else None,
        "analyzer_cache_version": qoe.ANALYZER_CACHE_VERSION,
    }


def analyzer_config_state(config: qoe.AnalyzerConfig) -> dict[str, Any]:
    """Serialize analyzer config fields that affect parse output."""
    return {
        "site": config.site,
        "capture_point": config.capture_point,
        "expected_dscp": config.expected_dscp,
        "servers": dict(sorted(config.servers.items())),
        "badge_subnets": [str(subnet) for subnet in config.badge_subnets],
        "devices": {
            ip: {
                "name": device.name,
                "role": device.role,
                "config": device.config,
                "mac": device.mac,
            }
            for ip, device in sorted(config.devices.items())
        },
        "media_ports": [[start, end] for start, end in config.media_ports],
        "payload_clock_rates": {str(key): value for key, value in sorted(config.payload_clock_rates.items())},
        "default_rtp_clock_hz": config.default_rtp_clock_hz,
        "max_capture_future_skew_seconds": config.max_capture_future_skew_seconds,
        "min_rtp_qoe_packets": config.min_rtp_qoe_packets,
        "max_rtp_transit_delta_seconds": config.max_rtp_transit_delta_seconds,
        "strict_rtp_plausibility": config.strict_rtp_plausibility,
        "require_known_rtp_clock_rate": config.require_known_rtp_clock_rate,
        "min_rtp_duration_seconds": config.min_rtp_duration_seconds,
        "max_rtp_interarrival_ms": config.max_rtp_interarrival_ms,
        "max_rtp_jitter_ms": config.max_rtp_jitter_ms,
        "min_rtp_sequence_progression_ratio": config.min_rtp_sequence_progression_ratio,
        "min_rtp_timestamp_progression_ratio": config.min_rtp_timestamp_progression_ratio,
        "max_rtp_timestamp_wallclock_error_ms": config.max_rtp_timestamp_wallclock_error_ms,
        "min_voice_packetization_ms": config.min_voice_packetization_ms,
        "max_voice_packetization_ms": config.max_voice_packetization_ms,
        "max_rtp_loss_ratio_for_plausibility": config.max_rtp_loss_ratio_for_plausibility,
        "max_rtp_duplicate_ratio_for_plausibility": config.max_rtp_duplicate_ratio_for_plausibility,
        "max_rtp_out_of_order_ratio_for_plausibility": config.max_rtp_out_of_order_ratio_for_plausibility,
    }


def discover_pcaps(raw_dir: Path) -> list[Path]:
    """Return supported pcap files in deterministic oldest-to-newest order."""
    if not raw_dir.is_dir():
        return []
    files = [
        path
        for path in raw_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in PCAP_SUFFIXES
    ]
    return sorted(files, key=lambda path: (path.stat().st_mtime_ns, str(path)))


def _safe_name(value: str) -> str:
    """Convert a capture filename to a safe cache filename stem."""
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
    return safe[:96] or "capture"


def _cache_base(parsed_dir: Path, pcap: Path) -> Path:
    """Return the cache base path for a source pcap."""
    # Include a path digest so two captures with the same basename from
    # different upload directories cannot overwrite one another's cache files.
    digest = hashlib.sha256(str(pcap.resolve()).encode("utf-8")).hexdigest()[:16]
    return parsed_dir / f"{_safe_name(pcap.name)}.{digest}"


def cache_paths(parsed_dir: Path, pcap: Path) -> tuple[Path, Path]:
    """Return JSON and Prometheus cache paths for a source pcap."""
    base = _cache_base(parsed_dir, pcap)
    return base.with_suffix(base.suffix + ".json"), base.with_suffix(base.suffix + ".prom")


def cached_current(json_path: Path, prom_path: Path, state: dict[str, Any]) -> bool:
    """Return true when both cache files match the current source state."""
    if not json_path.is_file() or not prom_path.is_file():
        return False
    try:
        payload = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("source_pcap") == state


def _analysis_payload(result: qoe.AnalysisResult, state: dict[str, Any] | None) -> dict[str, Any]:
    """Attach source/cache metadata to a single-capture analysis result."""
    payload = result.to_json()
    payload["source_pcap"] = state
    payload["parsed_at_seconds"] = int(time.time())
    return payload


def write_analysis_outputs(
    *,
    result: qoe.AnalysisResult,
    state: dict[str, Any] | None,
    json_path: Path,
    prom_path: Path,
) -> None:
    """Write one capture's JSON and Prometheus cache artifacts."""
    qoe.write_text(json_path, json.dumps(_analysis_payload(result, state), indent=2, sort_keys=True))
    qoe.write_text(prom_path, qoe.render_prometheus(result))


def parse_capture(
    pcap: Path,
    *,
    config: qoe.AnalyzerConfig,
    json_path: Path,
    prom_path: Path,
    state: dict[str, Any],
) -> qoe.AnalysisResult:
    """Analyze a pcap or emit a structured parse failure result."""
    if state.get("size_matches_expected") is False:
        # Catalyst Center can expose a pcap before the download is complete.
        # Treat a sidecar size mismatch as a parse failure rather than
        # publishing misleading zero-loss/zero-jitter metrics.
        result = qoe.AnalysisResult(
            streams=[],
            packets_read=0,
            udp_packets_seen=0,
            last_capture_timestamp_seconds=None,
            parse_success=0,
            error=(
                "local pcap size does not match Catalyst Center metadata: "
                f"local={state.get('size_bytes')} expected={state.get('expected_size_bytes')}"
            ),
        )
    else:
        try:
            result = qoe.analyze_pcap(pcap, config)
            if result.packets_read == 0:
                result = qoe.AnalysisResult(
                    streams=[],
                    packets_read=0,
                    udp_packets_seen=0,
                    last_capture_timestamp_seconds=None,
                    parse_success=0,
                    error="pcap contains no packet records",
                )
        except Exception as exc:
            result = qoe.AnalysisResult(
                streams=[],
                packets_read=0,
                udp_packets_seen=0,
                last_capture_timestamp_seconds=None,
                parse_success=0,
                error=str(exc),
            )
    write_analysis_outputs(result=result, state=state, json_path=json_path, prom_path=prom_path)
    return result


def write_history_outputs(
    *,
    parsed_dir: Path,
    sql_out: Path | None,
    postgres_url: str | None,
    psql_bin: str,
    schema_sql: Path,
    views_sql: Path,
    study_id: str | None = None,
    install_db: bool = True,
) -> tuple[Path | None, bool]:
    """Emit PostgreSQL history SQL and optionally load it immediately."""
    if sql_out is None and not postgres_url:
        return None, False
    sql = history.emit_sql(parsed_dir=parsed_dir, study_id=study_id)
    target = sql_out or parsed_dir.parent / "vocera_media_qoe_import.sql"
    qoe.write_text(target, sql)
    target.chmod(0o644)
    if postgres_url:
        if install_db:
            history.install_schema(
                postgres_url=postgres_url,
                schema_sql=schema_sql,
                views_sql=views_sql,
                psql_bin=psql_bin,
            )
        history.load_sql(postgres_url=postgres_url, sql_path=target, psql_bin=psql_bin)
        return target, True
    return target, False


def _existing_sidecars(paths: list[Path]) -> list[Path]:
    """Return Catalyst Center sidecar files for archived pcaps."""
    sidecars: list[Path] = []
    for path in paths:
        sidecar = path.with_suffix(path.suffix + ".json")
        if sidecar.is_file() and sidecar not in sidecars:
            sidecars.append(sidecar)
    return sidecars


def _unique_paths(paths: list[Path | None]) -> list[Path]:
    """Preserve path order while removing duplicates and empty values."""
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        if path is None:
            continue
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def archive_batch_run(
    *,
    archive_dir: Path,
    result: BatchPublishResult,
    raw_dir: Path,
    parsed_dir: Path,
    config_path: Path | None,
    prom_out: Path,
    json_out: Path,
    textfile_out: Path | None,
    archive_label: str | None = None,
) -> Path:
    """Archive the ICAP parser inputs, generated artifacts, and run log."""

    archived_pcaps = _unique_paths(result.parsed + ([result.published_pcap] if result.published_pcap else []))
    inputs = _unique_paths(([config_path] if config_path else []) + archived_pcaps + _existing_sidecars(archived_pcaps))
    cache_outputs: list[Path] = []
    for pcap in archived_pcaps:
        json_path, prom_path = cache_paths(parsed_dir, pcap)
        if json_path.is_file():
            cache_outputs.append(json_path)
        if prom_path.is_file():
            cache_outputs.append(prom_path)
    outputs = _unique_paths([json_out, prom_out, textfile_out, result.history_sql] + cache_outputs)
    log_lines = [
        "Vocera media QoE ICAP batch parser run",
        f"raw_dir={raw_dir}",
        f"config={config_path or '<in-memory>'}",
        f"discovered_capture_count={len(result.discovered)}",
        f"parsed_capture_count={len(result.parsed)}",
        f"skipped_capture_count={len(result.skipped)}",
        f"published_pcap={result.published_pcap or '<none>'}",
        f"history_sql={result.history_sql or '<none>'}",
        f"db_loaded={result.db_loaded}",
        "discovered_captures:",
        *(f"  {path}" for path in result.discovered),
        "parsed_captures:",
        *(f"  {path}" for path in result.parsed),
        "skipped_captures:",
        *(f"  {path}" for path in result.skipped),
    ]
    return create_run_archive(
        archive_dir=archive_dir,
        workflow="vocera_media_qoe_icap_batch",
        command="vocera_media_qoe_batch",
        inputs=inputs,
        outputs=outputs,
        metadata={
            "raw_dir": str(raw_dir),
            "discovered_capture_count": len(result.discovered),
            "parsed_capture_count": len(result.parsed),
            "skipped_capture_count": len(result.skipped),
            "published_pcap": str(result.published_pcap) if result.published_pcap else None,
            "db_loaded": result.db_loaded,
        },
        log_lines=log_lines,
        label=archive_label or (result.published_pcap.stem if result.published_pcap else None),
    )


def publish_cache(
    *,
    json_path: Path,
    prom_path: Path,
    json_out: Path,
    prom_out: Path,
    textfile_out: Path | None,
) -> None:
    """Publish a cached capture to stable latest-output paths."""
    json_out.parent.mkdir(parents=True, exist_ok=True)
    prom_out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(json_path, json_out)
    shutil.copyfile(prom_path, prom_out)
    json_out.chmod(0o644)
    prom_out.chmod(0o644)
    if textfile_out is not None:
        textfile_out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(prom_path, textfile_out)
        textfile_out.chmod(0o644)


def write_empty_outputs(
    *,
    message: str,
    json_out: Path,
    prom_out: Path,
    textfile_out: Path | None,
) -> None:
    """Publish a parser-health failure snapshot when no captures are present."""
    result = qoe.AnalysisResult(
        streams=[],
        packets_read=0,
        udp_packets_seen=0,
        last_capture_timestamp_seconds=None,
        parse_success=0,
        error=message,
    )
    qoe.write_text(json_out, json.dumps(_analysis_payload(result, None), indent=2, sort_keys=True))
    prom = qoe.render_prometheus(result)
    qoe.write_text(prom_out, prom)
    json_out.chmod(0o644)
    prom_out.chmod(0o644)
    if textfile_out is not None:
        qoe.write_text(textfile_out, prom)
        textfile_out.chmod(0o644)


def publish_unparsed_captures(
    *,
    raw_dir: Path,
    config: qoe.AnalyzerConfig,
    prom_out: Path,
    json_out: Path,
    parsed_dir: Path,
    textfile_out: Path | None = None,
    pcap: Path | None = None,
    force: bool = False,
    sql_out: Path | None = None,
    postgres_url: str | None = None,
    psql_bin: str = "psql",
    schema_sql: Path = Path("sql/vocera_media_qoe_schema.sql"),
    views_sql: Path = Path("sql/vocera_media_qoe_views.sql"),
    config_path: Path | None = None,
    archive_dir: Path | None = None,
    archive_label: str | None = None,
    study_id: str | None = None,
    install_db: bool = True,
) -> BatchPublishResult:
    """Parse stale captures, publish the newest cache, and archive the run.

    Historical panels read every current per-capture JSON from parsed_dir, but
    node_exporter's textfile collector can expose only one snapshot. The newest
    pcap by mtime is therefore copied to the stable prom/json output paths.
    """
    parsed_dir.mkdir(parents=True, exist_ok=True)
    captures = [pcap] if pcap is not None else discover_pcaps(raw_dir)
    captures = [path for path in captures if path.is_file()]
    result = BatchPublishResult(discovered=list(captures))

    if not captures:
        target = pcap if pcap is not None else raw_dir
        write_empty_outputs(
            message=f"no pcap files found under {target}",
            json_out=json_out,
            prom_out=prom_out,
            textfile_out=textfile_out,
        )
        result.published_json = json_out
        result.published_prom = prom_out
        if archive_dir is not None:
            result.archive_zip = archive_batch_run(
                archive_dir=archive_dir,
                result=result,
                raw_dir=raw_dir,
                parsed_dir=parsed_dir,
                config_path=config_path,
                prom_out=prom_out,
                json_out=json_out,
                textfile_out=textfile_out,
                archive_label=archive_label,
            )
        return result

    latest = max(captures, key=lambda path: (path.stat().st_mtime_ns, str(path)))
    latest_json: Path | None = None
    latest_prom: Path | None = None

    for capture in captures:
        state = capture_state(capture)
        state["analyzer_config"] = analyzer_config_state(config)
        json_path, prom_path = cache_paths(parsed_dir, capture)
        if not force and cached_current(json_path, prom_path, state):
            result.skipped.append(capture)
        else:
            parse_capture(capture, config=config, json_path=json_path, prom_path=prom_path, state=state)
            result.parsed.append(capture)
        if capture == latest:
            latest_json = json_path
            latest_prom = prom_path

    if latest_json is None or latest_prom is None:
        raise RuntimeError("unable to identify latest capture outputs")
    publish_cache(
        json_path=latest_json,
        prom_path=latest_prom,
        json_out=json_out,
        prom_out=prom_out,
        textfile_out=textfile_out,
    )
    result.published_pcap = latest
    result.published_json = json_out
    result.published_prom = prom_out
    result.history_sql, result.db_loaded = write_history_outputs(
        parsed_dir=parsed_dir,
        sql_out=sql_out,
        postgres_url=postgres_url,
        psql_bin=psql_bin,
        schema_sql=schema_sql,
        views_sql=views_sql,
        study_id=study_id,
        install_db=install_db,
    )
    if archive_dir is not None:
        result.archive_zip = archive_batch_run(
            archive_dir=archive_dir,
            result=result,
            raw_dir=raw_dir,
            parsed_dir=parsed_dir,
            config_path=config_path,
            prom_out=prom_out,
            json_out=json_out,
            textfile_out=textfile_out,
            archive_label=archive_label,
        )
    return result


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments for the batch publisher."""
    parser = argparse.ArgumentParser(description="Parse unprocessed local Vocera media ICAP pcaps and publish the latest textfile metrics.")
    parser.add_argument("--raw-dir", default="/var/lib/vocera-media-qoe/raw")
    parser.add_argument("--pcap", help="Optional exact pcap path. When omitted, scans --raw-dir recursively.")
    parser.add_argument("--config", default="config/vocera-media-qoe.yaml")
    parser.add_argument("--prom-out", default="data/vocera-media-qoe/out/vocera_media_qoe.prom")
    parser.add_argument("--json-out", default="data/vocera-media-qoe/out/vocera_media_qoe_summary.json")
    parser.add_argument("--parsed-dir", default="data/vocera-media-qoe/out/captures")
    parser.add_argument("--textfile-out", help="Optional node_exporter textfile destination.")
    parser.add_argument("--sql-out", help="Optional PostgreSQL import SQL output for capture-time history.")
    parser.add_argument("--postgres-url", help="Optional PostgreSQL URL. When set, schema/views are applied and SQL is loaded.")
    parser.add_argument("--psql-bin", default="psql")
    parser.add_argument("--schema-sql", default="sql/vocera_media_qoe_schema.sql")
    parser.add_argument("--views-sql", default="sql/vocera_media_qoe_views.sql")
    parser.add_argument("--skip-install-db", action="store_true", help="Load generated SQL without applying schema/views first.")
    parser.add_argument("--archive-dir", help="Directory for per-run ZIP archives. Defaults beside --json-out.")
    parser.add_argument("--archive-label", help="Optional label appended to the archive filename.")
    parser.add_argument("--no-archive", action="store_true", help="Disable per-run ZIP archive creation.")
    parser.add_argument("--force", action="store_true", help="Reparse captures even when their cached state is current.")
    parser.add_argument("--study-id", default=os.environ.get("VOCERA_MEDIA_QOE_STUDY_ID"), help="Optional study_id applied to imported capture rows.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for batch ICAP parsing and publication."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    archive_dir = None if args.no_archive else Path(args.archive_dir or (Path(args.json_out).parent / "archives"))
    install_db = not args.skip_install_db and os.environ.get("VOCERA_MEDIA_QOE_INSTALL_DB", "1").strip().lower() not in {"0", "false", "no", "off"}
    try:
        config = qoe.load_config(args.config)
        result = publish_unparsed_captures(
            raw_dir=Path(args.raw_dir),
            config=config,
            prom_out=Path(args.prom_out),
            json_out=Path(args.json_out),
            parsed_dir=Path(args.parsed_dir),
            textfile_out=Path(args.textfile_out) if args.textfile_out else None,
            pcap=Path(args.pcap) if args.pcap else None,
            force=args.force,
            sql_out=Path(args.sql_out) if args.sql_out else None,
            postgres_url=args.postgres_url,
            psql_bin=args.psql_bin,
            schema_sql=Path(args.schema_sql),
            views_sql=Path(args.views_sql),
            config_path=Path(args.config),
            archive_dir=archive_dir,
            archive_label=args.archive_label,
            study_id=args.study_id,
            install_db=install_db,
        )
    except Exception as exc:
        if archive_dir is not None:
            failure = BatchPublishResult(discovered=discover_pcaps(Path(args.raw_dir)))
            failure.archive_zip = create_run_archive(
                archive_dir=archive_dir,
                workflow="vocera_media_qoe_icap_batch",
                command="vocera_media_qoe_batch",
                inputs=[Path(args.config)] + ([Path(args.pcap)] if args.pcap else []),
                outputs=[Path(args.json_out), Path(args.prom_out), Path(args.sql_out)] if args.sql_out else [Path(args.json_out), Path(args.prom_out)],
                metadata={"error": str(exc), "raw_dir": args.raw_dir},
                log_lines=[
                    "Vocera media QoE ICAP batch parser failed before normal completion",
                    f"raw_dir={args.raw_dir}",
                    f"pcap={args.pcap or '<scan raw dir>'}",
                    f"error={exc}",
                ],
                label=args.archive_label or "failed",
            )
            print(f"Archived failed parser inputs and outputs to {failure.archive_zip}", file=sys.stderr)
        raise
    if result.published_pcap is None:
        print(f"No local ICAP pcaps found under {args.pcap or args.raw_dir}")
    else:
        print(
            "Parsed "
            f"{len(result.parsed)} new ICAP capture(s), skipped {len(result.skipped)} current capture(s); "
            f"published {result.published_pcap}"
        )
    if result.archive_zip is not None:
        print(f"Archived parser inputs and outputs to {result.archive_zip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
