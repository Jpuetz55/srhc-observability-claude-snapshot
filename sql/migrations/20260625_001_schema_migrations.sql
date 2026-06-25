-- Phase 0 migration ledger.
--
-- This table records one checksum per immutable migration file. Production
-- rollouts should apply migrations through scripts/apply_vocera_media_qoe_migrations.py
-- instead of repeatedly replaying the monolithic bootstrap schema.

create table if not exists schema_migrations (
  migration_id text primary key,
  checksum text not null,
  applied_at timestamptz not null default now(),
  applied_by text not null,
  source_commit text not null
);

create index if not exists idx_schema_migrations_applied_at
  on schema_migrations (applied_at desc);
