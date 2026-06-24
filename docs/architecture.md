# Architecture Overview

This repo is the source of truth for Grafana dashboards, Prometheus rules,
metric contracts, deployment helpers, and the optional Cisco wireless RF
observability extension. Runtime systems collect and store telemetry; the repo
defines how that telemetry is normalized, validated, visualized, and promoted.

## System Context

```mermaid
flowchart LR
  repo["Git repo\nDashboards, rules, contracts, scripts"]
  grafana_dev["Grafana DEV\nEditable dashboards"]
  grafana_prod["Grafana PROD\nProvisioned dashboards"]
  prometheus["Prometheus\nScrape, 30-day retention, rule evaluation"]
  mimir["Mimir\nLonger-term metrics backend"]
  platform["Platform exporters\nKubernetes, node_exporter, Telegraf"]
    wireless["Wireless collectors\nWLC CLI, Catalyst Center, badge client jobs, path probes"]

  platform --> prometheus
  wireless --> prometheus
  prometheus -->|remote_write| mimir
  grafana_dev -->|queries| mimir
  grafana_prod -->|queries| mimir

  grafana_dev -->|export| repo
  repo -->|validate and promote| grafana_prod
  repo -->|provision rules and config| prometheus
  repo -->|provision datasource and dashboards| grafana_prod
```

## Runtime Deployment Topology

The single-VM profile keeps collection, rule evaluation, storage, and
visualization on the collectors host. Optional collectors publish normalized
textfiles or scrape targets; Prometheus records and remote-writes the curated
metric surface into Mimir; Grafana reads from Mimir and the topology/RF
PostgreSQL datasources.

```mermaid
flowchart TB
  subgraph external["External evidence sources"]
    k8s["Kubernetes clusters"]
    wlc["Cisco WLCs"]
    dnac["Catalyst Center"]
    ekahau["Ekahau exports"]
    pcaps["Vocera media pcaps"]
    wlc_attempts["Manual WLC capture sessions\nEvent markers + EPC ring pcaps"]
    laptops["Vocera iperf laptops"]
  end

  subgraph vm["Collectors VM"]
    subgraph timers["systemd timers and services"]
      rf_timer["wireless-rf timers"]
      badge_timer["badge-client timer"]
      path_timer["path-probe timer"]
      media_timer["media QoE timer"]
      iperf_timer["iperf QoE timer"]
    end

    textfiles["node_exporter textfile collector"]
    prometheus["Prometheus\nscrape, rules, 30d/300GB local TSDB"]
    mimir["Mimir\nlonger-term PromQL API"]
    grafana["Grafana\nDEV and PROD orgs"]
    topology_db["Topology PostgreSQL"]
    rf_validation_db["RF validation PostgreSQL"]
  end

  k8s --> prometheus
  wlc --> rf_timer
  dnac --> rf_timer
  dnac --> badge_timer
  dnac --> topology_db
  ekahau --> rf_validation_db
  pcaps --> media_timer
  wlc_attempts --> media_timer
  laptops --> iperf_timer
  rf_timer --> textfiles
  badge_timer --> textfiles
  path_timer --> textfiles
  media_timer --> textfiles
  iperf_timer --> textfiles
  textfiles --> prometheus
  prometheus -->|remote_write allowlist| mimir
  grafana -->|PromQL| mimir
  grafana -->|SQL| topology_db
  grafana -->|SQL| rf_validation_db
```

## Runtime Metric Flow

Prometheus is the active scrape and rule-evaluation layer. Mimir is the query
backend that Grafana uses for dashboards. Local Prometheus retention is capped
at 30 days/300GB so it behaves like an evaluation buffer, not the durable
metrics store.

```mermaid
flowchart TD
  subgraph sources["Telemetry sources"]
    kube["Kubernetes and platform metrics"]
    node["node_exporter textfile metrics"]
    telegraf["Telegraf Cisco MDT scrape"]
    wlc["Generated wireless RF .prom files"]
  end

  subgraph prom["Prometheus"]
    scrape["Scrape targets"]
    rules["Recording rules"]
    contract["Metric contract checks"]
  end

  subgraph storage["Metrics storage and query"]
    local_tsdb["30-day local TSDB"]
    mimir["Local Mimir\n/prometheus API"]
  end

  subgraph grafana["Grafana"]
    dashboards["Provisioned and editable dashboards"]
    alerts["Managed alerting rules"]
  end

  kube --> scrape
  node --> scrape
  telegraf --> scrape
  wlc --> scrape
  scrape --> local_tsdb
  scrape --> rules
  rules --> local_tsdb
  local_tsdb -->|remote_write allowlist| mimir
  contract -. "validates names" .-> rules
  dashboards -->|PromQL| mimir
  alerts -->|PromQL| mimir
```

## Dashboard Promotion Flow

