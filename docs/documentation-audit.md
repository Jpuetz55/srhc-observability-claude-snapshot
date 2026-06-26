# Documentation audit - 2026-06-26

## Scope

This audit reconciled the current source tree, Study Web behavior, WLC session
runbooks, schema/migration guidance, service wrappers, and Media QoE docs with
the application goal:

```text
manual WLC EPC control
  -> WLC SCP export
  -> collector ingest
  -> WLC evidence + packet evidence
  -> attempt-by-attempt Vocera multicast investigation
```

The source line inspected started at commit
`9593eed0698337fb5ce4ff99855376ae32323e9d`, then this audit corrected
documentation drift found during review.

## Authoritative Sources Checked

- Cisco Catalyst 9800 Embedded Packet Capture documentation for EPC interface
  attachment, filters, circular files, duration controls, and export:
  <https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-15/config-guide/b_wl_17_15_cg/m_embedded_packet_capture.html>
- Cisco Catalyst 9800 Vocera broadcast and multicast troubleshooting guidance
  for the separate Vocera application multicast group and WLC-to-AP multicast
  forwarding evidence chain:
  <https://www.cisco.com/c/en/us/support/docs/wireless/catalyst-9800-series-wireless-controllers/225171-understand-vocera-broadcast-on-wlc-9800.html>
  and
  <https://www.cisco.com/c/en/us/support/docs/wireless/catalyst-9800-series-wireless-controllers/225203-troubleshoot-multicast-on-c9800.html>
- Vocera multicast planning guidance for Vocera badge multicast behavior and
  IGMP expectations:
  <https://pubs.vocera.com/solution/vig/production/help/vig_vig_help/solution/vig/production/topics/vig_igmpmulticasts.html>
- RFC 1112 for IPv4 multicast-to-Ethernet MAC mapping limits:
  <https://www.rfc-editor.org/rfc/rfc1112>
- PostgreSQL documentation for consistent `pg_dump` exports, migration lock
  risk around `ALTER TABLE`, `INSERT ... ON CONFLICT`, and advisory locks:
  <https://www.postgresql.org/docs/current/app-pgdump.html>,
  <https://www.postgresql.org/docs/current/sql-altertable.html>,
  <https://www.postgresql.org/docs/current/sql-insert.html>,
  <https://www.postgresql.org/docs/current/functions-admin.html>
- systemd service sandboxing and runtime behavior:
  <https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html>
- `flock(1)` for the host-level non-overlap guard:
  <https://man7.org/linux/man-pages/man1/flock.1.html>
- NIST least privilege and SSDF guidance for avoiding unnecessary controller
  command execution and requiring testable release gates:
  <https://csrc.nist.gov/glossary/term/least_privilege>,
  <https://csrc.nist.gov/pubs/sp/800/218/final>

## Corrections Made In This Audit

- Updated the WLC manual capture command reference so it matches the active
  Study Web session generator and Cisco EPC syntax:

  ```text
  monitor capture <CAPTURE_NAME> buffer circular file <COUNT> file-size <MB>
  ```

  The stale `buffer circular size <MB>` example remains a legacy-attempt helper
  issue and is now called out explicitly.

- Updated the Phase 0 ingest rehearsal runbook to exercise the versioned
  migration runner:

  ```bash
  make vocera-media-qoe-apply-migrations
  ```

  instead of proving production readiness by replaying the monolithic bootstrap
  schema file.

## Validation Performed

Recent application validation before this audit:

- `make test` completed successfully.
- `./scripts/build_study_web_static.sh` completed successfully.
- `bash -n scripts/run_vocera_wlc_session_ingest.sh` completed successfully.
- `bash -n scripts/install_vocera_wlc_session_ingest.sh` completed
  successfully.
- Live Study Web health endpoints responded for `/api/health`,
  `/api/backend-status`, `/api/media-qoe/summary`, and WLC defaults.

Documentation-focused validation during this audit:

- Checked WLC session docs against the active generator in
  `tools/vocera_media_qoe/vocera_wlc_session.py`.
