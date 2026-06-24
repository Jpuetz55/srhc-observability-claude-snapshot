"""Command line interface for Vocera RF validation workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    from tools.common.files import write_json as common_write_json
    from tools.common.files import write_text
except ModuleNotFoundError as exc:
    if exc.name != "tools":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from tools.common.files import write_json as common_write_json
    from tools.common.files import write_text

from .badge_diag_parser import parse_badge_input
from .config import load_config
from .correlate import (
    build_manual_entry_template,
    correlate_template_csv,
    load_badge_result,
    load_ekahau_result,
    summarize_match_alignment,
    write_matches_csv,
    write_matches_json,
    write_template_csv,
)
from .db import install_schema
from .ekahau_importer import inspect_ekahau_json, parse_ekahau_json
from .ipad_client_detail import parse_client_detail_inputs
from .run_archive import create_run_archive
from .sql_export import emit_sql


def _write_json(payload: dict[str, object], path: str | Path) -> None:
    """Write a JSON artifact, creating the parent directory first."""
    common_write_json(path, payload)


def _archive_dir(args: argparse.Namespace, outputs: list[str | Path | None]) -> Path:
    """Resolve the archive directory from CLI, env, output path, or default."""
    if args.archive_dir:
        return Path(args.archive_dir)
    env_dir = os.environ.get("VOCERA_RF_VALIDATION_ARCHIVE_DIR")
    if env_dir:
        return Path(env_dir)
    first_output = next((Path(path) for path in outputs if path), None)
    if first_output is not None:
        return first_output.parent / "archives"
    return Path("data/vocera-rf-validation/out/archives")


def _archive_cli_run(
    args: argparse.Namespace,
    *,
    command: str,
    inputs: list[str | Path | None],
    outputs: list[str | Path | None],
    metadata: dict[str, object],
    log_lines: list[str],
    label: str | None = None,
) -> Path | None:
    """Archive every parser subcommand unless the operator opts out.

    The RF validation workflow often uses one-off survey projects and badge
    diagnostic bundles. Archiving each step keeps enough input/output context to
    audit a run after the raw folder has been cleaned up.
    """
    if args.no_archive:
        return None
    archive_path = create_run_archive(
        archive_dir=_archive_dir(args, outputs),
        workflow="vocera_rf_validation",
        command=command,
        inputs=[path for path in inputs if path],
        outputs=[path for path in outputs if path],
        metadata=metadata,
        log_lines=log_lines,
        label=args.archive_label or label,
    )
    print(f"Archived parser inputs and outputs to {archive_path}", file=sys.stderr)
    return archive_path


def main(argv: list[str] | None = None) -> int:
    """Run one RF validation subcommand and archive parser runs by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config/vocera-rf-validation.yaml")
    parser.add_argument("--archive-dir", help="Directory for per-run ZIP archives. Defaults beside the command output.")
    parser.add_argument("--archive-label", help="Optional label appended to the archive filename.")
    parser.add_argument("--no-archive", action="store_true", help="Disable per-run ZIP archive creation.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_badge = subparsers.add_parser("parse-badge", help="Parse Vocera badge diagnostic sys input")
    parse_badge.add_argument("--test-run-id", required=True)
    parse_badge.add_argument("--input", required=True)
    parse_badge.add_argument("--badge-mac")
    parse_badge.add_argument("--badge-model")
    parse_badge.add_argument("--json-out", required=True)

    parse_ipad = subparsers.add_parser(
        "parse-ipad-client-detail",
        help="Parse iPad WLC Client Scan Reports from collected client-detail output",
    )
    parse_ipad.add_argument("--test-run-id", required=True)
    parse_ipad.add_argument(
        "--input",
        action="append",
        required=True,
        help="Collected client-detail file or directory. Can be repeated.",
    )
    parse_ipad.add_argument("--client-mac")
    parse_ipad.add_argument("--client-model", default="iPad")
    parse_ipad.add_argument("--json-out", required=True)

    inspect_ekahau = subparsers.add_parser("inspect-ekahau", help="Inspect Ekahau JSON timestamp fields")
    inspect_ekahau.add_argument("--input", required=True)

    parse_ekahau = subparsers.add_parser("parse-ekahau-json", help="Parse Ekahau JSON timestamps")
    parse_ekahau.add_argument("--test-run-id", required=True)
    parse_ekahau.add_argument("--input", required=True)
    parse_ekahau.add_argument("--json-out", required=True)

    template = subparsers.add_parser("manual-template", help="Generate manual RSSI/SNR entry CSV")
    template.add_argument("--badge-json", required=True)
    template.add_argument("--ekahau-json", required=True)
    template.add_argument("--csv-out", required=True)

    correlate = subparsers.add_parser("correlate", help="Compute calibrated badge-vs-Ekahau deltas")
    correlate.add_argument("--template-csv", required=True)
    correlate.add_argument("--manual-csv")
    correlate.add_argument("--json-out", required=True)
    correlate.add_argument("--csv-out")

    install = subparsers.add_parser("install-db", help="Apply PostgreSQL schema and views")
    install.add_argument("--postgres-url", required=True)
    install.add_argument("--psql-bin", default="psql")
    install.add_argument("--schema-sql", default="sql/vocera_rf_validation_schema.sql")
    install.add_argument("--views-sql", default="sql/vocera_rf_validation_views.sql")

    emit = subparsers.add_parser("emit-sql", help="Emit run-scoped PostgreSQL insert SQL from parsed artifacts")
    emit.add_argument("--badge-json", required=True)
    emit.add_argument("--ekahau-json", required=True)
    emit.add_argument("--template-csv")
    emit.add_argument("--matches-json")
    emit.add_argument("--sql-out", required=True)

    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "parse-badge":
        result = parse_badge_input(
            args.input,
            test_run_id=args.test_run_id,
            badge_mac=args.badge_mac,
            badge_model=args.badge_model,
            timezone=config.get("timezone", "America/Chicago"),
        )
        _write_json(result.to_dict(), args.json_out)
        _archive_cli_run(
            args,
            command="parse-badge",
            inputs=[args.config, args.input],
            outputs=[args.json_out],
            metadata={
                "test_run_id": args.test_run_id,
                "parse_success": result.parse_success,
                "event_count": len(result.events),
                "rrm_neighbor_count": len(result.rrm_neighbors),
                "radio_signal_sample_count": len(result.radio_signal_samples),
                "line_count": result.line_count,
            },
            log_lines=[
                "Vocera RF validation badge diagnostic parser run",
                f"test_run_id={args.test_run_id}",
                f"input={args.input}",
                f"json_out={args.json_out}",
                f"parse_success={result.parse_success}",
                f"event_count={len(result.events)}",
                f"rrm_neighbor_count={len(result.rrm_neighbors)}",
                f"radio_signal_sample_count={len(result.radio_signal_samples)}",
                f"warnings={len(result.warnings)}",
                *(f"warning={warning}" for warning in result.warnings),
                *(["parse_error=" + result.parse_error] if result.parse_error else []),
            ],
            label=args.test_run_id,
        )
        if not result.parse_success:
            print(f"ERROR: {result.parse_error or '; '.join(result.warnings) or 'no badge scan events parsed'}")
            return 2
        print(
            "Parsed "
            f"{len(result.events)} badge scan events, "
            f"{len(result.rrm_neighbors)} RRM neighbors, and "
            f"{len(result.radio_signal_samples)} radio signal samples"
        )
        return 0

    if args.command == "parse-ipad-client-detail":
        result = parse_client_detail_inputs(
            args.input,
            test_run_id=args.test_run_id,
            client_mac=args.client_mac,
            client_model=args.client_model,
            timezone=config.get("timezone", "America/Chicago"),
        )
        _write_json(result.to_dict(), args.json_out)
        _archive_cli_run(
            args,
            command="parse-ipad-client-detail",
            inputs=[args.config, *args.input],
            outputs=[args.json_out],
            metadata={
                "test_run_id": args.test_run_id,
                "parse_success": result.parse_success,
                "event_count": len(result.events),
                "candidate_count": sum(len(event.candidates) for event in result.events),
                "line_count": result.line_count,
                "input_count": len(args.input),
            },
            log_lines=[
                "iPad WLC RF validation client-detail parser run",
                f"test_run_id={args.test_run_id}",
                f"input={args.input}",
                f"json_out={args.json_out}",
                f"parse_success={result.parse_success}",
                f"event_count={len(result.events)}",
                f"candidate_count={sum(len(event.candidates) for event in result.events)}",
                f"warnings={len(result.warnings)}",
                *(f"warning={warning}" for warning in result.warnings),
                *(["parse_error=" + result.parse_error] if result.parse_error else []),
            ],
            label=args.test_run_id,
        )
        if not result.parse_success:
            print(f"ERROR: {result.parse_error or '; '.join(result.warnings) or 'no iPad client scan reports parsed'}")
            return 2
        print(
            "Parsed "
            f"{len(result.events)} iPad WLC scan events and "
            f"{sum(len(event.candidates) for event in result.events)} scan candidates"
        )
        return 0

    if args.command == "inspect-ekahau":
        result = inspect_ekahau_json(args.input, config=config)
        print(json.dumps(result, indent=2, sort_keys=True))
        _archive_cli_run(
            args,
            command="inspect-ekahau",
            inputs=[args.config, args.input],
            outputs=[],
            metadata={
                "path": result.get("path"),
                "json_source_count": len(result.get("json_sources", [])),
                "survey_json_files": result.get("survey_json_files"),
                "route_points": result.get("route_points"),
            },
            log_lines=[
                "Vocera RF validation Ekahau inspection run",
                f"input={args.input}",
                f"json_source_count={len(result.get('json_sources', []))}",
                f"survey_json_files={result.get('survey_json_files')}",
                f"route_points={result.get('route_points')}",
                f"timestamp_keys={result.get('timestamp_keys')}",
            ],
            label=Path(args.input).stem,
        )
        return 0

    if args.command == "parse-ekahau-json":
        result = parse_ekahau_json(args.input, test_run_id=args.test_run_id, config=config)
        _write_json(result.to_dict(), args.json_out)
        _archive_cli_run(
            args,
            command="parse-ekahau-json",
            inputs=[args.config, args.input],
            outputs=[args.json_out],
            metadata={
                "test_run_id": args.test_run_id,
                "parse_success": result.parse_success,
                "survey_point_count": len(result.survey_points),
                "timestamp_keys_seen": result.timestamp_keys_seen,
                "ap_name_mapping_count": len(result.ap_name_by_bssid),
            },
            log_lines=[
                "Vocera RF validation Ekahau parser run",
                f"test_run_id={args.test_run_id}",
                f"input={args.input}",
                f"json_out={args.json_out}",
                f"parse_success={result.parse_success}",
                f"survey_point_count={len(result.survey_points)}",
                f"timestamp_keys_seen={result.timestamp_keys_seen}",
                f"warnings={len(result.warnings)}",
                *(f"warning={warning}" for warning in result.warnings),
                *(["parse_error=" + result.parse_error] if result.parse_error else []),
            ],
            label=args.test_run_id,
        )
        print(f"Parsed {len(result.survey_points)} Ekahau survey timestamps")
        return 0 if result.parse_success else 2

    if args.command == "manual-template":
        badge_result = load_badge_result(args.badge_json)
        ekahau_result = load_ekahau_result(args.ekahau_json)
        rows = build_manual_entry_template(badge_result, ekahau_result, config=config)
        write_template_csv(rows, args.csv_out)
        alignment = summarize_match_alignment(badge_result, ekahau_result, config=config)
        _archive_cli_run(
            args,
            command="manual-template",
            inputs=[args.config, args.badge_json, args.ekahau_json],
            outputs=[args.csv_out],
            metadata={
                "test_run_id": badge_result.test_run_id,
                "row_count": len(rows),
                "alignment": alignment,
            },
            log_lines=[
                "Vocera RF validation badge/Ekahau manual-template run",
                f"badge_json={args.badge_json}",
                f"ekahau_json={args.ekahau_json}",
                f"csv_out={args.csv_out}",
                f"row_count={len(rows)}",
                f"alignment={json.dumps(alignment, sort_keys=True)}",
            ],
            label=badge_result.test_run_id,
        )
        print(f"Wrote {len(rows)} manual-entry candidate rows to {args.csv_out}")
        if not rows:
            print(
                "WARNING: no badge/Ekahau rows matched. "
                f"reason={alignment['unmatched_reason']} "
                f"badge_events={alignment['badge_event_count']} "
                f"ekahau_points={alignment['ekahau_survey_point_count']} "
                f"window_seconds={alignment['configured_match_window_seconds']} "
                f"badge_dates={alignment['badge_measurement_dates']} "
                f"ekahau_dates={alignment['ekahau_measurement_dates']} "
                f"same_dates={alignment['same_measurement_dates']} "
                f"nearest_delta_min_seconds={alignment['nearest_delta_min_seconds']} "
                f"nearest_delta_any_date_seconds={alignment['nearest_delta_any_date_seconds']} "
                f"badge_range={alignment['badge_time_range']} "
                f"ekahau_range={alignment['ekahau_time_range']}"
            )
        return 0

    if args.command == "correlate":
        matches = correlate_template_csv(args.template_csv, config=config, manual_csv=args.manual_csv)
        write_matches_json(matches, args.json_out)
        if args.csv_out:
            write_matches_csv(
                matches,
                args.csv_out,
                minimum_samples=int(config.get("minimum_samples_for_outlier_stats", 30)),
                z_score_threshold=float(config.get("outlier_z_score_threshold", 2.0)),
            )
        complete = sum(1 for match in matches if match.manual_entry_status == "complete")
        test_run_id = matches[0].test_run_id if matches else None
        _archive_cli_run(
            args,
            command="correlate",
            inputs=[args.config, args.template_csv, args.manual_csv],
            outputs=[args.json_out, args.csv_out],
            metadata={
                "test_run_id": test_run_id,
                "match_count": len(matches),
                "complete_manual_entry_count": complete,
            },
            log_lines=[
                "Vocera RF validation badge/Ekahau correlation run",
                f"template_csv={args.template_csv}",
                f"manual_csv={args.manual_csv or '<none>'}",
                f"json_out={args.json_out}",
                f"csv_out={args.csv_out or '<none>'}",
                f"match_count={len(matches)}",
                f"complete_manual_entry_count={complete}",
            ],
            label=test_run_id,
        )
        print(f"Wrote {len(matches)} matches ({complete} complete manual entries)")
        return 0

    if args.command == "install-db":
        install_schema(
            postgres_url=args.postgres_url,
            schema_sql=Path(args.schema_sql),
            views_sql=Path(args.views_sql),
            psql_bin=args.psql_bin,
        )
        print("Installed Vocera RF validation PostgreSQL schema and views")
        return 0

    if args.command == "emit-sql":
        sql = emit_sql(
            badge_json=args.badge_json,
            ekahau_json=args.ekahau_json,
            template_csv=args.template_csv,
            matches_json=args.matches_json,
        )
        write_text(args.sql_out, sql)
        _archive_cli_run(
            args,
            command="emit-sql",
            inputs=[args.config, args.badge_json, args.ekahau_json, args.template_csv, args.matches_json],
            outputs=[args.sql_out],
            metadata={
                "sql_out": str(args.sql_out),
                "sql_bytes": len(sql.encode("utf-8")),
            },
            log_lines=[
                "Vocera RF validation PostgreSQL SQL emitter run",
                f"badge_json={args.badge_json}",
                f"ekahau_json={args.ekahau_json}",
                f"template_csv={args.template_csv or '<none>'}",
                f"matches_json={args.matches_json or '<none>'}",
                f"sql_out={args.sql_out}",
                f"sql_bytes={len(sql.encode('utf-8'))}",
            ],
            label=Path(args.sql_out).stem,
        )
        print(f"Wrote PostgreSQL import SQL to {args.sql_out}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
