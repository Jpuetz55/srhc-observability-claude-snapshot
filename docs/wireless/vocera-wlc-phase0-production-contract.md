# Vocera WLC Phase 0 Production Contract

This is the current production contract for the manual WLC EPC to collector
ingest workflow. It supersedes historical Phase 1 UX notes for this workflow.
Phase 0 is only the evidence handoff:

```text
operator-controlled WLC EPC
  -> WLC SCP push into session incoming/
  -> collector stability validation
  -> root-owned finalization into pcaps/
  -> artifact registration
  -> parser execution
  -> Study Web status
```

The application prepares command sheets, records operator events, validates
evidence, and presents results. It does not SSH to the WLC, run WLC commands,
store WLC credentials, or store SCP passwords.

## Authoritative Basis

- Cisco Catalyst 9800 Embedded Packet Capture is a CLI troubleshooting feature
  that supports interface attachment, filters/ACLs, circular file buffers,
  continuous capture, multiple inner MAC filters, and export. Cisco documents
  that physical controllers should use the configured port channel where
  applicable, that circular files work as a ring buffer, and that controller
  swap files are not PCAP evidence until exported.
  Source: <https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-15/config-guide/b_wl_17_15_cg/m_embedded_packet_capture.html>
- PostgreSQL `pg_dump` provides a consistent export while the database is in
  concurrent use, which is why production Phase 0 changes require a fresh
  backup and rehearsal restore before rollout.
  Source: <https://www.postgresql.org/docs/current/app-pgdump.html>
- PostgreSQL documents that many `ALTER TABLE` forms acquire strong locks, so
  production changes after bootstrap must move toward small reviewed migrations
  instead of repeatedly applying a monolithic schema file.
  Source: <https://www.postgresql.org/docs/current/sql-altertable.html>
- PostgreSQL `INSERT ... ON CONFLICT` and advisory locks provide the intended
  idempotency and cross-process coordination model for artifact rows.
  Sources: <https://www.postgresql.org/docs/current/sql-insert.html>,
  <https://www.postgresql.org/docs/current/explicit-locking.html>
- NIST least privilege requires giving a process only the resources and
  authorization needed for its function. NIST SSDF supports explicit
  threat-handling, testing, and release evidence before production enablement.
  Sources: <https://csrc.nist.gov/glossary/term/least_privilege>,
  <https://csrc.nist.gov/pubs/sp/800/218/final>
- systemd service sandboxing, timers, and journaling remain the runtime model.
  Source: <https://man7.org/linux/man-pages/man5/systemd.exec.5.html>

## Package Layout

Every WLC capture session package lives under:

```text
/var/lib/vocera-media-qoe/raw/wlc-sessions/<study>/<session>/
```

Required subdirectories:

| Path | Purpose | Writer |
| --- | --- | --- |
| `incoming/` | WLC SCP upload staging only | collector SCP account |
| `pcaps/` | finalized EPC evidence | Study Web ingest service |
| `cli/terminal/` | output-only terminal transcript artifacts | operator console recorder |
| `attempts/` | operator marker files | Study Web / package CLI |
| `validation/` | rehearsal and recovery evidence | maintainer |

The WLC export command must target `incoming/`, never `pcaps/`.

## Ownership and Modes

The intended production ownership contract is:

```text
incoming/     <scp-user>:<operational-group> 0750
pcaps/        root:root                       0755 or stricter
pcaps/*.pcap  root:root                       0440 or 0400
```

The SCP account must be able to create a file in `incoming/` and must not be
able to modify a finalized EPC in `pcaps/`.

Required checks before timer enablement:

```bash
sudo -u appsadmin test -w "$SESSION_DIR/incoming"
sudo -u appsadmin test ! -w "$SESSION_DIR/pcaps"
sudo -u appsadmin test ! -w "$SESSION_DIR/pcaps/<finalized-file>.pcap"
```

The third check is mandatory. A root-owned `pcaps/` directory alone is
insufficient because a rename would preserve the uploader-owned file mode.

## Artifact State Machine

Allowed Phase 0 states:

```text
waiting_for_export
upload_detected
waiting_for_stability
validating
validated
promoted
registered
parsing
parsed
retry_pending
failed
quarantined
```

State meaning:

| State | Meaning |
| --- | --- |
| `upload_detected` | First scan saw an incoming file; it is not stable yet. |
| `waiting_for_stability` | File exists but size/mtime changed or the stable interval has not elapsed. |
| `validating` | The service is claiming and validating a stable candidate. |
| `validated` | Container, hash, ownership, and finalization checks passed. |
| `promoted` | Final root-owned artifact exists in `pcaps/`; the state name is retained for schema compatibility. |
| `registered` | The artifact is linked to a `wlc_epc` capture record. |
| `parsing` | The shared parser is running. |
| `parsed` | Parser completed or the artifact was safely marked duplicate. |
| `retry_pending` | A transient parser/lock failure will be retried. |
| `failed` | A service/dependency failure needs retry or operator attention. |
| `quarantined` | The upload itself is unsafe or invalid and must not be parsed. |

## Finalization Rule

