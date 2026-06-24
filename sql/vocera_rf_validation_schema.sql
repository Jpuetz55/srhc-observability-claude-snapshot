-- PostgreSQL contract for Vocera badge-side RF validation against Ekahau
-- survey timestamps and manually entered Ekahau RSSI/SNR observations.

create table if not exists vocera_projects (
  project_id text primary key,
  project_name text not null,
  project_type text not null default 'rf_validation',
  description text,
  site text,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create table if not exists vocera_studies (
  study_id text primary key,
  project_id text not null references vocera_projects(project_id),
  study_type text not null default 'rf_validation',
  study_scope text not null default 'vocera_badge',
  study_name text not null,
  description text,
  study_status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create table if not exists validation_test_runs (
  test_run_id text primary key,
  study_id text references vocera_studies(study_id),
  site text,
  building text,
  floor text,
  area text,
  ssid text,
  badge_mac text,
  badge_model text,
  ekahau_device text,
  ekahau_project text,
  timezone text not null default 'America/Chicago',
  badge_time_offset_seconds integer not null default 0,
  ekahau_time_offset_seconds integer not null default 0,
  default_match_window_seconds integer not null default 1,
  vendor_offset_source text,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists validation_source_files (
  source_file_id text primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  source_type text not null,
  source_path text,
  source_sha256 text not null,
  parsed_at timestamptz not null default now(),
  parse_success boolean not null,
  parse_error text,
  line_count integer
);

create table if not exists vocera_rf_validation_input_files (
  input_file_id text primary key,
  study_scope text not null default 'vocera_badge',
  source_type text not null,
  file_path text not null,
  display_name text,
  file_name text,
  file_size_bytes bigint,
  file_mtime timestamptz,
  source_sha256 text,
  discovered_at timestamptz not null default now(),
  last_seen_at timestamptz not null default now(),
  is_available boolean not null default true,
  notes text,
  constraint vocera_rf_validation_input_files_scope_path_key unique (study_scope, file_path)
);

create index if not exists idx_vocera_rf_validation_input_files_scope_type
  on vocera_rf_validation_input_files (study_scope, source_type, is_available, last_seen_at desc);

create table if not exists vocera_rf_validation_run_input_files (
  test_run_id text not null references validation_test_runs(test_run_id) on delete cascade,
  input_file_id text not null references vocera_rf_validation_input_files(input_file_id) on delete restrict,
  source_role text not null,
  selected_at timestamptz not null default now(),
  primary key (test_run_id, input_file_id, source_role)
);

create index if not exists idx_vocera_rf_validation_run_input_files_input
  on vocera_rf_validation_run_input_files (input_file_id, selected_at desc);

create table if not exists badge_scan_events (
  event_id text primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  source_file_id text references validation_source_files(source_file_id),
  badge_mac text,
  badge_model text,
  event_time timestamptz not null,
  ssid text,
  roam_reason text,
  total_aps integer,
  roam_candidate_aps integer,
  outage_ms integer,
  total_scan_time_ms integer,
  connected_bssid text,
  connected_channel integer,
  connected_band text,
  connected_ssid text,
  connected_ip inet,
  gateway inet,
  source_line integer,
  warnings text[] not null default '{}',
  created_at timestamptz not null default now()
);

create table if not exists badge_scan_candidates (
  event_id text not null references badge_scan_events(event_id),
  candidate_index integer not null,
  selected boolean not null default false,
  bssid text not null,
  channel integer,
  band text,
  rssi_dbm numeric,
  channel_utilization_percent numeric,
  score numeric,
  is_roam_candidate boolean,
  source_line integer,
  primary key (event_id, candidate_index)
);

create table if not exists badge_rrm_neighbors (
  id bigserial primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  source_file_id text references validation_source_files(source_file_id),
  badge_mac text,
  event_time timestamptz not null,
  bssid text not null,
  op_class integer,
  channel integer,
  band text,
  phy_type integer,
  info_hex text,
  source_line integer
);

create table if not exists badge_radio_signal_samples (
  id bigserial primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  source_file_id text references validation_source_files(source_file_id),
  badge_mac text,
  event_time timestamptz not null,
  sig_bars integer,
  noise_dbm numeric,
  level_dbm numeric,
  snr_db numeric,
  channel integer,
  band text,
  bandwidth_mhz integer,
  powersave integer,
  channel_utilization_percent numeric,
  source_line integer
);

create table if not exists ekahau_survey_points (
  survey_point_id text primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  source_file_id text references validation_source_files(source_file_id),
  measured_at timestamptz not null,
  floor text,
  area text,
  x_m numeric,
  y_m numeric,
  source_json_path text,
  raw_context jsonb,
  created_at timestamptz not null default now()
);

create table if not exists manual_ekahau_observations (
  id bigserial primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  survey_point_id text references ekahau_survey_points(survey_point_id),
  measured_at timestamptz not null,
  floor text,
  area text,
  x_m numeric,
  y_m numeric,
  ssid text,
  bssid text not null,
  ap_name text,
  channel integer,
  frequency_mhz integer,
  band text,
  rssi_dbm numeric not null,
  snr_db numeric,
  noise_dbm numeric,
  source_row integer,
  entered_by text,
  notes text,
  created_at timestamptz not null default now()
);

create table if not exists badge_ekahau_candidate_matches (
  id bigserial primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  survey_point_id text references ekahau_survey_points(survey_point_id),
  badge_event_id text not null references badge_scan_events(event_id),
  badge_candidate_index integer not null,
  survey_time timestamptz not null,
  ekahau_survey_id text,
  ekahau_survey_name text,
  badge_time timestamptz not null,
  time_delta_seconds numeric not null,
  badge_mac text,
  badge_model text,
  ssid text,
  bssid text not null,
  ap_name text,
  channel integer,
  band text,
  badge_rssi_dbm numeric,
  badge_noise_floor_dbm numeric,
  badge_snr_db numeric,
  badge_snr_source text,
  badge_snr_time timestamptz,
  badge_snr_time_delta_seconds numeric,
  badge_radio_signal_level_dbm numeric,
  badge_cu_percent numeric,
  badge_score numeric,
  badge_selected boolean,
  floor text,
  area text,
  x_m numeric,
  y_m numeric,
  match_quality text not null,
  manual_entry_status text not null default 'pending',
  created_at timestamptz not null default now()
);

create table if not exists badge_ekahau_matches (
  id bigserial primary key,
  test_run_id text not null references validation_test_runs(test_run_id),
  candidate_match_id bigint references badge_ekahau_candidate_matches(id),
  ekahau_observation_id bigint references manual_ekahau_observations(id),
  survey_point_id text references ekahau_survey_points(survey_point_id),
  badge_event_id text not null references badge_scan_events(event_id),
  badge_candidate_index integer not null,
  badge_time timestamptz not null,
  ekahau_time timestamptz not null,
  ekahau_survey_id text,
  ekahau_survey_name text,
  time_delta_seconds numeric not null,
  badge_mac text,
  badge_model text,
  ssid text,
  bssid text not null,
  ap_name text,
  channel integer,
  band text,
  badge_rssi_dbm numeric not null,
  badge_noise_floor_dbm numeric,
  badge_snr_db numeric,
  badge_snr_source text,
  badge_snr_time timestamptz,
  badge_snr_time_delta_seconds numeric,
  badge_radio_signal_level_dbm numeric,
  ekahau_rssi_dbm numeric,
  ekahau_snr_db numeric,
  vendor_offset_db numeric,
  expected_badge_rssi_dbm numeric,
  raw_delta_db numeric,
  calibrated_delta_db numeric,
  absolute_calibrated_delta_db numeric,
  badge_cu_percent numeric,
  badge_score numeric,
  badge_selected boolean,
  floor text,
  area text,
  x_m numeric,
  y_m numeric,
  match_quality text not null,
  manual_entry_status text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_badge_scan_events_run_time
  on badge_scan_events (test_run_id, event_time);

create index if not exists idx_badge_scan_candidates_bssid
  on badge_scan_candidates (bssid, channel, band);

create index if not exists idx_badge_rrm_neighbors_run_time
  on badge_rrm_neighbors (test_run_id, event_time);

create index if not exists idx_badge_radio_signal_samples_run_channel_time
  on badge_radio_signal_samples (test_run_id, channel, event_time);

create index if not exists idx_ekahau_survey_points_run_time
  on ekahau_survey_points (test_run_id, measured_at);

create index if not exists idx_manual_ekahau_observations_run_bssid
  on manual_ekahau_observations (test_run_id, bssid, measured_at);

create index if not exists idx_badge_ekahau_matches_run_band
  on badge_ekahau_matches (test_run_id, floor, band);

create index if not exists idx_badge_ekahau_matches_run_bssid
  on badge_ekahau_matches (test_run_id, bssid, channel, band);

create index if not exists idx_vocera_projects_type_active
  on vocera_projects (project_type, deleted_at, project_name);

create index if not exists idx_vocera_studies_project_type_status
  on vocera_studies (project_id, study_type, study_status, deleted_at, study_name);

create table if not exists vocera_rf_validation_current_studies (
  study_scope text primary key,
  study_name text not null,
  started_at timestamptz not null default now(),
  started_by text,
  updated_at timestamptz,
  updated_by text,
  notes text
);

create table if not exists vocera_rf_validation_study_archives (
  archive_id text primary key,
  study_scope text not null default 'vocera_badge',
  archive_label text,
  archived_at timestamptz not null default now(),
  archived_by text,
  updated_at timestamptz,
  updated_by text,
  notes text,
  test_run_count integer not null default 0,
  badge_event_count integer not null default 0,
  survey_point_count integer not null default 0,
  candidate_match_count integer not null default 0,
  completed_match_count integer not null default 0,
  manual_observation_count integer not null default 0,
  first_badge_time timestamptz,
  last_badge_time timestamptz,
  first_survey_time timestamptz,
  last_survey_time timestamptz,
  payload jsonb not null
);

create index if not exists idx_vocera_rf_validation_study_archives_time
  on vocera_rf_validation_study_archives (archived_at desc);

create index if not exists idx_vocera_rf_validation_study_archives_scope_time
  on vocera_rf_validation_study_archives (study_scope, archived_at desc);

create table if not exists vocera_rf_validation_study_archive_selections (
  selection_owner text not null,
  study_scope text not null default 'vocera_badge',
  archive_id text not null references vocera_rf_validation_study_archives(archive_id) on delete cascade,
  selected_at timestamptz not null default now(),
  primary key (selection_owner, archive_id)
);

create index if not exists idx_vocera_rf_validation_study_archive_selections_scope_owner
  on vocera_rf_validation_study_archive_selections (study_scope, selection_owner, selected_at desc);

alter table validation_test_runs
  add column if not exists study_id text references vocera_studies(study_id),
  add column if not exists run_name text,
  add column if not exists run_status text not null default 'draft',
  add column if not exists run_created_by text,
  add column if not exists run_updated_at timestamptz,
  add column if not exists run_executed_at timestamptz,
  add column if not exists run_execution_error text,
  add column if not exists run_notes text,
  add column if not exists deleted_at timestamptz,
  add column if not exists deleted_by text;

-- Effective parameters actually used by the last execution (provenance). These
-- differ from the configured per-run fields above: the configured value is the
-- request, while *_used records what the executor resolved and ran with.
alter table validation_test_runs
  add column if not exists match_window_seconds_used numeric,
  add column if not exists runtime_config_path text;

alter table vocera_studies
  add column if not exists study_scope text not null default 'vocera_badge';

create index if not exists idx_vocera_studies_project_scope_status
  on vocera_studies (project_id, study_scope, study_status, deleted_at, study_name);

do $$
begin
  alter table vocera_projects
    add constraint vocera_projects_project_type_check
    check (project_type in ('rf_validation', 'media_qoe', 'mixed'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table vocera_studies
    add constraint vocera_studies_study_type_check
    check (study_type in ('rf_validation', 'media_qoe'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table vocera_studies
    add constraint vocera_studies_study_scope_check
    check (study_scope in ('vocera_badge', 'ipad', 'media_qoe'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table vocera_studies
    add constraint vocera_studies_study_status_check
    check (study_status in ('active', 'complete', 'archived', 'deleted'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table vocera_rf_validation_input_files
    add constraint vocera_rf_validation_input_files_source_type_check
    check (source_type in ('badge_log', 'ekahau_json', 'manual_csv', 'ipad_client_detail', 'other'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table vocera_rf_validation_run_input_files
    add constraint vocera_rf_validation_run_input_files_source_role_check
    check (source_role in ('badge_log', 'ekahau_json', 'manual_csv', 'ipad_client_detail', 'other'));
exception
  when duplicate_object then null;
end;
$$;

do $$
begin
  alter table validation_test_runs
    add constraint validation_test_runs_run_status_check
    check (run_status in ('draft', 'running', 'complete', 'failed', 'deleted'));
exception
  when duplicate_object then null;
end;
$$;

alter table badge_ekahau_candidate_matches
  add column if not exists ap_name text;

alter table badge_ekahau_matches
  add column if not exists ap_name text;

alter table badge_ekahau_candidate_matches
  add column if not exists ekahau_survey_id text,
  add column if not exists ekahau_survey_name text;

alter table badge_ekahau_matches
  add column if not exists ekahau_survey_id text,
  add column if not exists ekahau_survey_name text;

alter table badge_ekahau_candidate_matches
  add column if not exists badge_noise_floor_dbm numeric,
  add column if not exists badge_snr_db numeric,
  add column if not exists badge_snr_source text,
  add column if not exists badge_snr_time timestamptz,
  add column if not exists badge_snr_time_delta_seconds numeric,
  add column if not exists badge_radio_signal_level_dbm numeric;

alter table badge_ekahau_matches
  add column if not exists badge_noise_floor_dbm numeric,
  add column if not exists badge_snr_db numeric,
  add column if not exists badge_snr_source text,
  add column if not exists badge_snr_time timestamptz,
  add column if not exists badge_snr_time_delta_seconds numeric,
  add column if not exists badge_radio_signal_level_dbm numeric;

create or replace function vocera_rf_validation_study_scope(p_test_run_id text)
returns text
language sql
immutable
as $$
  select case
    when coalesce(p_test_run_id, '') like 'ipad_%' then 'ipad'
    else 'vocera_badge'
  end;
$$;

create or replace function vocera_rf_validation_normalize_study_scope(p_study_scope text)
returns text
language sql
immutable
as $$
  select case lower(regexp_replace(coalesce(nullif(trim(p_study_scope), ''), 'vocera_badge'), '[^a-zA-Z0-9]+', '_', 'g'))
    when 'badge' then 'vocera_badge'
    when 'vocera' then 'vocera_badge'
    when 'vocera_badge' then 'vocera_badge'
    when 'ipad' then 'ipad'
    when 'ipad_wlc' then 'ipad'
    when 'all' then 'all'
    else lower(regexp_replace(coalesce(nullif(trim(p_study_scope), ''), 'vocera_badge'), '[^a-zA-Z0-9]+', '_', 'g'))
  end;
$$;

create or replace function vocera_rf_validation_truthy(p_value text)
returns boolean
language sql
immutable
as $$
  select lower(trim(coalesce(p_value, ''))) in ('true', 't', '1', 'yes', 'y', 'on', 'selected', 'select', 'run', 'delete', 'clear', 'create');
$$;

insert into vocera_projects (
  project_id,
  project_name,
  project_type,
  description,
  site
)
values (
  'project_rf_validation_default',
  'RF Validation',
  'rf_validation',
  'Default project for migrated RF validation studies.',
  null
)
on conflict (project_id) do nothing;

insert into vocera_studies (
  study_id,
  project_id,
  study_type,
  study_scope,
  study_name,
  description,
  study_status
)
values
  (
    'study_rf_validation_vocera_badge_default',
    'project_rf_validation_default',
    'rf_validation',
    'vocera_badge',
    'Vocera Badge RF Validation',
    'Default study for existing Vocera badge RF validation runs.',
    'active'
  ),
  (
    'study_rf_validation_ipad_default',
    'project_rf_validation_default',
    'rf_validation',
    'ipad',
    'iPad RF Validation',
    'Default study for existing iPad/WLC RF validation runs.',
    'active'
  )
on conflict (study_id) do nothing;

update vocera_studies
set study_scope = 'vocera_badge'
where study_id = 'study_rf_validation_vocera_badge_default';

update vocera_studies
set study_scope = 'ipad'
where study_id = 'study_rf_validation_ipad_default';

update validation_test_runs
set study_id = case
  when vocera_rf_validation_study_scope(test_run_id) = 'ipad' then 'study_rf_validation_ipad_default'
  else 'study_rf_validation_vocera_badge_default'
end
where study_id is null;


alter table if exists vocera_rf_validation_current_studies
  add column if not exists source_archive_id text,
  add column if not exists source_archive_label text,
  add column if not exists source_archive_saved_at timestamptz;

create or replace function vocera_rf_validation_set_current_study(
  p_study_name text,
  p_notes text default null,
  p_user text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  study_scope text,
  study_name text,
  message text
)
language plpgsql
as $$
declare
  v_scope text;
  v_study_name text;
  v_notes text;
begin
  v_scope := vocera_rf_validation_normalize_study_scope(p_study_scope);
  if v_scope not in ('vocera_badge', 'ipad') then
    return query select 'error'::text, v_scope, null::text, format('Unsupported current RF study scope: %s', coalesce(p_study_scope, '<empty>'))::text;
    return;
  end if;

  v_study_name := nullif(trim(coalesce(p_study_name, '')), '');
  if v_study_name is null then
    return query select 'error'::text, v_scope, null::text, 'Study name is required.'::text;
    return;
  end if;

  v_notes := nullif(trim(coalesce(p_notes, '')), '');

  insert into vocera_rf_validation_current_studies (
    study_scope,
    study_name,
    started_by,
    updated_by,
    notes
  )
  values (
    v_scope,
    v_study_name,
    coalesce(nullif(trim(coalesce(p_user, '')), ''), current_user),
    coalesce(nullif(trim(coalesce(p_user, '')), ''), current_user),
    v_notes
  )
  on conflict on constraint vocera_rf_validation_current_studies_pkey
  do update set
    study_name = excluded.study_name,
    updated_at = now(),
    updated_by = excluded.updated_by,
    notes = excluded.notes
  returning vocera_rf_validation_current_studies.study_name
  into v_study_name;

  return query select
    'set'::text,
    v_scope,
    v_study_name,
    format('Current %s RF validation study is now "%s".', v_scope, v_study_name)::text;
end;
$$;

create or replace function vocera_rf_validation_archive_current_study(
  p_archive_label text default null,
  p_archived_by text default null,
  p_notes text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive_id text;
  v_scope text;
  v_run_ids text[];
  v_test_run_count integer := 0;
  v_badge_event_count integer := 0;
  v_survey_point_count integer := 0;
  v_candidate_match_count integer := 0;
  v_completed_match_count integer := 0;
  v_manual_observation_count integer := 0;
  v_first_badge_time timestamptz;
  v_last_badge_time timestamptz;
  v_first_survey_time timestamptz;
  v_last_survey_time timestamptz;
  v_current_study vocera_rf_validation_current_studies%rowtype;
  v_archive_label text;
  v_notes text;
  v_payload jsonb;
begin
  v_scope := vocera_rf_validation_normalize_study_scope(p_study_scope);
  if v_scope not in ('vocera_badge', 'ipad', 'all') then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, format('Unknown RF validation study scope: %s', coalesce(p_study_scope, '<empty>'))::text;
    return;
  end if;

  select coalesce(array_agg(tr.test_run_id order by tr.created_at, tr.test_run_id), '{}'::text[])
    into v_run_ids
  from validation_test_runs tr
  where (v_scope = 'all'
     or vocera_rf_validation_study_scope(tr.test_run_id) = v_scope)
    and tr.deleted_at is null;

  v_test_run_count := coalesce(array_length(v_run_ids, 1), 0);
  select *
    into v_current_study
  from vocera_rf_validation_current_studies s
  where s.study_scope = v_scope;

  if v_test_run_count = 0 then
    return query select
      'empty'::text,
      null::text,
      0::integer,
      0::integer,
      0::integer,
      format('No RF validation rows exist in the current %s study.', v_scope)::text;
    return;
  end if;

  select count(*)::integer, min(event_time), max(event_time)
    into v_badge_event_count, v_first_badge_time, v_last_badge_time
  from badge_scan_events
  where test_run_id = any(v_run_ids);

  select count(*)::integer, min(measured_at), max(measured_at)
    into v_survey_point_count, v_first_survey_time, v_last_survey_time
  from ekahau_survey_points
  where test_run_id = any(v_run_ids);

  select count(*)::integer
    into v_candidate_match_count
  from badge_ekahau_candidate_matches
  where test_run_id = any(v_run_ids);

  select count(*)::integer
    into v_completed_match_count
  from badge_ekahau_matches
  where test_run_id = any(v_run_ids)
    and manual_entry_status in ('complete', 'missing_vendor_offset');

  select count(*)::integer
    into v_manual_observation_count
  from manual_ekahau_observations
  where test_run_id = any(v_run_ids);

  v_archive_label := coalesce(nullif(trim(coalesce(p_archive_label, '')), ''), nullif(trim(coalesce(v_current_study.study_name, '')), ''));
  v_notes := coalesce(nullif(trim(coalesce(p_notes, '')), ''), v_current_study.notes);

  /*
    Save Study behavior:

      - If no saved study exists with this name, create a new saved study.
      - If the loaded saved study has this name, update that same saved study.
      - If a different saved study already has this name, refuse the save.
      - Restore checkpoints are hidden safety artifacts and are never selected.
      - Combined-study creation remains separate and always creates a new saved study.
  */
  if v_archive_label is not null
     and v_archive_label not like 'Checkpoint before restoring %' then
    select a.archive_id
      into v_archive_id
    from vocera_rf_validation_study_archives a
    where a.study_scope = v_scope
      and a.archive_label = v_archive_label
      and coalesce(a.archive_label, '') not like 'Checkpoint before restoring %'
    order by a.archived_at desc, a.archive_id desc
    limit 1;

    if v_archive_id is not null
       and coalesce(v_current_study.source_archive_id, '') <> v_archive_id then
      return query select
        'error'::text,
        v_archive_id,
        0::integer,
        0::integer,
        0::integer,
        format('A saved RF study named "%s" already exists. Rename the working study before saving.', v_archive_label)::text;
      return;
    end if;
  end if;

  if v_archive_id is null then
    v_archive_id := 'rf_study_' || v_scope || '_' || to_char(clock_timestamp() at time zone 'UTC', 'YYYYMMDD_HH24MISS_US') || '_' || substr(md5(random()::text), 1, 8);
  end if;

  select jsonb_build_object(
    'study_scope', v_scope,
    'current_study',
    case
      when v_current_study.study_scope is null then null::jsonb
      else to_jsonb(v_current_study)
    end,
    'vocera_rf_validation_input_files',
    coalesce(
      (
        select jsonb_agg(to_jsonb(input_file) order by input_file.file_path, input_file.input_file_id)
        from (
          select distinct f.*
          from vocera_rf_validation_input_files f
          join vocera_rf_validation_run_input_files rif
            on rif.input_file_id = f.input_file_id
          where rif.test_run_id = any(v_run_ids)
        ) input_file
      ),
      '[]'::jsonb
    ),
    'vocera_rf_validation_run_input_files',
    coalesce(
      (
        select jsonb_agg(to_jsonb(rif) order by rif.test_run_id, rif.source_role, rif.input_file_id)
        from vocera_rf_validation_run_input_files rif
        where rif.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'validation_test_runs',
    coalesce(
      (
        select jsonb_agg(to_jsonb(tr) order by tr.created_at, tr.test_run_id)
        from validation_test_runs tr
        where tr.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'validation_source_files',
    coalesce(
      (
        select jsonb_agg(to_jsonb(sf) order by sf.parsed_at, sf.source_file_id)
        from validation_source_files sf
        where sf.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_scan_events',
    coalesce(
      (
        select jsonb_agg(to_jsonb(e) order by e.event_time, e.event_id)
        from badge_scan_events e
        where e.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_scan_candidates',
    coalesce(
      (
        select jsonb_agg(to_jsonb(c) order by c.event_id, c.candidate_index)
        from badge_scan_candidates c
        join badge_scan_events e
          on e.event_id = c.event_id
        where e.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_rrm_neighbors',
    coalesce(
      (
        select jsonb_agg(to_jsonb(n) order by n.event_time, n.id)
        from badge_rrm_neighbors n
        where n.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_radio_signal_samples',
    coalesce(
      (
        select jsonb_agg(to_jsonb(s) order by s.event_time, s.id)
        from badge_radio_signal_samples s
        where s.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'ekahau_survey_points',
    coalesce(
      (
        select jsonb_agg(to_jsonb(p) order by p.measured_at, p.survey_point_id)
        from ekahau_survey_points p
        where p.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'manual_ekahau_observations',
    coalesce(
      (
        select jsonb_agg(to_jsonb(o) order by o.measured_at, o.id)
        from manual_ekahau_observations o
        where o.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_ekahau_candidate_matches',
    coalesce(
      (
        select jsonb_agg(to_jsonb(c) order by c.survey_time, c.id)
        from badge_ekahau_candidate_matches c
        where c.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    ),
    'badge_ekahau_matches',
    coalesce(
      (
        select jsonb_agg(to_jsonb(m) order by m.ekahau_time, m.id)
        from badge_ekahau_matches m
        where m.test_run_id = any(v_run_ids)
      ),
      '[]'::jsonb
    )
  )
  into v_payload;

  insert into vocera_rf_validation_study_archives (
    archive_id,
    study_scope,
    archive_label,
    archived_by,
    notes,
    test_run_count,
    badge_event_count,
    survey_point_count,
    candidate_match_count,
    completed_match_count,
    manual_observation_count,
    first_badge_time,
    last_badge_time,
    first_survey_time,
    last_survey_time,
    payload
  )
  values (
    v_archive_id,
    v_scope,
    v_archive_label,
    coalesce(nullif(trim(coalesce(p_archived_by, '')), ''), current_user),
    v_notes,
    v_test_run_count,
    v_badge_event_count,
    v_survey_point_count,
    v_candidate_match_count,
    v_completed_match_count,
    v_manual_observation_count,
    v_first_badge_time,
    v_last_badge_time,
    v_first_survey_time,
    v_last_survey_time,
    v_payload
  )
  on conflict on constraint vocera_rf_validation_study_archives_pkey
  do update set
    archive_label = excluded.archive_label,
    archived_at = now(),
    archived_by = excluded.archived_by,
    updated_at = now(),
    updated_by = excluded.archived_by,
    notes = excluded.notes,
    test_run_count = excluded.test_run_count,
    badge_event_count = excluded.badge_event_count,
    survey_point_count = excluded.survey_point_count,
    candidate_match_count = excluded.candidate_match_count,
    completed_match_count = excluded.completed_match_count,
    manual_observation_count = excluded.manual_observation_count,
    first_badge_time = excluded.first_badge_time,
    last_badge_time = excluded.last_badge_time,
    first_survey_time = excluded.first_survey_time,
    last_survey_time = excluded.last_survey_time,
    payload = excluded.payload;

  return query select
    'archived'::text,
    v_archive_id,
    v_test_run_count,
    v_candidate_match_count,
    v_completed_match_count,
    format('Saved current %s RF validation study "%s" as archive %s with %s run(s), %s candidate row(s), and %s completed match row(s).', v_scope, coalesce(v_archive_label, v_archive_id), v_archive_id, v_test_run_count, v_candidate_match_count, v_completed_match_count)::text;
end;
$$;

create or replace function vocera_rf_validation_clear_current_study(
  p_cleared_by text default null,
  p_notes text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_scope text;
  v_run_ids text[];
  v_test_run_count integer := 0;
  v_candidate_match_count integer := 0;
  v_completed_match_count integer := 0;
  v_deleted_runs integer := 0;
  v_deleted_metadata integer := 0;
begin
  v_scope := vocera_rf_validation_normalize_study_scope(p_study_scope);
  if v_scope not in ('vocera_badge', 'ipad', 'all') then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, format('Unknown RF validation study scope: %s', coalesce(p_study_scope, '<empty>'))::text;
    return;
  end if;

  select coalesce(array_agg(tr.test_run_id order by tr.created_at, tr.test_run_id), '{}'::text[])
    into v_run_ids
  from validation_test_runs tr
  where v_scope = 'all'
     or vocera_rf_validation_study_scope(tr.test_run_id) = v_scope;

  v_test_run_count := coalesce(array_length(v_run_ids, 1), 0);
  if v_test_run_count = 0 then
    delete from vocera_rf_validation_current_studies
    where study_scope = v_scope;
    get diagnostics v_deleted_metadata = row_count;

    return query select
      case when v_deleted_metadata = 0 then 'empty' else 'cleared' end::text,
      null::text,
      0::integer,
      0::integer,
      0::integer,
      case
        when v_deleted_metadata = 0 then format('No RF validation rows existed in the current %s study.', v_scope)
        else format('Cleared current %s RF validation study metadata.', v_scope)
      end::text;
    return;
  end if;

  select count(*)::integer
    into v_candidate_match_count
  from badge_ekahau_candidate_matches
  where test_run_id = any(v_run_ids);

  select count(*)::integer
    into v_completed_match_count
  from badge_ekahau_matches
  where test_run_id = any(v_run_ids)
    and manual_entry_status in ('complete', 'missing_vendor_offset');

  delete from badge_ekahau_matches
  where test_run_id = any(v_run_ids);

  delete from manual_ekahau_observations
  where test_run_id = any(v_run_ids);

  delete from badge_ekahau_candidate_matches
  where test_run_id = any(v_run_ids);

  delete from badge_scan_candidates c
  using badge_scan_events e
  where e.event_id = c.event_id
    and e.test_run_id = any(v_run_ids);

  delete from badge_rrm_neighbors
  where test_run_id = any(v_run_ids);

  delete from badge_radio_signal_samples
  where test_run_id = any(v_run_ids);

  delete from ekahau_survey_points
  where test_run_id = any(v_run_ids);

  delete from badge_scan_events
  where test_run_id = any(v_run_ids);

  delete from validation_source_files
  where test_run_id = any(v_run_ids);

  delete from validation_test_runs
  where test_run_id = any(v_run_ids);
  get diagnostics v_deleted_runs = row_count;

  delete from vocera_rf_validation_current_studies
  where study_scope = v_scope;

  return query select
    case when v_deleted_runs = 0 then 'empty' else 'cleared' end::text,
    null::text,
    v_test_run_count,
    v_candidate_match_count,
    v_completed_match_count,
    case
      when v_deleted_runs = 0 then format('No current %s RF validation study existed to clear.', v_scope)
      else format('Cleared current %s RF validation study: deleted %s run(s), %s candidate row(s), and %s completed match row(s).', v_scope, v_deleted_runs, v_candidate_match_count, v_completed_match_count)
    end::text;
end;
$$;

create or replace function vocera_rf_validation_delete_run(
  p_test_run_id text,
  p_user text default null
)
returns table (
  status text,
  test_run_id text,
  candidate_match_count integer,
  completed_match_count integer,
  source_file_count integer,
  message text
)
language plpgsql
as $$
declare
  v_run validation_test_runs%rowtype;
  v_candidate_match_count integer := 0;
  v_completed_match_count integer := 0;
  v_source_file_count integer := 0;
begin
  if nullif(trim(coalesce(p_test_run_id, '')), '') is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, 'Missing test_run_id.'::text;
    return;
  end if;

  select *
    into v_run
  from validation_test_runs tr
  where tr.test_run_id = p_test_run_id;

  if not found then
    return query select 'not_found'::text, p_test_run_id, 0::integer, 0::integer, 0::integer, format('No RF validation run found for %s.', p_test_run_id)::text;
    return;
  end if;

  select count(*)::integer
    into v_candidate_match_count
  from badge_ekahau_candidate_matches
  where badge_ekahau_candidate_matches.test_run_id = p_test_run_id;

  select count(*)::integer
    into v_completed_match_count
  from badge_ekahau_matches
  where badge_ekahau_matches.test_run_id = p_test_run_id
    and badge_ekahau_matches.manual_entry_status in ('complete', 'missing_vendor_offset');

  select count(*)::integer
    into v_source_file_count
  from validation_source_files
  where validation_source_files.test_run_id = p_test_run_id;

  delete from badge_ekahau_matches
  where badge_ekahau_matches.test_run_id = p_test_run_id;

  delete from badge_ekahau_candidate_matches
  where badge_ekahau_candidate_matches.test_run_id = p_test_run_id;

  delete from manual_ekahau_observations
  where manual_ekahau_observations.test_run_id = p_test_run_id;

  delete from ekahau_survey_points
  where ekahau_survey_points.test_run_id = p_test_run_id;

  delete from badge_radio_signal_samples
  where badge_radio_signal_samples.test_run_id = p_test_run_id;

  delete from badge_rrm_neighbors
  where badge_rrm_neighbors.test_run_id = p_test_run_id;

  delete from badge_scan_candidates c
  using badge_scan_events e
  where e.event_id = c.event_id
    and e.test_run_id = p_test_run_id;

  delete from badge_scan_events
  where badge_scan_events.test_run_id = p_test_run_id;

  delete from validation_source_files
  where validation_source_files.test_run_id = p_test_run_id;

  delete from vocera_rf_validation_run_input_files
  where vocera_rf_validation_run_input_files.test_run_id = p_test_run_id;

  delete from validation_test_runs
  where validation_test_runs.test_run_id = p_test_run_id;

  return query select
    'deleted'::text,
    p_test_run_id,
    v_candidate_match_count,
    v_completed_match_count,
    v_source_file_count,
    format('Deleted RF validation run %s with %s candidate row(s), %s completed match row(s), and %s parsed source file row(s).', p_test_run_id, v_candidate_match_count, v_completed_match_count, v_source_file_count)::text;
end;
$$;

create or replace function vocera_rf_validation_archive_and_clear_current_study(
  p_archive_label text default null,
  p_archived_by text default null,
  p_notes text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive record;
  v_clear record;
begin
  select *
    into v_archive
  from vocera_rf_validation_archive_current_study(p_archive_label, p_archived_by, p_notes, p_study_scope);

  if v_archive.status in ('empty', 'error') then
    return query select
      v_archive.status::text,
      v_archive.archive_id::text,
      v_archive.test_run_count::integer,
      v_archive.candidate_match_count::integer,
      v_archive.completed_match_count::integer,
      v_archive.message::text;
    return;
  end if;

  select *
    into v_clear
  from vocera_rf_validation_clear_current_study(p_archived_by, p_notes, p_study_scope);

  return query select
    'archived_and_cleared'::text,
    v_archive.archive_id::text,
    v_archive.test_run_count::integer,
    v_archive.candidate_match_count::integer,
    v_archive.completed_match_count::integer,
    format('Archived %s and cleared %s current RF validation run(s).', v_archive.archive_id, v_clear.test_run_count)::text;
end;
$$;

create or replace function vocera_rf_validation_apply_current_study_action(
  p_action text,
  p_archive_label text default null,
  p_notes text default null,
  p_user text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_action text;
begin
  v_action := lower(regexp_replace(coalesce(nullif(trim(p_action), ''), ''), '[^a-zA-Z0-9]+', '_', 'g'));

  if v_action in ('archive', 'archive_current', 'archive_current_study', 'checkpoint') then
    return query
      select *
      from vocera_rf_validation_archive_current_study(p_archive_label, p_user, p_notes, p_study_scope);
    return;
  end if;

  if v_action in ('archive_and_clear', 'archive_clear', 'clear_archive', 'clear_and_archive', 'new', 'new_study') then
    return query
      select *
      from vocera_rf_validation_archive_and_clear_current_study(p_archive_label, p_user, p_notes, p_study_scope);
    return;
  end if;

  if v_action in ('clear', 'clear_current', 'clear_current_study') then
    return query
      select *
      from vocera_rf_validation_clear_current_study(p_user, p_notes, p_study_scope);
    return;
  end if;

  return query select
    'error'::text,
    null::text,
    0::integer,
    0::integer,
    0::integer,
    format('Unknown RF validation study action: %s', coalesce(p_action, '<empty>'))::text;
end;
$$;

create or replace function vocera_rf_validation_apply_current_study_row(
  p_action text,
  p_run_action text default null,
  p_archive_label text default null,
  p_notes text default null,
  p_user text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
begin
  if not vocera_rf_validation_truthy(p_run_action) then
    return query select
      'noop'::text,
      null::text,
      0::integer,
      0::integer,
      0::integer,
      'Set Run=true and save the row to execute this RF study action.'::text;
    return;
  end if;

  return query
    select *
    from vocera_rf_validation_apply_current_study_action(p_action, p_archive_label, p_notes, p_user, p_study_scope);
end;
$$;

drop function if exists vocera_rf_validation_update_study_archive(text, text, text, text);

create or replace function vocera_rf_validation_update_study_archive(
  p_archive_id text,
  p_archive_label text default null,
  p_notes text default null,
  p_updated_by text default null,
  p_combine_selected text default null
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive vocera_rf_validation_study_archives%rowtype;
  v_user text;
  v_selection text;
begin
  if nullif(trim(coalesce(p_archive_id, '')), '') is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, 'Missing archive_id.'::text;
    return;
  end if;

  v_user := coalesce(nullif(trim(coalesce(p_updated_by, '')), ''), current_user);

  update vocera_rf_validation_study_archives a
  set
    archive_label = nullif(trim(coalesce(p_archive_label, '')), ''),
    notes = nullif(trim(coalesce(p_notes, '')), ''),
    updated_at = now(),
    updated_by = v_user
  where a.archive_id = p_archive_id
  returning *
  into v_archive;

  if not found then
    return query select 'not_found'::text, p_archive_id, 0::integer, 0::integer, 0::integer, format('No RF validation study archive found for %s.', p_archive_id)::text;
    return;
  end if;

  v_selection := lower(trim(coalesce(p_combine_selected, '')));
  if v_selection in ('true', 't', '1', 'yes', 'y', 'on', 'selected', 'select') then
    insert into vocera_rf_validation_study_archive_selections (
      selection_owner,
      study_scope,
      archive_id,
      selected_at
    )
    values (
      v_user,
      v_archive.study_scope,
      v_archive.archive_id,
      now()
    )
    on conflict on constraint vocera_rf_validation_study_archive_selections_pkey
    do update set
      study_scope = excluded.study_scope,
      selected_at = excluded.selected_at;
  elsif v_selection in ('false', 'f', '0', 'no', 'n', 'off', 'unselected', 'clear', 'remove') then
    delete from vocera_rf_validation_study_archive_selections
    where selection_owner = v_user
      and archive_id = v_archive.archive_id;
  elsif nullif(v_selection, '') is not null then
    return query select
      'error'::text,
      v_archive.archive_id,
      v_archive.test_run_count,
      v_archive.candidate_match_count,
      v_archive.completed_match_count,
      format('Invalid combine selection value for %s: %s. Use true/false.', v_archive.archive_id, p_combine_selected)::text;
    return;
  end if;

  return query select
    'updated'::text,
    v_archive.archive_id,
    v_archive.test_run_count,
    v_archive.candidate_match_count,
    v_archive.completed_match_count,
    format('Updated RF validation study archive %s.', v_archive.archive_id)::text;
end;
$$;

create or replace function vocera_rf_validation_apply_study_archive_row(
  p_archive_id text,
  p_archive_label text default null,
  p_notes text default null,
  p_combine_selected text default null,
  p_delete_archive text default null,
  p_user text default null
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
begin
  if vocera_rf_validation_truthy(p_delete_archive) then
    return query
      select *
      from vocera_rf_validation_delete_study_archive(p_archive_id, p_user);
    return;
  end if;

  return query
    select *
    from vocera_rf_validation_update_study_archive(p_archive_id, p_archive_label, p_notes, p_user, p_combine_selected);
end;
$$;

create or replace function vocera_rf_validation_clear_study_archive_selection(
  p_user text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  cleared_count integer,
  message text
)
language plpgsql
as $$
declare
  v_scope text;
  v_user text;
  v_cleared_count integer := 0;
begin
  v_scope := vocera_rf_validation_normalize_study_scope(p_study_scope);
  v_user := coalesce(nullif(trim(coalesce(p_user, '')), ''), current_user);

  delete from vocera_rf_validation_study_archive_selections
  where selection_owner = v_user
    and study_scope = v_scope;
  get diagnostics v_cleared_count = row_count;

  return query select
    'cleared'::text,
    v_cleared_count,
    format('Cleared %s selected RF validation archive(s) for %s.', v_cleared_count, v_user)::text;
end;
$$;

create or replace function vocera_rf_validation_create_combined_study_archive(
  p_archive_label text,
  p_notes text default null,
  p_created_by text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  source_archive_count integer,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_scope text;
  v_user text;
  v_archive_id text;
  v_archive_label text;
  v_notes text;
  v_payload jsonb;
  v_source_archive_count integer := 0;
  v_test_run_count integer := 0;
  v_badge_event_count integer := 0;
  v_survey_point_count integer := 0;
  v_candidate_match_count integer := 0;
  v_completed_match_count integer := 0;
  v_manual_observation_count integer := 0;
  v_first_badge_time timestamptz;
  v_last_badge_time timestamptz;
  v_first_survey_time timestamptz;
  v_last_survey_time timestamptz;
begin
  v_scope := vocera_rf_validation_normalize_study_scope(p_study_scope);
  if v_scope not in ('vocera_badge', 'ipad') then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, 0::integer, format('Unsupported RF validation study scope for combine: %s', coalesce(p_study_scope, '<empty>'))::text;
    return;
  end if;

  v_user := coalesce(nullif(trim(coalesce(p_created_by, '')), ''), current_user);
  v_archive_label := nullif(trim(coalesce(p_archive_label, '')), '');
  if v_archive_label is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, 0::integer, 'Combined study label is required.'::text;
    return;
  end if;
  v_notes := nullif(trim(coalesce(p_notes, '')), '');

  select count(*)::integer
    into v_source_archive_count
  from vocera_rf_validation_study_archive_selections s
  join vocera_rf_validation_study_archives a
    on a.archive_id = s.archive_id
  where s.selection_owner = v_user
    and s.study_scope = v_scope
    and a.study_scope = v_scope;

  if v_source_archive_count < 2 then
    return query select
      'error'::text,
      null::text,
      v_source_archive_count,
      0::integer,
      0::integer,
      0::integer,
      format('Select at least two archived %s RF validation studies before creating a combined study.', v_scope)::text;
    return;
  end if;

  with source_archives as (
    select a.*
    from vocera_rf_validation_study_archive_selections s
    join vocera_rf_validation_study_archives a
      on a.archive_id = s.archive_id
    where s.selection_owner = v_user
      and s.study_scope = v_scope
      and a.study_scope = v_scope
  ),
  selected_sources as (
    select coalesce(
      jsonb_agg(
        jsonb_build_object(
          'archive_id', archive_id,
          'archive_label', archive_label,
          'archived_at', archived_at,
          'archived_by', archived_by,
          'test_run_count', test_run_count,
          'candidate_match_count', candidate_match_count,
          'completed_match_count', completed_match_count,
          'notes', notes
        )
        order by archived_at, archive_id
      ),
      '[]'::jsonb
    ) as items
    from source_archives
  ),
  input_file_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'file_path', elem->>'input_file_id'), '[]'::jsonb) as items
    from (
      select distinct on (elem->>'input_file_id') elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'vocera_rf_validation_input_files', '[]'::jsonb)) as item(elem)
      order by elem->>'input_file_id', a.archived_at desc, a.archive_id desc
    ) d
  ),
  run_input_file_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'test_run_id', elem->>'source_role', elem->>'input_file_id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'input_file_id', elem->>'source_role')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'vocera_rf_validation_run_input_files', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'input_file_id', elem->>'source_role'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  validation_test_runs_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'created_at', elem->>'test_run_id'), '[]'::jsonb) as items
    from (
      select distinct on (elem->>'test_run_id') elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'validation_test_runs', '[]'::jsonb)) as item(elem)
      order by elem->>'test_run_id', a.archived_at desc, a.archive_id desc
    ) d
  ),
  validation_source_files_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'parsed_at', elem->>'source_file_id'), '[]'::jsonb) as items
    from (
      select distinct on (elem->>'source_file_id') elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'validation_source_files', '[]'::jsonb)) as item(elem)
      order by elem->>'source_file_id', a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_scan_events_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'event_time', elem->>'event_id'), '[]'::jsonb) as items
    from (
      select distinct on (elem->>'event_id') elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_scan_events', '[]'::jsonb)) as item(elem)
      order by elem->>'event_id', a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_scan_candidates_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'event_id', elem->>'candidate_index'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'event_id', elem->>'candidate_index')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_scan_candidates', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'event_id', elem->>'candidate_index'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_rrm_neighbors_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'event_time', elem->>'id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'id')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_rrm_neighbors', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'id'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_radio_signal_samples_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'event_time', elem->>'id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'id')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_radio_signal_samples', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'id'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  ekahau_survey_points_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'measured_at', elem->>'survey_point_id'), '[]'::jsonb) as items
    from (
      select distinct on (elem->>'survey_point_id') elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'ekahau_survey_points', '[]'::jsonb)) as item(elem)
      order by elem->>'survey_point_id', a.archived_at desc, a.archive_id desc
    ) d
  ),
  manual_ekahau_observations_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'measured_at', elem->>'id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'id')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'manual_ekahau_observations', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'id'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_ekahau_candidate_matches_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'survey_time', elem->>'id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'id')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_ekahau_candidate_matches', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'id'), a.archived_at desc, a.archive_id desc
    ) d
  ),
  badge_ekahau_matches_rows as (
    select coalesce(jsonb_agg(elem order by elem->>'ekahau_time', elem->>'id'), '[]'::jsonb) as items
    from (
      select distinct on (concat_ws('|', elem->>'test_run_id', elem->>'id')) elem
      from source_archives a
      cross join lateral jsonb_array_elements(coalesce(a.payload->'badge_ekahau_matches', '[]'::jsonb)) as item(elem)
      order by concat_ws('|', elem->>'test_run_id', elem->>'id'), a.archived_at desc, a.archive_id desc
    ) d
  )
  select jsonb_build_object(
    'study_scope', v_scope,
    'current_study', null::jsonb,
    'combined_from', selected_sources.items,
    'combined_by', v_user,
    'combined_at', now(),
    'vocera_rf_validation_input_files', input_file_rows.items,
    'vocera_rf_validation_run_input_files', run_input_file_rows.items,
    'validation_test_runs', validation_test_runs_rows.items,
    'validation_source_files', validation_source_files_rows.items,
    'badge_scan_events', badge_scan_events_rows.items,
    'badge_scan_candidates', badge_scan_candidates_rows.items,
    'badge_rrm_neighbors', badge_rrm_neighbors_rows.items,
    'badge_radio_signal_samples', badge_radio_signal_samples_rows.items,
    'ekahau_survey_points', ekahau_survey_points_rows.items,
    'manual_ekahau_observations', manual_ekahau_observations_rows.items,
    'badge_ekahau_candidate_matches', badge_ekahau_candidate_matches_rows.items,
    'badge_ekahau_matches', badge_ekahau_matches_rows.items
  )
  into v_payload
  from selected_sources
  cross join input_file_rows
  cross join run_input_file_rows
  cross join validation_test_runs_rows
  cross join validation_source_files_rows
  cross join badge_scan_events_rows
  cross join badge_scan_candidates_rows
  cross join badge_rrm_neighbors_rows
  cross join badge_radio_signal_samples_rows
  cross join ekahau_survey_points_rows
  cross join manual_ekahau_observations_rows
  cross join badge_ekahau_candidate_matches_rows
  cross join badge_ekahau_matches_rows;

  v_test_run_count := jsonb_array_length(coalesce(v_payload->'validation_test_runs', '[]'::jsonb));
  v_badge_event_count := jsonb_array_length(coalesce(v_payload->'badge_scan_events', '[]'::jsonb));
  v_survey_point_count := jsonb_array_length(coalesce(v_payload->'ekahau_survey_points', '[]'::jsonb));
  v_candidate_match_count := jsonb_array_length(coalesce(v_payload->'badge_ekahau_candidate_matches', '[]'::jsonb));
  v_completed_match_count := jsonb_array_length(coalesce(v_payload->'badge_ekahau_matches', '[]'::jsonb));
  v_manual_observation_count := jsonb_array_length(coalesce(v_payload->'manual_ekahau_observations', '[]'::jsonb));

  select
    min(a.first_badge_time),
    max(a.last_badge_time),
    min(a.first_survey_time),
    max(a.last_survey_time)
  into
    v_first_badge_time,
    v_last_badge_time,
    v_first_survey_time,
    v_last_survey_time
  from vocera_rf_validation_study_archive_selections s
  join vocera_rf_validation_study_archives a
    on a.archive_id = s.archive_id
  where s.selection_owner = v_user
    and s.study_scope = v_scope
    and a.study_scope = v_scope;

  v_archive_id := 'rf_study_combined_' || v_scope || '_' || to_char(clock_timestamp() at time zone 'UTC', 'YYYYMMDD_HH24MISS_US') || '_' || substr(md5(random()::text), 1, 8);

  insert into vocera_rf_validation_study_archives (
    archive_id,
    study_scope,
    archive_label,
    archived_by,
    notes,
    test_run_count,
    badge_event_count,
    survey_point_count,
    candidate_match_count,
    completed_match_count,
    manual_observation_count,
    first_badge_time,
    last_badge_time,
    first_survey_time,
    last_survey_time,
    payload
  )
  values (
    v_archive_id,
    v_scope,
    v_archive_label,
    v_user,
    v_notes,
    v_test_run_count,
    v_badge_event_count,
    v_survey_point_count,
    v_candidate_match_count,
    v_completed_match_count,
    v_manual_observation_count,
    v_first_badge_time,
    v_last_badge_time,
    v_first_survey_time,
    v_last_survey_time,
    v_payload
  );

  delete from vocera_rf_validation_study_archive_selections
  where selection_owner = v_user
    and study_scope = v_scope;

  return query select
    'combined'::text,
    v_archive_id,
    v_source_archive_count,
    v_test_run_count,
    v_candidate_match_count,
    v_completed_match_count,
    format('Created combined %s RF validation study %s from %s source archive(s).', v_scope, v_archive_id, v_source_archive_count)::text;
end;
$$;

create or replace function vocera_rf_validation_apply_combined_study_builder(
  p_archive_label text,
  p_notes text default null,
  p_clear_selection text default null,
  p_created_by text default null,
  p_study_scope text default 'vocera_badge'
)
returns table (
  status text,
  archive_id text,
  source_archive_count integer,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_clear record;
begin
  if vocera_rf_validation_truthy(p_clear_selection) then
    select *
      into v_clear
    from vocera_rf_validation_clear_study_archive_selection(p_created_by, p_study_scope);

    return query select
      v_clear.status::text,
      null::text,
      v_clear.cleared_count::integer,
      0::integer,
      0::integer,
      0::integer,
      v_clear.message::text;
    return;
  end if;

  return query
    select *
    from vocera_rf_validation_create_combined_study_archive(p_archive_label, p_notes, p_created_by, p_study_scope);
end;
$$;



drop function if exists vocera_rf_validation_make_archive_current(text, text, text);

create or replace function vocera_rf_validation_make_archive_current(
  p_archive_id text,
  p_user text default null,
  p_notes text default null
)
returns table (
  status text,
  archived_current_archive_id text,
  restored_archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive vocera_rf_validation_study_archives%rowtype;
  v_scope text;
  v_user text;
  v_restore_notes text;
  v_checkpoint record;
  v_clear record;
  v_current jsonb;
  v_existing_current record;
begin
  v_user := coalesce(nullif(trim(coalesce(p_user, '')), ''), current_user);

  select *
    into v_archive
  from vocera_rf_validation_study_archives a
  where a.archive_id = p_archive_id;

  if not found then
    return query select
      'not_found'::text,
      null::text,
      p_archive_id,
      0::integer,
      0::integer,
      0::integer,
      format('No RF validation study archive found for %s.', coalesce(p_archive_id, '<empty>'))::text;
    return;
  end if;

  v_scope := vocera_rf_validation_normalize_study_scope(v_archive.study_scope);
  v_restore_notes := coalesce(nullif(trim(coalesce(p_notes, '')), ''), v_archive.notes);

  /*
    If the selected archive is already the named current study and the live
    row counts match the archive snapshot, do not checkpoint/clear/restore.
    This makes "Make Current" idempotent when the study is already current.
  */
  select
    cs.study_name,
    coalesce((
      select count(*)
      from validation_test_runs tr
      where vocera_rf_validation_study_scope(tr.test_run_id) = v_scope
        and tr.deleted_at is null
    ), 0)::integer as test_run_count,
    coalesce((
      select count(*)
      from badge_ekahau_candidate_matches c
      join validation_test_runs tr
        on tr.test_run_id = c.test_run_id
      where vocera_rf_validation_study_scope(c.test_run_id) = v_scope
        and tr.deleted_at is null
    ), 0)::integer as candidate_match_count,
    coalesce((
      select count(*)
      from badge_ekahau_matches m
      join validation_test_runs tr
        on tr.test_run_id = m.test_run_id
      where vocera_rf_validation_study_scope(m.test_run_id) = v_scope
        and tr.deleted_at is null
        and m.manual_entry_status in ('complete', 'missing_vendor_offset')
    ), 0)::integer as completed_match_count
    into v_existing_current
  from vocera_rf_validation_current_studies cs
  where cs.study_scope = v_scope;

  if found
     and coalesce(nullif(trim(v_existing_current.study_name), ''), '') =
         coalesce(nullif(trim(coalesce(v_archive.archive_label, '')), ''), nullif(trim(coalesce(v_archive.payload->'current_study'->>'study_name', '')), ''), '')
     and v_existing_current.test_run_count = v_archive.test_run_count
     and v_existing_current.candidate_match_count = v_archive.candidate_match_count
     and v_existing_current.completed_match_count = v_archive.completed_match_count then
    update vocera_rf_validation_current_studies
    set
      source_archive_id = v_archive.archive_id,
      source_archive_label = v_archive.archive_label,
      source_archive_saved_at = v_archive.archived_at
    where study_scope = v_scope;

    return query select
      'already_current'::text,
      null::text,
      v_archive.archive_id,
      v_archive.test_run_count,
      v_archive.candidate_match_count,
      v_archive.completed_match_count,
      format('Archived study %s is already the current %s study.', v_archive.archive_id, v_scope)::text;
    return;
  end if;

  select *
    into v_checkpoint
  from vocera_rf_validation_archive_current_study(
    format('Checkpoint before restoring %s', v_archive.archive_id),
    v_user,
    format('Automatic checkpoint before restoring archived study %s.', v_archive.archive_id),
    v_scope
  );

  if v_checkpoint.status = 'error' then
    return query select
      'error'::text,
      v_checkpoint.archive_id::text,
      v_archive.archive_id,
      0::integer,
      0::integer,
      0::integer,
      format('Unable to checkpoint current study before restore: %s', v_checkpoint.message)::text;
    return;
  end if;

  select *
    into v_clear
  from vocera_rf_validation_clear_current_study(
    v_user,
    format('Cleared before restoring %s.', v_archive.archive_id),
    v_scope
  );

  if v_clear.status = 'error' then
    return query select
      'error'::text,
      v_checkpoint.archive_id::text,
      v_archive.archive_id,
      0::integer,
      0::integer,
      0::integer,
      format('Unable to clear current study before restore: %s', v_clear.message)::text;
    return;
  end if;

  insert into vocera_rf_validation_input_files (
    input_file_id,
    study_scope,
    source_type,
    file_path,
    display_name,
    file_name,
    file_size_bytes,
    file_mtime,
    source_sha256,
    discovered_at,
    last_seen_at,
    is_available,
    notes
  )
  select
    input_file_id,
    coalesce(study_scope, v_scope),
    coalesce(source_type, 'other'),
    file_path,
    display_name,
    file_name,
    file_size_bytes,
    file_mtime,
    source_sha256,
    coalesce(discovered_at, now()),
    coalesce(last_seen_at, now()),
    coalesce(is_available, true),
    notes
  from jsonb_populate_recordset(null::vocera_rf_validation_input_files, coalesce(v_archive.payload->'vocera_rf_validation_input_files', '[]'::jsonb))
  on conflict on constraint vocera_rf_validation_input_files_pkey
  do update set
    study_scope = excluded.study_scope,
    source_type = excluded.source_type,
    file_path = excluded.file_path,
    display_name = excluded.display_name,
    file_name = excluded.file_name,
    file_size_bytes = excluded.file_size_bytes,
    file_mtime = excluded.file_mtime,
    source_sha256 = excluded.source_sha256,
    last_seen_at = greatest(vocera_rf_validation_input_files.last_seen_at, excluded.last_seen_at),
    is_available = excluded.is_available,
    notes = excluded.notes;

  insert into validation_test_runs (
    test_run_id,
    site,
    building,
    floor,
    area,
    ssid,
    badge_mac,
    badge_model,
    ekahau_device,
    ekahau_project,
    timezone,
    badge_time_offset_seconds,
    ekahau_time_offset_seconds,
    default_match_window_seconds,
    vendor_offset_source,
    notes,
    created_at,
    run_name,
    run_status,
    run_created_by,
    run_updated_at,
    run_executed_at,
    run_execution_error,
    run_notes,
    deleted_at,
    deleted_by
  )
  select
    test_run_id,
    site,
    building,
    floor,
    area,
    ssid,
    badge_mac,
    badge_model,
    ekahau_device,
    ekahau_project,
    coalesce(timezone, 'America/Chicago'),
    coalesce(badge_time_offset_seconds, 0),
    coalesce(ekahau_time_offset_seconds, 0),
    coalesce(default_match_window_seconds, 1),
    vendor_offset_source,
    notes,
    coalesce(created_at, now()),
    run_name,
    coalesce(run_status, case when deleted_at is not null then 'deleted' else 'complete' end),
    run_created_by,
    run_updated_at,
    run_executed_at,
    run_execution_error,
    run_notes,
    deleted_at,
    deleted_by
  from jsonb_populate_recordset(null::validation_test_runs, coalesce(v_archive.payload->'validation_test_runs', '[]'::jsonb));

  insert into vocera_rf_validation_run_input_files
  select * from jsonb_populate_recordset(null::vocera_rf_validation_run_input_files, coalesce(v_archive.payload->'vocera_rf_validation_run_input_files', '[]'::jsonb))
  on conflict on constraint vocera_rf_validation_run_input_files_pkey
  do update set selected_at = excluded.selected_at;

  insert into validation_source_files
  select * from jsonb_populate_recordset(null::validation_source_files, coalesce(v_archive.payload->'validation_source_files', '[]'::jsonb));

  insert into badge_scan_events
  select * from jsonb_populate_recordset(null::badge_scan_events, coalesce(v_archive.payload->'badge_scan_events', '[]'::jsonb));

  insert into badge_scan_candidates
  select * from jsonb_populate_recordset(null::badge_scan_candidates, coalesce(v_archive.payload->'badge_scan_candidates', '[]'::jsonb));

  insert into badge_rrm_neighbors
  select * from jsonb_populate_recordset(null::badge_rrm_neighbors, coalesce(v_archive.payload->'badge_rrm_neighbors', '[]'::jsonb));

  insert into badge_radio_signal_samples
  select * from jsonb_populate_recordset(null::badge_radio_signal_samples, coalesce(v_archive.payload->'badge_radio_signal_samples', '[]'::jsonb));

  insert into ekahau_survey_points
  select * from jsonb_populate_recordset(null::ekahau_survey_points, coalesce(v_archive.payload->'ekahau_survey_points', '[]'::jsonb));

  insert into manual_ekahau_observations
  select * from jsonb_populate_recordset(null::manual_ekahau_observations, coalesce(v_archive.payload->'manual_ekahau_observations', '[]'::jsonb));

  insert into badge_ekahau_candidate_matches
  select * from jsonb_populate_recordset(null::badge_ekahau_candidate_matches, coalesce(v_archive.payload->'badge_ekahau_candidate_matches', '[]'::jsonb));

  insert into badge_ekahau_matches
  select * from jsonb_populate_recordset(null::badge_ekahau_matches, coalesce(v_archive.payload->'badge_ekahau_matches', '[]'::jsonb));

  perform setval(pg_get_serial_sequence('badge_rrm_neighbors', 'id'), greatest(coalesce((select max(id) from badge_rrm_neighbors), 0), 1)::bigint, true);
  perform setval(pg_get_serial_sequence('badge_radio_signal_samples', 'id'), greatest(coalesce((select max(id) from badge_radio_signal_samples), 0), 1)::bigint, true);
  perform setval(pg_get_serial_sequence('manual_ekahau_observations', 'id'), greatest(coalesce((select max(id) from manual_ekahau_observations), 0), 1)::bigint, true);
  perform setval(pg_get_serial_sequence('badge_ekahau_candidate_matches', 'id'), greatest(coalesce((select max(id) from badge_ekahau_candidate_matches), 0), 1)::bigint, true);
  perform setval(pg_get_serial_sequence('badge_ekahau_matches', 'id'), greatest(coalesce((select max(id) from badge_ekahau_matches), 0), 1)::bigint, true);

  v_current := coalesce(v_archive.payload->'current_study', '{}'::jsonb);

  insert into vocera_rf_validation_current_studies (
    study_scope,
    study_name,
    started_at,
    started_by,
    updated_at,
    updated_by,
    notes
  )
  values (
    v_scope,
    coalesce(nullif(trim(v_current->>'study_name'), ''), nullif(trim(coalesce(v_archive.archive_label, '')), ''), v_archive.archive_id),
    coalesce(nullif(v_current->>'started_at', '')::timestamptz, now()),
    coalesce(nullif(trim(v_current->>'started_by'), ''), v_user),
    now(),
    v_user,
    coalesce(v_restore_notes, nullif(trim(v_current->>'notes'), ''))
  )
  on conflict on constraint vocera_rf_validation_current_studies_pkey
  do update set
    study_name = excluded.study_name,
    updated_at = excluded.updated_at,
    updated_by = excluded.updated_by,
    notes = excluded.notes;

  update vocera_rf_validation_current_studies
  set
    source_archive_id = v_archive.archive_id,
    source_archive_label = v_archive.archive_label,
    source_archive_saved_at = v_archive.archived_at
  where study_scope = v_scope;

  return query select
    'restored'::text,
    case when v_checkpoint.status = 'archived' then v_checkpoint.archive_id::text else null::text end,
    v_archive.archive_id,
    v_archive.test_run_count,
    v_archive.candidate_match_count,
    v_archive.completed_match_count,
    format(
      'Archived current study%s, cleared current %s data, and restored archived study %s with %s run(s), %s candidate row(s), and %s completed match row(s).',
      case when v_checkpoint.status = 'archived' then format(' as %s', v_checkpoint.archive_id) else ' checkpoint skipped because current study was empty' end,
      v_scope,
      v_archive.archive_id,
      v_archive.test_run_count,
      v_archive.candidate_match_count,
      v_archive.completed_match_count
    )::text;
end;
$$;

create or replace function vocera_rf_validation_delete_study_archive(
  p_archive_id text,
  p_deleted_by text default null
)
returns table (
  status text,
  archive_id text,
  test_run_count integer,
  candidate_match_count integer,
  completed_match_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive vocera_rf_validation_study_archives%rowtype;
begin
  if nullif(trim(coalesce(p_archive_id, '')), '') is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 0::integer, 'Missing archive_id.'::text;
    return;
  end if;

  delete from vocera_rf_validation_study_archives a
  where a.archive_id = p_archive_id
  returning *
  into v_archive;

  if not found then
    return query select 'not_found'::text, p_archive_id, 0::integer, 0::integer, 0::integer, format('No RF validation study archive found for %s.', p_archive_id)::text;
    return;
  end if;

  return query select
    'deleted'::text,
    v_archive.archive_id,
    v_archive.test_run_count,
    v_archive.candidate_match_count,
    v_archive.completed_match_count,
    format('Deleted RF validation study archive %s.', v_archive.archive_id)::text;
end;
$$;

create or replace function vocera_rf_validation_vendor_offset(p_band text)
returns numeric
language sql
immutable
as $$
  select case p_band
    when '2.4GHz' then -5::numeric
    when '5GHz' then -8::numeric
    else null::numeric
  end;
$$;

create or replace function vocera_rf_validation_submit_candidate_match(
  p_candidate_match_id text,
  p_ekahau_rssi_dbm text,
  p_ekahau_snr_db text default null,
  p_notes text default null,
  p_entered_by text default null
)
returns table (
  status text,
  candidate_rows integer,
  inserted_matches integer,
  message text
)
language plpgsql
as $$
declare
  v_candidate_match_id bigint;
  v_candidate badge_ekahau_candidate_matches%rowtype;
  v_rssi numeric;
  v_snr numeric;
  v_observation_id bigint;
  v_candidate_rows integer;
  v_inserted_matches integer;
begin
  if nullif(trim(coalesce(p_candidate_match_id, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Missing candidate_match_id.'::text;
    return;
  end if;

  if nullif(trim(coalesce(p_ekahau_rssi_dbm, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Ekahau RSSI is required.'::text;
    return;
  end if;

  begin
    v_candidate_match_id := trim(p_candidate_match_id)::bigint;
    v_rssi := trim(p_ekahau_rssi_dbm)::numeric;
    if nullif(trim(coalesce(p_ekahau_snr_db, '')), '') is not null then
      v_snr := trim(p_ekahau_snr_db)::numeric;
    end if;
  exception
    when others then
      return query select 'error'::text, 0::integer, 0::integer, SQLERRM::text;
      return;
  end;

  select *
    into v_candidate
  from badge_ekahau_candidate_matches c
  where c.id = v_candidate_match_id;

  if not found then
    return query select 'error'::text, 0::integer, 0::integer, format('No candidate row found for id %s.', v_candidate_match_id)::text;
    return;
  end if;

  select count(*)
    into v_candidate_rows
  from badge_ekahau_candidate_matches c
  where c.test_run_id = v_candidate.test_run_id
    and lower(c.bssid) = lower(v_candidate.bssid)
    and c.survey_time = v_candidate.survey_time;

  delete from badge_ekahau_matches m
  where m.test_run_id = v_candidate.test_run_id
    and lower(m.bssid) = lower(v_candidate.bssid)
    and m.ekahau_time = v_candidate.survey_time;

  delete from manual_ekahau_observations o
  where o.test_run_id = v_candidate.test_run_id
    and lower(o.bssid) = lower(v_candidate.bssid)
    and o.measured_at = v_candidate.survey_time;

  insert into manual_ekahau_observations (
    test_run_id,
    survey_point_id,
    measured_at,
    floor,
    area,
    x_m,
    y_m,
    ssid,
    bssid,
    ap_name,
    channel,
    band,
    rssi_dbm,
    snr_db,
    entered_by,
    notes
  )
  values (
    v_candidate.test_run_id,
    v_candidate.survey_point_id,
    v_candidate.survey_time,
    v_candidate.floor,
    v_candidate.area,
    v_candidate.x_m,
    v_candidate.y_m,
    v_candidate.ssid,
    v_candidate.bssid,
    v_candidate.ap_name,
    v_candidate.channel,
    v_candidate.band,
    v_rssi,
    v_snr,
    coalesce(nullif(trim(coalesce(p_entered_by, '')), ''), current_user),
    nullif(trim(coalesce(p_notes, '')), '')
  )
  returning id into v_observation_id;

  insert into badge_ekahau_matches (
    test_run_id,
    candidate_match_id,
    ekahau_observation_id,
    survey_point_id,
    badge_event_id,
    badge_candidate_index,
    badge_time,
    ekahau_time,
    ekahau_survey_id,
    ekahau_survey_name,
    time_delta_seconds,
    badge_mac,
    badge_model,
    ssid,
    bssid,
    ap_name,
    channel,
    band,
    badge_rssi_dbm,
    badge_noise_floor_dbm,
    badge_snr_db,
    badge_snr_source,
    badge_snr_time,
    badge_snr_time_delta_seconds,
    badge_radio_signal_level_dbm,
    ekahau_rssi_dbm,
    ekahau_snr_db,
    vendor_offset_db,
    expected_badge_rssi_dbm,
    raw_delta_db,
    calibrated_delta_db,
    absolute_calibrated_delta_db,
    badge_cu_percent,
    badge_score,
    badge_selected,
    floor,
    area,
    x_m,
    y_m,
    match_quality,
    manual_entry_status
  )
  select
    c.test_run_id,
    c.id,
    v_observation_id,
    c.survey_point_id,
    c.badge_event_id,
    c.badge_candidate_index,
    c.badge_time,
    c.survey_time,
    c.ekahau_survey_id,
    c.ekahau_survey_name,
    c.time_delta_seconds,
    c.badge_mac,
    c.badge_model,
    c.ssid,
    c.bssid,
    c.ap_name,
    c.channel,
    c.band,
    c.badge_rssi_dbm,
    c.badge_noise_floor_dbm,
    c.badge_snr_db,
    c.badge_snr_source,
    c.badge_snr_time,
    c.badge_snr_time_delta_seconds,
    c.badge_radio_signal_level_dbm,
    v_rssi,
    v_snr,
    o.vendor_offset_db,
    case when o.vendor_offset_db is not null then v_rssi + o.vendor_offset_db end,
    case when c.badge_rssi_dbm is not null then c.badge_rssi_dbm - v_rssi end,
    case when c.badge_rssi_dbm is not null and o.vendor_offset_db is not null then c.badge_rssi_dbm - (v_rssi + o.vendor_offset_db) end,
    abs(case when c.badge_rssi_dbm is not null and o.vendor_offset_db is not null then c.badge_rssi_dbm - (v_rssi + o.vendor_offset_db) end),
    c.badge_cu_percent,
    c.badge_score,
    c.badge_selected,
    c.floor,
    c.area,
    c.x_m,
    c.y_m,
    c.match_quality,
    case when o.vendor_offset_db is null then 'missing_vendor_offset' else 'complete' end
  from badge_ekahau_candidate_matches c
  cross join lateral (
    select vocera_rf_validation_vendor_offset(c.band) as vendor_offset_db
  ) o
  where c.id = v_candidate_match_id;

  get diagnostics v_inserted_matches = row_count;

  update badge_ekahau_candidate_matches c
  set manual_entry_status = 'complete'
  where c.test_run_id = v_candidate.test_run_id
    and lower(c.bssid) = lower(v_candidate.bssid)
    and c.survey_time = v_candidate.survey_time;

  return query select
    'complete'::text,
    v_candidate_rows,
    v_inserted_matches,
    format(
      'Stored Ekahau RSSI %s dBm for candidate %s (%s) and materialized %s match row(s).',
      v_rssi,
      v_candidate_match_id,
      v_candidate.bssid,
      v_inserted_matches
    )::text;
end;
$$;

create or replace function vocera_rf_validation_delete_candidate_match(
  p_candidate_match_id text,
  p_deleted_by text default null
)
returns table (
  status text,
  candidate_rows integer,
  inserted_matches integer,
  message text
)
language plpgsql
as $$
declare
  v_candidate_match_id bigint;
  v_candidate badge_ekahau_candidate_matches%rowtype;
  v_observation_ids bigint[];
  v_deleted_matches integer := 0;
  v_deleted_observations integer := 0;
  v_deleted_candidates integer := 0;
begin
  if nullif(trim(coalesce(p_candidate_match_id, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Missing candidate_match_id.'::text;
    return;
  end if;

  begin
    v_candidate_match_id := trim(p_candidate_match_id)::bigint;
  exception
    when others then
      return query select 'error'::text, 0::integer, 0::integer, SQLERRM::text;
      return;
  end;

  select *
    into v_candidate
  from badge_ekahau_candidate_matches c
  where c.id = v_candidate_match_id;

  if not found then
    return query select 'error'::text, 0::integer, 0::integer, format('No candidate row found for id %s.', v_candidate_match_id)::text;
    return;
  end if;

  select coalesce(array_agg(distinct m.ekahau_observation_id) filter (where m.ekahau_observation_id is not null), '{}'::bigint[])
    into v_observation_ids
  from badge_ekahau_matches m
  where m.candidate_match_id = v_candidate_match_id;

  delete from badge_ekahau_matches m
  where m.candidate_match_id = v_candidate_match_id;
  get diagnostics v_deleted_matches = row_count;

  delete from manual_ekahau_observations o
  where o.id = any(v_observation_ids)
    and not exists (
      select 1
      from badge_ekahau_matches m
      where m.ekahau_observation_id = o.id
    );
  get diagnostics v_deleted_observations = row_count;

  delete from badge_ekahau_candidate_matches c
  where c.id = v_candidate_match_id;
  get diagnostics v_deleted_candidates = row_count;

  return query select
    'deleted'::text,
    v_deleted_candidates,
    v_deleted_matches,
    format(
      'Deleted candidate %s (%s), %s match row(s), and %s now-unused manual observation row(s).',
      v_candidate_match_id,
      v_candidate.bssid,
      v_deleted_matches,
      v_deleted_observations
    )::text;
end;
$$;

create or replace function vocera_rf_validation_clear_candidate_manual_entry(
  p_candidate_match_id text,
  p_deleted_by text default null
)
returns table (
  status text,
  candidate_rows integer,
  inserted_matches integer,
  message text
)
language plpgsql
as $$
declare
  v_candidate_match_id bigint;
  v_candidate badge_ekahau_candidate_matches%rowtype;
  v_observation_ids bigint[];
  v_deleted_matches integer := 0;
  v_deleted_observations integer := 0;
  v_updated_candidates integer := 0;
begin
  if nullif(trim(coalesce(p_candidate_match_id, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Missing candidate_match_id.'::text;
    return;
  end if;

  begin
    v_candidate_match_id := trim(p_candidate_match_id)::bigint;
  exception
    when others then
      return query select 'error'::text, 0::integer, 0::integer, SQLERRM::text;
      return;
  end;

  select *
    into v_candidate
  from badge_ekahau_candidate_matches c
  where c.id = v_candidate_match_id;

  if not found then
    return query select 'error'::text, 0::integer, 0::integer, format('No candidate row found for id %s.', v_candidate_match_id)::text;
    return;
  end if;

  select coalesce(array_agg(distinct m.ekahau_observation_id) filter (where m.ekahau_observation_id is not null), '{}'::bigint[])
    into v_observation_ids
  from badge_ekahau_matches m
  join badge_ekahau_candidate_matches c
    on c.id = m.candidate_match_id
  where lower(c.bssid) = lower(v_candidate.bssid)
    and c.test_run_id = v_candidate.test_run_id
    and c.survey_time = v_candidate.survey_time;

  delete from badge_ekahau_matches m
  where m.test_run_id = v_candidate.test_run_id
    and lower(m.bssid) = lower(v_candidate.bssid)
    and m.ekahau_time = v_candidate.survey_time;
  get diagnostics v_deleted_matches = row_count;

  delete from manual_ekahau_observations o
  where o.id = any(v_observation_ids)
    and o.test_run_id = v_candidate.test_run_id
    and not exists (
      select 1
      from badge_ekahau_matches m
      where m.ekahau_observation_id = o.id
    );
  get diagnostics v_deleted_observations = row_count;

  update badge_ekahau_candidate_matches c
  set manual_entry_status = 'pending'
  where c.test_run_id = v_candidate.test_run_id
    and lower(c.bssid) = lower(v_candidate.bssid)
    and c.survey_time = v_candidate.survey_time;
  get diagnostics v_updated_candidates = row_count;

  return query select
    'cleared'::text,
    v_updated_candidates,
    v_deleted_matches,
    format(
      'Cleared manual entry for candidate %s (%s): deleted %s match row(s), deleted %s now-unused manual observation row(s), and returned %s candidate row(s) to pending.',
      v_candidate_match_id,
      v_candidate.bssid,
      v_deleted_matches,
      v_deleted_observations,
      v_updated_candidates
    )::text;
end;
$$;

create or replace function vocera_rf_validation_submit_manual_entry(
  p_submit text,
  p_test_run_id text,
  p_survey_point_id text,
  p_bssid text,
  p_survey_time text,
  p_ekahau_rssi_dbm text,
  p_ekahau_snr_db text default null,
  p_notes text default null,
  p_entered_by text default null
)
returns table (
  status text,
  candidate_rows integer,
  inserted_matches integer,
  message text
)
language plpgsql
as $$
declare
  v_survey_time timestamptz;
  v_rssi numeric;
  v_snr numeric;
  v_observation_id bigint;
  v_candidate_rows integer;
  v_inserted_matches integer;
  v_bssid text;
begin
  if coalesce(nullif(trim(p_submit), ''), 'idle') <> 'submit' then
    return query select
      'waiting'::text,
      0::integer,
      0::integer,
      'Choose a pending row, enter Ekahau RSSI/SNR, then set Submit Manual Entry to submit.'::text;
    return;
  end if;

  if nullif(trim(coalesce(p_test_run_id, '')), '') is null
    or nullif(trim(coalesce(p_survey_point_id, '')), '') is null
    or nullif(trim(coalesce(p_bssid, '')), '') is null
    or nullif(trim(coalesce(p_survey_time, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Missing pending-row identity. Use the row link in the pending manual entry table.'::text;
    return;
  end if;

  if nullif(trim(coalesce(p_ekahau_rssi_dbm, '')), '') is null then
    return query select 'error'::text, 0::integer, 0::integer, 'Ekahau RSSI is required.'::text;
    return;
  end if;

  begin
    v_survey_time := trim(p_survey_time)::timestamptz;
    v_rssi := trim(p_ekahau_rssi_dbm)::numeric;
    if nullif(trim(coalesce(p_ekahau_snr_db, '')), '') is not null then
      v_snr := trim(p_ekahau_snr_db)::numeric;
    end if;
  exception
    when others then
      return query select 'error'::text, 0::integer, 0::integer, SQLERRM::text;
      return;
  end;

  v_bssid := lower(trim(p_bssid));

  select count(*)
    into v_candidate_rows
  from badge_ekahau_candidate_matches c
  where c.test_run_id = p_test_run_id
    and lower(c.bssid) = v_bssid
    and c.survey_time = v_survey_time;

  if v_candidate_rows = 0 then
    return query select 'error'::text, 0::integer, 0::integer, 'No pending candidate row matched the selected BSSID and survey time.'::text;
    return;
  end if;

  delete from badge_ekahau_matches m
  where m.test_run_id = p_test_run_id
    and lower(m.bssid) = v_bssid
    and m.ekahau_time = v_survey_time;

  delete from manual_ekahau_observations o
  where o.test_run_id = p_test_run_id
    and lower(o.bssid) = v_bssid
    and o.measured_at = v_survey_time;

  insert into manual_ekahau_observations (
    test_run_id,
    survey_point_id,
    measured_at,
    floor,
    area,
    x_m,
    y_m,
    ssid,
    bssid,
    ap_name,
    channel,
    band,
    rssi_dbm,
    snr_db,
    entered_by,
    notes
  )
  select
    c.test_run_id,
    c.survey_point_id,
    c.survey_time,
    c.floor,
    c.area,
    c.x_m,
    c.y_m,
    c.ssid,
    c.bssid,
    c.ap_name,
    c.channel,
    c.band,
    v_rssi,
    v_snr,
    coalesce(nullif(trim(coalesce(p_entered_by, '')), ''), current_user),
    nullif(trim(coalesce(p_notes, '')), '')
  from badge_ekahau_candidate_matches c
  where c.test_run_id = p_test_run_id
    and lower(c.bssid) = v_bssid
    and c.survey_time = v_survey_time
  order by c.badge_selected desc, c.badge_score desc nulls last, c.badge_rssi_dbm desc nulls last, c.badge_candidate_index
  limit 1
  returning id into v_observation_id;

  insert into badge_ekahau_matches (
    test_run_id,
    candidate_match_id,
    ekahau_observation_id,
    survey_point_id,
    badge_event_id,
    badge_candidate_index,
    badge_time,
    ekahau_time,
    ekahau_survey_id,
    ekahau_survey_name,
    time_delta_seconds,
    badge_mac,
    badge_model,
    ssid,
    bssid,
    ap_name,
    channel,
    band,
    badge_rssi_dbm,
    badge_noise_floor_dbm,
    badge_snr_db,
    badge_snr_source,
    badge_snr_time,
    badge_snr_time_delta_seconds,
    badge_radio_signal_level_dbm,
    ekahau_rssi_dbm,
    ekahau_snr_db,
    vendor_offset_db,
    expected_badge_rssi_dbm,
    raw_delta_db,
    calibrated_delta_db,
    absolute_calibrated_delta_db,
    badge_cu_percent,
    badge_score,
    badge_selected,
    floor,
    area,
    x_m,
    y_m,
    match_quality,
    manual_entry_status
  )
  select
    c.test_run_id,
    c.id,
    v_observation_id,
    c.survey_point_id,
    c.badge_event_id,
    c.badge_candidate_index,
    c.badge_time,
    c.survey_time,
    c.ekahau_survey_id,
    c.ekahau_survey_name,
    c.time_delta_seconds,
    c.badge_mac,
    c.badge_model,
    c.ssid,
    c.bssid,
    c.ap_name,
    c.channel,
    c.band,
    c.badge_rssi_dbm,
    c.badge_noise_floor_dbm,
    c.badge_snr_db,
    c.badge_snr_source,
    c.badge_snr_time,
    c.badge_snr_time_delta_seconds,
    c.badge_radio_signal_level_dbm,
    v_rssi,
    v_snr,
    o.vendor_offset_db,
    case when o.vendor_offset_db is not null then v_rssi + o.vendor_offset_db end,
    case when c.badge_rssi_dbm is not null then c.badge_rssi_dbm - v_rssi end,
    case when c.badge_rssi_dbm is not null and o.vendor_offset_db is not null then c.badge_rssi_dbm - (v_rssi + o.vendor_offset_db) end,
    abs(case when c.badge_rssi_dbm is not null and o.vendor_offset_db is not null then c.badge_rssi_dbm - (v_rssi + o.vendor_offset_db) end),
    c.badge_cu_percent,
    c.badge_score,
    c.badge_selected,
    c.floor,
    c.area,
    c.x_m,
    c.y_m,
    c.match_quality,
    case when o.vendor_offset_db is null then 'missing_vendor_offset' else 'complete' end
  from badge_ekahau_candidate_matches c
  cross join lateral (
    select vocera_rf_validation_vendor_offset(c.band) as vendor_offset_db
  ) o
  where c.id = (
    select c2.id
    from badge_ekahau_candidate_matches c2
    where c2.test_run_id = p_test_run_id
      and lower(c2.bssid) = v_bssid
      and c2.survey_time = v_survey_time
    order by c2.badge_selected desc, c2.badge_score desc nulls last, c2.badge_rssi_dbm desc nulls last, c2.id
    limit 1
  );

  get diagnostics v_inserted_matches = row_count;

  update badge_ekahau_candidate_matches c
  set manual_entry_status = 'complete'
  where c.test_run_id = p_test_run_id
    and lower(c.bssid) = v_bssid
    and c.survey_time = v_survey_time;

  return query select
    'complete'::text,
    v_candidate_rows,
    v_inserted_matches,
    format('Stored Ekahau RSSI %s dBm for %s and materialized %s match row(s).', v_rssi, v_bssid, v_inserted_matches)::text;
end;
$$;

-- ---------------------------------------------------------------------------
-- Manual statistical samples
--
-- Study-scoped manually entered Ekahau measurements (RSSI dBm and/or SNR dB).
-- Studies are the unit of analysis: a human types observed Ekahau values into a
-- study and the app computes central-limit summary statistics (mean, std dev,
-- p05/p95, etc.) and flags outliers. This is independent of the badge-log/Ekahau
-- file parsing path and does not require a test run.
-- ---------------------------------------------------------------------------
create table if not exists vocera_rf_manual_samples (
  sample_id text primary key,
  study_id text not null references vocera_studies(study_id),
  label text,
  ekahau_rssi_dbm numeric,
  ekahau_snr_db numeric,
  notes text,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create index if not exists idx_vocera_rf_manual_samples_study
  on vocera_rf_manual_samples (study_id)
  where deleted_at is null;
