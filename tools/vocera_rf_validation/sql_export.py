"""Emit PostgreSQL insert SQL for offline RF validation artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .correlate import load_badge_result, load_ekahau_result, read_template_rows
from .models import CandidateTemplateRow, CorrelatedMatch, dt_from_iso


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


def _text_array(values: list[str]) -> str:
    """Render warning lists as PostgreSQL text arrays."""
    if not values:
        return "'{}'::text[]"
    return "array[" + ", ".join(_literal(value) for value in values) + "]::text[]"


def _jsonb(value: Any) -> str:
    """Render a JSON-serializable value as a PostgreSQL jsonb literal."""
    return _literal(json.dumps(value or {}, sort_keys=True)) + "::jsonb"


def _insert(table: str, columns: list[str], values: list[Any], *, conflict: str | None = None) -> str:
    """Build one simple insert statement used by the offline SQL exporter."""
    sql = f"insert into {table} ({', '.join(columns)}) values ({', '.join(_literal(value) for value in values)})"
    if conflict:
        sql += f" {conflict}"
    return sql + ";"


MANUAL_OBSERVATION_COLUMNS = [
    "id",
    "test_run_id",
    "survey_point_id",
    "measured_at",
    "floor",
    "area",
    "x_m",
    "y_m",
    "ssid",
    "bssid",
    "ap_name",
    "channel",
    "frequency_mhz",
    "band",
    "rssi_dbm",
    "snr_db",
    "noise_dbm",
    "source_row",
    "entered_by",
    "notes",
    "created_at",
]


def _preserve_manual_observations_sql(test_run_id: str) -> str:
    """Save manual observations so a parser reload does not re-open completed rows."""
    return (
        "create temporary table _vocera_rf_validation_preserved_manual_observations "
        "on commit drop as "
        "select * from manual_ekahau_observations "
        f"where test_run_id = {_literal(test_run_id)};"
    )


def _restore_manual_observations_sql() -> str:
    """Restore preserved manual observations whose survey points still exist."""
    columns = ", ".join(MANUAL_OBSERVATION_COLUMNS)
    return (
        f"insert into manual_ekahau_observations ({columns})\n"
        f"select {columns}\n"
        "from _vocera_rf_validation_preserved_manual_observations o\n"
        "where o.survey_point_id is null\n"
        "   or exists (\n"
        "     select 1\n"
        "     from ekahau_survey_points p\n"
        "     where p.survey_point_id = o.survey_point_id\n"
        "   )\n"
        "on conflict (id) do nothing;"
    )


def _mark_completed_candidates_from_matches_sql(test_run_id: str) -> str:
    """Mark candidates complete only when a completed match row already exists.

    The run import step must not auto-create badge_ekahau_matches from matching
    timestamps.  Candidate rows stay pending until manual-entry save creates the
    manual observation and materialized match row.
    """
    test_run_literal = _literal(test_run_id)
    return (
        "update badge_ekahau_matches m\n"
        "set candidate_match_id = c.id\n"
        "from badge_ekahau_candidate_matches c\n"
        f"where m.test_run_id = {test_run_literal}\n"
        "  and c.test_run_id = m.test_run_id\n"
        "  and m.candidate_match_id is null\n"
        "  and lower(m.bssid) = lower(c.bssid)\n"
        "  and m.ekahau_time = c.survey_time\n"
        "  and m.badge_event_id = c.badge_event_id\n"
        "  and m.badge_candidate_index = c.badge_candidate_index\n"
        "  and m.manual_entry_status in ('complete', 'missing_vendor_offset');\n"
        "\n"
        "update badge_ekahau_candidate_matches c\n"
        "set manual_entry_status = 'complete'\n"
        f"where c.test_run_id = {test_run_literal}\n"
        "  and c.manual_entry_status = 'pending'\n"
        "  and exists (\n"
        "    select 1\n"
        "    from badge_ekahau_matches m\n"
        "    where m.candidate_match_id = c.id\n"
        "      and m.manual_entry_status in ('complete', 'missing_vendor_offset')\n"
        "  );"
    )

def _match_from_dict(payload: dict[str, Any]) -> CorrelatedMatch:
    """Rehydrate a correlated-match JSON object into its dataclass."""
    return CorrelatedMatch(
        test_run_id=payload["test_run_id"],
        survey_point_id=payload.get("survey_point_id"),
        badge_event_id=payload["badge_event_id"],
        badge_candidate_index=int(payload["badge_candidate_index"]),
        badge_time=dt_from_iso(payload["badge_time"]),
        ekahau_time=dt_from_iso(payload["ekahau_time"]),
        ekahau_survey_id=payload.get("ekahau_survey_id"),
        ekahau_survey_name=payload.get("ekahau_survey_name"),
        time_delta_seconds=float(payload["time_delta_seconds"]),
        badge_mac=payload.get("badge_mac"),
        badge_model=payload.get("badge_model"),
        ssid=payload.get("ssid"),
        bssid=payload["bssid"],
        ap_name=payload.get("ap_name"),
        channel=payload.get("channel"),
        band=payload.get("band"),
        badge_rssi_dbm=payload.get("badge_rssi_dbm"),
        badge_noise_floor_dbm=payload.get("badge_noise_floor_dbm"),
        badge_snr_db=payload.get("badge_snr_db"),
        badge_snr_source=payload.get("badge_snr_source"),
        badge_snr_time=dt_from_iso(payload["badge_snr_time"]) if payload.get("badge_snr_time") else None,
        badge_snr_time_delta_seconds=payload.get("badge_snr_time_delta_seconds"),
        badge_radio_signal_level_dbm=payload.get("badge_radio_signal_level_dbm"),
        ekahau_rssi_dbm=payload.get("ekahau_rssi_dbm"),
        ekahau_snr_db=payload.get("ekahau_snr_db"),
        vendor_offset_db=payload.get("vendor_offset_db"),
        expected_badge_rssi_dbm=payload.get("expected_badge_rssi_dbm"),
        raw_delta_db=payload.get("raw_delta_db"),
        calibrated_delta_db=payload.get("calibrated_delta_db"),
        absolute_calibrated_delta_db=payload.get("absolute_calibrated_delta_db"),
        badge_cu_percent=payload.get("badge_cu_percent"),
        badge_score=payload.get("badge_score"),
        badge_selected=bool(payload.get("badge_selected")),
        floor=payload.get("floor"),
        area=payload.get("area"),
        x_m=payload.get("x_m"),
        y_m=payload.get("y_m"),
        match_quality=payload["match_quality"],
        manual_entry_status=payload["manual_entry_status"],
    )


def load_matches_json(path: str | Path) -> list[CorrelatedMatch]:
    """Load correlated match rows emitted by the correlate subcommand."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [_match_from_dict(item) for item in payload.get("matches", [])]


