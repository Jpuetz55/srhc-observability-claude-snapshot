begin;

-- Manual-entry identity is the Ekahau survey timestamp plus BSSID. Parser runs
-- and regenerated survey_point_id values can differ for the same real entry.

-- Attach existing completed matches to freshly parsed candidate rows when the
-- specific badge event identity matches but the match row was created before
-- the current candidate id existed.
with attached as (
  update badge_ekahau_matches m
  set candidate_match_id = c.id
  from badge_ekahau_candidate_matches c
  where c.test_run_id = m.test_run_id
    and m.candidate_match_id is null
    and lower(m.bssid) = lower(c.bssid)
    and m.ekahau_time = c.survey_time
    and m.badge_event_id = c.badge_event_id
    and m.badge_candidate_index = c.badge_candidate_index
  returning m.id
)
select 'attached_completed_matches_to_candidates' as action, count(*) as row_count
from attached;

-- If a manual observation exists but no completed match exists for this
-- timestamp/BSSID yet, materialize one completed match using the strongest
-- candidate for that manual-entry identity.
with ranked_candidates as (
  select
    c.*,
    row_number() over (
      partition by lower(c.bssid), c.survey_time
      order by c.badge_selected desc, c.badge_score desc nulls last, c.badge_rssi_dbm desc nulls last, c.id
    ) as manual_rank
  from badge_ekahau_candidate_matches c
), inserted as (
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
    mo.id,
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
    mo.rssi_dbm,
    mo.snr_db,
    offsets.vendor_offset_db,
    case when offsets.vendor_offset_db is not null then mo.rssi_dbm + offsets.vendor_offset_db end,
    case when c.badge_rssi_dbm is not null then c.badge_rssi_dbm - mo.rssi_dbm end,
    case when c.badge_rssi_dbm is not null and offsets.vendor_offset_db is not null then c.badge_rssi_dbm - (mo.rssi_dbm + offsets.vendor_offset_db) end,
    abs(case when c.badge_rssi_dbm is not null and offsets.vendor_offset_db is not null then c.badge_rssi_dbm - (mo.rssi_dbm + offsets.vendor_offset_db) end),
    c.badge_cu_percent,
    c.badge_score,
    c.badge_selected,
    c.floor,
    c.area,
    c.x_m,
    c.y_m,
    c.match_quality,
    case when offsets.vendor_offset_db is null then 'missing_vendor_offset' else 'complete' end
  from ranked_candidates c
  join lateral (
    select o.*
    from manual_ekahau_observations o
    where lower(o.bssid) = lower(c.bssid)
      and o.measured_at = c.survey_time
    order by (o.test_run_id = c.test_run_id) desc, o.created_at desc, o.id desc
    limit 1
  ) mo on true
  cross join lateral (
    select vocera_rf_validation_vendor_offset(c.band) as vendor_offset_db
  ) offsets
  where c.manual_rank = 1
    and not exists (
      select 1
      from badge_ekahau_matches existing
      where lower(existing.bssid) = lower(c.bssid)
        and existing.ekahau_time = c.survey_time
        and existing.manual_entry_status in ('complete', 'missing_vendor_offset')
    )
  returning id
)
select 'inserted_missing_completed_matches_from_manual_observations' as action, count(*) as row_count
from inserted;

-- Pending rows are manual-entry candidates, not samples. Keep only the
-- strongest pending candidate for a timestamp/BSSID identity when no completed
-- match exists yet.
with ranked_pending as (
  select
    c.id,
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
), duplicate_pending as (
  select rp.id
  from ranked_pending rp
  where rp.pending_rank > 1
    and not exists (
      select 1
      from badge_ekahau_matches m
      where m.candidate_match_id = rp.id
    )
), deleted as (
  delete from badge_ekahau_candidate_matches c
  using duplicate_pending d
  where c.id = d.id
  returning c.id
)
select 'deleted_duplicate_pending_candidates_by_timestamp' as action, count(*) as row_count
from deleted;

-- Remove unreferenced pending candidates when a completed entry already exists
-- for the same BSSID/survey time.
with duplicate_pending as (
  select c.id
  from badge_ekahau_candidate_matches c
  where c.manual_entry_status = 'pending'
    and exists (
      select 1
      from badge_ekahau_matches m
      where lower(m.bssid) = lower(c.bssid)
        and m.ekahau_time = c.survey_time
        and m.manual_entry_status in ('complete', 'missing_vendor_offset')
    )
    and not exists (
      select 1
      from badge_ekahau_matches m
      where m.candidate_match_id = c.id
    )
), deleted as (
  delete from badge_ekahau_candidate_matches c
  using duplicate_pending d
  where c.id = d.id
  returning c.id
)
select 'deleted_unreferenced_duplicate_pending_candidates' as action, count(*) as row_count
from deleted;

-- Hide/close any remaining pending candidates that already have completed
-- materialized rows for the same manual-entry identity.
with updated as (
  update badge_ekahau_candidate_matches c
  set manual_entry_status = 'complete'
  where c.manual_entry_status = 'pending'
    and exists (
      select 1
      from badge_ekahau_matches m
      where lower(m.bssid) = lower(c.bssid)
        and m.ekahau_time = c.survey_time
        and m.manual_entry_status in ('complete', 'missing_vendor_offset')
    )
  returning c.id
)
select 'marked_duplicate_pending_candidates_complete' as action, count(*) as row_count
from updated;

select 'remaining_duplicate_pending_candidates' as action, count(*) as row_count
from badge_ekahau_candidate_matches c
where c.manual_entry_status = 'pending'
  and exists (
    select 1
    from badge_ekahau_matches m
    where lower(m.bssid) = lower(c.bssid)
      and m.ekahau_time = c.survey_time
      and m.manual_entry_status in ('complete', 'missing_vendor_offset')
  );

select 'remaining_repeated_pending_timestamp_bssid_identities' as action, count(*) as row_count
from (
  select lower(c.bssid), c.survey_time
  from badge_ekahau_candidate_matches c
  where c.manual_entry_status = 'pending'
  group by lower(c.bssid), c.survey_time
  having count(*) > 1
) repeated_pending;

commit;