- Checked command-sheet expectations against `scripts/test_vocera_wlc_session.py`.
- Checked Phase 0 migration guidance against the Make target and
  `scripts/apply_vocera_media_qoe_migrations.py`.
- Searched for forbidden or misleading language around "overall latency",
  mouth-to-ear latency, MOS, CAPWAP-only media claims, WLC command execution,
  and generic ICAP/WLC artifact mixing.

## Potential Problems Found

### 1. Legacy Attempt Helper Still Contains Old EPC Syntax

`tools/vocera_media_qoe/vocera_wlc_attempt.py` still contains:

```text
monitor capture {session} buffer circular size 50
```

The active WLC capture-session path uses the corrected syntax and has tests for
it. The legacy attempt-only helper should not be used as the production command
source. If that helper remains in the repo, either retire it from operator docs
or update it to the current EPC syntax before anyone uses it in the field.

### 2. Production Timer Still Needs Real Rehearsal And Smoke Evidence

The documentation correctly treats timer enablement as gated. Do not enable the
production WLC session ingest timer until the Phase 0 rehearsal matrix and the
90-second real WLC SCP smoke export prove:

```text
incoming/ -> stable validation -> root-owned pcaps/ -> artifact -> wlc_epc capture -> parser
```

### 3. Active Service May Lag Source

The live service previously returned healthy core endpoints, but newer ingest
status/metrics routes appeared to fall through to the SPA. That indicates the
running Study Web process may not yet be deployed from the newest source line.
Treat local source docs as desired state until the service version is confirmed
after deployment.

### 4. Vocera Multicast Pool Wording Needs Operator Confirmation

The repo config uses:

```text
230.230.0.0/20
first usable: 230.230.0.1
last usable: 230.230.15.254
```

That is a practical operational guardrail, but the docs also mention Vocera's
"4096 address" range. A `/20` contains 4096 addresses including network and
broadcast-style boundary values, while the configured first/last usable range
excludes `.0` and `.15.255`. Before changing code, confirm the exact active
Vocera/WLC configuration and document whether boundaries are intentionally
excluded.

### 5. CAPWAP-Only Evidence Must Stay Limited

The docs and UI must continue to distinguish:

```text
outer CAPWAP transport evidence
```

from:

```text
inner UDP/RTP media visibility
```

CAPWAP-only EPC evidence can support controller/AP transport observations. It
must not produce RTP loss, jitter, MOS, mouth-to-ear latency, receiver delivery,
or speaker-output claims.

### 6. Migration Guidance Is Now Split By Use Case

`sql/vocera_media_qoe_schema.sql` is still used by bootstrap/install paths and
some compatibility tooling. Production rehearsal and rollout should use the
versioned migration runner so the `schema_migrations` ledger and checksum
contract are tested before timer enablement.

### 7. Transcript Parsing Is Initial, Not Decision-Grade For Every Case

The current documentation should describe terminal transcript ingestion as
output-only, block-oriented, and confidence-bound. It should not imply that all
possible WLC terminal output can be automatically interpreted or bound to an
attempt. Ambiguous blocks must remain session-scoped or require operator review.

### 8. WLC Syntax Still Requires Device-Side Verification

The command sheets are generated from the current source and aligned with Cisco
EPC documentation, but first live use still needs `?` verification on
`SRHC-WLC-40G-SEC`. Controller software, platform, privilege level, and capture
attachment points can affect exact CLI availability.

## Current Documentation Position

The docs now correctly separate:

- Catalyst Center ICAP QoE from Vocera multicast WLC investigation.
- Manual WLC command execution from repository-owned evidence ingestion.
- WLC SCP upload staging in `incoming/` from finalized evidence in `pcaps/`.
- Configured Vocera VLAN 684 from observed badge/client/group VLAN context.
- Packet evidence visibility from unsupported media-quality conclusions.
- Bootstrap schema use from production migration-runner use.

The remaining work is not another documentation rewrite. It is operational
proof: run the Phase 0 rehearsal, run one real 90-second WLC smoke export, and
record the resulting validation evidence.
