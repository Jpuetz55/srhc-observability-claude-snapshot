create or replace view v_vocera_ekahau_stats_by_floor_band as
select
  test_run_id,
  floor,
  band,
  count(*) as sample_count,
  avg(calibrated_delta_db) as mean_calibrated_delta_db,
  stddev_samp(calibrated_delta_db) as stddev_calibrated_delta_db,
  percentile_cont(0.05) within group (order by calibrated_delta_db) as p05_calibrated_delta_db,
  percentile_cont(0.95) within group (order by calibrated_delta_db) as p95_calibrated_delta_db,
  percentile_cont(0.95) within group (order by absolute_calibrated_delta_db) as p95_abs_calibrated_delta_db
from badge_ekahau_matches
where match_quality = 'exact_1s'
  and manual_entry_status = 'complete'
  and calibrated_delta_db is not null
group by test_run_id, floor, band;

create or replace view v_vocera_ekahau_stats_by_bssid as
select
  test_run_id,
  bssid,
  ap_name,
  channel,
  band,
  count(*) as sample_count,
  avg(calibrated_delta_db) as mean_calibrated_delta_db,
  stddev_samp(calibrated_delta_db) as stddev_calibrated_delta_db,
  percentile_cont(0.05) within group (order by calibrated_delta_db) as p05_calibrated_delta_db,
  percentile_cont(0.95) within group (order by calibrated_delta_db) as p95_calibrated_delta_db,
  percentile_cont(0.95) within group (order by absolute_calibrated_delta_db) as p95_abs_calibrated_delta_db
from badge_ekahau_matches
where match_quality = 'exact_1s'
  and manual_entry_status = 'complete'
  and calibrated_delta_db is not null
group by test_run_id, bssid, ap_name, channel, band;

create or replace view v_vocera_ekahau_outliers as
with stats as (
  select
    test_run_id,
    floor,
    band,
    count(*) as sample_count,
    avg(calibrated_delta_db) as mean_delta,
    stddev_samp(calibrated_delta_db) as stddev_delta
  from badge_ekahau_matches
  where match_quality = 'exact_1s'
    and manual_entry_status = 'complete'
    and calibrated_delta_db is not null
  group by test_run_id, floor, band
)
select
  m.*,
  s.sample_count,
  s.mean_delta,
  s.stddev_delta,
  (m.calibrated_delta_db - s.mean_delta) / nullif(s.stddev_delta, 0) as z_score,
  case
    when s.sample_count < 30 then 'insufficient_samples'
    when s.stddev_delta is null or s.stddev_delta = 0 then 'no_variance'
    when abs((m.calibrated_delta_db - s.mean_delta) / nullif(s.stddev_delta, 0)) > 2 then 'outlier'
    else 'normal'
  end as outlier_status
from badge_ekahau_matches m
join stats s
  on s.test_run_id = m.test_run_id
 and coalesce(s.floor, '') = coalesce(m.floor, '')
 and coalesce(s.band, '') = coalesce(m.band, '')
where m.manual_entry_status = 'complete';

drop view if exists v_vocera_ekahau_pending_manual_entry;
drop view if exists v_vocera_ekahau_completed_manual_entry;

create or replace view v_vocera_ekahau_pending_manual_entry as
with pending as (
  select
    c.*,
    row_number() over (
      partition by lower(c.bssid), c.survey_time
      order by c.badge_selected desc, c.badge_score desc nulls last, c.badge_rssi_dbm desc nulls last, c.id
    ) as pending_rank
  from badge_ekahau_candidate_matches c
  where c.manual_entry_status = 'pending'
    and not exists (
      select 1
      from badge_ekahau_matches m
      where lower(m.bssid) = lower(c.bssid)
        and m.ekahau_time = c.survey_time
        and m.manual_entry_status in ('complete', 'missing_vendor_offset')
    )
)
select
  test_run_id,
  survey_point_id,
  (survey_time at time zone 'America/Chicago')::text as survey_time,
  ekahau_survey_id,
  ekahau_survey_name,
  badge_time,
  time_delta_seconds,
  floor,
  area,
  x_m,
  y_m,
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
  badge_cu_percent,
  badge_score,
  badge_selected,
  match_quality,
  id as candidate_match_id
