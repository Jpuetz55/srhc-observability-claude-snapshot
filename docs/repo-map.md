# Repo map

This map explains ownership boundaries and where to start reading before making
changes. For end-to-end flow, use `docs/codebase-walkthrough.md`.

## Control Plane

- `.github/workflows/`: CI entrypoints for repo validation.
- `Makefile`: stable operator API. Prefer adding targets here instead of
  documenting ad hoc commands.
- `scripts/`: validation, export, promotion, sync, installer, rollback, and
  collector orchestration helpers. See `scripts/README.md`.
- `scripts/lib/`: shared shell libraries for repo paths, Grafana credentials,
  and Python selection.
- `docs/`: architecture, runbooks, measurement semantics, and maintainer
  walkthroughs.

## Runtime Definitions

- `grafana/`: dashboard JSON and Grafana provisioning files. PROD dashboards are
  provisioned from this tree.
- `prometheus/`: scrape config and recording rules. Recording rules form most
  of the dashboard-facing metric surface.
- `contracts/`: lightweight metric contract used to catch dashboard/rule drift.
- `mimir/`: local single-node Mimir config and systemd unit.
- `systemd/`: standalone VM service and timer units installed by scripts or
  deploy promotion.
- `systemd-overrides/`: targeted runtime unit overrides.
- `deploy/k8s/`: minimal Kustomize structure for dev/prod Kubernetes examples.

## Source-Specific Tools

- `tools/wireless_rf/`: Cisco WLC RF parser, Catalyst Center collectors, badge
  client parser, and optional Streamlit review UIs.
- `tools/path_probe/`: synthetic RTT, delay-variation, and loss probe
  implementation.
- `tools/vocera_iperf_qoe/`: parser and textfile renderer for laptop iperf
  uploads.
- `tools/vocera_media_qoe/`: pcap analyzer, Catalyst Center ICAP downloader,
  batch publisher, PostgreSQL SQL exporter, and run-archive helper.
- `tools/vocera_rf_validation/`: badge diagnostic parser, Ekahau importer,
  badge/Ekahau correlator, SQL exporter, and run-archive helper.
- `tools/dnac_topology_bridge/`: staging helper for transforming DNAC raw export
  into the sibling `Network-Topology` repo's canonical CSV shape.

## Data And Database Contracts

- `data/`: local generated outputs and parser caches. Raw operational output and
  site-specific generated artifacts should not be committed.
- `sql/`: PostgreSQL schema/views for Vocera media QoE and RF validation
  datasources.
- `topology/postgres/`: PostgreSQL schema/views for the Network Topology Node
  Graph datasource.
- `topology/sql/`: topology SQL helpers and dashboard-facing queries.
- `tests/fixtures/`: small committed fixtures that make parser tests stable.

## Read Order For New Maintainers

1. `README.md`
2. `docs/architecture.md`
3. `docs/codebase-walkthrough.md`
4. `scripts/README.md`
5. The README or runbook for the source-specific area you are changing
6. The matching `scripts/test_*.py` file before editing parser behavior
