-- AP-OTA companion evidence legs for Media QoE WLC sessions.
--
-- This is only the data model and artifact contract. Capture start/stop and FTP
-- intake remain guarded by preflight and operator confirmation.

create table if not exists vocera_media_capture_legs (
  leg_id text primary key,
  capture_session_id text not null references vocera_media_capture_sessions(session_id) on delete cascade,
  leg_type text not null
    check (leg_type in ('wlc_epc', 'ap_client_ota', 'wired_vlan_span', 'icap_ota')),
  leg_state text not null default 'preflight_required'
    check (leg_state in (
      'preflight_required', 'preflight_blocked', 'ready', 'prepared',
      'running', 'stopped', 'attached', 'parsed', 'failed', 'aborted'
    )),
  target_client_mac text,
  target_client_ip inet,
  target_client_role text,
  target_ap_name text,
  target_ap_mac text,
  target_bssid text,
  target_radio text,
  target_band text,
  target_channel integer,
  target_channel_width text,
  capture_mode text,
  transfer_protocol text,
  transfer_host text,
  transfer_path text,
  profile_name text,
  started_at timestamptz,
  stopped_at timestamptz,
  created_by text,
  raw_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create index if not exists idx_vocera_media_capture_legs_session
  on vocera_media_capture_legs (capture_session_id, leg_type, leg_state);

create index if not exists idx_vocera_media_capture_legs_target
  on vocera_media_capture_legs (target_client_mac, target_ap_name);

alter table vocera_media_session_artifacts
  add column if not exists capture_leg_id text references vocera_media_capture_legs(leg_id) on delete set null;

create index if not exists idx_vocera_media_session_artifacts_leg
  on vocera_media_session_artifacts (capture_leg_id, artifact_kind);

alter table vocera_media_session_artifacts
  drop constraint if exists vocera_media_session_artifacts_artifact_kind_check;

alter table vocera_media_session_artifacts
  drop constraint if exists chk_vocera_media_session_artifacts_artifact_kind;

alter table vocera_media_session_artifacts
  add constraint chk_vocera_media_session_artifacts_artifact_kind
  check (artifact_kind in (
    'wlc_epc', 'wlc_terminal_output', 'wlc_terminal_timing', 'wlc_transcript',
    'ap_ota_pcap', 'ap_ota_terminal_output', 'ap_ota_terminal_timing', 'ap_ota_metadata'
  ));

create or replace view v_vocera_media_capture_legs as
select *
from vocera_media_capture_legs;

create or replace view v_vocera_media_capture_sessions as
select
  s.*,
  coalesce(attempt_stats.attempt_count, 0)::integer as attempt_count,
  coalesce(attempt_stats.heard_attempt_count, 0)::integer as heard_attempt_count,
  coalesce(attempt_stats.missed_attempt_count, 0)::integer as missed_attempt_count,
  coalesce(attempt_stats.degraded_attempt_count, 0)::integer as degraded_attempt_count,
  coalesce(event_stats.event_count, 0)::integer as event_count,
  event_stats.latest_event_time,
  latest_resolved_attempt.attempt_id as latest_resolved_attempt_id,
  latest_resolved_attempt.resolved_group_ip as latest_resolved_group_ip,
  latest_resolved_attempt.resolved_group_vlan as latest_resolved_group_vlan,
  latest_resolved_attempt.resolved_mgid as latest_resolved_mgid,
  latest_resolved_attempt.vlan_context_state as latest_resolved_vlan_context_state,
  latest_resolved_attempt.active_group_selected_at as latest_resolved_at,
  coalesce(leg_stats.leg_count, 0)::integer as leg_count,
  coalesce(leg_stats.ap_ota_leg_count, 0)::integer as ap_ota_leg_count,
  coalesce(leg_stats.ready_ap_ota_leg_count, 0)::integer as ready_ap_ota_leg_count
from vocera_media_capture_sessions s
left join lateral (
  select
    count(*) as attempt_count,
    count(*) filter (where audio_result = 'heard') as heard_attempt_count,
    count(*) filter (where audio_result = 'missed') as missed_attempt_count,
    count(*) filter (where audio_result in ('partial', 'choppy')) as degraded_attempt_count
  from vocera_media_broadcast_attempts attempt
  where attempt.capture_session_id = s.session_id
) attempt_stats on true
left join lateral (
  select
    count(*) as event_count,
    max(event_time) as latest_event_time
  from vocera_media_capture_session_events event
  where event.capture_session_id = s.session_id
) event_stats on true
left join lateral (
  select
    attempt.attempt_id,
    attempt.resolved_group_ip,
    attempt.resolved_group_vlan,
    attempt.resolved_mgid,
    attempt.vlan_context_state,
    attempt.active_group_selected_at
  from vocera_media_broadcast_attempts attempt
  where attempt.capture_session_id = s.session_id
    and attempt.resolved_group_ip is not null
  order by coalesce(
    attempt.active_group_selected_at,
    attempt.attempt_started_at,
    attempt.started_at,
    attempt.created_at
  ) desc
  limit 1
) latest_resolved_attempt on true
left join lateral (
  select
    count(*) as leg_count,
    count(*) filter (where leg_type = 'ap_client_ota') as ap_ota_leg_count,
    count(*) filter (where leg_type = 'ap_client_ota' and leg_state in ('ready', 'prepared', 'running', 'stopped', 'attached', 'parsed')) as ready_ap_ota_leg_count
  from vocera_media_capture_legs leg
  where leg.capture_session_id = s.session_id
) leg_stats on true;