Production Grafana content is intentionally Git-backed and provisioned. DEV is
editable for iteration; PROD is converged from files after validation.

```mermaid
sequenceDiagram
  participant Operator
  participant Dev as Grafana DEV
  participant Repo as Git repo
  participant Checks as Validation scripts
  participant Prod as Grafana PROD

  Operator->>Dev: Edit dashboards
  Operator->>Repo: Export DEV dashboards
  Repo->>Checks: Validate JSON, metrics, rules, contracts
  Checks-->>Repo: Pass or fail
  Repo->>Prod: Promote provisioned dashboards, rules, datasource config
  Prod-->>Operator: Locked-down dashboard baseline
```

## Repository Control Plane

The repo is the control plane for promotion. `Makefile` exposes stable operator
commands; scripts hold the implementation; shared libraries keep path and
credential lookup consistent across export, validation, promotion, and status
operations.

```mermaid
flowchart LR
  operator["Operator or CI"]
  make["Makefile targets"]
  pipeline["scripts/pipeline.sh"]
  preflight["scripts/preflight.sh"]
  promote["scripts/promote_repo_to_prod.sh"]
  export["scripts/export_dashboards.sh"]
  status["scripts/status.sh"]
  libs["scripts/lib\npaths, Grafana auth, Python"]

  repo_state["Repo state\ndashboards, rules, datasources, systemd overrides"]
  runtime["Runtime host\n/etc, /var/lib/grafana, systemd"]
  grafana_api["Grafana API"]
  prom_api["Prometheus/Mimir APIs"]

  operator --> make
  make --> pipeline
  make --> export
  make --> status
  pipeline --> preflight
  pipeline --> promote
  preflight --> repo_state
  export --> grafana_api
  promote --> repo_state
  promote --> runtime
  promote --> grafana_api
  status --> repo_state
  status --> grafana_api
  status --> prom_api
  libs -. "sourced by" .-> export
  libs -. "sourced by" .-> promote
  libs -. "sourced by" .-> status
```

## Validation Gate Detail

Validation is intentionally layered. Fast local checks catch malformed JSON and
metric-contract drift before promotion touches Grafana, Prometheus, or systemd.

```mermaid
flowchart TD
  start["make validate or deploy"]
  dashboard_json["Dashboard JSON checks"]
  topology_shape["Topology dashboard shape"]
  metric_contract["Metric contract schema"]
  promql_refs["Dashboard PromQL metric references"]
  metric_overlap["Metric name overlap checks"]
  prom_rules["Prometheus config and rule syntax"]
  tests["Collector and parser smoke tests"]
  pass["Promotion allowed"]
  fail["Stop with file-specific diagnostics"]

  start --> dashboard_json
  dashboard_json --> topology_shape
  topology_shape --> metric_contract
  metric_contract --> promql_refs
  promql_refs --> metric_overlap
  metric_overlap --> prom_rules
  prom_rules --> tests
  tests --> pass
  dashboard_json -. failure .-> fail
  topology_shape -. failure .-> fail
  promql_refs -. failure .-> fail
  metric_overlap -. failure .-> fail
  prom_rules -. failure .-> fail
  tests -. failure .-> fail
```

## Wireless Extension Flow

The wireless extension is optional and source-specific. It does not change the
core Grafana/Mimir workflow; it adds WLC and badge telemetry as another metric
producer.

```mermaid
flowchart LR
  subgraph evidence["Wireless evidence"]
    cli["WLC CLI output\nAP RF and traffic distribution"]
    mdt["Cisco MDT client/AP metrics"]
    dnac["Catalyst Center API\nbadge client detail"]
    probe_targets["Path probe targets\nAPs, WLCs, badges, servers"]
    media_pcaps["Vocera media pcaps\nserver-side capture"]
  end

  subgraph tools["Repo-owned tools"]
    parser["tools/wireless_rf parser"]
    collector["Catalyst Center collector"]
    badge["Badge client collector"]
    path_probe["Path probe collector"]
    media_qoe["Vocera media QoE analyzer"]
    sqlite["SQLite history"]
    promfile["Prometheus exposition files"]
  end

  subgraph rules["Prometheus normalization"]
    rf_rules["RF and DFS rules"]
    voice_rules["AP voice AC latency rules"]
    badge_rules["Badge client RUN-state and FT rules"]
    path_metrics["Path RTT, delay variation, and loss metrics"]
    media_metrics["Vocera media QoE snapshot metrics"]
  end

  subgraph views["Grafana views"]
    rf_dash["AP RF drilldowns"]
    badge_dash["Vocera badge dashboard"]
  end

  cli --> parser
  dnac --> collector
  dnac --> badge
  probe_targets --> path_probe
  media_pcaps --> media_qoe
  parser --> sqlite
  parser --> promfile
  badge --> sqlite
  badge --> promfile
  path_probe --> promfile
  media_qoe --> promfile
  mdt --> rf_rules
  mdt --> badge_rules
  promfile --> rf_rules
  promfile --> voice_rules
  promfile --> path_metrics
  promfile --> media_metrics
  rf_rules --> rf_dash
  voice_rules --> badge_dash
  badge_rules --> badge_dash
  path_metrics --> badge_dash
  media_metrics --> badge_dash
```