from pending
where pending_rank = 1;

create or replace view v_vocera_ekahau_completed_manual_entry as
select
  m.id as match_id,
  m.candidate_match_id,
  m.test_run_id,
  m.survey_point_id,
  (m.ekahau_time at time zone 'America/Chicago')::text as survey_time,
  m.ekahau_survey_id,
  m.ekahau_survey_name,
  m.floor,
  m.area,
  m.x_m,
  m.y_m,
  m.badge_mac,
  m.badge_model,
  m.ssid,
  m.bssid,
  m.ap_name,
  m.channel,
  m.band,
  m.ekahau_rssi_dbm,
  m.ekahau_snr_db,
  o.notes,
  o.entered_by,
  o.created_at as entered_at,
  m.badge_rssi_dbm,
  m.badge_radio_signal_level_dbm,
  m.badge_noise_floor_dbm,
  m.badge_snr_db,
  m.badge_snr_source,
  m.badge_snr_time_delta_seconds,
  m.expected_badge_rssi_dbm,
  m.raw_delta_db,
  m.calibrated_delta_db,
  m.absolute_calibrated_delta_db,
  m.badge_cu_percent,
  m.badge_score,
  m.badge_selected,
  m.match_quality,
  m.manual_entry_status
from badge_ekahau_matches m
left join manual_ekahau_observations o
  on o.id = m.ekahau_observation_id
where m.manual_entry_status in ('complete', 'missing_vendor_offset');