def _add_source_id(source_ids: dict[str, tuple[str, str | None]], source_file_id: str | None, source_type: str) -> None:
    """Track all source ids referenced by parsed rows before inserting data."""
    if source_file_id:
        source_ids.setdefault(source_file_id, (source_type, None))


def _first_non_empty(values: list[str | None]) -> str | None:
    """Return the first non-empty string from a parsed run."""

    for value in values:
        if value:
            return value
    return None


def emit_sql(
    *,
    badge_json: str | Path,
    ekahau_json: str | Path,
    template_csv: str | Path | None = None,
    matches_json: str | Path | None = None,
) -> str:
    """Emit idempotent, run-scoped SQL for parsed RF validation artifacts."""
    badge = load_badge_result(badge_json)
    ekahau = load_ekahau_result(ekahau_json)
    template_rows = read_template_rows(template_csv) if template_csv else []
    matches = load_matches_json(matches_json) if matches_json else []
    test_run_id = badge.test_run_id or ekahau.test_run_id
    run_badge_mac = _first_non_empty([event.badge_mac for event in badge.events])
    run_badge_model = _first_non_empty([event.badge_model for event in badge.events])
    source_type = "ipad_wlc_client_detail" if run_badge_model == "iPad" else "badge_sys"
    source_member_type = "ipad_wlc_client_detail_member" if run_badge_model == "iPad" else "badge_sys_member"

    lines: list[str] = [
        "begin;",
        _preserve_manual_observations_sql(test_run_id),
        f"delete from badge_ekahau_matches where test_run_id = {_literal(test_run_id)};",
        f"delete from badge_ekahau_candidate_matches where test_run_id = {_literal(test_run_id)};",
        f"delete from manual_ekahau_observations where test_run_id = {_literal(test_run_id)};",
        f"delete from ekahau_survey_points where test_run_id = {_literal(test_run_id)};",
        f"delete from badge_rrm_neighbors where test_run_id = {_literal(test_run_id)};",
        f"delete from badge_radio_signal_samples where test_run_id = {_literal(test_run_id)};",
        "delete from badge_scan_candidates using badge_scan_events "
        f"where badge_scan_candidates.event_id = badge_scan_events.event_id and badge_scan_events.test_run_id = {_literal(test_run_id)};",
        f"delete from badge_scan_events where test_run_id = {_literal(test_run_id)};",
        f"delete from validation_source_files where test_run_id = {_literal(test_run_id)};",
        _insert(
            "validation_test_runs",
            ["test_run_id", "timezone", "badge_mac", "badge_model"],
            [test_run_id, "America/Chicago", run_badge_mac, run_badge_model],
            conflict=(
                "on conflict (test_run_id) do update set "
                "badge_mac = excluded.badge_mac, "
                "badge_model = excluded.badge_model"
            ),
        ),
    ]

    source_ids: dict[str, tuple[str, str | None]] = {}
    _add_source_id(source_ids, badge.source_file_id, source_type)
    _add_source_id(source_ids, ekahau.source_file_id, "ekahau_json")
    for event in badge.events:
        _add_source_id(source_ids, event.source_file_id, source_member_type)
    for neighbor in badge.rrm_neighbors:
        _add_source_id(source_ids, neighbor.source_file_id, source_member_type)
    for sample in badge.radio_signal_samples:
        _add_source_id(source_ids, sample.source_file_id, source_member_type)
    for point in ekahau.survey_points:
        _add_source_id(source_ids, point.source_file_id, "ekahau_json_member")
    if badge.source_file_id:
        source_ids[badge.source_file_id] = (source_type, badge.source_path)
    if ekahau.source_file_id:
        source_ids[ekahau.source_file_id] = ("ekahau_json", ekahau.source_path)

    # Insert every referenced source id before child evidence rows. Archive
    # members inside tar/zip inputs can have source ids that differ from the
    # top-level badge/Ekahau source file id.
    for source_file_id, (source_type, source_path) in sorted(source_ids.items()):
        lines.append(
            _insert(
                "validation_source_files",
                ["source_file_id", "test_run_id", "source_type", "source_path", "source_sha256", "parse_success", "parse_error", "line_count"],
                [
                    source_file_id,
                    test_run_id,
                    source_type,
                    source_path or source_file_id,
                    source_file_id,
                    True,
                    None,
                    badge.line_count if source_type in {"badge_sys", "ipad_wlc_client_detail"} else None,
                ],
                conflict="on conflict (source_file_id) do nothing",
            )
        )

    for event in badge.events:
        columns = [
            "event_id",
            "test_run_id",
            "source_file_id",
            "badge_mac",
            "badge_model",
            "event_time",
            "ssid",
            "roam_reason",
            "total_aps",
            "roam_candidate_aps",
            "outage_ms",
            "total_scan_time_ms",
            "connected_bssid",
            "connected_channel",
            "connected_band",
            "connected_ssid",
            "connected_ip",
            "gateway",
            "source_line",
            "warnings",
        ]
        values = [
            event.event_id,
            event.test_run_id,
            event.source_file_id,
            event.badge_mac,
            event.badge_model,
            event.event_time.isoformat(),
            event.ssid,
            event.roam_reason,
            event.total_aps,
            event.roam_candidate_aps,
            event.outage_ms,
            event.total_scan_time_ms,
            event.connected_bssid,
            event.connected_channel,
            event.connected_band,
            event.connected_ssid,
            event.connected_ip,
            event.gateway,
            event.source_line,
            "__WARNINGS__",
        ]
        sql = _insert("badge_scan_events", columns, values)
        lines.append(sql.replace(_literal("__WARNINGS__"), _text_array(event.warnings)))
        for candidate in event.candidates:
            lines.append(
                _insert(
                    "badge_scan_candidates",
                    [
                        "event_id",
                        "candidate_index",
                        "selected",
                        "bssid",
                        "channel",
                        "band",
                        "rssi_dbm",
                        "channel_utilization_percent",
                        "score",
                        "is_roam_candidate",
                        "source_line",
                    ],
                    [
                        candidate.event_id,
                        candidate.candidate_index,
                        candidate.selected,
                        candidate.bssid,
                        candidate.channel,
                        candidate.band,
                        candidate.rssi_dbm,
                        candidate.channel_utilization_percent,
                        candidate.score,
                        candidate.is_roam_candidate,
                        candidate.source_line,
                    ],
                )
            )

    for neighbor in badge.rrm_neighbors:
        lines.append(
            _insert(
                "badge_rrm_neighbors",
                ["test_run_id", "source_file_id", "badge_mac", "event_time", "bssid", "op_class", "channel", "band", "phy_type", "info_hex", "source_line"],
                [
                    neighbor.test_run_id,
                    neighbor.source_file_id,
                    neighbor.badge_mac,
                    neighbor.event_time.isoformat(),
                    neighbor.bssid,
                    neighbor.op_class,
                    neighbor.channel,
                    neighbor.band,
                    neighbor.phy_type,
                    neighbor.info_hex,
                    neighbor.source_line,
                ],
            )
        )

    for sample in badge.radio_signal_samples:
        lines.append(
            _insert(
                "badge_radio_signal_samples",
                [
                    "test_run_id",
                    "source_file_id",
                    "badge_mac",
                    "event_time",
                    "sig_bars",
                    "noise_dbm",
                    "level_dbm",
                    "snr_db",
                    "channel",
                    "band",
                    "bandwidth_mhz",
                    "powersave",
                    "channel_utilization_percent",
                    "source_line",
                ],
                [
                    sample.test_run_id,
                    sample.source_file_id,
                    sample.badge_mac,
                    sample.event_time.isoformat(),
                    sample.sig_bars,
                    sample.noise_dbm,
                    sample.level_dbm,
                    sample.snr_db,
                    sample.channel,
                    sample.band,
                    sample.bandwidth_mhz,
                    sample.powersave,
                    sample.channel_utilization_percent,
                    sample.source_line,
                ],
            )
        )

    for point in ekahau.survey_points:
        sql = _insert(
            "ekahau_survey_points",
            ["survey_point_id", "test_run_id", "source_file_id", "measured_at", "floor", "area", "x_m", "y_m", "source_json_path", "raw_context"],
            [
                point.survey_point_id,
                point.test_run_id,
                point.source_file_id,
                point.measured_at.isoformat(),
                point.floor,
                point.area,
                point.x_m,
                point.y_m,
                point.source_json_path,
                "__RAW_CONTEXT__",
            ],
            conflict="on conflict (survey_point_id) do nothing",
        )
        lines.append(sql.replace(_literal("__RAW_CONTEXT__"), _jsonb(point.raw_context)))

    lines.append(_restore_manual_observations_sql())

    for row in template_rows:
        lines.append(_candidate_match_sql(row))

    # Web-run imports should only create pending candidate rows.  Do not
    # materialize badge_ekahau_matches until a human enters Ekahau RSSI/SNR
    # through the manual-entry workflow.  If a legacy/manual CSV supplies RSSI
    # values, keep supporting that path; blank rows remain candidate-only.
    for match in matches:
        if match.ekahau_rssi_dbm is not None:
            lines.append(_match_sql(match))

    lines.append(_mark_completed_candidates_from_matches_sql(test_run_id))

    lines.append("commit;")
    return "\n".join(lines) + "\n"


