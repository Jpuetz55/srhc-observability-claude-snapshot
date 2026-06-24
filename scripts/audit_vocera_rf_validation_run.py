#!/usr/bin/env python3
"""Audit one Vocera RF validation web run as a data pipeline."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
DECIMAL_TOLERANCE = Decimal("0.000001")
DISPLAY_TIME_TOLERANCE_SECONDS = 0.000001


def sql_literal(value: str | None) -> str:
    """Return a PostgreSQL string literal for simple audit queries."""

    if value is None:
        return "null"
    return "'" + str(value).replace("'", "''") + "'"


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value {value!r}") from exc


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    return int(text)


def parse_bool(value: Any) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text == "":
        return None
    if text in {"1", "t", "true", "y", "yes"}:
        return True
    if text in {"0", "f", "false", "n", "no"}:
        return False
    raise ValueError(f"Invalid boolean value {value!r}")


def text_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def mac_or_none(value: Any) -> str | None:
    text = text_or_none(value)
    return text.lower() if text else None


def parse_timestamp(value: Any) -> datetime | None:
    """Parse ISO or PostgreSQL timestamptz CSV output."""

    text = text_or_none(value)
    if text is None:
        return None
    text = text.replace("Z", "+00:00")
    if re.search(r"[+-]\d{2}$", text):
        text += ":00"
    elif re.search(r"[+-]\d{4}$", text):
        text = text[:-2] + ":" + text[-2:]
    try:
        return datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp value {value!r}") from exc


def utc_timestamp(value: Any) -> datetime | None:
    timestamp = parse_timestamp(value)
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def decimal_equal(left: Decimal | None, right: Decimal | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs(left - right) <= DECIMAL_TOLERANCE


def datetime_equal(left: datetime | None, right: datetime | None) -> bool:
    if left is None or right is None:
        return left is right
    return abs((left - right).total_seconds()) <= DISPLAY_TIME_TOLERANCE_SECONDS


class Audit:
    def __init__(self, *, sample_limit: int) -> None:
        self.sample_limit = sample_limit
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def pass_(self, name: str, detail: str = "") -> None:
        suffix = f": {detail}" if detail else ""
        print(f"PASS {name}{suffix}")

    def fail(self, name: str, detail: str) -> None:
        message = f"{name}: {detail}"
        self.failures.append(message)
        print(f"FAIL {message}")

    def warn(self, name: str, detail: str) -> None:
        message = f"{name}: {detail}"
        self.warnings.append(message)
        print(f"WARN {message}")

    def check(self, condition: bool, name: str, detail: str = "") -> None:
        if condition:
            self.pass_(name, detail)
        else:
            self.fail(name, detail or "condition was false")

    def compare_counters(self, name: str, actual: Counter, expected: Counter) -> None:
        only_actual = actual - expected
        only_expected = expected - actual
        if not only_actual and not only_expected:
            self.pass_(name, f"{sum(actual.values())} row(s)")
            return
        details: list[str] = [
            f"only_in_db={sum(only_actual.values())}",
            f"only_in_artifact={sum(only_expected.values())}",
        ]
        for label, counter in (("ONLY_DB", only_actual), ("ONLY_ARTIFACT", only_expected)):
            for key, count in list(counter.items())[: self.sample_limit]:
                details.append(f"{label} count={count} key={key!r}")
        self.fail(name, "; ".join(details))

    def finish(self) -> int:
        print()
        if self.failures:
            print(f"RF validation audit failed: {len(self.failures)} failure(s), {len(self.warnings)} warning(s).")
            return 1
        print(f"RF validation audit passed: {len(self.warnings)} warning(s).")
        return 0


def default_psql_bin() -> str:
    configured = os.environ.get("VOCERA_RF_VALIDATION_PSQL_BIN", "").strip()
    if configured:
        return configured
    wrapper = ROOT / "scripts" / "vocera_rf_validation_psql_in_container.sh"
    return str(wrapper) if wrapper.exists() else "psql"


def psql_rows(*, psql_bin: str, postgres_url: str, sql: str) -> list[dict[str, str]]:
    completed = subprocess.run(
        [psql_bin, postgres_url, "-X", "-q", "--csv", "-v", "ON_ERROR_STOP=1", "-c", sql],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(detail or f"psql exited {completed.returncode}")
    output = completed.stdout.strip()
    if not output:
        return []
    return list(csv.DictReader(StringIO(output)))


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def candidate_template_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Normalize candidate evidence for same-run DB/template comparison."""

    return (
        utc_timestamp(row.get("survey_time")),
        utc_timestamp(row.get("badge_time")),
        parse_decimal(row.get("time_delta_seconds")),
        text_or_none(row.get("badge_event_id")),
        parse_int(row.get("badge_candidate_index")),
        mac_or_none(row.get("bssid")),
        parse_int(row.get("channel")),
        text_or_none(row.get("band")),
        parse_decimal(row.get("badge_rssi_dbm")),
        parse_decimal(row.get("badge_snr_db")),
        text_or_none(row.get("badge_snr_source")),
    )