create or replace view v_vocera_rf_validation_current_study as
with scopes as (
  select unnest(array['vocera_badge'::text, 'ipad'::text]) as study_scope
),
runs as (
  select
    vocera_rf_validation_study_scope(tr.test_run_id) as study_scope,
    count(*)::integer as test_run_count,
    min(tr.created_at) as first_run_created_at,
    max(tr.created_at) as last_run_created_at
  from validation_test_runs tr
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(tr.test_run_id)
),
badge_events as (
  select
    vocera_rf_validation_study_scope(e.test_run_id) as study_scope,
    count(*)::integer as badge_event_count,
    min(e.event_time) as first_badge_time,
    max(e.event_time) as last_badge_time
  from badge_scan_events e
  join validation_test_runs tr
    on tr.test_run_id = e.test_run_id
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(e.test_run_id)
),
survey_points as (
  select
    vocera_rf_validation_study_scope(p.test_run_id) as study_scope,
    count(*)::integer as survey_point_count,
    min(p.measured_at) as first_survey_time,
    max(p.measured_at) as last_survey_time
  from ekahau_survey_points p
  join validation_test_runs tr
    on tr.test_run_id = p.test_run_id
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(p.test_run_id)
),
candidate_matches as (
  select
    vocera_rf_validation_study_scope(c.test_run_id) as study_scope,
    count(*)::integer as candidate_match_count,
    count(*) filter (where c.manual_entry_status = 'pending')::integer as pending_candidate_match_count
  from badge_ekahau_candidate_matches c
  join validation_test_runs tr
    on tr.test_run_id = c.test_run_id
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(c.test_run_id)
),
completed_matches as (
  select
    vocera_rf_validation_study_scope(m.test_run_id) as study_scope,
    count(*) filter (where m.manual_entry_status in ('complete', 'missing_vendor_offset'))::integer as completed_match_count,
    count(*) filter (where m.manual_entry_status = 'complete')::integer as complete_match_count,
    count(*) filter (where m.manual_entry_status = 'missing_vendor_offset')::integer as missing_vendor_offset_match_count,
    avg(m.calibrated_delta_db) filter (where m.manual_entry_status = 'complete' and m.calibrated_delta_db is not null) as mean_calibrated_delta_db,
    avg(m.calibrated_delta_db) filter (where m.manual_entry_status = 'complete' and m.band = '2.4GHz' and m.calibrated_delta_db is not null) as mean_24ghz_calibrated_delta_db,
    avg(m.calibrated_delta_db) filter (where m.manual_entry_status = 'complete' and m.band = '5GHz' and m.calibrated_delta_db is not null) as mean_5ghz_calibrated_delta_db
  from badge_ekahau_matches m
  join validation_test_runs tr
    on tr.test_run_id = m.test_run_id
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(m.test_run_id)
),
manual_observations as (
  select
    vocera_rf_validation_study_scope(o.test_run_id) as study_scope,
    count(*)::integer as manual_observation_count
  from manual_ekahau_observations o
  join validation_test_runs tr
    on tr.test_run_id = o.test_run_id
  where tr.deleted_at is null
  group by vocera_rf_validation_study_scope(o.test_run_id)
),
archives as (
  select
    a.study_scope,
    count(*)::integer as archive_count,
    max(a.archived_at) as latest_archived_at
  from vocera_rf_validation_study_archives a
  where coalesce(a.archive_label, '') not like 'Checkpoint before restoring %'
  group by a.study_scope
)
select
  s.study_scope,
  coalesce(r.test_run_count, 0) as test_run_count,
  r.first_run_created_at,
  r.last_run_created_at,
  coalesce(be.badge_event_count, 0) as badge_event_count,
  be.first_badge_time,
  be.last_badge_time,
  coalesce(sp.survey_point_count, 0) as survey_point_count,
  sp.first_survey_time,
  sp.last_survey_time,
  coalesce(cm.candidate_match_count, 0) as candidate_match_count,
  coalesce(cm.pending_candidate_match_count, 0) as pending_candidate_match_count,
  coalesce(matches.completed_match_count, 0) as completed_match_count,
  coalesce(matches.complete_match_count, 0) as complete_match_count,
  coalesce(matches.missing_vendor_offset_match_count, 0) as missing_vendor_offset_match_count,
  coalesce(mo.manual_observation_count, 0) as manual_observation_count,
  matches.mean_calibrated_delta_db,
  matches.mean_24ghz_calibrated_delta_db,
  matches.mean_5ghz_calibrated_delta_db,
  coalesce(a.archive_count, 0) as archive_count,
  a.latest_archived_at,
  meta.study_name,
  meta.started_at as study_started_at,
  meta.started_by as study_started_by,
  meta.updated_at as study_updated_at,
  meta.updated_by as study_updated_by,
  meta.notes as study_notes,
  meta.source_archive_id,
  meta.source_archive_label,
  meta.source_archive_saved_at
from scopes s
left join vocera_rf_validation_current_studies meta
  on meta.study_scope = s.study_scope
left join runs r
  on r.study_scope = s.study_scope
left join badge_events be
  on be.study_scope = s.study_scope
left join survey_points sp
  on sp.study_scope = s.study_scope
left join candidate_matches cm
  on cm.study_scope = s.study_scope
left join completed_matches matches
  on matches.study_scope = s.study_scope
left join manual_observations mo
  on mo.study_scope = s.study_scope
left join archives a
  on a.study_scope = s.study_scope;

create or replace view v_vocera_rf_validation_study_archive_selection as
select
  s.selection_owner,
  s.study_scope,
  s.archive_id,
  s.selected_at,
  a.archive_label,
  a.archived_at,
  a.archived_by,
  a.test_run_count,
  a.badge_event_count,
  a.survey_point_count,
  a.candidate_match_count,
  a.completed_match_count,
  a.manual_observation_count,
  a.first_badge_time,
  a.last_badge_time,
  a.first_survey_time,
  a.last_survey_time,
  a.notes,
  case
    when a.payload ? 'combined_from' then jsonb_array_length(coalesce(a.payload->'combined_from', '[]'::jsonb))
    else null::integer
  end as source_archive_count