Finalization from `incoming/` to `pcaps/` is not a rename. The service must:

```text
lstat source
reject symlink
reject non-regular file
reject hard-linked file
enforce extension and size limit
verify free space
open with no-follow semantics where available
validate pcap/pcapng magic bytes
copy into a service-created temp file in pcaps/
hash while copying
fsync temp file
chown root:root
chmod 0440 or 0400
atomic rename temp -> final
fsync pcaps directory
verify final SHA-256
remove original incoming file only when the inode still matches
```

This prevents the SCP upload account from retaining write access to final
evidence.

## Failure Categories

Structured failure categories:

```text
invalid_magic
truncated_container
symlink_rejected
hardlink_rejected
not_regular_file
size_limit_exceeded
disk_space_insufficient
source_changed_during_claim
promotion_copy_failed
promotion_hash_mismatch
capture_registration_failed
parser_failed
retry_limit_reached
```

Invalid source objects are `quarantined`. Transient service conditions are
`failed` or `retry_pending` and must preserve the source or final artifact for
operator review.

## Retry Policy

Files already finalized into `pcaps/` are never moved back to `incoming/`.
Retries operate on the same `vocera_media_session_artifacts` row, final path,
capture identity, and parser lineage. Multiple parse-run rows are acceptable
only when they represent justified retry history; duplicate files, artifacts,
or captures are not acceptable.

## Concurrency Policy

The systemd trigger must acquire a non-blocking host-level lock before calling
the local ingest-scan endpoint:

```text
/run/vocera-media-qoe/wlc-session-ingest.lock
```

If another pass is running, the trigger exits successfully and logs:

```json
{"event":"wlc_ingest_scan_skipped","reason":"already_running"}
```

The application remains idempotent through deterministic artifact IDs, the
session/SHA unique key, and parser retry lineage. A future persistent database
client can add PostgreSQL advisory locks around individual artifact processing;
until then, do not add a no-op advisory-lock query that is released before file
finalization completes.

## Trigger Preflight

Before the timer calls `/api/media-qoe/wlc/sessions/ingest-scan`, the trigger
must verify:

```text
local Study Web /api/health responds
VOCERA_MEDIA_QOE_RAW_DIR exists
STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT exists
free bytes under the session root >= STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES
```

Default runtime values:

```text
VOCERA_MEDIA_QOE_RAW_DIR=/var/lib/vocera-media-qoe/raw
STUDY_WEB_MEDIA_QOE_WLC_SESSION_ROOT=/var/lib/vocera-media-qoe/raw/wlc-sessions
STUDY_WEB_WLC_INGEST_LOCK_FILE=/run/vocera-media-qoe/wlc-session-ingest.lock
STUDY_WEB_WLC_INGEST_MIN_FREE_BYTES=536870912
```

Preflight failures should emit a concise JSON reason and exit non-zero so
systemd/journald shows the operational cause without requiring a Python
traceback.

## Operational Telemetry

Study Web exposes WLC ingest health at:

```text
GET /api/media-qoe/wlc/ingest/status
GET /api/media-qoe/wlc/ingest/metrics
```

The Prometheus-text endpoint intentionally uses only bounded labels:

```text
vocera_wlc_ingest_artifacts_total{state}
vocera_wlc_ingest_quarantined_total{reason}
```

It must not label metrics by session ID, artifact ID, capture ID, filename,
SHA-256, MAC address, IP address, or study name. Those values belong in
PostgreSQL and Study Web evidence views, not in time-series labels.

Required health values:

```text
pending uploads
oldest pending upload age
current artifacts by ingest state
current quarantines by bounded reason
retry-pending count
last successful import/parse timestamp
session-root disk free bytes
```

## Generic Ingest Isolation

The generic ICAP/imported-PCAP path must never scan:

```text
wlc-sessions/
wlc-attempts/
```

WLC EPCs use the session ingest path only and are registered with:

```text
capture_point = wlc_epc
```

## Timer Enablement Conditions

Do not enable `vocera-media-qoe-wlc-session-ingest.timer` until:

1. Schema and app code match the reviewed commit.
2. A production backup exists and was restored in rehearsal.
3. Required additive schema changes were applied through:

   ```bash
   make vocera-media-qoe-apply-migrations
   ```

4. The Phase 0 rehearsal matrix passes.
5. A manual localhost empty scan succeeds.
6. One real 90-second WLC smoke export succeeds end to end.
7. The final EPC is root-owned and not writable by the SCP account.
8. Generic ICAP/raw-PCAP ingest ignores WLC roots.
9. WLC cleanup was confirmed after export.

Enable only after those gates:

```bash
sudo systemctl enable --now vocera-media-qoe-wlc-session-ingest.timer
```

## Recovery Boundary

On an incident:

```text
disable timer
stop ingest service
preserve incoming/, pcaps/, cli/, attempts/, validation/
preserve database rows
revert application commit if needed
restart Study Web
resume from final artifact or incoming source based on recorded state
```

Do not delete evidence to make a retry easier. Do not run the generic media
publisher as a substitute for WLC session ingest.