def trusted_template_key(row: dict[str, Any]) -> tuple[Any, ...]:
    """Normalize trusted CLI vs web template evidence, ignoring run-scoped IDs."""

    return (
        utc_timestamp(row.get("survey_time")),
        utc_timestamp(row.get("badge_time")),
        parse_decimal(row.get("time_delta_seconds")),
        parse_int(row.get("badge_candidate_index")),
        mac_or_none(row.get("bssid")),
        parse_int(row.get("channel")),
        text_or_none(row.get("band")),
        parse_decimal(row.get("badge_rssi_dbm")),
        parse_decimal(row.get("badge_snr_db")),
        text_or_none(row.get("badge_snr_source")),
    )


def raw_badge_candidate_keys_from_artifact(badge: dict[str, Any]) -> Counter:
    keys = []
    for event in badge.get("events", []):
        for candidate in event.get("candidates", []):
            keys.append(
                (
                    text_or_none(event.get("event_id")),
                    parse_int(candidate.get("candidate_index")),
                    mac_or_none(candidate.get("bssid")),
                    parse_int(candidate.get("channel")),
                    text_or_none(candidate.get("band")),
                    parse_decimal(candidate.get("rssi_dbm")),
                    parse_bool(candidate.get("selected")),
                )
            )
    return Counter(keys)


def raw_badge_candidate_keys_from_db(rows: list[dict[str, str]]) -> Counter:
    return Counter(
        (
            text_or_none(row.get("event_id")),
            parse_int(row.get("candidate_index")),
            mac_or_none(row.get("bssid")),
            parse_int(row.get("channel")),
            text_or_none(row.get("band")),
            parse_decimal(row.get("rssi_dbm")),
            parse_bool(row.get("selected")),
        )
        for row in rows
    )


def survey_point_keys_from_artifact(ekahau: dict[str, Any]) -> Counter:
    return Counter(
        (
            text_or_none(point.get("survey_point_id")),
            utc_timestamp(point.get("measured_at")),
            text_or_none(point.get("floor")),
            text_or_none(point.get("area")),
            parse_decimal(point.get("x_m")),
            parse_decimal(point.get("y_m")),
        )
        for point in ekahau.get("survey_points", [])
    )


def survey_point_keys_from_db(rows: list[dict[str, str]]) -> Counter:
    return Counter(
        (
            text_or_none(row.get("survey_point_id")),
            utc_timestamp(row.get("measured_at")),
            text_or_none(row.get("floor")),
            text_or_none(row.get("area")),
            parse_decimal(row.get("x_m")),
            parse_decimal(row.get("y_m")),
        )
        for row in rows
    )