from vocera_rf_validation_study_archive_selections s
join vocera_rf_validation_study_archives a
  on a.archive_id = s.archive_id
where coalesce(a.archive_label, '') not like 'Checkpoint before restoring %';

create or replace view v_vocera_rf_validation_input_files as
with selections as (
  select
    rif.input_file_id,
    count(*)::integer as selected_run_count,
    count(*) filter (where tr.deleted_at is null)::integer as active_selected_run_count,
    max(rif.selected_at) as last_selected_at
  from vocera_rf_validation_run_input_files rif
  join validation_test_runs tr
    on tr.test_run_id = rif.test_run_id
  group by rif.input_file_id
)
select
  f.input_file_id,
  f.study_scope,
  f.source_type,
  f.file_path,
  coalesce(f.display_name, f.file_name, f.file_path) as display_name,
  f.file_name,
  f.file_size_bytes,
  f.file_mtime,
  f.source_sha256,
  f.discovered_at,
  f.last_seen_at,
  f.is_available,
  f.notes,
  coalesce(s.selected_run_count, 0) as selected_run_count,
  coalesce(s.active_selected_run_count, 0) as active_selected_run_count,
  s.last_selected_at
from vocera_rf_validation_input_files f
left join selections s
  on s.input_file_id = f.input_file_id;

create or replace view v_vocera_rf_validation_run_files as
select
  vocera_rf_validation_study_scope(rif.test_run_id) as study_scope,
  tr.study_id,
  s.project_id,
  rif.test_run_id,
  rif.input_file_id,
  rif.source_role,
  rif.selected_at,
  f.source_type,
  f.file_path,
  coalesce(f.display_name, f.file_name, f.file_path) as display_name,
  f.file_name,
  f.file_size_bytes,
  f.file_mtime,
  f.source_sha256,
  f.is_available,
  f.notes as input_file_notes
from vocera_rf_validation_run_input_files rif
join validation_test_runs tr
  on tr.test_run_id = rif.test_run_id
left join vocera_studies s
  on s.study_id = tr.study_id
join vocera_rf_validation_input_files f
  on f.input_file_id = rif.input_file_id;

