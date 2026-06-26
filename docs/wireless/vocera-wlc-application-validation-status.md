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
investigation-first Vocera multicast UI source contract
```

Not run in this validation pass:

```text
production database migration
production ingest timer enablement
live 90-second WLC EPC smoke export
long reproduction capture
manual WLC SSH console recording against a real controller
browser smoke of the investigation-first multicast UI against production data
```

## Live Runtime Gate - 2026-06-26

The repository checkout is clean at:

```text
fe97b0d Refresh documentation audit findings
```

Host-level systemd inspection showed the Study Web service is active and points
at the expected checkout:

```text
WorkingDirectory=/home/appsadmin/srhc-observability-claude-snapshot
ExecStart=/bin/bash /home/appsadmin/srhc-observability-claude-snapshot/scripts/run_study_web.sh
```

The static Study Web bundle was rebuilt successfully from this checkout with:

```bash
./scripts/build_study_web_static.sh
```

The running process had started before the newest WLC ingest routes were
validated:

```text
start_time=Thu 2026-06-25 17:29:59 CDT
```

Endpoint checks on 2026-06-26 showed:

| Endpoint | Result |
| --- | --- |
| `GET /api/health` | `200 application/json` with `{"status":"ok"}` |
| `GET /api/media-qoe/wlc/ingest/status` | `200 text/html` Study Web SPA shell |
| `GET /metrics` | `200 text/html` Study Web SPA shell |

That is a **no-go** state for production WLC ingest. The source now contains
both the WLC ingest metrics endpoint and the top-level `/metrics` Prometheus
alias, but the live backend process has not been restarted onto that source
revision.

Restart from this session was blocked by host policy:

```text
systemctl restart vocera-rf-validation-study-web.service
-> Interactive authentication required.
```

An operator with systemd privileges must run:

```bash
cd /home/appsadmin/srhc-observability-claude-snapshot
./scripts/build_study_web_static.sh
sudo env STUDY_WEB_PYTHON_BIN=/usr/bin/python3.11 \
  bash scripts/install_vocera_rf_validation_study_web.sh \
    --install-python-deps \
    --skip-frontend-build \
    --enable \
    --start-now
```

or otherwise restart the installed service after confirming the installed unit
still points at this checkout.

Do not apply production DB changes, enable the WLC ingest timer, or gather WLC
data until the endpoint go condition below passes.

Also do not use the WLC multicast page for live controller work until the UI
smoke confirms these source-level constraints in the running browser bundle:

```text
no WLC controls before an investigation is selected
one explicit selected WLC session in the URL/state
operator buttons record intent only
capture profile defaults are read-only unless advanced override is opened
active-group selection is bound to the selected attempt/session
```

The operational gate remains:

```text
redeploy/restart Study Web from current source
prove WLC ingest status and metrics routes return API content
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

Required go condition after redeploy/restart:

```text
GET /api/health                          -> application/json
GET /api/backend-status                  -> application/json
GET /api/media-qoe/wlc/defaults          -> application/json
GET /api/media-qoe/wlc/ingest/status     -> application/json
GET /metrics                             -> Prometheus text, not HTML
```

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