## Source-Specific Parser Pattern

Every optional parser follows the same shape: source-specific raw evidence is
normalized once, low-cardinality metrics go to Prometheus/Mimir, and detailed
investigation state goes to files or SQL tables.

```mermaid
flowchart LR
  raw["Raw source evidence\nCLI, API JSON, pcap, zip, CSV"]
  parser["Parser module under tools/"]
  normalized["Normalized artifacts\nJSON, CSV, prom"]
  history["History store\nSQLite or PostgreSQL"]
  archive["Run archive ZIP\ninputs, outputs, manifest, log"]
  textfile["node_exporter textfile"]
  prometheus["Prometheus rules"]
  mimir["Mimir"]
  grafana["Grafana dashboard"]

  raw --> parser
  parser --> normalized
  parser --> archive
  normalized --> textfile
  normalized --> history
  textfile --> prometheus
  prometheus --> mimir
  mimir --> grafana
  history --> grafana
```

This boundary keeps dashboard labels stable while preserving raw-enough detail
for debugging and rollback.

## Semantic Boundaries

| Area | Owned by | Important boundary |
| --- | --- | --- |
| Dashboard JSON | `grafana/dashboards-*` | DEV exports are editable snapshots; PROD is provisioned from Git. |
| Datasources and alerting | `grafana/provisioning/` | Stable datasource UIDs are referenced by dashboards and alerting rules. |
| Prometheus scrape and rules | `prometheus/` | Recording rules are the dashboard-facing metric surface. |
| Metric contract | `contracts/metric_contract.yaml` | Dashboard PromQL should reference only known raw, recorded, or allowed external metrics. |
| Platform deploy helpers | `scripts/`, `systemd/`, `mimir/` | Scripts converge the VM runtime from repo state. |
| Kubernetes scaffold | `deploy/k8s/` | Minimal Kustomize structure for dev/prod overlays. |
| Wireless parser and collectors | `tools/wireless_rf/` | Source-specific producers; they emit normalized files and metrics for Prometheus. |
| Path probe collector | `tools/path_probe/` | Measures synthetic RTT, delay variation, and loss; WLC-to-AP probes are round-trip, not one-way AP-to-WLC latency or RTP jitter. |
| Vocera media QoE analyzer | `tools/vocera_media_qoe/` | Offline pcap analyzer for server-side observed media quality; exact stream identity stays in JSON, not Prometheus labels. |
| Vocera WLC capture toolkit | `tools/vocera_media_qoe/vocera_wlc_*` | Manual WLC session-package generation, event markers, transcript parsing, artifact validation, attempt/session SQL, and conservative broadcast verdicts. |

## Wireless Latency Semantics

The dashboard intentionally keeps these concepts separate:

- AP voice access-category latency comes from WLC traffic-distribution CLI
  evidence and is recorded as `wireless_ap_voice_latency_*`.
- Client RUN-state latency comes from Cisco MDT client mobility history and is
  recorded as `wireless_badge_client_run_state_latency_*`.
- Legacy roam-duration compatibility metrics are sourced from the same
  RUN-state latency field and should not be presented as voice handoff
  interruption, RTP latency, or AP-to-client latency.
- Path probe latency is active RTT telemetry between infrastructure endpoints.
  It should not be mixed with AP voice access-category latency, client
  RUN-state latency, or badge media QoE.
- Badge-to-badge and badge-to-server latency/jitter require media-stream
  measurements, such as RTP/vRTP sequence, timestamp, and receiver-arrival
  analysis.

## Operational Responsibilities

```mermaid
flowchart TB
  change["Dashboard or rule change"]
  validate["Run validation\nmake validate / scripts/preflight.sh"]
  promote["Promote repo state\nmake deploy or release flow"]
  observe["Observe in Grafana\nquery Mimir"]
  debug["Debug sources\nPrometheus, textfiles, SQLite, raw WLC evidence"]

  change --> validate
  validate --> promote
  promote --> observe
  observe -->|panel is wrong or empty| debug
  debug --> change
```

## Where To Look Next

- `docs/cicd.md` explains dashboard export, validation, promotion, and DEV
  reseeding.
- `docs/local-mimir-vm.md` explains the local single-node Mimir profile.
- `docs/wireless-rf-observability.md` explains WLC RF parsing, badge metrics,
  and wireless dashboard semantics.
- `docs/repo-map.md` maps the main directories to their responsibilities.