create or replace view v_vocera_rf_validation_runs as
with file_summary as (
  select
    rif.test_run_id,
    count(*)::integer as selected_file_count,
    string_agg(coalesce(f.display_name, f.file_name, f.file_path), E'\n' order by rif.selected_at, f.file_path)
      filter (where rif.source_role = 'badge_log') as badge_file,
    string_agg(coalesce(f.display_name, f.file_name, f.file_path), E'\n' order by rif.selected_at, f.file_path)
      filter (where rif.source_role = 'ekahau_json') as ekahau_file,
    string_agg(coalesce(f.display_name, f.file_name, f.file_path), E'\n' order by rif.selected_at, f.file_path)
      filter (where rif.source_role = 'manual_csv') as manual_csv,
    string_agg(coalesce(f.display_name, f.file_name, f.file_path), E'\n' order by rif.selected_at, f.file_path)
      filter (where rif.source_role = 'ipad_client_detail') as ipad_client_detail_file
  from vocera_rf_validation_run_input_files rif
  join vocera_rf_validation_input_files f
    on f.input_file_id = rif.input_file_id
  group by rif.test_run_id
),
events as (
  select test_run_id, count(*)::integer as badge_event_count
  from badge_scan_events
  group by test_run_id
),
points as (
  select test_run_id, count(*)::integer as survey_point_count
  from ekahau_survey_points
  group by test_run_id
),
candidates as (
  select
    test_run_id,
    count(*)::integer as candidate_match_count,
    count(*) filter (where manual_entry_status = 'pending')::integer as pending_candidate_match_count
  from badge_ekahau_candidate_matches
  group by test_run_id
),
matches as (
  select
    test_run_id,
    count(*) filter (where manual_entry_status in ('complete', 'missing_vendor_offset'))::integer as completed_match_count
  from badge_ekahau_matches
  group by test_run_id
),
manual as (
  select test_run_id, count(*)::integer as manual_observation_count
  from manual_ekahau_observations
  group by test_run_id
)
select
  coalesce(s.study_scope, vocera_rf_validation_study_scope(tr.test_run_id)) as study_scope,
  tr.study_id,
  s.study_name,
  s.study_type,
  s.study_status,
  s.project_id,
  p.project_name,
  p.project_type,
  tr.test_run_id,
  coalesce(tr.run_name, tr.test_run_id) as run_name,
  coalesce(tr.run_status, case when tr.deleted_at is not null then 'deleted' else 'complete' end) as run_status,
  tr.run_created_by,
  tr.run_updated_at,
  tr.run_executed_at,
  tr.run_execution_error,
  coalesce(tr.run_notes, tr.notes, '') as run_notes,
  tr.deleted_at,
  tr.deleted_by,
  tr.created_at,
  tr.site,
  tr.building,
  tr.floor,
  tr.area,
  tr.ssid,
  tr.badge_mac,
  tr.badge_model,
  tr.ekahau_device,
  tr.ekahau_project,
  tr.timezone,
  tr.badge_time_offset_seconds,
  tr.ekahau_time_offset_seconds,
  tr.default_match_window_seconds,
  tr.vendor_offset_source,
  tr.notes,
  coalesce(fs.selected_file_count, 0) as selected_file_count,
  fs.badge_file,
  fs.ekahau_file,
  fs.manual_csv,
  fs.ipad_client_detail_file,
  coalesce(events.badge_event_count, 0) as badge_event_count,
  coalesce(points.survey_point_count, 0) as survey_point_count,
  coalesce(candidates.candidate_match_count, 0) as candidate_match_count,
  coalesce(candidates.pending_candidate_match_count, 0) as pending_candidate_match_count,
  coalesce(matches.completed_match_count, 0) as completed_match_count,
  coalesce(manual.manual_observation_count, 0) as manual_observation_count,
  tr.match_window_seconds_used,
  tr.runtime_config_path
from validation_test_runs tr
left join vocera_studies s
  on s.study_id = tr.study_id
left join vocera_projects p
  on p.project_id = s.project_id
left join file_summary fs
  on fs.test_run_id = tr.test_run_id
left join events
  on events.test_run_id = tr.test_run_id
left join points
  on points.test_run_id = tr.test_run_id
left join candidates
  on candidates.test_run_id = tr.test_run_id
left join matches
  on matches.test_run_id = tr.test_run_id
left join manual
  on manual.test_run_id = tr.test_run_id;

create or replace view v_vocera_studies as
with run_counts as (
  select
    study_id,
    count(*) filter (where deleted_at is null)::integer as active_run_count,
    count(*)::integer as total_run_count,
    min(created_at) filter (where deleted_at is null) as first_run_created_at,
    max(created_at) filter (where deleted_at is null) as last_run_created_at,
    (sum(badge_event_count) filter (where deleted_at is null))::integer as badge_event_count,
    (sum(survey_point_count) filter (where deleted_at is null))::integer as survey_point_count,
    (sum(candidate_match_count) filter (where deleted_at is null))::integer as candidate_match_count,
    (sum(pending_candidate_match_count) filter (where deleted_at is null))::integer as pending_candidate_match_count,
    (sum(completed_match_count) filter (where deleted_at is null))::integer as completed_match_count,
    (sum(manual_observation_count) filter (where deleted_at is null))::integer as manual_observation_count
  from v_vocera_rf_validation_runs
  group by study_id
)
select
  s.study_id,
  s.project_id,
  p.project_name,
  p.project_type,
  s.study_type,
  s.study_name,
  s.description,
  s.study_status,
  s.created_at,
  s.updated_at,
  s.deleted_at,
  coalesce(r.active_run_count, 0) as active_run_count,
  coalesce(r.total_run_count, 0) as total_run_count,
  r.first_run_created_at,
  r.last_run_created_at,
  coalesce(r.badge_event_count, 0) as badge_event_count,
  coalesce(r.survey_point_count, 0) as survey_point_count,
  coalesce(r.candidate_match_count, 0) as candidate_match_count,
  coalesce(r.pending_candidate_match_count, 0) as pending_candidate_match_count,
  coalesce(r.completed_match_count, 0) as completed_match_count,
  coalesce(r.manual_observation_count, 0) as manual_observation_count,
  s.study_scope
