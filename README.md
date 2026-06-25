# Collectors VM Observability and Wireless Evidence

This repository is the source of truth for the observability services
and operator workflows that run on the collectors VM. It is **not** a generic
Kubernetes monitoring starter. The live platform combines Grafana, Prometheus,
a local single-node Mimir, Cisco Catalyst 9800 model-driven telemetry (MDT),
node-exporter textfile metrics, local PostgreSQL investigation stores, and the
collector-hosted Study Workflow web application.

The repository deliberately separates two kinds of information:

1. **Metrics/control plane** — low-cardinality WLC and host metrics, Prometheus
   recording rules, Mimir, Grafana provisioning, and validation gates.
2. **Evidence/investigation plane** — WLC CLI/EPC artifacts, completed Catalyst
   Center ICAP downloads, badge/Ekahau studies, PCAP parser outputs, iperf JSON,
   topology imports, and PostgreSQL lineage.

## Runtime in brief

```text
Catalyst 9800 WLC
  -- gRPC dial-out + mTLS --> Telegraf MDT listener on collectors01:57000
  -- Telegraf Prometheus exposition --> 127.0.0.1:9273

node_exporter textfiles (RF / media parser / iperf / path probe)
  --> 127.0.0.1:9100

Telegraf + node_exporter + Mimir self-metrics
  --> Prometheus :9090 (scrape + recording rules)
  --> local Mimir :9009 (remote_write allowlist)
  --> Grafana :3000 (PromQL through Mimir)

Study Workflow :8097
  --> RF Validation PostgreSQL :15433
  --> Media QoE PostgreSQL :15434

Network-Topology published CSV
  --> Topology PostgreSQL :15432
```

The tested Grafana inventory is intentionally small:

- **WLC Control Plane**
- **Vocera Iperf QoE**

The repository also contains RF validation, media QoE, topology, and path-probe
parsers and data sources. Their presence does **not** mean a matching Grafana
dashboard is currently provisioned. `make test` enforces the dashboard
inventory.

## Operational boundaries

- The WLC is the source of live telemetry and packet evidence. This repository
  does not deploy WLC configuration, certificates, or MDT subscriptions.
- A WLC EPC is an **operator-run CLI workflow**. Study Web creates command
  sheets and preserves session evidence; it does not SSH to the WLC, retain WLC
  credentials, or invoke Catalyst Center Command Runner.
- A finalized WLC EPC is SCP-pushed by the WLC to a session-specific
  `incoming/` directory. The optional local ingest timer validates, hashes,
  promotes, registers, and parses the stable file without making it part of the
  generic ICAP scan path.
- Catalyst Center integration is read-only. It may list/download **completed**
  ICAP captures and read topology/client data; it cannot start a capture, change
  settings, or run device commands.
- Prometheus is the active scrape and rule-evaluation engine. Mimir is the local
  long-retention PromQL backend. PostgreSQL retains detailed evidence that would
  be unsafe as Prometheus label cardinality.
- Raw captures, transcripts, runtime databases, uploads, generated artifacts,
  and secret material are operational data. They do not belong in Git.

## Start here

| Need | Read or run |
| --- | --- |
| Understand installed components, ports, data stores, and boundaries | [`docs/architecture.md`](docs/architecture.md) |
| Verify the WLC MDT → Telegraf → Prometheus path | [`docs/wlc-mdt-telemetry.md`](docs/wlc-mdt-telemetry.md) |
| Use Study Web for RF, ICAP, or WLC capture-session work | [`docs/study-workflow-web-ui.md`](docs/study-workflow-web-ui.md) |
| Reproduce intermittent V5000 → C1000 multicast failures | [`docs/wireless/vocera-wlc-continuous-capture-runbook.md`](docs/wireless/vocera-wlc-continuous-capture-runbook.md) |
| Rehearse the automatic WLC EPC session ingest before enabling it | [`docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md`](docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md) |
| Handle completed Catalyst Center ICAP PCAPs | [`docs/wireless/vocera-media-dnac-icap-runbook.md`](docs/wireless/vocera-media-dnac-icap-runbook.md) |
| Promote Grafana/rules/runtime configuration | [`docs/cicd.md`](docs/cicd.md) |
| Follow the repository branch and validation workflow | [`docs/private-git-workflow.md`](docs/private-git-workflow.md) |
| Find a component or service | [`docs/repo-map.md`](docs/repo-map.md) |

## Safe first commands

Run from the current checkout as the normal operator account:

```bash
make help
make test
make validate
make plan
```

`make test` and `make validate` are repository checks. `make plan` runs the
promotion logic in dry-run mode. `make deploy` changes local runtime only after
preflight succeeds. Read [`docs/cicd.md`](docs/cicd.md) before using `make
release`, `make deploy`, or `make dashboard-sync-prod-to-dev`.

## Source-control policy

Treat this repository's reviewed `main` branch and tags as the source of truth.
Use focused branches, validation, and a reviewed merge before changing the
collector runtime. Repository hosting or remote changes are separate operational
work, not part of an application, evidence, or dashboard change. See
[`docs/private-git-workflow.md`](docs/private-git-workflow.md).

## Repository map

- `grafana/` — DEV/PROD dashboard JSON and Grafana provisioning
- `prometheus/` — scrape configuration and recording rules
- `mimir/` — local single-node Mimir configuration and unit
- `systemd/` — collector services and timers
- `scripts/` — validation, promotion, installers, and operator wrappers
- `tools/` — source-specific parsers and Study Workflow backend
- `web/study-ui/` — React/TypeScript Study Workflow frontend
- `sql/` and `topology/postgres/` — PostgreSQL schemas and views
- `config/` — committed non-secret defaults and examples
- `secrets/` — templates and secret-materialization tooling; never live values
- `docs/` — maintained architecture, runbooks, and audit record