def _candidate_match_sql(row: CandidateTemplateRow) -> str:
    """Render one pre-manual-entry candidate match row."""
    return _insert(
        "badge_ekahau_candidate_matches",
        [
            "test_run_id",
            "survey_point_id",
            "badge_event_id",
            "badge_candidate_index",
            "survey_time",
            "ekahau_survey_id",
            "ekahau_survey_name",
            "badge_time",
            "time_delta_seconds",
            "badge_mac",
            "badge_model",
            "ssid",
            "bssid",
            "ap_name",
            "channel",
            "band",
            "badge_rssi_dbm",
            "badge_noise_floor_dbm",
            "badge_snr_db",
            "badge_snr_source",
            "badge_snr_time",
            "badge_snr_time_delta_seconds",
            "badge_radio_signal_level_dbm",
            "badge_cu_percent",
            "badge_score",
            "badge_selected",
            "floor",
            "area",
            "x_m",
            "y_m",
            "match_quality",
            "manual_entry_status",
        ],
        [
            row.test_run_id,
            row.survey_point_id,
            row.badge_event_id,
            row.badge_candidate_index,
            row.survey_time.isoformat(),
            row.ekahau_survey_id,
            row.ekahau_survey_name,
            row.badge_time.isoformat(),
            row.time_delta_seconds,
            row.badge_mac,
            row.badge_model,
            row.ssid,
            row.bssid,
            row.ap_name,
            row.channel,
            row.band,
            row.badge_rssi_dbm,
            row.badge_noise_floor_dbm,
            row.badge_snr_db,
            row.badge_snr_source,
            row.badge_snr_time.isoformat() if row.badge_snr_time else None,
            row.badge_snr_time_delta_seconds,
            row.badge_radio_signal_level_dbm,
            row.badge_cu_percent,
            row.badge_score,
            row.badge_selected,
            row.floor,
            row.area,
            row.x_m,
            row.y_m,
            row.match_quality,
            "pending",
        ],
    )


