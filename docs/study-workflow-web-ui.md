# Study Workflow web application

Study Workflow is the collector-hosted application for RF validation, completed
Catalyst Center ICAP evidence, imported PCAP review, and manual WLC EPC capture
sessions. It is an evidence workflow application, not a WLC automation system.

## What it does and does not do

It **does**:

- manage Projects, Studies, RF runs, manual samples, and evidence attachment;
- read/write the RF Validation and Media QoE PostgreSQL stores;
- list/download completed ICAP files through the read-only Catalyst Center
  client when configured;
- generate password-free WLC command sheets and preserve manual WLC session
  markers, attempts, transcripts, and artifacts;
- register and parse media evidence using the existing parser; and
- show WLC session artifact state after the local ingest timer processes a
  stable SCP upload.

It **does not**:

- SSH to a WLC, start/stop an EPC, or run WLC CLI commands;
- keep WLC, SCP, or Catalyst Center passwords in a browser form or package;
- use Catalyst Center Command Runner, start ICAP, or deploy ICAP settings;
- claim a PCAP packet has been correlated to a human observation unless a
  separate, explicit correlation feature records that linkage.

## Components

```text
tools/study_web/                 FastAPI backend and generated static UI
tools/vocera_rf_validation/      RF parser/correlation/SQL helpers
tools/vocera_media_qoe/          PCAP, ICAP, WLC-session, and ingest helpers
web/study-ui/                    React + TypeScript + Vite + Tailwind frontend
systemd/vocera-rf-validation-study-web.service
scripts/install_vocera_rf_validation_study_web.sh
```

The standard library legacy RF page remains available only for compatibility:

```bash
make vocera-rf-validation-study-web-legacy
```

## Build and run

From the active checkout:

```bash
make study-web-frontend-build
PYTHONPATH=tools python3 -m uvicorn study_web.main:app --host 127.0.0.1 --port 8097
```

The service installer creates the Python virtual environment, installs API
dependencies, builds the frontend when `npm` is available, installs the systemd
unit, and can enable/start it. Study Web requires **Python 3.10 or newer**:
the backend uses modern union annotations and cannot start under the collector's
default Python 3.9. The installer prefers `/usr/bin/python3.12`, then
`/usr/bin/python3.11`, then `/usr/bin/python3.10`, and validates the selection
before modifying the virtualenv or systemd. Override the interpreter explicitly
when the host requires it:

```bash
sudo env STUDY_WEB_PYTHON_BIN=/usr/bin/python3.11 \
  bash scripts/install_vocera_rf_validation_study_web.sh --install-python-deps --enable --start-now
```

When `--install-python-deps` finds an unsupported or different-major/minor
repo-local virtualenv, it rebuilds the default `.venv-study-web` so Python
wheels are never reused across incompatible interpreter versions.


```bash
sudo bash scripts/install_vocera_rf_validation_study_web.sh --install-python-deps --enable --start-now
systemctl status vocera-rf-validation-study-web --no-pager -l
curl -fsS http://127.0.0.1:8097/healthz
```

The installed unit is the runtime authority for checkout paths and environment
files. The installer renders the service template with the checkout from which
it was run and writes a late-sorting override:

```text
/etc/systemd/system/vocera-rf-validation-study-web.service.d/zz-study-web-repo-root.conf
```

That override deliberately wins over a stale `override.conf` from an older
checkout while preserving independent settings such as
`20-grafana-embed.conf`. It pins `WorkingDirectory`, `PYTHONPATH`, the helper
scripts, the static UI directory, virtualenv path, and `ExecStart` to one
checkout. Do not hand-edit these paths after an install; rerun the installer
from the checkout that should be authoritative.

Verify the active runtime path with:

```bash
systemctl cat vocera-rf-validation-study-web.service
systemctl show vocera-rf-validation-study-web.service \
  -p WorkingDirectory -p ExecStart -p Environment
```

## WLC capture-session workflow

Use **Vocera multicast → Capture Sessions** in the UI to create a long
reproduction or short validation package. The package contains `session.json`,
event/attempt records, and generated command sheets. The operator runs those
commands from an approved WLC terminal and handles the WLC's interactive SCP
password prompt.

A long session uses this state flow:

```text
prepared_not_started -> active -> stopped/exported -> completed or aborted
WLC SCP output -> incoming/ -> stable/validated -> pcaps/ -> registered -> parsed
```

When the Phase 0 service is installed and enabled,
`vocera-media-qoe-wlc-session-ingest.timer` calls a **localhost-only** API every
minute. It observes a file under the session `incoming/` directory, waits for
stable size/mtime, checks pcap magic bytes, finalizes the upload into a
root-owned non-writable `pcaps/` artifact, records `capture_point=wlc_epc`, and
starts the parser. Failures retain the finalized artifact and retry without
moving or duplicating the capture. See
[`wireless/vocera-wlc-continuous-capture-runbook.md`](wireless/vocera-wlc-continuous-capture-runbook.md),
[`wireless/vocera-wlc-phase0-production-contract.md`](wireless/vocera-wlc-phase0-production-contract.md),
and [`wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md`](wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md).

The generic ICAP/imported-PCAP scanner must never process `wlc-sessions/` or
`wlc-attempts/`; those package roots are owned by their dedicated ingest paths.

## Read-only ICAP workflow

The ICAP page is separate from WLC sessions. It can discover/download completed
Catalyst Center ICAP files, register them, execute the parser, and review
capture/stream results. It cannot request a new capture or change Catalyst
Center/WLC configuration. See [`wireless/vocera-media-dnac-icap-runbook.md`](wireless/vocera-media-dnac-icap-runbook.md).

## Important API routes

Operators normally use the UI; the API list is useful for health checks and
integration tests.

```text
GET   /healthz
GET   /api/health
GET   /api/backend-status
GET   /api/projects
POST  /api/projects
GET   /api/projects/{project_id}/studies
POST  /api/projects/{project_id}/studies
GET   /api/studies/{study_id}/runs
POST  /api/studies/{study_id}/runs
GET   /api/studies/{study_id}/media-qoe/dnac/captures
POST  /api/studies/{study_id}/media-qoe/dnac/captures/download
GET   /api/studies/{study_id}/media-qoe/wlc/sessions
POST  /api/studies/{study_id}/media-qoe/wlc/sessions
POST  /api/media-qoe/wlc/sessions/{session_id}/events
POST  /api/media-qoe/wlc/sessions/{session_id}/attempts/start
PATCH /api/media-qoe/wlc/attempts/{attempt_id}/outcome
PATCH /api/media-qoe/wlc/attempts/{attempt_id}/active-group
GET   /api/media-qoe/wlc/sessions/{session_id}/artifacts
POST  /api/media-qoe/wlc/sessions/ingest-scan   # localhost timer only
```

Do not expose the ingest scan endpoint as a remote operational control. The UI
reads artifact status; the installed local timer initiates scans.

## Grafana embedding

Study Web can proxy/embed Grafana paths when the optional Grafana proxy is
enabled. The current provisioned dashboard inventory contains only WLC Control
Plane and Vocera Iperf QoE. Leave optional panel UID/slug/ID environment
settings unset unless a reviewed dashboard/panel exists in both the intended
runtime and repository inventory.
