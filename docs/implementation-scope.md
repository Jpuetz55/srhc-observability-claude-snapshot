# Current implementation scope and status

This document describes what the checked-in collector-VM repository owns, what
is available but not represented by a provisioned Grafana dashboard, and what
is deliberately deferred.

## Deployed and maintained

| Capability | Status | Source of truth |
| --- | --- | --- |
| local Grafana/Prometheus/Mimir promotion | deployed control plane | `scripts/pipeline.sh`, `scripts/promote_repo_to_prod.sh` |
| editable DEV → reviewed repository change → provisioned PROD | deployed workflow | `docs/cicd.md` |
| WLC MDT gRPC dial-out to Telegraf/Prometheus | live telemetry integration | `docs/wlc-mdt-telemetry.md` |
| WLC Control Plane dashboard | tracked/provisioned | dashboard inventory test |
| Vocera Iperf QoE dashboard | tracked/provisioned | dashboard inventory test |
| RF validation PostgreSQL + Study Web | deployed workflow service | `tools/study_web/`, service unit |
| manual WLC EPC capture-session packages | deployed operator workflow | WLC session tools/runbooks |
| WLC SCP session ingestion | implementation complete; enable only after Phase 0 rehearsal | session importer/timer + rehearsal runbook |
| completed ICAP read-only discovery/download | available when API is healthy | ICAP client / Study Web |
| topology/RF/media PostgreSQL services | deployed datasource capability | units + schemas |

## Available but not provisioned as dashboards

- RF/DFS parser output and retained recording rules
- badge telemetry parser output
- Media QoE capture/stream history datasource
- topology datasource/node-edge tables
- path-probe metrics

These are valid modules. Documentation must not describe a visualization as
live unless dashboard JSON exists in both dashboard trees and passes the
inventory/contract checks.

## Explicitly deferred / out of scope

- Catalyst Center Command Runner and device-command execution
- WLC changes from Study Web, Grafana, parser code, or deployment scripts
- unattended WLC SSH terminal logging
- automatic parsing of every terminal transcript
- automatic packet-to-attempt causality verdicts
- CAPWAP decapsulation
- raw PCAP/transcript storage in Git
- automatic promotion from unreviewed runtime state
- repository-hosting changes bundled with an application or evidence workflow

## Completion rule for future changes

A feature is not complete merely because code exists. It needs safe input/output
and credential boundaries, tests where feasible, maintained operator docs,
service/Make integration for recurring operations, dashboard
inventory/metric-contract updates where visualized, and an explicit status here
when optional, legacy, or deferred.
