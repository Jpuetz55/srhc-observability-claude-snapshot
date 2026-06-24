"""Command-line entry point for collection, parsing, exports, and storage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    from tools.common.files import write_csv as common_write_csv
    from tools.common.files import write_json as common_write_json
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from tools.common.files import write_csv as common_write_csv
    from tools.common.files import write_json as common_write_json

from .client_collector import collect_configured_badge_jobs, load_badge_config, select_jobs
from .client_models import BADGE_CLIENT_ROW_FIELDS
from .client_parser import filter_badge_snapshots, parse_badge_client_raw
from .client_prometheus import render_badge_prometheus
from .client_storage import save_badge_run
from .parser import apply_filters, build_collection_stats, parse_wlc_rf_dump
from .prometheus import render_prometheus
from .stats_engine import describe, summarize_snapshots_by_site
from .storage import save_run


def write_csv(path: str | Path, rows: list[dict[str, object]], fieldnames: list[str] | None = None) -> None:
    """Write table rows while preserving a stable empty-file header."""

    fieldnames = fieldnames or (list(rows[0].keys()) if rows else [
        "wlc", "ap_name", "site_tag", "policy_tag", "rf_tag", "band", "nearby_ap_count"
    ])
    common_write_csv(path, fieldnames, rows)


def write_json(path: str | Path, payload: object) -> None:
    """Write deterministic JSON so generated summaries diff cleanly."""

    common_write_json(path, payload)


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Define the CLI surface for RF and badge collection workflows."""

    parser = argparse.ArgumentParser(
        prog="wireless-rf",
        description="Parse Cisco WLC RF evidence into CSV, JSON, SQLite history, and Prometheus exposition.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("parse", help="Parse an existing raw WLC evidence file.")
    p.add_argument("input", help="Raw WLC dump file containing show ap tag summary and per-AP auto-rf output.")
    p.add_argument("--wlc", default="unknown", help="WLC name or management IP to stamp into output labels.")
    p.add_argument("--band", default="5ghz", help="Band to include, for example 5ghz or 24ghz.")
    p.add_argument("--site-tag")
    p.add_argument("--site-tag-regex")
    p.add_argument("--ap-name-regex")
    p.add_argument("--min-neighbors", type=int)
    p.add_argument("--csv-out", default="data/wireless-rf/exports/wlc_rf_snapshot.csv")
    p.add_argument("--json-out", default="data/wireless-rf/exports/wlc_rf_summary.json")
    p.add_argument("--prom-out", default="data/wireless-rf/exports/wlc_rf.prom")
    p.add_argument("--sqlite-db", default="data/wireless-rf/wlc_rf.sqlite")
    p.add_argument("--no-sqlite", action="store_true", help="Do not persist the run to SQLite.")

    cb = sub.add_parser("collect-badges", help="Collect explicit badge client details through Catalyst Center.")
    cb.add_argument("--config", default="config/badge-client-observability.yaml")
    cb.add_argument("--job", help="Only run the named badge collection job.")
    cb.add_argument("--timestamp-ms", type=int, help="Optional Catalyst Center client-detail timestamp in epoch ms.")

    pb = sub.add_parser("parse-badges", help="Parse badge client raw JSON into CSV, JSON, SQLite, and Prometheus.")
    pb.add_argument("--input", default="data/wireless-rf/raw/badge_client_raw.json")
    pb.add_argument("--config", help="Optional badge client config whose outputs and defaults should be used.")
    pb.add_argument("--job", help="Optional job name to read from --config.")
    pb.add_argument("--device-group")
    pb.add_argument("--wlc")
    pb.add_argument("--ssid")
    pb.add_argument("--badge-model")
    pb.add_argument("--csv-out", default="data/wireless-rf/exports/badge_client_snapshot.csv")
    pb.add_argument("--json-out", default="data/wireless-rf/exports/badge_client_summary.json")
    pb.add_argument("--prom-out", default="data/wireless-rf/exports/badge_client.prom")
    pb.add_argument("--sqlite-db", default="data/wireless-rf/badge_client.sqlite")
    pb.add_argument("--no-sqlite", action="store_true", help="Do not persist the run to SQLite.")

    return parser.parse_args(argv)


def command_parse(args: argparse.Namespace) -> int:
    """Parse a raw WLC RF file and emit CSV, JSON, Prometheus, and SQLite."""

    raw_path = Path(args.input)
    text = raw_path.read_text(encoding="utf-8", errors="replace")
    snapshots = parse_wlc_rf_dump(text, wlc=args.wlc, default_band=args.band)
    filtered = apply_filters(
        snapshots,
        site_tag=args.site_tag,
        site_tag_regex=args.site_tag_regex,
        ap_name_regex=args.ap_name_regex,
        band=args.band,
        min_neighbors=args.min_neighbors,
    )

    rows = [snapshot.to_row() for snapshot in filtered]
    counts = [snapshot.neighbor_count for snapshot in filtered]
    payload = {
        "input": str(raw_path),
        "wlc": args.wlc,
        "band": args.band,
        "total_snapshots_parsed": len(snapshots),
        "snapshots_after_filters": len(filtered),
        "neighbor_count_summary": describe(counts),
        "neighbor_count_summary_by_site_tag": summarize_snapshots_by_site(filtered),
        "dfs_summary": {
            "aps_checked": len(filtered),
            "aps_on_dfs_channel": sum(1 for snapshot in filtered if snapshot.is_dfs_channel),
            "aps_in_cac": sum(1 for snapshot in filtered if snapshot.cac_running),
            "aps_with_radar_counter_gt_zero": sum(
                1 for snapshot in filtered
                if snapshot.radar_changes_total is not None and snapshot.radar_changes_total > 0
            ),
        },
        "rows": rows,
    }

    write_csv(args.csv_out, rows)
    write_json(args.json_out, payload)
    Path(args.prom_out).parent.mkdir(parents=True, exist_ok=True)
    # Use the raw evidence file mtime as the success timestamp for manual parse
    # runs, while live collection runs can embed precise metadata in the file.
    collection_stats = build_collection_stats(
        text,
        filtered,
        wlc=args.wlc,
        last_success_timestamp_seconds=raw_path.stat().st_mtime,
    )
    Path(args.prom_out).write_text(render_prometheus(filtered, collection_stats=collection_stats), encoding="utf-8")

    if not args.no_sqlite:
        run_id = save_run(args.sqlite_db, filtered, wlc=args.wlc, source="cli", raw_file=str(raw_path))
        payload["sqlite_run_id"] = run_id
        write_json(args.json_out, payload)

    print(f"Parsed {len(filtered)} AP RF snapshots from {raw_path}")
    print(f"CSV:  {args.csv_out}")
    print(f"JSON: {args.json_out}")
    print(f"Prom: {args.prom_out}")
    if not args.no_sqlite:
        print(f"DB:   {args.sqlite_db}")
    return 0


def _first_badge_config_job(config_path: str | None, job_name: str | None) -> dict[str, object]:
    """Return the config job whose outputs/defaults should influence parsing."""

    if not config_path:
        return {}
    config = load_badge_config(config_path)
    jobs = select_jobs(config, job_name=job_name)
    return jobs[0] if jobs else {}


def _apply_badge_config_outputs(args: argparse.Namespace) -> None:
    """Overlay badge parse arguments with output paths/defaults from config."""

    job = _first_badge_config_job(args.config, args.job)
    outputs = job.get("outputs") if isinstance(job, dict) else None
    if isinstance(outputs, dict):
        args.csv_out = outputs.get("csv") or args.csv_out
        args.json_out = outputs.get("json") or args.json_out
        args.prom_out = outputs.get("prometheus") or args.prom_out
        args.sqlite_db = outputs.get("sqlite") or args.sqlite_db
    if isinstance(job, dict):
        args.device_group = args.device_group or job.get("device_group")
        args.wlc = args.wlc or job.get("wlc")
        ssids = job.get("ssids")
        badge_models = job.get("badge_models")
        if not args.ssid and isinstance(ssids, list) and len(ssids) == 1:
            args.ssid = ssids[0]
        if not args.badge_model and isinstance(badge_models, list) and len(badge_models) == 1:
            args.badge_model = badge_models[0]


def _numeric_summary(rows: list[object], attr: str) -> dict[str, object]:
    """Summarize an optional numeric attribute across parsed snapshots."""

    values = [getattr(row, attr) for row in rows if getattr(row, attr) is not None]
    return describe(values)


def command_collect_badges(args: argparse.Namespace) -> int:
    """Collect Catalyst Center client-detail JSON for configured badges."""

    payload = collect_configured_badge_jobs(args.config, job_name=args.job, timestamp_ms=args.timestamp_ms)
    for job in payload.get("jobs", []):
        outputs = {}
        try:
            config = load_badge_config(args.config)
            matching = select_jobs(config, job_name=job.get("name"))
            outputs = (matching[0].get("outputs") or {}) if matching else {}
        except Exception:
            outputs = {}
        raw_out = outputs.get("raw")
        collected = len(job.get("clients", []))
        errors = sum(1 for record in job.get("clients", []) if record.get("error"))
        if raw_out:
            print(f"Wrote badge raw client evidence to {raw_out} ({collected} clients, {errors} errors)")
        else:
            print(json.dumps({"job": job.get("name"), "clients": collected, "errors": errors}, sort_keys=True))
    return 0


def command_parse_badges(args: argparse.Namespace) -> int:
    """Parse badge client JSON and emit all configured output formats."""

    _apply_badge_config_outputs(args)
    raw_path = Path(args.input)
    payload = json.loads(raw_path.read_text(encoding="utf-8"))
    snapshots = parse_badge_client_raw(payload)
    filtered = filter_badge_snapshots(
        snapshots,
        device_group=args.device_group,
        wlc=args.wlc,
        ssid=args.ssid,
        badge_model=args.badge_model,
    )
    rows = [snapshot.to_row() for snapshot in filtered]
    summary = {
        "input": str(raw_path),
        "total_snapshots_parsed": len(snapshots),
        "snapshots_after_filters": len(filtered),
        "filters": {
            "device_group": args.device_group,
            "wlc": args.wlc,
            "ssid": args.ssid,
            "badge_model": args.badge_model,
        },
        "rssi_dbm": _numeric_summary(filtered, "rssi_dbm"),
        "snr_db": _numeric_summary(filtered, "snr_db"),
        "rx_retry_pct": _numeric_summary(filtered, "rx_retry_pct"),
        "latency_voice_us": _numeric_summary(filtered, "latency_voice_us"),
        "latency_be_us": _numeric_summary(filtered, "latency_be_us"),
        "max_roaming_duration_ms": _numeric_summary(filtered, "max_roaming_duration_ms"),
        "ft_state_counts": {
            state: sum(1 for snapshot in filtered if snapshot.ft_state == state)
            for state in sorted({snapshot.ft_state for snapshot in filtered})
        },
        "rows": rows,
    }

    write_csv(args.csv_out, rows, fieldnames=BADGE_CLIENT_ROW_FIELDS)
    write_json(args.json_out, summary)
    Path(args.prom_out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.prom_out).write_text(render_badge_prometheus(filtered), encoding="utf-8")

    if not args.no_sqlite:
        run_id = save_badge_run(
            args.sqlite_db,
            filtered,
            wlc=args.wlc or "unknown",
            source="catalyst_center",
            raw_file=str(raw_path),
        )
        summary["sqlite_run_id"] = run_id
        write_json(args.json_out, summary)

    print(f"Parsed {len(filtered)} badge client snapshots from {raw_path}")
    print(f"CSV:  {args.csv_out}")
    print(f"JSON: {args.json_out}")
    print(f"Prom: {args.prom_out}")
    if not args.no_sqlite:
        print(f"DB:   {args.sqlite_db}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch the selected subcommand."""

    args = parse_args(sys.argv[1:] if argv is None else argv)
    if args.command == "parse":
        return command_parse(args)
    if args.command == "collect-badges":
        return command_collect_badges(args)
    if args.command == "parse-badges":
        return command_parse_badges(args)
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
