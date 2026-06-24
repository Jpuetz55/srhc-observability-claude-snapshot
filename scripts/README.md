# Script Catalog

This directory contains operator entrypoints, validation checks, deployment
helpers, and source-specific collection utilities. Prefer the `make` targets in
the repo root for routine work; call scripts directly only when the script usage
block or a runbook says to do so.

## Cleanup Rule

Keep scripts only when they are one of these:

- Called by `Makefile`, CI, `scripts/pipeline.sh`, or `scripts/promote_repo_to_prod.sh`.
- Documented as a manual operator tool in `docs/` or this catalog.
- Part of a self-contained field bundle, such as `vocera_iperf_laptop_roles_v5/`.

One-off dashboard patchers, local diagnostics, and temporary migration helpers
should live in an incident note or runbook, not as permanent repo scripts.

## Core Promotion

- `pipeline.sh` selects `validate`, `plan`, or `deploy` and routes to the
  canonical implementation.
- `preflight.sh` runs the local validation gate before deploy or release.
- `promote_repo_to_prod.sh` converges runtime Prometheus, Mimir, Grafana,
  datasource, dashboard, and optional collector state from the repo.
- `release.sh` exports DEV dashboards, commits them, and promotes the result.
- `status.sh` compares DEV, repo, and PROD dashboard state without writing.
- `sync_prod_to_dev.sh` and `seed_dev_from_files.sh` reseed editable DEV from
  the repo-managed PROD baseline.

## Dashboard And Contract Checks

- `check_dashboards.py` validates dashboard JSON and required dashboard fields.
- `check_dashboard_inventory.py` validates the intentional retained dashboard
  set.
- `check_topology_dashboard.py` validates the Network Topology dashboard shape
  when that dashboard is present.
- `check_contract_schema.py` validates the metric contract document structure.
- `check_dashboard_metric_contract.py` compares dashboard PromQL references to
  the metric contract.
- `check_metric_name_overlap.py` catches conflicting metric families.
- `audit_vocera_dashboard.py` queries Vocera dashboard panel expressions against
  Mimir for live panel-contract checks.

## Export And Runtime Installers

- `export_dashboards.sh` exports dashboards from Grafana through the API.
- `export_dev_db_to_repo.sh` stages DEV dashboard snapshots into the repo.
- `install_mimir_local_vm.sh` installs the local single-node Mimir service.
- `install_network_topology_postgres.sh` installs the local topology Postgres
  service used by the Network Topology dashboard.
- `install_wireless_rf_textfile.sh` installs the parser-only RF textfile timer.
- `install_wireless_rf_hourly.sh` installs the RF collect-and-publish timer.
- `install_wireless_badge_hourly.sh` installs badge-client collection on a
  timer.
- `install_path_probe_textfile.sh` installs the synthetic path probe timer.
- `install_vocera_media_qoe_textfile.sh` installs the media pcap QoE publisher.
- `install_vocera_media_qoe_postgres.sh` installs the local media QoE
  PostgreSQL history datasource.
- `vocera_media_qoe_psql_in_container.sh` runs `psql` inside that local media
  QoE PostgreSQL container.
- `vocera_media_qoe_data_audit.sh` runs the fixed read-only media QoE data-shape
  audit (project/capture/stream/classification/health views) for dashboard and
  UI design; wired as `make vocera-media-qoe-data-audit`.
- `install_vocera_iperf_qoe_textfile.sh` installs the iperf QoE publisher.

## Collector Utilities

- `publish_dnac_topology.py` publishes Catalyst Center topology CSVs for the
  Grafana Node Graph datasource.
- `run_vocera_media_qoe_textfile.sh` scans local media pcaps, parses captures
  missing a current cache entry, and publishes the newest capture textfile to
  node_exporter. It also emits PostgreSQL import SQL and can load capture-time
  history when `VOCERA_MEDIA_QOE_DATABASE_URL` is set. Each run writes a ZIP
  archive with inputs, outputs, `manifest.json`, and `logs/run.log`.
- `run_vocera_survey_refresh.sh` is the hard-coded SRHC operator workflow for
  the recurring Vocera survey: parse local ICAPs, publish media QoE `.prom`,
  parse the newest badge diagnostic archive, parse the Ekahau project,
  regenerate the RF validation JSON/CSV/SQL artifacts, and load RF validation
  SQL into PostgreSQL unless `VOCERA_SURVEY_RF_LOAD_DB=0`. The media and RF
  parser steps each emit their own ZIP run archive. Runs also write a job
  manifest under `data/vocera-rf-validation/out/jobs`.
- `rollback_vocera_survey_refresh.sh` rolls back one survey refresh run by run
  id: it removes RF validation rows, removes media QoE rows for pcaps uploaded
  with that job, and moves the uploaded bundle aside.
- `vocera_rf_validation/windows/Sync-RfValidationDataAndRun.ps1` is the
  Windows-side field script for uploading `C:\rf-validation-data\Pcaps`,
  `survey`, and `badge-log` contents to the collector and rerunning the
  validation parsers.
- `topology_psql_in_container.sh` runs `psql` inside the local topology Postgres
  container when the host does not have a direct client.
- `verify_wireless_rf_cli_parse.py` compares selected raw WLC CLI values to the
  generated Prometheus exposition output.
- `wireless_rf_smoke_test.sh` runs a scoped collect/parse/publish/query RF path
  test.
- `wireless_rf_status.sh` inspects collector timers, textfile artifacts, and
  Prometheus/Mimir query paths for RF metrics.

## Tests

The `test_*.py` scripts are lightweight repository tests run by `make test`.
They intentionally avoid a test framework dependency so validation can run on a
plain VM with Python available.

## Shared Libraries

- `lib/paths.sh` centralizes repo and runtime paths.
- `lib/grafana_auth.sh` centralizes Grafana token discovery.
- `lib/python.sh` and `python.sh` centralize the selected Python interpreter.

## Vocera Iperf Laptop Bundle

`vocera_iperf_laptop_roles_v5/` is a field bundle for two Windows laptop probes,
the Linux iperf server endpoint, and the collector SCP ingest directory. The
bundle is kept together even though individual helper scripts are not called by
repo automation.
