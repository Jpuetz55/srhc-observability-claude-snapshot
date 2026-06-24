"""Small web UI for Vocera RF validation study lifecycle operations.

This intentionally uses only the Python standard library and the existing psql
wrapper. The workflow is operational CRUD around PostgreSQL rows; keeping it
outside Grafana avoids plugin-specific action semantics and preserves useful
database error messages.
"""

from __future__ import annotations

import csv
import html
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCOPE = "vocera_badge"
DEFAULT_USER = "study_web"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8097


def sql_literal(value: str | None) -> str:
    if value is None:
        return "null"
    stripped = value.strip()
    if stripped == "":
        return "null"
    return "'" + stripped.replace("'", "''") + "'"


def h(value: Any) -> str:
    if value is None:
        return ""
    return html.escape(str(value), quote=True)


class Db:
    def __init__(self) -> None:
        credential_name = "VOCERA_RF_VALIDATION_POSTGRES_" + "PASSWORD"
        credential = os.environ.get(credential_name, "")
        self.url = os.environ.get(
            "VOCERA_RF_VALIDATION_DATABASE_URL",
            f"postgresql://vocera_rf_validation:{credential or 'unused'}@127.0.0.1:15433/vocera_rf_validation",
        )
        self.psql_bin = os.environ.get(
            "VOCERA_RF_VALIDATION_PSQL_BIN",
            str(ROOT / "scripts" / "vocera_rf_validation_psql_in_container.sh"),
        )

    def rows(self, sql: str) -> list[dict[str, str]]:
        completed = subprocess.run(
            [
                self.psql_bin,
                self.url,
                "-X",
                "-q",
                "--csv",
                "-v",
                "ON_ERROR_STOP=1",
                "-c",
                sql,
            ],
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

    def one(self, sql: str) -> dict[str, str]:
        rows = self.rows(sql)
        return rows[0] if rows else {}


def backend_status_sql() -> str:
    return """
select
  case
    when to_regclass('public.vocera_projects') is null then 'schema update required'
    when to_regclass('public.vocera_studies') is null then 'schema update required'
    when to_regclass('public.vocera_rf_validation_input_files') is null then 'schema update required'
    when to_regclass('public.vocera_rf_validation_run_input_files') is null then 'schema update required'
    when to_regclass('public.vocera_rf_manual_samples') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_validation_input_files') is null then 'schema update required'
    when to_regclass('public.v_vocera_projects') is null then 'schema update required'
    when to_regclass('public.v_vocera_studies') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_project_canonical_completed_matches') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_project_duplicate_datapoints') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_validation_runs') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_validation_run_files') is null then 'schema update required'
    when to_regclass('public.v_vocera_rf_manual_samples') is null then 'schema update required'
    when to_regprocedure('public.vocera_rf_validation_delete_run(text,text)') is null then 'schema update required'
    else 'ready'
  end as backend_status,
  case when to_regclass('public.vocera_projects') is not null then 'ok' else 'missing' end as project_table,
  case when to_regclass('public.vocera_studies') is not null then 'ok' else 'missing' end as study_table,
  case when to_regclass('public.vocera_rf_validation_input_files') is not null then 'ok' else 'missing' end as input_file_table,
  case when to_regclass('public.vocera_rf_validation_run_input_files') is not null then 'ok' else 'missing' end as run_input_file_table,
  case when to_regclass('public.vocera_rf_manual_samples') is not null then 'ok' else 'missing' end as manual_sample_table,
  case when to_regclass('public.v_vocera_rf_validation_input_files') is not null then 'ok' else 'missing' end as input_file_view,
  case when to_regclass('public.v_vocera_projects') is not null then 'ok' else 'missing' end as project_view,
  case when to_regclass('public.v_vocera_studies') is not null then 'ok' else 'missing' end as study_view,
  case when to_regclass('public.v_vocera_rf_project_canonical_completed_matches') is not null then 'ok' else 'missing' end as project_canonical_view,
  case when to_regclass('public.v_vocera_rf_project_duplicate_datapoints') is not null then 'ok' else 'missing' end as project_duplicate_view,
  case when to_regclass('public.v_vocera_rf_validation_runs') is not null then 'ok' else 'missing' end as run_view,
  case when to_regclass('public.v_vocera_rf_validation_run_files') is not null then 'ok' else 'missing' end as run_file_view,
  case when to_regclass('public.v_vocera_rf_manual_samples') is not null then 'ok' else 'missing' end as manual_sample_view,
  case when to_regprocedure('public.vocera_rf_validation_delete_run(text,text)') is not null then 'ok' else 'missing' end as run_delete_function;
"""


def current_study_sql(scope: str) -> str:
    return f"""
select
  study_scope,
  coalesce(study_name, '') as study_name,
  study_started_at,
  study_started_by,
  test_run_count,
  candidate_match_count,
  pending_candidate_match_count,
  completed_match_count,
  manual_observation_count,
  archive_count,
  coalesce(study_notes, '') as study_notes,
  coalesce(source_archive_id, '') as source_archive_id,
  coalesce(source_archive_label, '') as source_archive_label,
  source_archive_saved_at
from v_vocera_rf_validation_current_study
where study_scope = {sql_literal(scope)};
"""


def live_runs_sql(scope: str) -> str:
    return f"""
select
  tr.test_run_id,
  coalesce(tr.run_name, tr.test_run_id) as run_name,
  tr.run_status,
  tr.created_at,
  tr.badge_mac,
  tr.badge_model,
  tr.ekahau_project,
  coalesce(events.badge_event_count, 0) as badge_event_count,
  coalesce(points.survey_point_count, 0) as survey_point_count,
  coalesce(candidates.candidate_match_count, 0) as candidate_match_count,
  coalesce(candidates.pending_candidate_match_count, 0) as pending_candidate_match_count,
  coalesce(matches.completed_match_count, 0) as completed_match_count,
  coalesce(manual.manual_observation_count, 0) as manual_observation_count
from validation_test_runs tr
left join (
  select test_run_id, count(*)::integer as badge_event_count
  from badge_scan_events
  group by test_run_id
) events on events.test_run_id = tr.test_run_id
left join (
  select test_run_id, count(*)::integer as survey_point_count
  from ekahau_survey_points
  group by test_run_id
) points on points.test_run_id = tr.test_run_id
left join (
  select
    test_run_id,
    count(*)::integer as candidate_match_count,
    count(*) filter (where manual_entry_status = 'pending')::integer as pending_candidate_match_count
  from badge_ekahau_candidate_matches
  group by test_run_id
) candidates on candidates.test_run_id = tr.test_run_id
left join (
  select test_run_id, count(*)::integer as completed_match_count
  from badge_ekahau_matches
  group by test_run_id
) matches on matches.test_run_id = tr.test_run_id
left join (
  select test_run_id, count(*)::integer as manual_observation_count
  from manual_ekahau_observations
  group by test_run_id
) manual on manual.test_run_id = tr.test_run_id
where vocera_rf_validation_study_scope(tr.test_run_id) = {sql_literal(scope)}
  and tr.deleted_at is null
order by tr.created_at desc, tr.test_run_id desc
limit 100;
"""


def archives_sql(scope: str, user: str) -> str:
    return f"""
select
  case when s.archive_id is null then 'false' else 'true' end as combine_selected,
  a.archive_id,
  a.archived_at,
  a.archive_label,
  a.archived_by,
  a.updated_at,
  a.updated_by,
  a.test_run_count,
  a.candidate_match_count,
  a.completed_match_count,
  a.manual_observation_count,
  case
    when a.payload ? 'combined_from' then jsonb_array_length(coalesce(a.payload->'combined_from', '[]'::jsonb))
    else null::integer
  end as source_archive_count,
  a.first_badge_time,
  a.last_badge_time,
  a.first_survey_time,
  a.last_survey_time,
  a.notes
from vocera_rf_validation_study_archives a
left join vocera_rf_validation_study_archive_selections s
  on s.archive_id = a.archive_id
 and s.selection_owner = {sql_literal(user)}
 and s.study_scope = {sql_literal(scope)}
where a.study_scope = {sql_literal(scope)}
  and coalesce(a.archive_label, '') not like 'Checkpoint before restoring %'
order by a.archived_at desc
limit 100;
"""


def selection_sql(scope: str, user: str) -> str:
    return f"""
select
  count(*)::integer as selected_archive_count,
  coalesce(sum(test_run_count), 0)::integer as source_test_run_total,
  coalesce(sum(candidate_match_count), 0)::integer as source_candidate_total,
  coalesce(sum(completed_match_count), 0)::integer as source_completed_total,
  coalesce(string_agg(coalesce(archive_label, archive_id), E'\\n' order by selected_at, archive_id), '') as source_labels
from v_vocera_rf_validation_study_archive_selection
where study_scope = {sql_literal(scope)}
  and selection_owner = {sql_literal(user)};
"""


def safe_rows(db: Db, sql: str) -> tuple[list[dict[str, str]], str | None]:
    try:
        return db.rows(sql), None
    except Exception as exc:  # noqa: BLE001 - surface DB errors to operator
        return [], str(exc)


def safe_one(db: Db, sql: str) -> tuple[dict[str, str], str | None]:
    rows, error = safe_rows(db, sql)
    return (rows[0] if rows else {}), error


def table(rows: list[dict[str, str]], columns: list[tuple[str, str]]) -> str:
    if not rows:
        return '<p class="empty">No rows.</p>'
    head = "".join(f"<th>{h(label)}</th>" for _, label in columns)
    body = []
    for row in rows:
        cells = "".join(f"<td>{h(row.get(key, ''))}</td>" for key, _ in columns)
        body.append(f"<tr>{cells}</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def text_input(name: str, value: str = "", *, size: int = 36, placeholder: str = "") -> str:
    return f'<input type="text" name="{h(name)}" value="{h(value)}" size="{size}" placeholder="{h(placeholder)}">'


def textarea(name: str, value: str = "", *, rows: int = 2) -> str:
    return f'<textarea name="{h(name)}" rows="{rows}">{h(value)}</textarea>'


def render_archive_forms(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<p class="empty">No archived studies yet. Archive Current first.</p>'
    forms: list[str] = []
    for row in rows:
        checked = "checked" if row.get("combine_selected") == "true" else ""
        forms.append(
            f"""
<form method="post" class="archive-row">
  <input type="hidden" name="form" value="archive_update">
  <input type="hidden" name="archive_id" value="{h(row.get('archive_id', ''))}">
  <div class="archive-title"><code>{h(row.get('archive_id', ''))}</code></div>
  <label>Combine <input type="checkbox" name="combine_selected" value="true" {checked}></label>
  <label>Delete <input type="checkbox" name="delete_archive" value="true"></label>
  <label>Label {text_input('archive_label', row.get('archive_label', ''), size=28)}</label>
  <label>Notes {textarea('notes', row.get('notes', ''), rows=1)}</label>
  <button type="submit">Save Archive Row</button>
  <div class="meta">
    archived={h(row.get('archived_at', ''))}
    runs={h(row.get('test_run_count', ''))}
    candidates={h(row.get('candidate_match_count', ''))}
    completed={h(row.get('completed_match_count', ''))}
    sources={h(row.get('source_archive_count', ''))}
  </div>
</form>
"""
        )
    return "\n".join(forms)


def render_page(db: Db, params: dict[str, list[str]]) -> str:
    scope = os.environ.get("VOCERA_RF_STUDY_WEB_SCOPE", DEFAULT_SCOPE)
    user = os.environ.get("VOCERA_RF_STUDY_WEB_USER", DEFAULT_USER)
    message = params.get("message", [""])[0]
    status = params.get("status", [""])[0]

    backend, backend_error = safe_one(db, backend_status_sql())
    current, current_error = safe_one(db, current_study_sql(scope))
    runs, runs_error = safe_rows(db, live_runs_sql(scope))
    archives, archives_error = safe_rows(db, archives_sql(scope, user))
    selection, selection_error = safe_one(db, selection_sql(scope, user))

    errors = [err for err in [backend_error, current_error, runs_error, archives_error, selection_error] if err]
    banner = ""
    if message:
        banner = f'<div class="banner {h(status or "info")}">{h(message)}</div>'
    error_html = "".join(f'<div class="banner error">{h(err)}</div>' for err in errors)

    current_name = current.get("study_name", "")
    current_notes = current.get("study_notes", "")
    selected_count = selection.get("selected_archive_count", "0") or "0"

    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vocera RF Validation Study Manager</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; color: #172026; background: #f7f8fa; }}
    h1 {{ margin: 0 0 6px; font-size: 24px; }}
    h2 {{ margin-top: 28px; font-size: 18px; }}
    .subtle, .meta {{ color: #667085; font-size: 12px; }}
    .panel {{ background: #fff; border: 1px solid #d8dee8; border-radius: 8px; padding: 16px; margin: 14px 0; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; }}
    .stat {{ background: #f2f4f7; border-radius: 6px; padding: 10px; }}
    .stat strong {{ display: block; font-size: 20px; }}
    label {{ display: block; margin: 8px 0; }}
    input[type=text], textarea, select {{ width: 100%; box-sizing: border-box; padding: 7px; border: 1px solid #c7ced9; border-radius: 5px; }}
    button {{ border: 0; background: #2563eb; color: white; padding: 8px 12px; border-radius: 5px; cursor: pointer; margin: 4px 4px 4px 0; }}
    button.danger {{ background: #b42318; }}
    button.secondary {{ background: #475467; }}
    .banner {{ padding: 10px 12px; border-radius: 6px; margin: 10px 0; background: #e0f2fe; border: 1px solid #7dd3fc; }}
    .banner.error {{ background: #fee4e2; border-color: #fda29b; white-space: pre-wrap; }}
    .banner.ok {{ background: #dcfae6; border-color: #75e0a7; }}
    .table-wrap {{ overflow-x: auto; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e4e7ec; text-align: left; padding: 7px 9px; vertical-align: top; }}
    th {{ background: #f2f4f7; position: sticky; top: 0; }}
    code {{ font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }}
    .archive-row {{ border-top: 1px solid #e4e7ec; padding: 12px 0; }}
    .archive-title {{ margin-bottom: 6px; }}
    .inline form {{ display: inline-block; }}
    .empty {{ color: #667085; }}
  </style>
</head>
<body>
  <h1>Vocera RF Validation Study Manager</h1>
  <div class="subtle">Scope: <code>{h(scope)}</code> | Selection owner: <code>{h(user)}</code></div>
  {banner}
  {error_html}

  <section class="panel">
    <h2>Backend Status</h2>
    {table([backend] if backend else [], [
      ("backend_status", "Status"),
      ("project_table", "Project Table"),
      ("study_table", "Study Table"),
      ("input_file_table", "Input File Table"),
      ("run_input_file_table", "Run File Table"),
      ("project_canonical_view", "Canonical Results"),
      ("project_duplicate_view", "Duplicate Warnings"),
      ("run_delete_function", "Run Delete"),
    ])}
  </section>

  <section class="panel">
    <h2>Current Study</h2>
    <div class="grid">
      <div class="stat"><span>Study</span><strong>{h(current_name or "(unnamed)")}</strong></div>
      <div class="stat"><span>Runs</span><strong>{h(current.get("test_run_count", "0"))}</strong></div>
      <div class="stat"><span>Candidates</span><strong>{h(current.get("candidate_match_count", "0"))}</strong></div>
      <div class="stat"><span>Pending</span><strong>{h(current.get("pending_candidate_match_count", "0"))}</strong></div>
      <div class="stat"><span>Completed</span><strong>{h(current.get("completed_match_count", "0"))}</strong></div>
      <div class="stat"><span>Archives</span><strong>{h(current.get("archive_count", "0"))}</strong></div>
    </div>
    <form method="post">
      <input type="hidden" name="form" value="set_current">
      <label>Study Name {text_input("study_name", current_name, placeholder="June basement validation")}</label>
      <label>Notes {textarea("notes", current_notes)}</label>
      <button type="submit">Save Study Name</button>
    </form>
    <div class="inline">
      <form method="post"><input type="hidden" name="form" value="current_action"><input type="hidden" name="action_key" value="archive_current"><button type="submit">Archive Current</button></form>
      <form method="post"><input type="hidden" name="form" value="current_action"><input type="hidden" name="action_key" value="archive_and_clear"><button class="danger" type="submit">Archive + Clear Current</button></form>
      <form method="post"><input type="hidden" name="form" value="current_action"><input type="hidden" name="action_key" value="clear_current"><button class="danger" type="submit">Clear Current</button></form>
    </div>
  </section>

  <section class="panel">
    <h2>Live Parser Runs</h2>
    {table(runs, [
      ("test_run_id", "Run ID"),
      ("created_at", "Created"),
      ("badge_mac", "Badge MAC"),
      ("badge_event_count", "Badge Events"),
      ("survey_point_count", "Survey Points"),
      ("candidate_match_count", "Candidates"),
      ("pending_candidate_match_count", "Pending"),
      ("completed_match_count", "Completed"),
      ("manual_observation_count", "Manual"),
    ])}
  </section>

  <section class="panel">
    <h2>Combine Archived Studies</h2>
    <div class="grid">
      <div class="stat"><span>Selected Archives</span><strong>{h(selected_count)}</strong></div>
      <div class="stat"><span>Source Runs</span><strong>{h(selection.get("source_test_run_total", "0"))}</strong></div>
      <div class="stat"><span>Source Candidates</span><strong>{h(selection.get("source_candidate_total", "0"))}</strong></div>
      <div class="stat"><span>Source Completed</span><strong>{h(selection.get("source_completed_total", "0"))}</strong></div>
    </div>
    <p class="subtle">Selected studies:<br>{h(selection.get("source_labels", "")).replace(chr(10), "<br>")}</p>
    <form method="post">
      <input type="hidden" name="form" value="combine_create">
      <label>New Study Name {text_input("archive_label", "", placeholder="Combined June baseline")}</label>
      <label>Notes {textarea("notes", "")}</label>
      <button type="submit">Create Combined Study</button>
    </form>
    <form method="post">
      <input type="hidden" name="form" value="selection_clear">
      <button class="secondary" type="submit">Clear Selection</button>
    </form>
  </section>

  <section class="panel">
    <h2>RF Study Archives</h2>
    {render_archive_forms(archives)}
  </section>
</body>
</html>"""


def success_url(row: dict[str, str], default: str = "ok") -> str:
    status = row.get("status") or default
    message = row.get("message") or status
    return "/?" + urlencode({"status": "ok" if status not in {"error", "not_found"} else "error", "message": message})


def error_url(message: str) -> str:
    return "/?" + urlencode({"status": "error", "message": message})


def first(form: dict[str, list[str]], key: str, default: str = "") -> str:
    return form.get(key, [default])[0]


def handle_post(db: Db, form: dict[str, list[str]]) -> str:
    scope = os.environ.get("VOCERA_RF_STUDY_WEB_SCOPE", DEFAULT_SCOPE)
    user = os.environ.get("VOCERA_RF_STUDY_WEB_USER", DEFAULT_USER)
    form_name = first(form, "form")

    if form_name == "set_current":
        row = db.one(
            "select status, study_scope, study_name, message "
            f"from vocera_rf_validation_set_current_study({sql_literal(first(form, 'study_name'))}, {sql_literal(first(form, 'notes'))}, {sql_literal(user)}, {sql_literal(scope)});"
        )
        return success_url(row)

    if form_name == "current_action":
        row = db.one(
            "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
            f"from vocera_rf_validation_apply_current_study_action({sql_literal(first(form, 'action_key'))}, null, null, {sql_literal(user)}, {sql_literal(scope)});"
        )
        return success_url(row)

    if form_name == "archive_update":
        combine = "true" if first(form, "combine_selected") == "true" else "false"
        if first(form, "delete_archive") == "true":
            row = db.one(
                "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
                f"from vocera_rf_validation_delete_study_archive({sql_literal(first(form, 'archive_id'))}, {sql_literal(user)});"
            )
        else:
            row = db.one(
                "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message "
                f"from vocera_rf_validation_update_study_archive({sql_literal(first(form, 'archive_id'))}, {sql_literal(first(form, 'archive_label'))}, {sql_literal(first(form, 'notes'))}, {sql_literal(user)}, {sql_literal(combine)});"
            )
        return success_url(row)

    if form_name == "combine_create":
        row = db.one(
            "select status, archive_id, source_archive_count, test_run_count, candidate_match_count, completed_match_count, message "
            f"from vocera_rf_validation_create_combined_study_archive({sql_literal(first(form, 'archive_label'))}, {sql_literal(first(form, 'notes'))}, {sql_literal(user)}, {sql_literal(scope)});"
        )
        return success_url(row)

    if form_name == "selection_clear":
        row = db.one(
            "select status, cleared_count, message "
            f"from vocera_rf_validation_clear_study_archive_selection({sql_literal(user)}, {sql_literal(scope)});"
        )
        return success_url(row)

    return error_url(f"Unknown form: {form_name}")


class Handler(BaseHTTPRequestHandler):
    db = Db()

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path not in {"/", "/healthz"}:
            self.send_error(404)
            return
        if parsed.path == "/healthz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n")
            return
        body = render_page(self.db, parse_qs(parsed.query)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        form = parse_qs(raw, keep_blank_values=True)
        try:
            location = handle_post(self.db, form)
        except Exception as exc:  # noqa: BLE001 - show operator actual DB error
            location = error_url(str(exc))
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stderr.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))


def main() -> int:
    host = os.environ.get("VOCERA_RF_STUDY_WEB_HOST", DEFAULT_HOST)
    port = int(os.environ.get("VOCERA_RF_STUDY_WEB_PORT", str(DEFAULT_PORT)))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Vocera RF validation study web app listening on http://{host}:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