def load_artifacts(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]]]:
    badge_path = run_dir / "badge.json"
    ekahau_path = run_dir / "ekahau.json"
    template_path = run_dir / "manual-template.csv"
    missing = [str(path) for path in (badge_path, ekahau_path, template_path) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing run artifact(s): " + ", ".join(missing))
    return read_json(badge_path), read_json(ekahau_path), read_csv_rows(template_path)


def audit_artifact_counts(
    audit: Audit,
    *,
    badge: dict[str, Any],
    ekahau: dict[str, Any],
    template_rows: list[dict[str, str]],
    db_counts: dict[str, str],
) -> None:
    badge_candidate_count = sum(len(event.get("candidates", [])) for event in badge.get("events", []))
    expected_counts = {
        "badge_event_count": len(badge.get("events", [])),
        "badge_candidate_count": badge_candidate_count,
        "rrm_neighbor_count": len(badge.get("rrm_neighbors", [])),
        "radio_signal_sample_count": len(badge.get("radio_signal_samples", [])),
        "survey_point_count": len(ekahau.get("survey_points", [])),
        "candidate_match_count": len(template_rows),
    }
    for column, expected in expected_counts.items():
        actual = parse_int(db_counts.get(column)) or 0
        audit.check(actual == expected, f"{column} matches artifacts", f"db={actual} artifact={expected}")


def audit_template_rows(
    audit: Audit,
    *,
    template_rows: list[dict[str, str]],
    candidate_rows: list[dict[str, str]],
) -> None:
    db_counter = Counter(candidate_template_key(row) for row in candidate_rows)
    template_counter = Counter(candidate_template_key(row) for row in template_rows)
    audit.compare_counters("candidate rows match manual-template.csv", db_counter, template_counter)

    nonblank_ekahau = [
        index
        for index, row in enumerate(template_rows, start=2)
        if text_or_none(row.get("ekahau_rssi_dbm")) is not None or text_or_none(row.get("ekahau_snr_db")) is not None
    ]
    audit.check(
        not nonblank_ekahau,
        "manual-template leaves Ekahau RSSI/SNR blank",
        f"nonblank CSV line(s)={nonblank_ekahau[:audit.sample_limit]}",
    )


def audit_raw_imports(
    audit: Audit,
    *,
    badge: dict[str, Any],
    ekahau: dict[str, Any],
    raw_candidate_rows: list[dict[str, str]],
    survey_point_rows: list[dict[str, str]],
) -> None:
    audit.compare_counters(
        "badge_scan_candidates match badge.json",
        raw_badge_candidate_keys_from_db(raw_candidate_rows),
        raw_badge_candidate_keys_from_artifact(badge),
    )
    audit.compare_counters(
        "ekahau_survey_points match ekahau.json",
        survey_point_keys_from_db(survey_point_rows),
        survey_point_keys_from_artifact(ekahau),
    )


def audit_candidate_values(
    audit: Audit,
    *,
    candidate_rows: list[dict[str, str]],
    match_window_seconds: Decimal,
    local_tz: ZoneInfo,
) -> None:
    delta_errors: list[str] = []
    window_errors: list[str] = []
    local_date_errors: list[str] = []
    raw_candidate_errors: list[str] = []
    snr_source_errors: list[str] = []
    display_time_errors: list[str] = []

    for row in candidate_rows:
        candidate_id = text_or_none(row.get("id")) or "unknown"
        stored_delta = parse_decimal(row.get("time_delta_seconds"))
        recomputed_delta = parse_decimal(row.get("recomputed_delta_seconds"))
        if not decimal_equal(stored_delta, recomputed_delta):
            delta_errors.append(f"id={candidate_id} stored={stored_delta} recomputed={recomputed_delta}")
        if stored_delta is not None and abs(stored_delta) > match_window_seconds:
            window_errors.append(f"id={candidate_id} abs_delta={abs(stored_delta)} window={match_window_seconds}")

        survey_time = utc_timestamp(row.get("survey_time"))
        badge_time = utc_timestamp(row.get("badge_time"))
        if survey_time is not None and badge_time is not None:
            if survey_time.astimezone(local_tz).date() != badge_time.astimezone(local_tz).date():
                local_date_errors.append(
                    f"id={candidate_id} survey={survey_time.isoformat()} badge={badge_time.isoformat()}"
                )

            expected_survey_central = survey_time.astimezone(local_tz).replace(tzinfo=None)
            expected_badge_central = badge_time.astimezone(local_tz).replace(tzinfo=None)
            actual_survey_central = parse_timestamp(row.get("survey_time_central"))
            actual_badge_central = parse_timestamp(row.get("badge_time_central"))
            if not datetime_equal(expected_survey_central, actual_survey_central):
                display_time_errors.append(
                    f"id={candidate_id} survey expected={expected_survey_central} db={actual_survey_central}"
                )
            if not datetime_equal(expected_badge_central, actual_badge_central):
                display_time_errors.append(
                    f"id={candidate_id} badge expected={expected_badge_central} db={actual_badge_central}"
                )

        if text_or_none(row.get("raw_scan_bssid")) is None:
            raw_candidate_errors.append(f"id={candidate_id} missing raw badge_scan_candidates row")
        else:
            raw_checks = [
                mac_or_none(row.get("bssid")) == mac_or_none(row.get("raw_scan_bssid")),
                parse_int(row.get("channel")) == parse_int(row.get("raw_scan_channel")),
                decimal_equal(parse_decimal(row.get("badge_rssi_dbm")), parse_decimal(row.get("raw_scan_rssi"))),
                parse_bool(row.get("badge_selected")) == parse_bool(row.get("raw_scan_selected")),
            ]
            if not all(raw_checks):
                raw_candidate_errors.append(
                    "id={id} bssid={bssid}/{raw_bssid} channel={channel}/{raw_channel} "
                    "rssi={rssi}/{raw_rssi} selected={selected}/{raw_selected}".format(
                        id=candidate_id,
                        bssid=row.get("bssid"),
                        raw_bssid=row.get("raw_scan_bssid"),
                        channel=row.get("channel"),
                        raw_channel=row.get("raw_scan_channel"),
                        rssi=row.get("badge_rssi_dbm"),
                        raw_rssi=row.get("raw_scan_rssi"),
                        selected=row.get("badge_selected"),
                        raw_selected=row.get("raw_scan_selected"),
                    )
                )

        if parse_decimal(row.get("badge_snr_db")) is not None and text_or_none(row.get("badge_snr_source")) is None:
            snr_source_errors.append(f"id={candidate_id} badge_snr_db={row.get('badge_snr_db')} has no source")

    audit.check(
        not delta_errors,
        "time_delta_seconds equals badge_time - survey_time",
        "; ".join(delta_errors[: audit.sample_limit]),
    )
    audit.check(
        not window_errors,
        "candidate deltas are within configured match window",
        "; ".join(window_errors[: audit.sample_limit]),
    )
    audit.check(
        not local_date_errors,
        f"candidate matches stay on same {local_tz.key} local date",
        "; ".join(local_date_errors[: audit.sample_limit]),
    )
    audit.check(
        not raw_candidate_errors,
        "candidate rows preserve raw badge scan candidate values",
        "; ".join(raw_candidate_errors[: audit.sample_limit]),
    )
    audit.check(
        not snr_source_errors,
        "badge SNR values carry a source label",
        "; ".join(snr_source_errors[: audit.sample_limit]),
    )
    audit.check(
        not display_time_errors,
        f"database Central display columns match {local_tz.key} conversion",
        "; ".join(display_time_errors[: audit.sample_limit]),
    )


def audit_candidate_status(
    audit: Audit,
    *,
    candidate_rows: list[dict[str, str]],
    run_row: dict[str, str],
    fresh_web_run: bool,
) -> None:
    statuses = Counter(text_or_none(row.get("manual_entry_status")) for row in candidate_rows)
    total = len(candidate_rows)
    pending = statuses.get("pending", 0)
    complete = statuses.get("complete", 0)
    unknown = {status: count for status, count in statuses.items() if status not in {"pending", "complete"}}

    audit.check(not unknown, "candidate manual_entry_status values are known", f"unknown={unknown}")
    audit.check(pending + complete == total, "pending + complete equals candidate total", f"pending={pending} complete={complete} total={total}")

    if fresh_web_run:
        candidate_count = parse_int(run_row.get("candidate_match_count")) or 0
        completed_count = parse_int(run_row.get("completed_match_count")) or 0
        manual_count = parse_int(run_row.get("manual_observation_count")) or 0
        audit.check(candidate_count > 0, "fresh web run produced candidate rows", f"candidate_match_count={candidate_count}")
        audit.check(pending == candidate_count, "fresh web run candidates are pending", f"pending={pending} total={candidate_count}")
        audit.check(completed_count == 0, "fresh web run has no completed matches", f"completed_match_count={completed_count}")
        audit.check(manual_count == 0, "fresh web run has no manual observations", f"manual_observation_count={manual_count}")


def audit_manual_matches(
    audit: Audit,
    *,
    match_rows: list[dict[str, str]],
    integrity_row: dict[str, str],
) -> None:
    link_errors: list[str] = []
    math_errors: list[str] = []
    observation_errors: list[str] = []

    for row in match_rows:
        match_id = text_or_none(row.get("match_id")) or "unknown"
        status = text_or_none(row.get("manual_entry_status"))
        if status in {"complete", "missing_vendor_offset"}:
            if text_or_none(row.get("candidate_match_id")) is None or text_or_none(row.get("candidate_test_run_id")) != text_or_none(row.get("test_run_id")):
                link_errors.append(f"match_id={match_id} candidate_run={row.get('candidate_test_run_id')}")
            if text_or_none(row.get("observation_id")) is None or text_or_none(row.get("observation_test_run_id")) != text_or_none(row.get("test_run_id")):
                observation_errors.append(f"match_id={match_id} observation_run={row.get('observation_test_run_id')}")
            if not decimal_equal(parse_decimal(row.get("ekahau_rssi_dbm")), parse_decimal(row.get("observation_rssi_dbm"))):
                observation_errors.append(
                    f"match_id={match_id} match_rssi={row.get('ekahau_rssi_dbm')} observation_rssi={row.get('observation_rssi_dbm')}"
                )
            if not decimal_equal(parse_decimal(row.get("ekahau_snr_db")), parse_decimal(row.get("observation_snr_db"))):
                observation_errors.append(
                    f"match_id={match_id} match_snr={row.get('ekahau_snr_db')} observation_snr={row.get('observation_snr_db')}"
                )

        badge_rssi = parse_decimal(row.get("badge_rssi_dbm"))
        ekahau_rssi = parse_decimal(row.get("ekahau_rssi_dbm"))
        vendor_offset = parse_decimal(row.get("vendor_offset_db"))
        expected_badge = parse_decimal(row.get("expected_badge_rssi_dbm"))
        raw_delta = parse_decimal(row.get("raw_delta_db"))
        calibrated_delta = parse_decimal(row.get("calibrated_delta_db"))
        absolute_calibrated_delta = parse_decimal(row.get("absolute_calibrated_delta_db"))

        expected_calc = ekahau_rssi + vendor_offset if ekahau_rssi is not None and vendor_offset is not None else None
        raw_calc = badge_rssi - ekahau_rssi if badge_rssi is not None and ekahau_rssi is not None else None
        calibrated_calc = badge_rssi - expected_calc if badge_rssi is not None and expected_calc is not None else None
        absolute_calc = abs(calibrated_calc) if calibrated_calc is not None else None
        if not decimal_equal(expected_badge, expected_calc):
            math_errors.append(f"match_id={match_id} expected_badge={expected_badge} calc={expected_calc}")
        if not decimal_equal(raw_delta, raw_calc):
            math_errors.append(f"match_id={match_id} raw_delta={raw_delta} calc={raw_calc}")
        if not decimal_equal(calibrated_delta, calibrated_calc):
            math_errors.append(f"match_id={match_id} calibrated_delta={calibrated_delta} calc={calibrated_calc}")
        if not decimal_equal(absolute_calibrated_delta, absolute_calc):
            math_errors.append(f"match_id={match_id} absolute_calibrated_delta={absolute_calibrated_delta} calc={absolute_calc}")

    completed_count = sum(1 for row in match_rows if text_or_none(row.get("manual_entry_status")) in {"complete", "missing_vendor_offset"})
    audit.check(not link_errors, "completed matches link to same-run candidate rows", "; ".join(link_errors[: audit.sample_limit]))
    audit.check(not observation_errors, "completed matches link to same-run manual observations", "; ".join(observation_errors[: audit.sample_limit]))
    audit.check(not math_errors, "manual-entry offset and delta math is correct", "; ".join(math_errors[: audit.sample_limit]))
    audit.pass_("completed match rows audited", str(completed_count))

    integrity_errors = {
        key: parse_int(integrity_row.get(key)) or 0
        for key in (
            "orphan_manual_observation_count",
            "completed_candidate_without_match_count",
            "pending_candidate_with_observation_count",
            "cross_run_link_count",
        )
    }
    bad_integrity = {key: value for key, value in integrity_errors.items() if value}
    audit.check(not bad_integrity, "manual-entry referential integrity is run-scoped", str(bad_integrity))


def audit_trusted_template(
    audit: Audit,
    *,
    web_template_rows: list[dict[str, str]],
    trusted_run_dir: Path,
) -> None:
    trusted_template_path = trusted_run_dir / "manual-template.csv"
    if not trusted_template_path.is_file():
        audit.fail("trusted CLI template exists", f"missing {trusted_template_path}")
        return
    trusted_rows = read_csv_rows(trusted_template_path)
    audit.compare_counters(
        "web manual-template.csv matches trusted CLI template",
        Counter(trusted_template_key(row) for row in web_template_rows),
        Counter(trusted_template_key(row) for row in trusted_rows),
    )


def run_audit(args: argparse.Namespace) -> int:
    audit = Audit(sample_limit=args.sample_limit)
    run_id_literal = sql_literal(args.run_id)

    badge, ekahau, template_rows = load_artifacts(args.run_dir)

    run_rows = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  test_run_id,
  run_status,
  badge_file,
  ekahau_file,
  badge_event_count,
  survey_point_count,
  candidate_match_count,
  pending_candidate_match_count,
  completed_match_count,
  manual_observation_count,
  coalesce(default_match_window_seconds, 1) as default_match_window_seconds,
  coalesce(timezone, 'America/Chicago') as timezone
from v_vocera_rf_validation_runs
where test_run_id = {run_id_literal};
""",
    )
    if not run_rows:
        audit.fail("run exists in v_vocera_rf_validation_runs", f"test_run_id={args.run_id}")
        return audit.finish()
    run_row = run_rows[0]
    timezone_name = args.timezone or run_row.get("timezone") or "America/Chicago"
    local_tz = ZoneInfo(timezone_name)
    match_window = parse_decimal(run_row.get("default_match_window_seconds")) or Decimal("1")

    audit.pass_("run state loaded", f"run_status={run_row.get('run_status')} timezone={timezone_name} match_window={match_window}")

    db_counts = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  (select count(*) from badge_scan_events where test_run_id = {run_id_literal})::integer as badge_event_count,
  (
    select count(*)
    from badge_scan_candidates sc
    join badge_scan_events e
      on e.event_id = sc.event_id
    where e.test_run_id = {run_id_literal}
  )::integer as badge_candidate_count,
  (select count(*) from badge_rrm_neighbors where test_run_id = {run_id_literal})::integer as rrm_neighbor_count,
  (select count(*) from badge_radio_signal_samples where test_run_id = {run_id_literal})::integer as radio_signal_sample_count,
  (select count(*) from ekahau_survey_points where test_run_id = {run_id_literal})::integer as survey_point_count,
  (select count(*) from badge_ekahau_candidate_matches where test_run_id = {run_id_literal})::integer as candidate_match_count;
""",
    )[0]

    candidate_rows = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  c.id::text as id,
  c.test_run_id,
  c.survey_point_id,
  c.badge_event_id,
  c.badge_candidate_index::text as badge_candidate_index,
  c.survey_time,
  c.survey_time at time zone {sql_literal(timezone_name)} as survey_time_central,
  c.badge_time,
  c.badge_time at time zone {sql_literal(timezone_name)} as badge_time_central,
  round(extract(epoch from (c.badge_time - c.survey_time))::numeric, 6) as recomputed_delta_seconds,
  c.time_delta_seconds,
  abs(c.time_delta_seconds) as abs_delta_seconds,
  c.match_quality,
  c.bssid,
  c.ap_name,
  c.channel::text as channel,
  c.band,
  c.badge_rssi_dbm,
  c.badge_noise_floor_dbm,
  c.badge_snr_db,
  c.badge_snr_source,
  c.badge_snr_time,
  c.badge_snr_time_delta_seconds,
  c.badge_radio_signal_level_dbm,
  c.badge_cu_percent,
  c.badge_score,
  c.badge_selected,
  c.manual_entry_status,
  sc.bssid as raw_scan_bssid,
  sc.channel::text as raw_scan_channel,
  sc.rssi_dbm as raw_scan_rssi,
  sc.selected as raw_scan_selected
