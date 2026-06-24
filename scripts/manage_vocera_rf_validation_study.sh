#!/usr/bin/env bash
set -euo pipefail

# Interactive current-study manager for the Vocera badge/Ekahau RF validation
# dashboard. The laptop still only uploads evidence; current-study CRUD happens
# on the collector against PostgreSQL.

usage() {
  cat <<'EOF'
Usage:
  bash scripts/manage_vocera_rf_validation_study.sh [options]

Interactive mode:
  bash scripts/manage_vocera_rf_validation_study.sh

Non-interactive shortcuts:
  bash scripts/manage_vocera_rf_validation_study.sh --show
  bash scripts/manage_vocera_rf_validation_study.sh --add "Study name" [--notes "text"]
  bash scripts/manage_vocera_rf_validation_study.sh --new "Study name" [--notes "text"] [--no-archive]
  bash scripts/manage_vocera_rf_validation_study.sh --archive-checkpoint [--label "Archive label"] [--notes "text"]

Options:
  --scope SCOPE          Study scope. Default: vocera_badge. Supported: vocera_badge, ipad.
  --psql-bin PATH       psql wrapper. Default: scripts/vocera_rf_validation_psql_in_container.sh
  --postgres-url URL    PostgreSQL URL. Default: local RF validation PostgreSQL URL.
  --show                Print current study, all archives, and live run IDs, then exit.
  --add NAME            Name/rename the current study and add future parser runs to it.
  --new NAME            Start a new named study. Archives+clears existing rows first by default.
  --no-archive          With --new, clear existing rows without archiving them.
  --archive-checkpoint  Archive current rows but leave them visible.
  --label LABEL         Archive label for --archive-checkpoint.
  --notes TEXT          Notes for the current study or archive action.
  -h, --help            Show this help.
EOF
}

die() { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SCOPE="${VOCERA_RF_VALIDATION_STUDY_SCOPE:-vocera_badge}"
RF_PSQL_BIN="${VOCERA_RF_VALIDATION_PSQL_BIN:-scripts/vocera_rf_validation_psql_in_container.sh}"
RF_DATABASE_URL="${VOCERA_RF_VALIDATION_DATABASE_URL:-}"
ACTION=""
STUDY_NAME=""
ARCHIVE_LABEL=""
NOTES=""
NO_ARCHIVE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scope)
      shift
      [[ $# -gt 0 ]] || die "missing value for --scope"
      SCOPE="$1"
      ;;
    --psql-bin)
      shift
      [[ $# -gt 0 ]] || die "missing value for --psql-bin"
      RF_PSQL_BIN="$1"
      ;;
    --postgres-url)
      shift
      [[ $# -gt 0 ]] || die "missing value for --postgres-url"
      RF_DATABASE_URL="$1"
      ;;
    --show)
      ACTION="show"
      ;;
    --add)
      shift
      [[ $# -gt 0 ]] || die "missing value for --add"
      ACTION="add"
      STUDY_NAME="$1"
      ;;
    --new)
      shift
      [[ $# -gt 0 ]] || die "missing value for --new"
      ACTION="new"
      STUDY_NAME="$1"
      ;;
    --no-archive)
      NO_ARCHIVE=1
      ;;
    --archive-checkpoint)
      ACTION="archive"
      ;;
    --label)
      shift
      [[ $# -gt 0 ]] || die "missing value for --label"
      ARCHIVE_LABEL="$1"
      ;;
    --notes)
      shift
      [[ $# -gt 0 ]] || die "missing value for --notes"
      NOTES="$1"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      usage
      die "unknown argument: $1"
      ;;
  esac
  shift
done

if [[ -z "$RF_DATABASE_URL" && -z "${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-}" \
    && -r /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env ]]; then
  # shellcheck disable=SC1091
  set -a; source /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env; set +a
fi
RF_DATABASE_URL="${RF_DATABASE_URL:-postgresql://vocera_rf_validation:${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD:-unused}@127.0.0.1:15433/vocera_rf_validation}"
USER_NAME="${SUDO_USER:-$(id -un)}"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

sql_literal() {
  python3 -c 'import sys; print("'"'"'" + sys.argv[1].replace("'"'"'", "'"'"''"'"'") + "'"'"'")' "$1"
}

run_sql() {
  local sql="$1"
  local path="$tmp_dir/run.sql"
  printf '%s\n' "$sql" >"$path"
  "$RF_PSQL_BIN" "$RF_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$path"
}

query_scalar() {
  local sql="$1"
  "$RF_PSQL_BIN" "$RF_DATABASE_URL" -At -v ON_ERROR_STOP=1 -c "$sql" | tail -1
}

current_runs() {
  local scope_lit
  scope_lit="$(sql_literal "$SCOPE")"
  query_scalar "select coalesce(test_run_count, 0) from v_vocera_rf_validation_current_study where study_scope = $scope_lit;"
}

current_name() {
  local scope_lit
  scope_lit="$(sql_literal "$SCOPE")"
  query_scalar "select coalesce(study_name, '') from v_vocera_rf_validation_current_study where study_scope = $scope_lit;"
}

show_state() {
  local scope_lit
  scope_lit="$(sql_literal "$SCOPE")"
  info "Current RF validation study ($SCOPE)"
  run_sql "select
  study_scope,
  coalesce(study_name, '(unnamed)') as study_name,
  study_started_at,
  study_started_by,
  test_run_count,
  candidate_match_count,
  pending_candidate_match_count,
  completed_match_count,
  manual_observation_count,
  archive_count,
  study_notes
from v_vocera_rf_validation_current_study
where study_scope = $scope_lit;"

  info "All RF validation studies ($SCOPE)"
  run_sql "with current_study as (
  select
    'current'::text as state,
    null::text as archive_id,
    coalesce(study_name, '(unnamed current study)') as study_name,
    study_started_at as study_time,
    study_started_by as study_user,
    test_run_count,
    candidate_match_count,
    completed_match_count,
    study_notes as notes
  from v_vocera_rf_validation_current_study
  where study_scope = $scope_lit
), archived_studies as (
  select
    'archived'::text as state,
    archive_id,
    coalesce(archive_label, '(unnamed archived study)') as study_name,
    archived_at as study_time,
    archived_by as study_user,
    test_run_count,
    candidate_match_count,
    completed_match_count,
    notes
  from vocera_rf_validation_study_archives
  where study_scope = $scope_lit
)
select
  state,
  study_name,
  archive_id,
  study_time,
  study_user,
  test_run_count,
  candidate_match_count,
  completed_match_count,
  notes
from (
  select 0 as sort_group, * from current_study
  union all
  select 1 as sort_group, * from archived_studies
) studies
order by sort_group, study_time desc nulls last, study_name;"

  info "Live parser runs in current RF validation study ($SCOPE)"
  run_sql "select
  tr.test_run_id,
  tr.created_at,
  tr.badge_mac,
  tr.badge_model,
  tr.ekahau_project,
  coalesce(events.badge_event_count, 0) as badge_event_count,
  coalesce(points.survey_point_count, 0) as survey_point_count,
  coalesce(candidates.candidate_match_count, 0) as candidate_match_count,
  coalesce(matches.completed_match_count, 0) as completed_match_count
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
  select test_run_id, count(*)::integer as candidate_match_count
  from badge_ekahau_candidate_matches
  group by test_run_id
) candidates on candidates.test_run_id = tr.test_run_id
left join (
  select test_run_id, count(*)::integer as completed_match_count
  from badge_ekahau_matches
  group by test_run_id
) matches on matches.test_run_id = tr.test_run_id
where vocera_rf_validation_study_scope(tr.test_run_id) = $scope_lit
order by tr.created_at desc, tr.test_run_id desc;"
}

set_current_study() {
  local name="$1"
  local notes="$2"
  local name_lit notes_lit user_lit scope_lit
  name_lit="$(sql_literal "$name")"
  notes_lit="$(sql_literal "$notes")"
  user_lit="$(sql_literal "$USER_NAME")"
  scope_lit="$(sql_literal "$SCOPE")"
  run_sql "select status, study_scope, study_name, message
from vocera_rf_validation_set_current_study($name_lit, $notes_lit, $user_lit, $scope_lit);"
}

apply_study_action() {
  local action="$1"
  local label="$2"
  local notes="$3"
  local action_lit label_sql notes_sql user_lit scope_lit
  action_lit="$(sql_literal "$action")"
  user_lit="$(sql_literal "$USER_NAME")"
  scope_lit="$(sql_literal "$SCOPE")"
  if [[ -n "$label" ]]; then label_sql="$(sql_literal "$label")"; else label_sql="null"; fi
  if [[ -n "$notes" ]]; then notes_sql="$(sql_literal "$notes")"; else notes_sql="null"; fi
  run_sql "select status, archive_id, test_run_count, candidate_match_count, completed_match_count, message
from vocera_rf_validation_apply_current_study_action($action_lit, $label_sql, $notes_sql, $user_lit, $scope_lit);"
}

prompt_required() {
  local prompt="$1"
  local value=""
  while [[ -z "$value" ]]; do
    read -r -p "$prompt" value
    value="$(printf '%s' "$value" | sed 's/^[[:space:]]*//; s/[[:space:]]*$//')"
  done
  printf '%s' "$value"
}

prompt_optional() {
  local prompt="$1"
  local value=""
  read -r -p "$prompt" value
  printf '%s' "$value"
}

start_new_study() {
  local name="$1"
  local notes="$2"
  local runs
  runs="$(current_runs)"
  if [[ "${runs:-0}" =~ ^[0-9]+$ && "$runs" -gt 0 ]]; then
    if [[ "$NO_ARCHIVE" == "1" ]]; then
      info "Clearing current study without archiving first"
      apply_study_action "clear_current" "" "$notes"
    else
      info "Archiving and clearing current study before starting the new one"
      apply_study_action "archive_and_clear" "" ""
    fi
  else
    info "No live rows to archive or clear; setting current study metadata"
    apply_study_action "clear_current" "" "" >/dev/null || true
  fi
  set_current_study "$name" "$notes"
}

add_to_current_study() {
  local name="$1"
  local notes="$2"
  set_current_study "$name" "$notes"
  echo
  echo "Next parser/upload run will be added to current RF study: $name"
}

interactive_menu() {
  show_state
  echo
  echo "Choose an action:"
  echo "  1) Add next parser/upload run to current study"
  echo "  2) Start a new named study (archive + clear current first)"
  echo "  3) Start a new named study (clear current without archive)"
  echo "  4) Rename current study"
  echo "  5) Archive current study checkpoint"
  echo "  q) Quit"
  echo

  local choice name notes keep existing label
  read -r -p "Selection: " choice
  case "$choice" in
    1)
      existing="$(current_name)"
      if [[ -n "$existing" ]]; then
        read -r -p "Use current study name \"$existing\"? [Y/n] " keep
        if [[ "$keep" =~ ^[Nn]$ ]]; then
          name="$(prompt_required "Study name: ")"
        else
          name="$existing"
        fi
      else
        name="$(prompt_required "Study name: ")"
      fi
      notes="$(prompt_optional "Notes (optional): ")"
      add_to_current_study "$name" "$notes"
      ;;
    2)
      name="$(prompt_required "New study name: ")"
      notes="$(prompt_optional "Notes (optional): ")"
      NO_ARCHIVE=0
      start_new_study "$name" "$notes"
      ;;
    3)
      read -r -p "Clear current rows without archiving? Type CLEAR to continue: " keep
      [[ "$keep" == "CLEAR" ]] || die "clear without archive cancelled"
      name="$(prompt_required "New study name: ")"
      notes="$(prompt_optional "Notes (optional): ")"
      NO_ARCHIVE=1
      start_new_study "$name" "$notes"
      ;;
    4)
      name="$(prompt_required "Study name: ")"
      notes="$(prompt_optional "Notes (optional): ")"
      set_current_study "$name" "$notes"
      ;;
    5)
      label="$(prompt_optional "Archive label (blank uses current study name): ")"
      notes="$(prompt_optional "Archive notes (optional): ")"
      apply_study_action "archive_current" "$label" "$notes"
      ;;
    q|Q)
      exit 0
      ;;
    *)
      die "unknown selection: $choice"
      ;;
  esac
}

case "$ACTION" in
  "")
    interactive_menu
    ;;
  show)
    show_state
    ;;
  add)
    [[ -n "$STUDY_NAME" ]] || die "--add requires a study name"
    add_to_current_study "$STUDY_NAME" "$NOTES"
    ;;
  new)
    [[ -n "$STUDY_NAME" ]] || die "--new requires a study name"
    start_new_study "$STUDY_NAME" "$NOTES"
    ;;
  archive)
    apply_study_action "archive_current" "$ARCHIVE_LABEL" "$NOTES"
    ;;
  *)
    die "unknown action: $ACTION"
    ;;
esac
