# Documentation audit — 2026-06-25

## Scope and source inspected

This audit reconciled the documentation with the current repository snapshot at
commit `86f632672af20aedd3772f628166dc2b3644435b`. It reviewed the Makefile,
service/timer templates, Prometheus/Mimir/Grafana provisioning, Study Web API,
WLC session importer, PCAP/ICAP tooling, database schemas, and the topology
integration boundary.

## Corrections made

- Replaced the Kubernetes-first project description with the collector-VM
  architecture and actual metric/evidence split.
- Corrected the WLC live telemetry path: WLC gRPC/mTLS reaches Telegraf's MDT
  receiver; Prometheus scrapes Telegraf's separate `:9273` exposition endpoint.
- Made the currently provisioned Grafana inventory explicit: WLC Control Plane
  and Vocera Iperf QoE only.
- Added `wlc-mdt-telemetry.md` and linked it from all canonical entry points.
- Documented the Phase 0 WLC EPC session importer: SCP landing in `incoming/`,
  stability checks, root-owned finalization into `pcaps/`, SHA-256 identity,
  `wlc_epc` registration, parser execution, visibility classification, and
  idempotent retry.
- Updated WLC transfer, recovery, evidence-contract, Media QoE, Study Web, and
  ICAP runbooks so WLC EPC is never treated as generic ICAP evidence.
- Indexed the Phase 0 rehearsal runbook and made timer enablement contingent on
  a rehearsal database/ingest proof.
- Preserved the newer continuous-capture runbook details: output-only WLC
  terminal recording, 90-second smoke mode, visibility classification, and
  timeout ordering.
- Removed claims that every parser or datasource has a provisioned Grafana
  dashboard.
- Clarified that a sanitized checkout carries templates/tooling but no live
  credentials, PCAPs, uploads, database volumes, or generated evidence.
- Kept source-control guidance scoped to this repository's branch, review, and
  runtime-promotion workflow rather than treating hosting changes as part of
  application operations.

## Validation performed

- Checked local Markdown links after the rewrite.
- Checked documented Make targets against the current Makefile.
- Reviewed repository service/timer templates and datasource/provisioning files.
- Ran `make validate` successfully.
- Ran the `make test` sequence against the rebased working tree. The sandbox
  terminated the monolithic command after `test_vocera_wlc_session`; the
  remaining commands then passed individually with the same `PYTHONPATH=.`
  environment that the Makefile exports.
- Confirmed the generated patch applies cleanly to the inspected snapshot.

## Remaining runtime-template cautions

These are real deployment concerns, not documentation assumptions:

1. Some older systemd templates use `/opt/grafana-mimir-observability`; newer
   Study Web/session-ingest templates use `/home/appsadmin/grafana-mimir-observability`.
   `systemctl cat <unit>` and its drop-ins are the authority on any host. Before
   reinstalling or relocating the repository, normalize each unit's
   `WorkingDirectory`, `ExecStart`, and sandbox `ReadWritePaths`.
2. Several datasource comments refer to `secrets/postgres.env.sops.yaml` as a
   secret source, but the sanitized snapshot does not contain that live
   encrypted file. Operators must materialize
   `/etc/grafana-mimir-observability/secrets/*.env` through the approved secret
   process rather than assuming a clone is deployable with credentials.
3. The WLC session-ingest timer is designed for automatic import but should not
   be enabled in production until the Phase 0 rehearsal runbook passes against
   a restored rehearsal database.

## Ownership rule

When code, an installed systemd unit, a generated command sheet, and a runbook
conflict, resolve the discrepancy deliberately. Do not "fix" it by silently
editing evidence, command transcripts, or credentials. Update the canonical
source, rerun validation, and record the operational change.