from badge_ekahau_candidate_matches c
left join badge_scan_candidates sc
  on sc.event_id = c.badge_event_id
 and sc.candidate_index = c.badge_candidate_index
where c.test_run_id = {run_id_literal}
order by c.survey_time, c.badge_candidate_index, c.bssid, c.id;
""",
    )

    raw_candidate_rows = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  e.event_id,
  sc.candidate_index::text as candidate_index,
  sc.bssid,
  sc.channel::text as channel,
  sc.band,
  sc.rssi_dbm,
  sc.selected
from badge_scan_events e
join badge_scan_candidates sc
  on sc.event_id = e.event_id
where e.test_run_id = {run_id_literal}
order by e.event_time, sc.candidate_index, sc.bssid;
""",
    )

    survey_point_rows = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  survey_point_id,
  measured_at,
  floor,
  area,
  x_m,
  y_m
from ekahau_survey_points
where test_run_id = {run_id_literal}
order by measured_at, survey_point_id;
""",
    )

    match_rows = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  m.id::text as match_id,
  m.test_run_id,
  m.candidate_match_id::text as candidate_match_id,
  c.test_run_id as candidate_test_run_id,
  m.ekahau_observation_id::text as ekahau_observation_id,
  m.bssid,
  m.band,
  m.badge_rssi_dbm,
  m.ekahau_rssi_dbm,
  m.vendor_offset_db,
  m.expected_badge_rssi_dbm,
  m.raw_delta_db,
  m.calibrated_delta_db,
  m.absolute_calibrated_delta_db,
  m.ekahau_snr_db,
  m.manual_entry_status,
  o.id::text as observation_id,
  o.test_run_id as observation_test_run_id,
  o.rssi_dbm as observation_rssi_dbm,
  o.snr_db as observation_snr_db
from badge_ekahau_matches m
left join badge_ekahau_candidate_matches c
  on c.id = m.candidate_match_id
left join manual_ekahau_observations o
  on o.id = m.ekahau_observation_id
where m.test_run_id = {run_id_literal}
order by m.ekahau_time, m.bssid, m.id;
""",
    )

    integrity_row = psql_rows(
        psql_bin=args.psql_bin,
        postgres_url=args.postgres_url,
        sql=f"""
select
  (
    select count(*)
    from manual_ekahau_observations o
    where o.test_run_id = {run_id_literal}
      and not exists (
        select 1
        from badge_ekahau_matches m
        where m.test_run_id = o.test_run_id
          and m.ekahau_observation_id = o.id
      )
  )::integer as orphan_manual_observation_count,
  (
    select count(*)
    from badge_ekahau_candidate_matches c
    where c.test_run_id = {run_id_literal}
      and c.manual_entry_status = 'complete'
      and not exists (
        select 1
        from badge_ekahau_matches m
        where m.test_run_id = c.test_run_id
          and m.candidate_match_id = c.id
          and m.manual_entry_status in ('complete', 'missing_vendor_offset')
      )
  )::integer as completed_candidate_without_match_count,
  (
    select count(*)
    from badge_ekahau_candidate_matches c
    where c.test_run_id = {run_id_literal}
      and c.manual_entry_status = 'pending'
      and exists (
        select 1
        from manual_ekahau_observations o
        where o.test_run_id = c.test_run_id
          and lower(o.bssid) = lower(c.bssid)
          and o.measured_at = c.survey_time
      )
  )::integer as pending_candidate_with_observation_count,
  (
    select count(*)
    from badge_ekahau_matches m
    join badge_ekahau_candidate_matches c
      on c.id = m.candidate_match_id
    where m.test_run_id = {run_id_literal}
      and c.test_run_id <> m.test_run_id
  )::integer as cross_run_link_count,
  (
    select count(*)
    from (
      select distinct c.bssid, c.survey_time, other.test_run_id
      from badge_ekahau_candidate_matches c
      join badge_ekahau_candidate_matches other
        on other.test_run_id <> c.test_run_id
       and lower(other.bssid) = lower(c.bssid)
       and other.survey_time = c.survey_time
      where c.test_run_id = {run_id_literal}
    ) collisions
  )::integer as cross_run_collision_count;
""",
    )[0]

    audit_artifact_counts(audit, badge=badge, ekahau=ekahau, template_rows=template_rows, db_counts=db_counts)
    audit_raw_imports(
        audit,
        badge=badge,
        ekahau=ekahau,
        raw_candidate_rows=raw_candidate_rows,
        survey_point_rows=survey_point_rows,
    )
    audit_template_rows(audit, template_rows=template_rows, candidate_rows=candidate_rows)
    audit_candidate_values(
        audit,
        candidate_rows=candidate_rows,
        match_window_seconds=match_window,
        local_tz=local_tz,
    )
    audit_candidate_status(audit, candidate_rows=candidate_rows, run_row=run_row, fresh_web_run=args.expect_fresh_web_run)
    audit_manual_matches(audit, match_rows=match_rows, integrity_row=integrity_row)

    collision_count = parse_int(integrity_row.get("cross_run_collision_count")) or 0
    if collision_count and args.fail_on_cross_run_collisions:
        audit.fail("no cross-run BSSID/timestamp collisions exist", f"collision_count={collision_count}")
    elif collision_count:
        audit.warn(
            "cross-run BSSID/timestamp collisions exist",
            f"collision_count={collision_count}; patched SQL must remain run-scoped",
        )
    else:
        audit.pass_("no cross-run BSSID/timestamp collisions detected")

    if args.trusted_run_dir:
        audit_trusted_template(audit, web_template_rows=template_rows, trusted_run_dir=args.trusted_run_dir)

    return audit.finish()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="RF validation test_run_id to audit.")
    parser.add_argument("--postgres-url", required=True, help="PostgreSQL connection URL.")
    parser.add_argument("--run-dir", required=True, type=Path, help="Run artifact directory containing badge.json, ekahau.json, and manual-template.csv.")
    parser.add_argument("--trusted-run-dir", type=Path, help="Optional old CLI artifact directory to compare against the web run template.")
    parser.add_argument("--psql-bin", default=default_psql_bin(), help="psql executable or repo wrapper script.")
    parser.add_argument("--timezone", help="Local display/matching timezone. Defaults to the run timezone, then America/Chicago.")
    parser.add_argument("--expect-fresh-web-run", action="store_true", help="Require all candidates to be pending and no manual/completed rows to exist.")
    parser.add_argument("--fail-on-cross-run-collisions", action="store_true", help="Fail if another run has the same BSSID and survey timestamp.")
    parser.add_argument("--sample-limit", type=int, default=10, help="Maximum mismatch samples to print per failed invariant.")
    return parser.parse_args()


def main() -> int:
    try:
        return run_audit(parse_args())
    except Exception as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
