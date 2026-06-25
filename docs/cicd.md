# CI/CD and local promotion

## Ownership model

```text
editable DEV Grafana -> repository branch/PR -> validation -> reviewed main -> local PROD convergence
```

- **DEV** is the editable dashboard workspace.
- **`main`** and reviewed tags are the canonical source for PROD dashboards,
  rules, provisioning, service units, installers, and documentation.
- **PROD** is file-provisioned and is not the place for durable UI edits.
- The dashboard inventory is intentionally enforced. Adding JSON alone is not a
  release: update the inventory/checks, metric contract, and docs in the same
  change when a new dashboard is intended.

## Routine dashboard change

```bash
# Start from current main and create a focused branch.
git switch main
git pull --ff-only origin main
git switch -c feature/dashboard-change

# Export intentional DEV changes, then review them.
make release MSG="describe the dashboard change"
git status

# Validate and commit the branch.
make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
git add grafana/ docs/ contracts/ prometheus/
git commit -m "feat: describe dashboard change"
git push -u origin feature/dashboard-change
```

Open, review, and merge the branch through the repository's normal pull-request
or review process. `make release` is a local export/promotion action; it does
not replace the commit/review decision and it does not push source for you.

## Controlled local runtime promotion

After the reviewed source change is available in the collector checkout:

```bash
git switch main
git pull --ff-only origin main
make test
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
make plan
make deploy
```

- `make test` runs source/unit checks.
- `make validate` runs deployment preflight.
- `make plan` runs preflight plus a non-destructive promotion preview.
- `make deploy` converges repository-managed runtime files and restarts/reloads
  only affected local services.

`make deploy` does not log into a WLC, change WLC/MDT certificates, run device
commands, or move raw investigation artifacts.

## DEV reseed

When DEV drifts or accumulates stale folders, reseed it from the
repository-managed PROD baseline rather than editing Grafana's SQLite database:

```bash
make status
make dashboard-sync-prod-to-dev
```

This is a write operation against the editable DEV org.

## CI scope

The checked-in CI workflows validate repository changes. Continue to run local
`make test` and `make validate` on the collector for runtime-specific checks
until a protected runner is deliberately installed. A green source check does
not prove host service state, credentials, WLC connectivity, or evidence
quality.

## Rollback boundaries

- **Dashboard/rules/runtime:** revert the reviewed source change, validate,
  plan, and deploy the revert.
- **RF/media investigation data:** use source-specific study/archive/database
  recovery. `git revert` is not an evidence-data rollback.
- **WLC capture:** stop/export/clean up the controller capture explicitly and
  use the WLC recovery runbook.
