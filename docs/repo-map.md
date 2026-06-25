# Repository map

## Control plane and runtime configuration

| Path | Owns |
| --- | --- |
| `Makefile` | stable operator commands and default paths |
| `scripts/pipeline.sh` | validate/plan/deploy dispatcher |
| `scripts/preflight.sh` | deployment gate |
| `scripts/promote_repo_to_prod.sh` | local runtime convergence |
| `scripts/release.sh` | DEV export + validation + promotion orchestration |
| `scripts/lib/` | shared path, Grafana, configuration, and shell helpers |
| `grafana/` | DEV/PROD JSON and datasource/dashboard/alerting provisioning |
| `prometheus/` | scrape config and recording rules |
| `mimir/` | local single-node Mimir config and service unit |
| `systemd/` | collector service/timer templates |
| `systemd-overrides/` | Prometheus/Grafana runtime overrides and secret integration |

## Data plane, ports, and stores

| Path/service | Role |
| --- | --- |
| collector `:57000` | Telegraf MDT receiver for WLC gRPC/mTLS dial-out |
| `127.0.0.1:9273` | Telegraf Prometheus exposition |
| `127.0.0.1:9100` | node_exporter and textfile metrics |
| `127.0.0.1:9090` | Prometheus scrape/rule engine |
| `127.0.0.1:9009` | Mimir PromQL/read-write endpoint |
| `127.0.0.1:3000` | Grafana |
| `127.0.0.1:8097` | Study Workflow FastAPI/React application |
| `127.0.0.1:15432` | topology PostgreSQL |
| `127.0.0.1:15433` | RF validation PostgreSQL |
| `127.0.0.1:15434` | media QoE PostgreSQL |
| `/var/lib/node_exporter/textfile_collector/` | atomic `.prom` output |
| `/var/lib/vocera-media-qoe/raw/` | generic PCAP input plus managed WLC session/attempt packages |
| `/var/lib/vocera-iperf-qoe/incoming/` | uploaded laptop iperf JSON |
| `/var/lib/prometheus/local-tsdb` | Prometheus local evaluation buffer |
| `/var/lib/prometheus/mimir` | Mimir blocks/WAL/compactor data |

## Source-specific tools

| Path | Primary job |
| --- | --- |
| `tools/study_web/` | FastAPI API, Project/Study workflow, WLC session registration, artifact visibility |
| `web/study-ui/` | React + TypeScript + Vite + Tailwind UI |
| `tools/vocera_media_qoe/` | PCAP parser, batch publisher, ICAP read-only client, WLC session/attempt helpers, session importer |
| `tools/vocera_rf_validation/` | badge parser, Ekahau importer, correlation, manual-entry, SQL helpers |
| `tools/vocera_iperf_qoe/` | uploaded iperf JSON parser/textfile renderer |
| `tools/wireless_rf/` | retained manual WLC CLI RF evidence parser/report tool |
| `tools/path_probe/` | synthetic RTT, variation, and loss collector |
| `tools/dnac_topology_bridge/` | read-only Catalyst Center topology normalization support |
| `tools/common/` | shared file, config, dashboard, and Prometheus utilities |

## Database and schema contracts

- `sql/` — media QoE/RF validation tables and views.
- `topology/postgres/init/` — topology node/edge schema.
- `contracts/metric_contract.yaml` — dashboard/rule metric naming contract.
- `config/` — committed non-secret defaults/examples.
- `/etc/grafana-mimir-observability/secrets/` — materialized runtime secrets;
  never commit the output.

## Services/timers worth recognizing

| Unit | Meaning |
| --- | --- |
| `vocera-rf-validation-study-web.service` | Study UI/API |
| `vocera-media-qoe-wlc-session-ingest.timer` | optional automatic WLC EPC session ingestion after Phase 0 rehearsal |
| `vocera-media-qoe-textfile.timer` | generic media publisher; excludes WLC package roots |
| `vocera-iperf-qoe-textfile.timer` | laptop iperf metrics refresh |
| `wireless-path-probe.timer` | synthetic path probe refresh |
| `wireless-rf-textfile.timer` | RF evidence textfile refresh |

The installed unit/drop-in is authoritative for the actual repository path;
inspect it with `systemctl cat <unit>` before relocating/reinstalling services.

## Recommended reading order

1. `README.md`
2. `docs/architecture.md`
3. `docs/wlc-mdt-telemetry.md`
4. `docs/cicd.md`
5. `docs/study-workflow-web-ui.md`
6. the source-specific runbook
7. `scripts/README.md` and the exact Make target implementation
