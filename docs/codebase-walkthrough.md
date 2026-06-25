# Codebase walkthrough

## Mental model

The repository is one control plane with several source-specific evidence
modules:

```text
repo source
  -> validation + promotion
  -> Grafana / Prometheus / Mimir / service configuration

source-specific evidence
  -> parser or Study Workflow
  -> low-cardinality .prom snapshot and/or detailed PostgreSQL history
  -> investigation UI/run archive
```

The current operating center is the collectors VM, not a Kubernetes deployment.
Kubernetes/Kustomize files remain scaffolding and are validated separately;
they are not the primary runtime described by the WLC/RF/QoE workflows.

## Primary entry points

| Entry point | Use it for |
| --- | --- |
| `Makefile` | stable operator command surface; start with `make help` |
| `scripts/pipeline.sh` | `make validate`, `make plan`, `make deploy` dispatcher |
| `scripts/promote_repo_to_prod.sh` | repo-to-local-runtime convergence, no DEV export or Git mutation |
| `scripts/release.sh` | intentional DEV dashboard export/release sequence |
| `tools/study_web/main.py` | FastAPI workflow/API application on port 8097 |
| `web/study-ui/` | React Study Workflow user interface |
| `tools/vocera_media_qoe/` | PCAP, ICAP, WLC session, and evidence-ledger tools |
| `tools/vocera_rf_validation/` | badge/Ekahau parsing, alignment, manual entry, and SQL export |

## Metric path

1. The WLC dials out over mTLS to Telegraf.
2. Prometheus scrapes Telegraf (`:9273`), node_exporter (`:9100`), and Mimir.
3. Rules under `prometheus/rules/` convert source metrics into stable
   `wireless_*`, `vocera_*`, and `platform_*` metrics.
4. Prometheus remote-writes the allowlisted metric surface to Mimir (`:9009`).
5. Grafana queries Mimir and selected local PostgreSQL datasources.

See `docs/wlc-mdt-telemetry.md` for telemetry transport and validation.

## Evidence modules

### Study Workflow (`tools/study_web` + `web/study-ui`)

The web app models **Projects → Studies → runs/samples/results** for RF
validation. It also provides two intentionally separate media paths:

- **ICAP QoE:** completed read-only Catalyst Center capture download/local PCAP
  registration and parsing.
- **Vocera multicast:** manual WLC EPC capture sessions, generated command
  sheets, event markers, attempt outcomes, final SCP export registration, and
  evidence tracking.

The app does not control a WLC. Its API functions call local parsers and
PostgreSQL helpers only after input validation and configured execution guards.

### Media QoE (`tools/vocera_media_qoe`)

- `vocera_media_qoe.py` parses one PCAP.
- `vocera_media_qoe_batch.py` scans/normalizes eligible generic raw captures.
- `vocera_dnac_icap.py` reads completed ICAP files through a read-only client.
- `vocera_wlc_session.py` creates/updates long-lived manual EPC session
  packages.
- `vocera_wlc_attempt.py` remains for legacy short attempt bundles.
- `vocera_wlc_evidence.py` and `vocera_wlc_cli.py` normalize CLI evidence into
  a structured ledger.

The generic batch path deliberately excludes WLC session/attempt trees.

### RF validation (`tools/vocera_rf_validation`)

The command-line tools parse badge diagnostic input, inspect/import Ekahau
source timing/location, create manual value templates, correlate samples, and
emit PostgreSQL SQL. The web app is the canonical UI; the CLI remains useful
for test, troubleshooting, and controlled batch work.

### Iperf and path probes

- `tools/vocera_iperf_qoe/` reads completed uploaded iperf JSON and writes a
  node-exporter textfile. The tracked **Vocera Iperf QoE** dashboard consumes
  this metric family.
- `tools/path_probe/` publishes bounded synthetic RTT/loss/variation metrics.
  These are round-trip probes, not RTP jitter or one-way media latency.

### Retained RF parser (`tools/wireless_rf`)

This parses staged WLC CLI RF/traffic-distribution evidence. It does not
collect via Catalyst Center Command Runner and is not currently a provisioned
dashboard path.

## Data stores and artifacts

| Artifact | Location | Reason |
| --- | --- | --- |
| local metric diagnostics | Prometheus local TSDB | scrape/rule troubleshooting |
| longer metric query store | Mimir filesystem store | Grafana PromQL history |
| RF validation detail | PostgreSQL `:15433` | study/run/sample analysis |
| media capture/stream detail | PostgreSQL `:15434` | capture-time evidence and parser history |
| topology node/edge rows | PostgreSQL `:15432` | datasource contract for future/current topology visualizations |
| raw evidence | `/var/lib/...` | sensitive operational material |
| generated reports/archives | ignored `data/` paths | reproducibility without Git bloat |

## Where changes belong

- New dashboard/rule: `grafana/`, `prometheus/rules/`, contract, inventory test,
  and documentation together.
- New source-specific parser behavior: module README, source runbook, tests,
  and artifact/schema docs together.
- New Study Web behavior: backend route, frontend client/page/component,
  service/config docs, and database migration contract together.
- New WLC automation request: first decide whether it violates the explicit
  manual/read-only boundary. Do not hide a controller-affecting action in a
  parser or web endpoint.

## Tests and validation

`make test` is the source test suite. `make validate` is the deployment
preflight. `make plan` is the required dry-run before local promotion. For
sensitive data-path work, also inspect generated JSON/SQL/.prom outputs and the
relevant PostgreSQL rows; source tests cannot prove a live WLC or Catalyst
Center transport path.
