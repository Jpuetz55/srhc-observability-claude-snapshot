# Documentation index

Use this index instead of treating every Markdown file as a current runbook.
The repository contains maintained operational documentation as well as
preserved implementation and history notes.

## Current architecture and operations

- [`architecture.md`](architecture.md) — deployed components, ports, data
  stores, runtime paths, and evidence boundaries.
- [`getting-started.md`](getting-started.md) — safe orientation, validation,
  deploy order, and source-control verification.
- [`wlc-mdt-telemetry.md`](wlc-mdt-telemetry.md) — WLC gRPC dial-out, Telegraf,
  Prometheus, Mimir, and WLC Control Plane checks.
- [`cicd.md`](cicd.md) — DEV → repository → PROD promotion and rollback
  boundaries.
- [`local-mimir-vm.md`](local-mimir-vm.md) — local Mimir lifecycle and safe
  Prometheus-only recovery.
- [`repo-map.md`](repo-map.md) — directory, service, datastore, and timer map.
- [`codebase-walkthrough.md`](codebase-walkthrough.md) — entry points, parsers,
  databases, and web application data flow.
- [`documentation-audit.md`](documentation-audit.md) — current audit result,
  resolved drift, and remaining runtime-template cautions.

## Wireless and evidence workflows

- [`study-workflow-web-ui.md`](study-workflow-web-ui.md) — projects/studies,
  RF validation, read-only ICAP intake, and manual WLC EPC sessions.
- [`wireless/vocera-wlc-continuous-capture-runbook.md`](wireless/vocera-wlc-continuous-capture-runbook.md)
  — canonical intermittent multicast capture workflow.
- [`wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md`](wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md)
  — rehearsal gate for the automatic SCP upload ingest timer.
- [`wireless/vocera-wlc-capture-transfer.md`](wireless/vocera-wlc-capture-transfer.md)
  — session `incoming/` staging, automatic promotion, and legacy attempt
  transfer boundary.
- [`wireless/vocera-wlc-capture-recovery.md`](wireless/vocera-wlc-capture-recovery.md)
  — safe stop/export/cleanup and ingest recovery.
- [`wireless/vocera-media-dnac-icap-runbook.md`](wireless/vocera-media-dnac-icap-runbook.md)
  — read-only completed-ICAP discovery/download and parser boundary.
- [`wireless/vocera-media-pcap-qoe-architecture.md`](wireless/vocera-media-pcap-qoe-architecture.md)
  — PCAP parser semantics, session ingestion, storage, and evidence limits.
- [`wireless/vocera-badge-ekahau-rf-validation-runbook.md`](wireless/vocera-badge-ekahau-rf-validation-runbook.md)
  — badge/Ekahau field workflow.
- [`vocera-iperf-qoe.md`](vocera-iperf-qoe.md) — laptop iperf upload and
  node-exporter textfile pipeline.
- [`path-probe-observability.md`](path-probe-observability.md) — synthetic RTT,
  variation, and loss probes.
- [`wireless-rf-observability.md`](wireless-rf-observability.md) — retained
  manual WLC CLI RF evidence parser; it is not a current dashboard promise.

## Data sources and integrations

- [`network-topology-grafana-integration.md`](network-topology-grafana-integration.md)
  — topology PostgreSQL and the sibling Network-Topology repository boundary.
- [`metrics.md`](metrics.md) — Prometheus/Mimir metric discovery and query
  troubleshooting.
- [`../secrets/README.md`](../secrets/README.md) — secret templates and local
  materialization; a sanitized clone contains no live secret values.
- [`private-git-workflow.md`](private-git-workflow.md) — current branch,
  validation, and runtime-promotion boundaries.

## Historical or planning notes

The following are retained for traceability. Do not use them as a current
operator entry point unless a current runbook explicitly points to them:

- `../PHASE1_IMPLEMENTATION.md`
- `../MANUAL_ENTRY_IMPLEMENTATION.md`
- `../STUDY_STATISTICS_IMPLEMENTATION.md`
- `BADGE_SNR_DISPLAY_FIX.md`
- `wireless/qoe-measurement-accuracy-audit.md`
- `python-toolkit-refactor-plan.md`
- `catalyst-center-wireless-rf-collection-runbook.md`
