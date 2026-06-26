# Vocera WLC Application Validation Status

Last updated: 2026-06-26

This document records the current tested stopping point for the manual WLC EPC
to collector ingest workflow. It is intentionally limited to application
validation and documentation status. It does not authorize production timer
enablement by itself.

## Current Boundary

Validated in the repository:

```text
manual WLC session package generation
WLC SCP staging path under incoming/
root-owned EPC finalization path into pcaps/
session artifact registration model
parser reuse contract
generic ICAP/raw-PCAP isolation
output-only WLC console recorder contract
block-level WLC transcript parser contract
bounded WLC ingest status/metrics endpoints in source
versioned Media QoE migration framework in source
```

Not run in this validation pass:

```text
production deployment
production database migration
production ingest timer enablement
live 90-second WLC EPC smoke export
long reproduction capture
manual WLC SSH console recording against a real controller
```

The operational gate remains:

```text
apply migrations
install ingest timer with --no-enable
run manual empty scan
run Phase 0 rehearsal matrix
run one real 90-second WLC EPC smoke export
confirm final EPC ownership and parser lineage
enable timer only after those gates pass
```

## Automated Tests Run

These commands passed from the repository checkout:

```bash
make test
./scripts/build_study_web_static.sh
bash -n scripts/run_vocera_wlc_session_ingest.sh
bash -n scripts/install_vocera_wlc_session_ingest.sh
```

Covered areas include:

```text
dashboard and metric-contract checks
Catalyst Center read/download-only contract
Media QoE parser tests
Vocera multicast helper tests
WLC CLI parser tests
WLC attempt package tests
WLC session package tests
WLC SCP ingest tests
WLC console recorder tests
WLC session Make safety tests
WLC documentation/comment contract tests
Study Web installer-path tests
RF validation tests
DNAC topology publisher tests
frontend TypeScript/Vite build
```

## Live Local Endpoint Checks

The running Study Web service responded successfully to:

```text
GET /api/health
GET /api/backend-status
GET /api/media-qoe/wlc/defaults
GET /api/media-qoe/summary
```

Observed useful confirmations:

```text
Study Web health returned status=ok.
Backend status returned ready.
WLC defaults preserved VLAN 684, Port-channel1, 230.230.0.0/20,
and no-password manual mode.
Media QoE summary returned existing capture/stream history.
```

The running service did **not** expose the newest WLC ingest-health routes from
this checkout:

```text
GET /api/media-qoe/wlc/ingest/status
GET /api/media-qoe/wlc/ingest/metrics
```

Those paths returned the Study Web SPA HTML, which means the active service was
not running the current source revision. Redeploy Study Web before using those
new endpoints as a production health signal.

## Documentation Status

Current source-of-truth documents:

```text
docs/wireless/vocera-wlc-phase0-production-contract.md
docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md
docs/wireless/vocera-wlc-continuous-capture-runbook.md
docs/wireless/vocera-wlc-capture-security.md
docs/wireless/vocera-wlc-capture-recovery.md
docs/wireless/vocera-wlc-capture-transfer.md
docs/wireless/vocera-wlc-session-maintainer-contract.md
docs/study-workflow-web-ui.md
```

## Authoritative References

The current workflow is aligned with:

- Cisco Catalyst 9800 Embedded Packet Capture documentation for EPC capture,
  circular buffers, port-channel capture guidance, and export behavior:
  <https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-15/config-guide/b_wl_17_15_cg/m_embedded_packet_capture.html>
- PostgreSQL documentation for `pg_dump`, `ALTER TABLE`, `INSERT ... ON
  CONFLICT`, and locking behavior:
  <https://www.postgresql.org/docs/current/>
- systemd service execution/sandboxing documentation:
  <https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html>
- `flock` non-blocking lock behavior:
  <https://man7.org/linux/man-pages/man1/flock.1.html>
- NIST least-privilege definition and Secure Software Development Framework:
  <https://csrc.nist.gov/glossary/term/least_privilege>
  and <https://csrc.nist.gov/pubs/sp/800/218/final>

