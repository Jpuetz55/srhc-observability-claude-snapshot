# Getting started on the collectors VM

This guide is for a maintainer/operator working from the current repository checkout.
It does not replace host build procedures, the WLC change process, or Catalyst
Center administration.

## 1. Confirm the source line and orient safely

```bash
cd /path/to/srhc-observability-claude-snapshot
git remote -v
git branch --show-current
git status --short
make help
```

Treat the repository's reviewed `main` branch and tags as canonical. Read before
changing runtime services:

- `docs/architecture.md`
- `docs/cicd.md`
- `docs/wlc-mdt-telemetry.md`
- `docs/study-workflow-web-ui.md`
- `secrets/README.md`

Do not run `sudo make deploy`. Use the normal operator account; scripts elevate
only when they need to install files or restart services.

## 2. Validate the checkout

```bash
make test
make validate
```

`make test` checks dashboard inventory, contracts, parser/unit tests, and
source-only behavior. `make validate` runs promotion preflight. Neither should
change Grafana, Prometheus, Mimir, WLC configuration, or raw evidence.

For a strict dashboard metric-contract check:

```bash
ENFORCE_DASHBOARD_METRIC_CONTRACT=1 make validate
```

## 3. Inspect the runtime before changing it

```bash
systemctl status grafana-server prometheus mimir --no-pager -l
curl -fsS http://127.0.0.1:9009/ready
curl -fsS http://127.0.0.1:3000/api/health
curl -fsS http://127.0.0.1:9090/-/ready

systemctl status vocera-rf-validation-study-web --no-pager -l
curl -fsS http://127.0.0.1:8097/healthz
```

Use `docs/wlc-mdt-telemetry.md` for WLC dial-out diagnostics. A failed optional
datasource or Study service does not by itself prove the Grafana/Prometheus/Mimir
metric path is unhealthy; check each lane independently.

## 4. Plan or deploy a canonical source change

```bash
make plan
make deploy
```

`make plan` previews promotion after preflight. `make deploy` converges
repository-managed Prometheus, Mimir, Grafana, provisioning, and configured
collector services on this host. The expected lifecycle is:

```text
DEV dashboard edit -> export to feature branch -> validate -> reviewed merge -> pull main -> plan -> deploy
```

## 5. Use the correct evidence workflow

- **WLC control-plane metrics:** validate WLC dial-out, Telegraf exposition, and
  Prometheus rules; do not collect CLI merely to troubleshoot a transport panel.
- **RF validation:** use Study Web Projects/Studies as the primary workflow.
- **Intermittent Vocera broadcast:** use the manual WLC EPC session runbook;
  never Catalyst Center Command Runner.
- **Completed ICAP:** list/download only after an approved capture exists; this
  repository cannot start a capture.
- **Iperf:** upload completed probe JSON to the controlled incoming tree; the
  publisher produces node-exporter metrics.

## 6. Data and secrets

```text
Git:       source, templates, documentation, approved encrypted material only
/var/lib:  raw captures, uploads, databases, runtime state
/etc:      root-owned materialized service secrets/configuration
data/:     ignored generated parser/report outputs when used
```

A sanitized clone contains no live secrets. Never commit PCAPs, terminal
transcripts, credentials, decrypted secret files, database data,
`web/study-ui/node_modules/`, or built Study Web static assets.