def _match_sql(match: CorrelatedMatch) -> str:
    """Render one completed/pending correlated match row."""
    return _insert(
        "badge_ekahau_matches",
        [
            "test_run_id",
            "survey_point_id",
            "badge_event_id",
            "badge_candidate_index",
            "badge_time",
            "ekahau_time",
            "ekahau_survey_id",
            "ekahau_survey_name",
            "time_delta_seconds",
            "badge_mac",
            "badge_model",
            "ssid",
            "bssid",
            "ap_name",
            "channel",
            "band",
            "badge_rssi_dbm",
            "badge_noise_floor_dbm",
            "badge_snr_db",
            "badge_snr_source",
            "badge_snr_time",
            "badge_snr_time_delta_seconds",
            "badge_radio_signal_level_dbm",
            "ekahau_rssi_dbm",
            "ekahau_snr_db",
            "vendor_offset_db",
            "expected_badge_rssi_dbm",
            "raw_delta_db",
            "calibrated_delta_db",
            "absolute_calibrated_delta_db",
            "badge_cu_percent",
            "badge_score",
            "badge_selected",
            "floor",
            "area",
            "x_m",
            "y_m",
            "match_quality",
            "manual_entry_status",
        ],
        [
            match.test_run_id,
            match.survey_point_id,
            match.badge_event_id,
            match.badge_candidate_index,
            match.badge_time.isoformat(),
            match.ekahau_time.isoformat(),
            match.ekahau_survey_id,
            match.ekahau_survey_name,
            match.time_delta_seconds,
            match.badge_mac,
            match.badge_model,
            match.ssid,
            match.bssid,
            match.ap_name,
            match.channel,
            match.band,
            match.badge_rssi_dbm,
            match.badge_noise_floor_dbm,
            match.badge_snr_db,
            match.badge_snr_source,
            match.badge_snr_time.isoformat() if match.badge_snr_time else None,
            match.badge_snr_time_delta_seconds,
            match.badge_radio_signal_level_dbm,
            match.ekahau_rssi_dbm,
            match.ekahau_snr_db,
            match.vendor_offset_db,
            match.expected_badge_rssi_dbm,
            match.raw_delta_db,
            match.calibrated_delta_db,
            match.absolute_calibrated_delta_db,
            match.badge_cu_percent,
            match.badge_score,
            match.badge_selected,
            match.floor,
            match.area,
            match.x_m,
            match.y_m,
            match.match_quality,
            match.manual_entry_status,
        ],
    )
