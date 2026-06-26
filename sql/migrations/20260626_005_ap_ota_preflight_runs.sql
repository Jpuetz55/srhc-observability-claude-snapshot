-- Immutable AP-OTA preflight evidence runs for the C1000 receiver workflow.
--
-- AP client packet capture on the Catalyst 9800 is not a generic "capture
-- anywhere" feature: the target client must already be associated to an AP that
-- inherits an AP packet-capture profile through its AP join profile / site-tag
-- chain, only one client capture is allowed per site, and the capture runs on
-- that AP's active radio/channel. Those are live facts that change every time
-- the badge roams, so they cannot be modeled as YAML booleans.
--
-- Each preflight run is an append-only observation derived from preserved,
-- read-only WLC CLI evidence. A single capture session can legitimately have
-- several runs (badge roams from AP-A to AP-B, operator re-runs discovery), so
-- overwriting one JSON column would lose the evidence that explains why the
-- targeted serving AP changed. A capture leg may only be created from a
-- still-fresh run whose derived gate state is ready_to_prepare.

create table if not exists vocera_media_ap_ota_preflight_runs (
  preflight_id text primary key,
  capture_session_id text not null
    references vocera_media_capture_sessions(session_id)
    on delete cascade,
  target_client_mac text not null,
  target_client_ip inet,
  target_client_role text not null default 'receiver',
  observed_at timestamptz not null,
  expires_at timestamptz not null,
  evidence_source text not null
    check (evidence_source in ('manual_cli_import', 'future_wlc_api')),
  target_client_associated boolean not null default false,
  serving_ap_name text,
  serving_ap_mac text,
  serving_ap_mode text,
  target_radio text,
  target_band text,
  target_channel integer,
  target_channel_width text,
  site_tag text,
  ap_join_profile text,
  packet_capture_profile text,
  site_capture_status_verified boolean not null default false,
  existing_site_capture_active boolean,
  active_capture_client_mac text,
  capture_capability text not null default 'unknown'
    check (capture_capability in (
      'unknown',
      'profile_unmapped',
      'profile_mapped_unverified',
      'validated'
    )),
  classifiers jsonb not null default '{}'::jsonb,
  ftp_server_host text,
  ftp_path text,
  ftp_username text,
  transcript_sha256 text,
  transcript_relpath text,
  evaluation_state text not null
    check (evaluation_state in (
      'blocked',
      'ready_for_profile_change',
      'ready_for_ftp_validation',
      'ready_to_prepare'
    )),
  blockers jsonb not null default '[]'::jsonb,
  notes text,
  created_by text,
  created_at timestamptz not null default now()
);

create index if not exists idx_vocera_media_ap_ota_preflight_session_time
  on vocera_media_ap_ota_preflight_runs
  (capture_session_id, observed_at desc);

-- A capture leg references the single successful preflight run it was prepared
-- from. on delete restrict keeps the evidence trail intact: a preflight run
-- that authorized a leg cannot be deleted out from under it.
alter table vocera_media_capture_legs
  add column if not exists preflight_id text
  references vocera_media_ap_ota_preflight_runs(preflight_id)
  on delete restrict;

create index if not exists idx_vocera_media_capture_legs_preflight
  on vocera_media_capture_legs (preflight_id);

create or replace view v_vocera_media_ap_ota_preflight_runs as
select *
from vocera_media_ap_ota_preflight_runs;