from vocera_studies s
join vocera_projects p
  on p.project_id = s.project_id
left join run_counts r
  on r.study_id = s.study_id;

create or replace view v_vocera_projects as
with study_counts as (
  select
    project_id,
    count(*) filter (where deleted_at is null)::integer as active_study_count,
    count(*)::integer as total_study_count,
    (sum(active_run_count) filter (where deleted_at is null))::integer as active_run_count,
    sum(total_run_count)::integer as total_run_count,
    (sum(badge_event_count) filter (where deleted_at is null))::integer as badge_event_count,
    (sum(survey_point_count) filter (where deleted_at is null))::integer as survey_point_count,
    (sum(candidate_match_count) filter (where deleted_at is null))::integer as candidate_match_count,
    (sum(pending_candidate_match_count) filter (where deleted_at is null))::integer as pending_candidate_match_count,
    (sum(completed_match_count) filter (where deleted_at is null))::integer as completed_match_count,
    (sum(manual_observation_count) filter (where deleted_at is null))::integer as manual_observation_count
  from v_vocera_studies
  group by project_id
)
select
  p.project_id,
  p.project_name,
  p.project_type,
  p.description,
  p.site,
  p.created_at,
  p.updated_at,
  p.deleted_at,
  coalesce(s.active_study_count, 0) as active_study_count,
  coalesce(s.total_study_count, 0) as total_study_count,
  coalesce(s.active_run_count, 0) as active_run_count,
  coalesce(s.total_run_count, 0) as total_run_count,
  coalesce(s.badge_event_count, 0) as badge_event_count,
  coalesce(s.survey_point_count, 0) as survey_point_count,
  coalesce(s.candidate_match_count, 0) as candidate_match_count,
  coalesce(s.pending_candidate_match_count, 0) as pending_candidate_match_count,
  coalesce(s.completed_match_count, 0) as completed_match_count,
  coalesce(s.manual_observation_count, 0) as manual_observation_count
from vocera_projects p
left join study_counts s
  on s.project_id = p.project_id;

create or replace view v_vocera_rf_project_completed_matches as
select
  p.project_id,
  p.project_name,
  s.study_id,
  s.study_name,
  tr.test_run_id,
  coalesce(tr.run_name, tr.test_run_id) as run_name,
  m.id as match_id,
  m.candidate_match_id,
  m.ekahau_observation_id,
  m.survey_point_id,
  m.badge_event_id,
  m.badge_candidate_index,
  m.badge_time,
  m.ekahau_time as survey_time,
  m.time_delta_seconds,
  m.badge_mac,
  m.badge_model,
  m.ssid,
  m.bssid,
  m.ap_name,
  m.channel,
  m.band,
  m.badge_rssi_dbm,
  m.badge_snr_db,
  m.badge_snr_source,
  m.ekahau_rssi_dbm,
  m.ekahau_snr_db,
  m.vendor_offset_db,
  m.expected_badge_rssi_dbm,
  m.raw_delta_db,
  m.calibrated_delta_db,
  m.absolute_calibrated_delta_db,
  m.floor,
  m.area,
  m.x_m,
  m.y_m,
  m.match_quality,
  m.manual_entry_status,
  o.entered_by,
  o.created_at as entered_at,
  m.created_at as match_created_at,
  s.study_scope
from badge_ekahau_matches m
join validation_test_runs tr
  on tr.test_run_id = m.test_run_id
join vocera_studies s
  on s.study_id = tr.study_id
