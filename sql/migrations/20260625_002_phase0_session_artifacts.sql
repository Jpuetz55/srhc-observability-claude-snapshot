-- Phase 0 WLC session-artifact ingest table and idempotency indexes.
--
-- This mirrors the bootstrap schema for production systems that should move to
-- explicit additive migrations. The ingest code finalizes WLC SCP uploads into
-- service-owned pcaps/ evidence before this table links the final artifact to a
-- wlc_epc capture record and parser lineage.

create table if not exists vocera_media_session_artifacts (
  artifact_id text primary key,
  capture_session_id text not null references vocera_media_capture_sessions(session_id) on delete cascade,
  artifact_kind text not null
    check (artifact_kind in ('wlc_epc', 'wlc_terminal_output', 'wlc_terminal_timing', 'wlc_transcript')),
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

create unique index if not exists uq_vocera_media_session_artifacts_session_sha
  on vocera_media_session_artifacts (capture_session_id, sha256)
  where sha256 is not null;

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
