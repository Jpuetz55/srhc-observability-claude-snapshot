# CI/CD and promotion

## Canonical flow
DEV Grafana org → repo export → validation → PROD promotion

## Validation steps
- dashboard JSON structure
- dashboard metric references
- Prometheus recording rules covered by the metric contract
- Kustomize base/dev/prod overlays build in CI

## Key scripts
- `scripts/export_dashboards.sh`
- `scripts/preflight.sh`
- `scripts/pipeline.sh`
- `scripts/promote_repo_to_prod.sh`
- `scripts/sync_prod_to_dev.sh`
- `scripts/seed_dev_from_files.sh`

## DEV reseed
When DEV needs to match PROD again, use the sync flow instead of direct database surgery where possible. The reseed path prunes stale dashboards and folders through the Grafana API, then reimports the repo baseline.