join vocera_projects p
  on p.project_id = s.project_id
left join manual_ekahau_observations o
  on o.id = m.ekahau_observation_id
where tr.deleted_at is null
  and s.deleted_at is null
  and p.deleted_at is null
  and m.manual_entry_status in ('complete', 'missing_vendor_offset');

create or replace view v_vocera_rf_project_duplicate_datapoints as
with keyed as (
  select
    m.*,
    count(*) over (
      partition by
        m.project_id,
        m.survey_time,
        lower(m.bssid),
        coalesce(m.channel, -1),
        coalesce(m.badge_mac, ''),
        m.badge_rssi_dbm,
        m.ekahau_rssi_dbm
    ) as duplicate_count,
    row_number() over (
      partition by
        m.project_id,
        m.survey_time,
        lower(m.bssid),
        coalesce(m.channel, -1),
        coalesce(m.badge_mac, ''),
        m.badge_rssi_dbm,
        m.ekahau_rssi_dbm
      order by m.entered_at desc nulls last, m.match_created_at desc, m.match_id desc
    ) as duplicate_rank
  from v_vocera_rf_project_completed_matches m
)
select
  project_id,
  project_name,
  study_id,
  study_name,
  test_run_id,
  run_name,
  match_id,
  survey_time,
  bssid,
  channel,
  badge_mac,
  badge_rssi_dbm,
  ekahau_rssi_dbm,
  badge_snr_db,
  ekahau_snr_db,
  duplicate_count,
  duplicate_rank,
  case
    when duplicate_count > 1 then 'same_project_time_bssid_channel_badge_and_ekahau_rssi'
    else null
  end as duplicate_reason,
  study_scope
from keyed
where duplicate_count > 1;

create or replace view v_vocera_rf_project_canonical_completed_matches as
with keyed as (
  select
    m.*,
    count(*) over (
      partition by
        m.project_id,
        m.survey_time,
        lower(m.bssid),
        coalesce(m.channel, -1),
        coalesce(m.badge_mac, ''),
        m.badge_rssi_dbm,
        m.ekahau_rssi_dbm
    ) as duplicate_count,
    row_number() over (
      partition by
        m.project_id,
        m.survey_time,
        lower(m.bssid),
        coalesce(m.channel, -1),
        coalesce(m.badge_mac, ''),
        m.badge_rssi_dbm,
        m.ekahau_rssi_dbm
      order by m.entered_at desc nulls last, m.match_created_at desc, m.match_id desc
    ) as canonical_rank
  from v_vocera_rf_project_completed_matches m
)
select
  project_id,
  project_name,
  study_id,
  study_name,
  study_scope,
  test_run_id,
  run_name,
  match_id,
  candidate_match_id,
  ekahau_observation_id,
  survey_point_id,
  badge_event_id,
  badge_candidate_index,
  badge_time,
  survey_time,
  time_delta_seconds,
  badge_mac,
  badge_model,
  ssid,
  bssid,
  ap_name,
  channel,
  band,
  badge_rssi_dbm,
  badge_snr_db,
  badge_snr_source,
  ekahau_rssi_dbm,
  ekahau_snr_db,
  vendor_offset_db,
  expected_badge_rssi_dbm,
  raw_delta_db,
  calibrated_delta_db,
  absolute_calibrated_delta_db,
  floor,
  area,
  x_m,
  y_m,
  match_quality,
  manual_entry_status,
  entered_by,
  entered_at,
  match_created_at,
  duplicate_count,
  canonical_rank
from keyed
where canonical_rank = 1;

