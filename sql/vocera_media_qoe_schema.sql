-- PostgreSQL contract for Vocera media PCAP QoE capture-time history.

create table if not exists schema_migrations (
  migration_id text primary key,
  checksum text not null,
  applied_at timestamptz not null default now(),
  applied_by text not null,
  source_commit text not null
);

create index if not exists idx_schema_migrations_applied_at
  on schema_migrations (applied_at desc);

create table if not exists vocera_projects (
  project_id text primary key,
  project_name text not null,
  project_type text not null default 'media_qoe',
  description text,
  site text,
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create table if not exists vocera_studies (
  study_id text primary key,
  project_id text not null references vocera_projects(project_id),
  study_type text not null default 'media_qoe',
  study_scope text not null default 'media_qoe',
  study_name text not null,
  description text,
  study_status text not null default 'active',
  created_at timestamptz not null default now(),
  updated_at timestamptz,
  deleted_at timestamptz
);

create table if not exists vocera_media_captures (
  capture_id text primary key,
  study_id text references vocera_studies(study_id) default 'study_media_qoe_default',
  source_path text not null,
  source_name text not null,
  source_size_bytes bigint,
  expected_size_bytes bigint,
  source_sha256 text,
  source_mtime timestamptz,
  source_mtime_ns bigint,
  source_discovered_at timestamptz,
  source_registered_at timestamptz,
  capture_time timestamptz,
  parsed_at timestamptz not null default now(),
  site text not null default 'unknown',
  capture_point text not null default 'unknown',
  capture_status text not null default 'complete' check (capture_status in ('registered', 'queued', 'running', 'complete', 'failed', 'deleted')),
  deleted_at timestamptz,
  parse_success boolean not null default false,
  parse_started_at timestamptz,
  parse_finished_at timestamptz,
  parse_duration_seconds double precision,
  parse_exit_code integer,
  parse_stdout text,
  parse_stderr text,
  parse_error text,
  parse_requested_by text,
  parse_requested_at timestamptz,
  packets_read integer not null default 0,
  udp_packets_seen integer not null default 0,
  stream_count integer not null default 0,
  raw_metadata jsonb not null default '{}'::jsonb
);

create table if not exists vocera_media_capture_parse_runs (
  parse_run_id text primary key,
  capture_id text not null references vocera_media_captures(capture_id) on delete cascade,
  study_id text references vocera_studies(study_id),
  source_path text not null,
  requested_by text,
  requested_at timestamptz not null default now(),
  started_at timestamptz,
  finished_at timestamptz,
  duration_seconds double precision,
  status text not null default 'queued',
  exit_code integer,
  stdout text,
  stderr text,
  error text,
  captures_imported integer,
  streams_imported integer,
  rtp_qoe_streams integer,
  dscp_mismatch_streams integer,
  lossy_streams integer
);


create table if not exists vocera_media_execution_locks (
  lock_name text primary key,
  capture_id text,
  parse_run_id text,
  acquired_by text,
  acquired_at timestamptz not null default now(),
  expires_at timestamptz not null,
  heartbeat_at timestamptz not null default now()
);

create table if not exists vocera_media_stream_samples (
  capture_id text not null references vocera_media_captures(capture_id) on delete cascade,
  stream_id text not null,
  sample_time timestamptz not null,
  first_seen timestamptz,
  last_seen timestamptz,
  site text not null default 'unknown',
  capture_point text not null default 'unknown',
  server text not null default 'unknown',
  direction text not null default 'unknown',
  measurement_mode text not null default 'unknown',
  src_role text not null default 'unknown',
  dst_role text not null default 'unknown',
  device_name text not null default 'unmapped',
  device_role text not null default 'unmapped',
  device_config text not null default 'unmapped',
  peer_device_name text not null default 'unmapped',
  peer_device_role text not null default 'unmapped',
  peer_device_config text not null default 'unmapped',
  src_ip inet,
  src_port integer,
  dst_ip inet,
  dst_port integer,
  ssrc text,
  payload_type integer,
  dscp integer,
  packet_count integer not null default 0,
  byte_count bigint not null default 0,
  expected_packets integer,
  lost_packets integer,
  loss_ratio numeric,
  duplicate_packets integer not null default 0,
  out_of_order_packets integer not null default 0,
  jitter_ms numeric,
  interarrival_p50_ms numeric,
  interarrival_p95_ms numeric,
  interarrival_max_ms numeric,
  packet_rate_pps numeric,
  dscp_mismatch boolean not null default false,
  accepted boolean,
  stream_classification text,
  review_status text not null default 'unreviewed',
  reviewed_at timestamptz,
  reviewed_by text,
  review_notes text,
  raw_stream jsonb not null default '{}'::jsonb,
  primary key (capture_id, stream_id)
);

create table if not exists vocera_media_study_archives (
  archive_id text primary key,
  archive_label text,
  archived_at timestamptz not null default now(),
  archived_by text,
  updated_at timestamptz,
  updated_by text,
  notes text,
  capture_count integer not null default 0,
  stream_count integer not null default 0,
  first_capture_time timestamptz,
  last_capture_time timestamptz,
  payload jsonb not null
);

create table if not exists vocera_media_capture_sessions (
  session_id text primary key,
  study_id text references vocera_studies(study_id),
  site text,
  wlc_name text,
  capture_method text not null default 'manual_wlc_epc',
  capture_name text not null,
  wlc_interface text,
  capture_filter_mode text,
  capture_mode text not null default 'long_reproduction',
  capture_started_at timestamptz,
  capture_stopped_at timestamptz,
  collector_host text,
  collector_scp_username text,
  collector_scp_port integer,
  collector_scp_path text,
  ring_file_count integer,
  ring_file_size_mb integer,
  ring_total_size_mb integer,
  continuous_export_enabled boolean not null default false,
  session_state text not null default 'prepared_not_started',
  sender_name text,
  sender_model text,
  sender_mac text,
  sender_ip inet,
  receiver_name text,
  receiver_model text,
  receiver_mac text,
  receiver_ip inet,
  expected_dscp integer,
  configured_vocera_vlan integer not null default 684,
  -- LEGACY/deprecated: active-group resolution is attempt-scoped (see
  -- vocera_media_broadcast_attempts). These session-level columns are retained only
  -- for backward compatibility with historical rows; the API rejects writes (HTTP
  -- 422) and v_vocera_media_capture_sessions derives the latest group from attempts.
  -- See the COMMENT ON COLUMN statements below.
  resolved_group_ip inet,
  resolved_group_vlan integer,
  resolved_mgid integer,
  resolved_at timestamptz,
  vlan_selection_source text not null default 'default',
  vlan_context_state text not null default 'configured_only',
  vocera_multicast_pool cidr,
  vocera_first_usable inet,
  vocera_last_usable inet,
  expected_mac_start text,
  expected_mac_end text,
  command_package_path text,
  created_by text,
  raw_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

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

create table if not exists vocera_media_broadcast_attempts (
  attempt_id text primary key,
  study_id text references vocera_studies(study_id),
  capture_session_id text references vocera_media_capture_sessions(session_id) on delete set null,
  site text,
  wlc_name text,
  started_at timestamptz,
  ended_at timestamptz,
  attempt_started_at timestamptz,
  attempt_marked_at timestamptz,
  attempt_ended_at timestamptz,
  attempt_state text not null default 'open',
  sender_name text,
  sender_model text,
  sender_mac text,
  sender_ip inet,
  receiver_name text,
  receiver_model text,
  receiver_mac text,
  receiver_ip inet,
  vocera_group inet,
  dynamic_multicast_ip inet,
  dynamic_multicast_mac text,
  multicast_group_detected_at timestamptz,
  configured_vocera_vlan integer,
  resolved_group_ip inet,
  resolved_group_vlan integer,
  resolved_mgid integer,
  vlan_selection_source text,
  group_selection_source text,
  vlan_override_reason text,
  active_group_selected_at timestamptz,
  active_group_summary_raw text,
  active_group_selected_row text,
  vlan_context_state text,
  vocera_vlan integer,
  operator_name text,
  audio_result text,
  alert_result boolean,
  alert_received boolean,
  audio_received boolean,
  sender_confirmed boolean,
  receiver_group_member boolean,
  failure_marker_type text,
  capture_window_before_seconds integer,
  capture_window_after_seconds integer,
  operator_notes text,
  verdict text,
  verdict_confidence text,
  verdict_explanation text,
  raw_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists vocera_media_capture_session_events (
  event_id text primary key,
  capture_session_id text not null references vocera_media_capture_sessions(session_id) on delete cascade,
  study_id text references vocera_studies(study_id),
  attempt_id text references vocera_media_broadcast_attempts(attempt_id) on delete set null,
  event_kind text not null,
  event_time timestamptz not null default now(),
  browser_event_time timestamptz,
  operator_name text,
  audio_result text,
  alert_received boolean,
  audio_received boolean,
  notes text,
  raw_context jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists vocera_media_attempt_artifacts (
  artifact_id text primary key,
  attempt_id text not null references vocera_media_broadcast_attempts(attempt_id) on delete cascade,
  artifact_type text not null,
  phase text,
  source_path text not null,
  sha256 text,
  size_bytes bigint,
  capture_id text references vocera_media_captures(capture_id) on delete set null,
  captured_at timestamptz,
  ingested_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb
);

create table if not exists vocera_media_wlc_snapshots (
  snapshot_id text primary key,
  attempt_id text not null references vocera_media_broadcast_attempts(attempt_id) on delete cascade,
  phase text,
  snapshot_time text,
  receiver_ap text,
  receiver_bssid text,
  receiver_channel integer,
  receiver_band text,
  receiver_rssi integer,
  receiver_snr integer,
  receiver_vlan integer,
  sender_client_vlan integer,
  sender_multicast_vlan integer,
  receiver_client_vlan integer,
  receiver_multicast_vlan integer,
  receiver_group_member boolean,
  receiver_group_status text,
  vocera_group inet,
  vocera_dynamic_group_ip inet,
  vocera_dynamic_group_mac text,
  vocera_group_evidence_confidence text,
  vocera_vlan integer,
  configured_vocera_vlan integer,
  resolved_group_vlan integer,
  group_vlan integer,
  vlan_context_state text,
  mgid integer,
  multicast_enabled boolean,
  capwap_multicast_mode text,
  ap_mom_status text,
  igmp_snooping_enabled boolean,
  igmp_querier_enabled boolean,
  raw_snapshot text
);

create table if not exists vocera_media_multicast_observations (
  observation_id text primary key,
  capture_session_id text references vocera_media_capture_sessions(session_id) on delete cascade,
  attempt_id text references vocera_media_broadcast_attempts(attempt_id) on delete cascade,
  observed_at timestamptz,
  phase text,
  evidence_source text not null,
  vocera_group_ip inet,
  vocera_group_mac text,
  vocera_vlan integer,
  source_ip inet,
  source_mac text,
  igmp_version text,
  mgid integer,
  receiver_mac text,
  receiver_ip inet,
  receiver_member boolean,
  receiver_blocklisted boolean,
  receiver_membership_mode text,
  wlc_capwap_group inet,
  wlc_capwap_mode text,
  ap_name text,
  ap_mom_status text,
  ap_mgid integer,
  ap_delivery_mode text,
  ap_rx_packets bigint,
  ap_tx_packets bigint,
  ap_slot text,
  capture_confidence text not null default 'unknown',
  raw_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists vocera_media_attempt_findings (
  finding_id text primary key,
  attempt_id text not null references vocera_media_broadcast_attempts(attempt_id) on delete cascade,
  finding_type text not null,
  severity text not null default 'info',
  confidence text not null default 'low',
  evidence_source text,
  message text not null,
  raw_evidence jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table vocera_media_stream_samples
  add column if not exists device_name text not null default 'unmapped',
  add column if not exists device_role text not null default 'unmapped',
  add column if not exists device_config text not null default 'unmapped',
  add column if not exists peer_device_name text not null default 'unmapped',
  add column if not exists peer_device_role text not null default 'unmapped',
  add column if not exists peer_device_config text not null default 'unmapped';

alter table vocera_media_captures
  add column if not exists study_id text references vocera_studies(study_id),
  add column if not exists capture_status text not null default 'complete',
  add column if not exists deleted_at timestamptz,
  add column if not exists source_sha256 text,
  add column if not exists source_mtime timestamptz,
  add column if not exists source_discovered_at timestamptz,
  add column if not exists source_registered_at timestamptz,
  add column if not exists parse_started_at timestamptz,
  add column if not exists parse_finished_at timestamptz,
  add column if not exists parse_duration_seconds double precision,
  add column if not exists parse_exit_code integer,
  add column if not exists parse_stdout text,
  add column if not exists parse_stderr text,
  add column if not exists parse_error text,
  add column if not exists parse_requested_by text,
  add column if not exists parse_requested_at timestamptz;

alter table vocera_media_captures
  alter column parse_success set default false;

alter table vocera_media_captures
  alter column study_id set default 'study_media_qoe_default';

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'chk_vocera_media_capture_status'
      and conrelid = 'vocera_media_captures'::regclass
  ) then
    alter table vocera_media_captures
      add constraint chk_vocera_media_capture_status
      check (capture_status in ('registered', 'queued', 'running', 'complete', 'failed', 'deleted'));
  end if;
end $$;

alter table vocera_media_stream_samples
  add column if not exists accepted boolean,
  add column if not exists stream_classification text,
  add column if not exists review_status text not null default 'unreviewed',
  add column if not exists reviewed_at timestamptz,
  add column if not exists reviewed_by text,
  add column if not exists review_notes text;

alter table vocera_media_broadcast_attempts
  add column if not exists capture_session_id text references vocera_media_capture_sessions(session_id) on delete set null,
  add column if not exists attempt_started_at timestamptz,
  add column if not exists attempt_marked_at timestamptz,
  add column if not exists attempt_ended_at timestamptz,
  add column if not exists attempt_state text not null default 'open',
  add column if not exists group_selection_source text,
  add column if not exists vlan_override_reason text,
  add column if not exists active_group_selected_at timestamptz,
  add column if not exists active_group_summary_raw text,
  add column if not exists active_group_selected_row text,
  add column if not exists dynamic_multicast_ip inet,
  add column if not exists dynamic_multicast_mac text,
  add column if not exists multicast_group_detected_at timestamptz,
  add column if not exists configured_vocera_vlan integer,
  add column if not exists resolved_group_ip inet,
  add column if not exists resolved_group_vlan integer,
  add column if not exists resolved_mgid integer,
  add column if not exists vlan_selection_source text,
  add column if not exists vlan_context_state text,
  add column if not exists alert_received boolean,
  add column if not exists audio_received boolean,
  add column if not exists sender_confirmed boolean,
  add column if not exists receiver_group_member boolean,
  add column if not exists failure_marker_type text,
  add column if not exists capture_window_before_seconds integer,
  add column if not exists capture_window_after_seconds integer;

-- Backfill a sane lifecycle state for attempt rows created before attempt_state
-- existed. Legacy rows always carry attempt_marked_at, so reclassify only those
-- away from the new 'open' default; genuinely in-flight attempts (no marker yet)
-- are left open. This also clears legacy duplicates before the one-open index.
update vocera_media_broadcast_attempts
set attempt_state = case
  when audio_result is not null and audio_result not in ('unknown', 'not_tested') then 'completed'
  else 'incomplete'
end
where attempt_state = 'open'
  and attempt_marked_at is not null;

-- Enforce one open broadcast attempt per capture session so PCAP attempt-window
-- correlation cannot be ambiguous during a long-running reproduction capture.
create unique index if not exists uq_vocera_media_attempt_one_open_per_session
  on vocera_media_broadcast_attempts (capture_session_id)
  where attempt_state = 'open' and capture_session_id is not null;

-- A completed attempt must carry an audio outcome.
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'chk_vocera_media_attempt_completed_outcome'
      and conrelid = 'vocera_media_broadcast_attempts'::regclass
  ) then
    alter table vocera_media_broadcast_attempts
      add constraint chk_vocera_media_attempt_completed_outcome
      check (attempt_state <> 'completed' or audio_result is not null);
  end if;
end $$;

-- A selected active-group VLAN that differs from the configured Vocera VLAN must
-- be a deliberate operator override carrying a non-empty reason. Added NOT VALID
-- so legacy rows are not retroactively rejected while all new writes are checked.
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'chk_vocera_media_attempt_vlan_override'
      and conrelid = 'vocera_media_broadcast_attempts'::regclass
  ) then
    alter table vocera_media_broadcast_attempts
      add constraint chk_vocera_media_attempt_vlan_override
      check (
        resolved_group_vlan is null
        or configured_vocera_vlan is null
        or resolved_group_vlan = configured_vocera_vlan
        or (
          group_selection_source = 'operator_override'
          and vlan_override_reason is not null
          and length(btrim(vlan_override_reason)) > 0
        )
      ) not valid;
  end if;
end $$;

alter table vocera_media_capture_sessions
  add column if not exists configured_vocera_vlan integer not null default 684,
  add column if not exists resolved_group_ip inet,
  add column if not exists resolved_group_vlan integer,
  add column if not exists resolved_mgid integer,
  add column if not exists resolved_at timestamptz,
  add column if not exists vlan_selection_source text not null default 'default',
  add column if not exists vlan_context_state text not null default 'configured_only';

-- Mark the session-level active-group resolution columns as deprecated. A Vocera
-- broadcast's dynamic group is transient, attempt-specific evidence, so resolution
-- now lives on vocera_media_broadcast_attempts. These columns are retained for
-- backward compatibility only: the API rejects writes (HTTP 422) and
-- v_vocera_media_capture_sessions exposes the latest attempt's group as derived
-- display data. Do not treat these as current evidence; do not drop until legacy
-- rows have been reviewed and archived.
comment on column vocera_media_capture_sessions.resolved_group_ip is
  'DEPRECATED: active-group resolution is attempt-scoped (vocera_media_broadcast_attempts.resolved_group_ip). Retained for backward compatibility; API rejects writes (HTTP 422).';
comment on column vocera_media_capture_sessions.resolved_group_vlan is
  'DEPRECATED: active-group resolution is attempt-scoped (vocera_media_broadcast_attempts.resolved_group_vlan). Retained for backward compatibility; API rejects writes (HTTP 422).';
comment on column vocera_media_capture_sessions.resolved_mgid is
  'DEPRECATED: active-group resolution is attempt-scoped (vocera_media_broadcast_attempts.resolved_mgid). Retained for backward compatibility; API rejects writes (HTTP 422).';
comment on column vocera_media_capture_sessions.resolved_at is
  'DEPRECATED: active-group resolution is attempt-scoped (vocera_media_broadcast_attempts.active_group_selected_at). Retained for backward compatibility; API rejects writes (HTTP 422).';

alter table vocera_media_wlc_snapshots
  add column if not exists vocera_dynamic_group_ip inet,
  add column if not exists vocera_dynamic_group_mac text,
  add column if not exists vocera_group_evidence_confidence text,
  add column if not exists sender_client_vlan integer,
  add column if not exists sender_multicast_vlan integer,
  add column if not exists receiver_client_vlan integer,
  add column if not exists receiver_multicast_vlan integer,
  add column if not exists configured_vocera_vlan integer,
  add column if not exists resolved_group_vlan integer,
  add column if not exists group_vlan integer,
  add column if not exists vlan_context_state text;

alter table vocera_media_multicast_observations
  add column if not exists source_ip inet,
  add column if not exists source_mac text,
  add column if not exists igmp_version text,
  add column if not exists wlc_capwap_group inet,
  add column if not exists wlc_capwap_mode text,
  add column if not exists ap_mgid integer,
  add column if not exists ap_delivery_mode text,
  add column if not exists ap_rx_packets bigint,
  add column if not exists ap_tx_packets bigint,
  add column if not exists ap_slot text;

insert into vocera_projects (
  project_id,
  project_name,
  project_type,
  description,
  site,
  updated_at
)
values (
  'project_media_qoe_default',
  'Media QoE',
  'media_qoe',
  'Default project for ICAP QoE capture analysis.',
  null,
  now()
)
on conflict (project_id) do nothing;

insert into vocera_studies (
  study_id,
  project_id,
  study_type,
  study_scope,
  study_name,
  description,
  study_status,
  updated_at
)
values (
  'study_media_qoe_default',
  'project_media_qoe_default',
  'media_qoe',
  'media_qoe',
  'Default ICAP QoE Study',
  'Default study for ICAP QoE captures.',
  'active',
  now()
)
on conflict (study_id) do nothing;

update vocera_media_captures
set study_id = 'study_media_qoe_default'
where study_id is null;

create index if not exists idx_vocera_media_captures_time
  on vocera_media_captures (capture_time desc);

create index if not exists idx_vocera_media_captures_site_point
  on vocera_media_captures (site, capture_point, capture_time desc);

create index if not exists idx_vocera_media_captures_study_time
  on vocera_media_captures (study_id, capture_time desc);

create index if not exists idx_vocera_media_captures_status_time
  on vocera_media_captures (capture_status, capture_time desc);

create index if not exists idx_vocera_media_captures_source_path
  on vocera_media_captures (source_path);

create index if not exists idx_vocera_media_captures_sha
  on vocera_media_captures (source_sha256)
  where source_sha256 is not null;

create index if not exists idx_vocera_media_parse_runs_capture_time
  on vocera_media_capture_parse_runs (capture_id, requested_at desc);

create index if not exists idx_vocera_media_parse_runs_study_time
  on vocera_media_capture_parse_runs (study_id, requested_at desc);


create index if not exists idx_vocera_media_execution_locks_expires
  on vocera_media_execution_locks (expires_at);

create index if not exists idx_vocera_media_stream_samples_time
  on vocera_media_stream_samples (sample_time desc);

create index if not exists idx_vocera_media_stream_samples_labels_time
  on vocera_media_stream_samples (site, capture_point, server, direction, measurement_mode, sample_time desc);

create index if not exists idx_vocera_media_stream_samples_device_time
  on vocera_media_stream_samples (site, capture_point, device_role, device_config, measurement_mode, sample_time desc);

create index if not exists idx_vocera_media_stream_review
  on vocera_media_stream_samples (review_status, stream_classification);

create index if not exists idx_vocera_media_stream_study_time
  on vocera_media_stream_samples (sample_time desc, capture_id, stream_id);

create index if not exists idx_vocera_media_study_archives_time
  on vocera_media_study_archives (archived_at desc);

create index if not exists idx_vocera_media_broadcast_attempts_study_time
  on vocera_media_broadcast_attempts (study_id, started_at desc);

create index if not exists idx_vocera_media_capture_sessions_study_time
  on vocera_media_capture_sessions (study_id, created_at desc);

create index if not exists idx_vocera_media_capture_sessions_state
  on vocera_media_capture_sessions (session_state, created_at desc);

create index if not exists idx_vocera_media_broadcast_attempts_session_time
  on vocera_media_broadcast_attempts (capture_session_id, attempt_marked_at desc);

create index if not exists idx_vocera_media_broadcast_attempts_verdict
  on vocera_media_broadcast_attempts (verdict, started_at desc);

create index if not exists idx_vocera_media_session_events_session_time
  on vocera_media_capture_session_events (capture_session_id, event_time desc);

create index if not exists idx_vocera_media_session_events_study_time
  on vocera_media_capture_session_events (study_id, event_time desc);

create index if not exists idx_vocera_media_attempt_artifacts_attempt
  on vocera_media_attempt_artifacts (attempt_id, artifact_type, phase);

create index if not exists idx_vocera_media_wlc_snapshots_attempt
  on vocera_media_wlc_snapshots (attempt_id, phase);

create index if not exists idx_vocera_media_multicast_observations_session_time
  on vocera_media_multicast_observations (capture_session_id, observed_at desc);

create index if not exists idx_vocera_media_multicast_observations_attempt
  on vocera_media_multicast_observations (attempt_id, phase, evidence_source);

create index if not exists idx_vocera_media_multicast_observations_group
  on vocera_media_multicast_observations (vocera_group_ip, vocera_vlan, observed_at desc);

create index if not exists idx_vocera_media_multicast_observations_receiver
  on vocera_media_multicast_observations (receiver_mac, observed_at desc);

create index if not exists idx_vocera_media_attempt_findings_attempt
  on vocera_media_attempt_findings (attempt_id, severity, finding_type);

-- ---------------------------------------------------------------------------
-- WLC capture-session artifacts (Phase 0: SCP session-artifact ingest)
-- ---------------------------------------------------------------------------
-- A session-owned evidence file the WLC SCP-pushes to the collector (today the
-- exported EPC; later interactive-console transcripts). The collector detects a
-- completed upload under <session>/incoming/, validates it, finalizes it into
-- service-owned <session>/pcaps/ evidence, registers it as a wlc_epc capture,
-- and queues the existing parser -- with no manual move/hash/register/parse
-- step. The EPC belongs to the capture session, not a single broadcast attempt:
-- one session EPC may later cover many attempts.
create table if not exists vocera_media_session_artifacts (
  artifact_id text primary key,
  capture_session_id text not null references vocera_media_capture_sessions(session_id) on delete cascade,
  capture_leg_id text references vocera_media_capture_legs(leg_id) on delete set null,
  artifact_kind text not null
    check (artifact_kind in (
      'wlc_epc', 'wlc_terminal_output', 'wlc_terminal_timing', 'wlc_transcript',
      'ap_ota_pcap', 'ap_ota_terminal_output', 'ap_ota_terminal_timing', 'ap_ota_metadata'
    )),
  source_path text not null,
  final_path text,
  source_name text not null,
  sha256 text,
  size_bytes bigint,
  received_at timestamptz not null default now(),
  validated_at timestamptz,
  ingest_state text not null default 'waiting_for_export'
    check (ingest_state in (
      'waiting_for_export', 'upload_detected', 'waiting_for_stability',
      'validating', 'validated', 'promoted', 'registered', 'imported',
      'parsing', 'parsed', 'failed', 'retry_pending', 'quarantined'
    )),
  capture_id text references vocera_media_captures(capture_id) on delete set null,
  parser_status text,
  visibility_class text,
  error_message text,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index if not exists idx_vocera_media_session_artifacts_session
  on vocera_media_session_artifacts (capture_session_id, artifact_kind);

create index if not exists idx_vocera_media_session_artifacts_state
  on vocera_media_session_artifacts (ingest_state, updated_at desc);

create index if not exists idx_vocera_media_session_artifacts_capture
  on vocera_media_session_artifacts (capture_id);

-- Identical content (same session + content hash) imports at most once so a
-- repeated SCP push or a repeated ingest scan stays idempotent.
create unique index if not exists uq_vocera_media_session_artifacts_session_sha
  on vocera_media_session_artifacts (capture_session_id, sha256)
  where sha256 is not null;

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

alter table vocera_media_session_artifacts
  drop constraint if exists vocera_media_session_artifacts_ingest_state_check;

alter table vocera_media_session_artifacts
  drop constraint if exists chk_vocera_media_session_artifacts_ingest_state;

alter table vocera_media_session_artifacts
  add constraint chk_vocera_media_session_artifacts_ingest_state
  check (ingest_state in (
    'waiting_for_export', 'upload_detected', 'waiting_for_stability',
    'validating', 'validated', 'promoted', 'registered', 'imported',
    'parsing', 'parsed', 'failed', 'retry_pending', 'quarantined'
  ));

alter table vocera_media_study_archives
  add column if not exists updated_at timestamptz,
  add column if not exists updated_by text;

create or replace function vocera_media_archive_current_study(
  p_archive_label text default null,
  p_archived_by text default null,
  p_notes text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive_id text;
  v_capture_count integer;
  v_stream_count integer;
  v_first_capture_time timestamptz;
  v_last_capture_time timestamptz;
  v_payload jsonb;
begin
  select
    count(*)::integer,
    min(capture_time),
    max(capture_time)
  into v_capture_count, v_first_capture_time, v_last_capture_time
  from vocera_media_captures;

  select count(*)::integer
    into v_stream_count
  from vocera_media_stream_samples;

  if coalesce(v_capture_count, 0) = 0 then
    return query select
      'empty'::text,
      null::text,
      0::integer,
      coalesce(v_stream_count, 0)::integer,
      'No media QoE captures exist in the current study.'::text;
    return;
  end if;

  v_archive_id := 'media_study_' || to_char(clock_timestamp() at time zone 'UTC', 'YYYYMMDD_HH24MISS_US') || '_' || substr(md5(random()::text), 1, 8);

  select jsonb_build_object(
    'captures',
    coalesce(
      (
        select jsonb_agg(to_jsonb(c) order by c.capture_time nulls last, c.source_name, c.capture_id)
        from vocera_media_captures c
      ),
      '[]'::jsonb
    ),
    'stream_samples',
    coalesce(
      (
        select jsonb_agg(to_jsonb(s) order by s.sample_time nulls last, s.capture_id, s.stream_id)
        from vocera_media_stream_samples s
      ),
      '[]'::jsonb
    )
  )
  into v_payload;

  insert into vocera_media_study_archives (
    archive_id,
    archive_label,
    archived_by,
    notes,
    capture_count,
    stream_count,
    first_capture_time,
    last_capture_time,
    payload
  )
  values (
    v_archive_id,
    nullif(trim(coalesce(p_archive_label, '')), ''),
    coalesce(nullif(trim(coalesce(p_archived_by, '')), ''), current_user),
    nullif(trim(coalesce(p_notes, '')), ''),
    v_capture_count,
    v_stream_count,
    v_first_capture_time,
    v_last_capture_time,
    v_payload
  );

  return query select
    'archived'::text,
    v_archive_id,
    v_capture_count,
    v_stream_count,
    format('Archived current media QoE study as %s with %s capture(s) and %s stream sample(s).', v_archive_id, v_capture_count, v_stream_count)::text;
end;
$$;

create or replace function vocera_media_clear_current_study(
  p_cleared_by text default null,
  p_notes text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
  message text
)
language plpgsql
as $$
declare
  v_capture_count integer := 0;
  v_stream_count integer := 0;
  v_deleted_captures integer := 0;
begin
  select count(*)::integer
    into v_capture_count
  from vocera_media_captures;

  select count(*)::integer
    into v_stream_count
  from vocera_media_stream_samples;

  delete from vocera_media_captures;
  get diagnostics v_deleted_captures = row_count;

  return query select
    case when v_deleted_captures = 0 then 'empty' else 'cleared' end::text,
    null::text,
    v_capture_count,
    v_stream_count,
    case
      when v_deleted_captures = 0 then 'No current media QoE study existed to clear.'
      else format('Cleared current media QoE study: deleted %s capture row(s) and %s stream sample(s).', v_deleted_captures, v_stream_count)
    end::text;
end;
$$;

create or replace function vocera_media_archive_and_clear_current_study(
  p_archive_label text default null,
  p_archived_by text default null,
  p_notes text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive record;
  v_deleted_captures integer := 0;
begin
  select *
    into v_archive
  from vocera_media_archive_current_study(p_archive_label, p_archived_by, p_notes);

  if v_archive.status = 'empty' then
    return query select
      'empty'::text,
      null::text,
      0::integer,
      v_archive.stream_count::integer,
      'No current media QoE study existed to archive or clear.'::text;
    return;
  end if;

  delete from vocera_media_captures;
  get diagnostics v_deleted_captures = row_count;

  return query select
    'archived_and_cleared'::text,
    v_archive.archive_id::text,
    v_archive.capture_count::integer,
    v_archive.stream_count::integer,
    format('Archived %s and cleared %s current capture row(s).', v_archive.archive_id, v_deleted_captures)::text;
end;
$$;

create or replace function vocera_media_apply_current_study_action(
  p_action text,
  p_archive_label text default null,
  p_notes text default null,
  p_user text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
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
      from vocera_media_archive_current_study(p_archive_label, p_user, p_notes);
    return;
  end if;

  if v_action in ('archive_and_clear', 'archive_clear', 'clear_archive', 'clear_and_archive', 'new', 'new_study') then
    return query
      select *
      from vocera_media_archive_and_clear_current_study(p_archive_label, p_user, p_notes);
    return;
  end if;

  if v_action in ('clear', 'clear_current', 'clear_current_study') then
    return query
      select *
      from vocera_media_clear_current_study(p_user, p_notes);
    return;
  end if;

  return query select
    'error'::text,
    null::text,
    0::integer,
    0::integer,
    format('Unknown media study action: %s', coalesce(p_action, '<empty>'))::text;
end;
$$;

create or replace function vocera_media_update_study_archive(
  p_archive_id text,
  p_archive_label text default null,
  p_notes text default null,
  p_updated_by text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive vocera_media_study_archives%rowtype;
begin
  if nullif(trim(coalesce(p_archive_id, '')), '') is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 'Missing archive_id.'::text;
    return;
  end if;

  update vocera_media_study_archives a
  set
    archive_label = nullif(trim(coalesce(p_archive_label, '')), ''),
    notes = nullif(trim(coalesce(p_notes, '')), ''),
    updated_at = now(),
    updated_by = coalesce(nullif(trim(coalesce(p_updated_by, '')), ''), current_user)
  where a.archive_id = p_archive_id
  returning *
  into v_archive;

  if not found then
    return query select 'not_found'::text, p_archive_id, 0::integer, 0::integer, format('No media study archive found for %s.', p_archive_id)::text;
    return;
  end if;

  return query select
    'updated'::text,
    v_archive.archive_id,
    v_archive.capture_count,
    v_archive.stream_count,
    format('Updated media study archive %s.', v_archive.archive_id)::text;
end;
$$;

create or replace function vocera_media_delete_study_archive(
  p_archive_id text,
  p_deleted_by text default null
)
returns table (
  status text,
  archive_id text,
  capture_count integer,
  stream_count integer,
  message text
)
language plpgsql
as $$
declare
  v_archive vocera_media_study_archives%rowtype;
begin
  if nullif(trim(coalesce(p_archive_id, '')), '') is null then
    return query select 'error'::text, null::text, 0::integer, 0::integer, 'Missing archive_id.'::text;
    return;
  end if;

  delete from vocera_media_study_archives a
  where a.archive_id = p_archive_id
  returning *
  into v_archive;

  if not found then
    return query select 'not_found'::text, p_archive_id, 0::integer, 0::integer, format('No media study archive found for %s.', p_archive_id)::text;
    return;
  end if;

  return query select
    'deleted'::text,
    v_archive.archive_id,
    v_archive.capture_count,
    v_archive.stream_count,
    format('Deleted media study archive %s.', v_archive.archive_id)::text;
end;
$$;
