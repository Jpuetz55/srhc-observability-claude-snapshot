# Grafana Mimir cloud observability

A tight, portfolio-ready repo for monitoring Kubernetes-based cloud deployments with Grafana, Mimir, and Prometheus.

This repo is centered on three things:
- Grafana dashboards for platform health and Kubernetes/Mimir visibility
- Prometheus rules and a lightweight metric contract
- a clean DEV → repo → PROD promotion workflow for Grafana content

It also includes an optional wireless RF observability extension for Cisco WLC AP neighbor-density, DFS/radar tracking, and AP traffic-distribution voice latency. That extension lives under `tools/wireless_rf/` and feeds Prometheus/Mimir through generated exposition metrics.

## What is intentionally in scope
- Kubernetes and Mimir monitoring
- Grafana dashboard promotion between editable DEV and provisioned PROD
- CI/CD validation before promotion
- minimal deployment scaffolding for Kustomize-based environments
- optional Cisco WLC RF and traffic-distribution evidence parsing into Prometheus/Mimir metrics

## What is intentionally out of scope
- legacy one-off runtime debugging artifacts
- replacing Catalyst Center, Ekahau, WLC, or MDT as the source of RF evidence
- storing raw operational report output in Git

## Core workflow
1. Make dashboard changes in the editable DEV org.
2. Export DEV dashboards back into the repo.
3. Run validation.
4. Promote repo-managed dashboards and rules into the locked-down PROD org.
5. Reseed DEV from PROD whenever you want DEV brought back to baseline.

## Main commands
```bash
make validate
make plan
make deploy
make release MSG="promote platform dashboard updates"
make dashboard-sync-prod-to-dev
make wireless-rf-textfile-install
make wireless-rf-parse INPUT=data/wireless-rf/raw/wlc_rf_raw.txt WLC=SRHC-WLC-40G-SEC
```

## Repo layout
- `grafana/` dashboards and Grafana provisioning files
- `prometheus/` Prometheus config and recording rules
- `deploy/k8s/` minimal Kustomize layout for dev and prod overlays
- `scripts/` CI/CD, validation, export, promotion, org-sync, installer, and collector helpers
- `docs/` fresh project documentation only
- `tools/wireless_rf/` optional WLC RF parser, Catalyst Center collector, and web UI

See `docs/architecture.md` for runtime and control-plane diagrams,
`docs/codebase-walkthrough.md` for the maintainer-oriented code/data-flow
guide, and `scripts/README.md` for the script catalog and cleanup rules.

## Wireless RF extension

The wireless RF extension turns raw WLC evidence into CSV, JSON, SQLite history, and Prometheus exposition. Its first use cases are AP neighbor-density reporting, DFS/radar event tracking, and AP traffic-distribution voice latency.

Start here:

```bash
make wireless-rf-parse INPUT=data/wireless-rf/raw/wlc_rf_raw.txt WLC=SRHC-WLC-40G-SEC
```

See `docs/wireless-rf-observability.md`, `docs/wireless-rf-textfile-ingestion.md`, `docs/catalyst-center-wireless-rf-collection-runbook.md`, and `tools/wireless_rf/README.md` for the full workflow.

## Notes on PROD
PROD is expected to be provisioned and effectively uneditable from the Grafana UI. The repo is the source of truth for PROD dashboards.

## Notes on DEV
DEV is expected to remain editable. When it drifts too far or accumulates stale folder objects, use the repo sync flow to prune and reseed it from PROD without relying on ad hoc database cleanup.