create or replace view v_vocera_ekahau_run_alignment as
with badge as (
  select
    bse.test_run_id,
    count(*) as badge_event_count,
    min(bse.event_time) as badge_first_time,
    max(bse.event_time) as badge_last_time,
    count(distinct (bse.event_time at time zone tr.timezone)::date) as badge_date_count
  from badge_scan_events bse
  join validation_test_runs tr
    on tr.test_run_id = bse.test_run_id
  group by bse.test_run_id
),
ekahau as (
  select
    esp.test_run_id,
    count(*) as ekahau_survey_point_count,
    min(esp.measured_at) as ekahau_first_time,
    max(esp.measured_at) as ekahau_last_time,
    count(distinct (esp.measured_at at time zone tr.timezone)::date) as ekahau_date_count
  from ekahau_survey_points esp
  join validation_test_runs tr
    on tr.test_run_id = esp.test_run_id
  group by esp.test_run_id
),
nearest_by_point as (
  select
    esp.test_run_id,
    abs(extract(epoch from (bse.event_time - esp.measured_at))) as nearest_same_date_delta_seconds
  from ekahau_survey_points esp
  join validation_test_runs tr
    on tr.test_run_id = esp.test_run_id
  join lateral (
    select b.event_time
    from badge_scan_events b
    where b.test_run_id = esp.test_run_id
      and (b.event_time at time zone tr.timezone)::date = (esp.measured_at at time zone tr.timezone)::date
    order by abs(extract(epoch from (b.event_time - esp.measured_at)))
    limit 1
  ) bse on true
),
nearest as (
  select
    nbp.test_run_id,
    count(*) as same_date_survey_point_count,
    count(*) filter (where nbp.nearest_same_date_delta_seconds <= tr.default_match_window_seconds) as matched_survey_point_count,
    min(nbp.nearest_same_date_delta_seconds) as nearest_delta_min_seconds,
    percentile_cont(0.5) within group (order by nbp.nearest_same_date_delta_seconds) as nearest_delta_p50_seconds,
    percentile_cont(0.9) within group (order by nbp.nearest_same_date_delta_seconds) as nearest_delta_p90_seconds
  from nearest_by_point nbp
  join validation_test_runs tr
    on tr.test_run_id = nbp.test_run_id
  group by nbp.test_run_id
)
select
  tr.test_run_id,
  tr.timezone,
  tr.default_match_window_seconds,
  coalesce(b.badge_event_count, 0) as badge_event_count,
  b.badge_first_time,
  b.badge_last_time,
  coalesce(b.badge_date_count, 0) as badge_date_count,
  coalesce(e.ekahau_survey_point_count, 0) as ekahau_survey_point_count,
  e.ekahau_first_time,
  e.ekahau_last_time,
  coalesce(e.ekahau_date_count, 0) as ekahau_date_count,
  coalesce(n.same_date_survey_point_count, 0) as same_date_survey_point_count,
  coalesce(n.matched_survey_point_count, 0) as matched_survey_point_count,
  n.nearest_delta_min_seconds,
  n.nearest_delta_p50_seconds,
  n.nearest_delta_p90_seconds,
  case
    when coalesce(b.badge_event_count, 0) = 0 then 'no_badge_events'
    when coalesce(e.ekahau_survey_point_count, 0) = 0 then 'no_ekahau_points'
    when coalesce(n.same_date_survey_point_count, 0) = 0 then 'no_same_date_overlap'
    when coalesce(n.matched_survey_point_count, 0) = 0 then 'no_points_within_match_window'
    else 'matched'
  end as alignment_status
from validation_test_runs tr
left join badge b
  on b.test_run_id = tr.test_run_id
left join ekahau e
  on e.test_run_id = tr.test_run_id
left join nearest n
  on n.test_run_id = tr.test_run_id;

-- ---------------------------------------------------------------------------
-- Manual statistical samples (study-scoped Ekahau RSSI/SNR entries)
-- ---------------------------------------------------------------------------
create or replace view v_vocera_rf_manual_samples as
select
  s.sample_id,
  s.study_id,
  st.study_name,
  st.project_id,
  s.label,
  s.ekahau_rssi_dbm,
  s.ekahau_snr_db,
  s.notes,
  s.created_at,
  s.updated_at,
  s.deleted_at
from vocera_rf_manual_samples s
left join vocera_studies st
  on st.study_id = s.study_id;
