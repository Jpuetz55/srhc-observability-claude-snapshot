# Script Catalog

This directory contains the operational entry points behind the repository’s
Make targets, deployment workflow, local service installers, and repository
checks. Prefer a documented `make` target for ordinary work. Invoke a script
directly only when a runbook names it or when diagnosing that script itself.

## Operating rule

The repository is a **collector-host observability and evidence platform**, not
a generic dashboard bundle. Scripts therefore fall into three different roles:

1. **Promotion and validation**: make the repo-managed local services and the
   two provisioned dashboards consistent.
2. **Evidence preparation**: parse files that an operator has already staged or
   downloaded through a read-only API.
3. **Investigation support**: generate command packages, session manifests,
   reports, database loads, and archives. These scripts do not connect to or
   execute commands on a WLC.

The canonical interfaces are in `Makefile`; use `make help` and the linked
runbooks in `docs/` before executing an installer on a production collector.

## Promotion and repository checks

| Script | Purpose |
| --- | --- |
| `pipeline.sh` | Routes `validate`, `plan`, and `deploy` through the supported promotion flow. |
| `preflight.sh` | Runs the repository validation gate before deployment/release. |
| `promote_repo_to_prod.sh` | Converges repo-managed Prometheus, Mimir, Grafana, datasource, dashboard, and eligible collector configuration. |
| `release.sh` | Exports reviewed DEV dashboard changes, commits them, and promotes the repository state. |
| `status.sh` | Compares DEV, repository, and PROD dashboard state without writing. |
| `sync_prod_to_dev.sh`, `seed_dev_from_files.sh` | Reseed the editable DEV environment from the repository/PROD baseline. |
| `check_dashboards.py` | Validates dashboard JSON structure. |
| `check_dashboard_inventory.py` | Enforces the intentionally small current dashboard inventory. |
| `check_dashboard_metric_contract.py` | Compares dashboard PromQL references to the metric contract. |
| `check_contract_schema.py` | Validates the metric-contract document structure. |
| `check_metric_name_overlap.py` | Detects conflicting metric-family ownership. |

`check_topology_dashboard.py` and `audit_vocera_dashboard.py` are retained
validation/audit utilities for optional dashboard work. They do **not** mean a
Topology or legacy Vocera badge dashboard is currently provisioned.

## Local service and collector installers

| Script | Purpose |
| --- | --- |
| `install_mimir_local_vm.sh` | Installs/configures the single-node local Mimir service. |
| `install_network_topology_postgres.sh` | Installs the topology PostgreSQL service on the collector. |
| `install_vocera_media_qoe_postgres.sh` | Installs the Media QoE PostgreSQL service. |
| `install_vocera_media_qoe_textfile.sh` | Installs the local generic media-PCAP textfile publisher; its scan excludes WLC session/attempt package roots. |
| `install_vocera_wlc_session_ingest.sh` | Installs the localhost Study Web trigger and optional one-minute timer that imports stable WLC EPC session SCP uploads. Enable only after the Phase 0 rehearsal runbook passes. |
| `install_vocera_iperf_qoe_textfile.sh` | Installs the iperf QoE textfile publisher. |
| `install_vocera_rf_validation_postgres.sh` | Installs RF-validation PostgreSQL support when invoked through the matching Make target. |
| `install_wireless_rf_textfile.sh` | Installs the parser-only WLC RF evidence textfile timer. |
| `install_wireless_rf_hourly.sh` | Retained optional installer for the separately configured collection workflow; do not enable it merely because the unit exists. |
| `install_path_probe_textfile.sh` | Installs a bounded synthetic path-probe timer after a real target config is supplied. |

Read the systemd unit and `/etc/default/...` file created by an installer before
enabling a timer. A timer parses or publishes staged evidence; it is not
permission to create a new capture or contact a WLC.

## Evidence and study support

- `run_vocera_media_qoe_textfile.sh` parses staged local PCAPs, writes parser
  outputs and a run archive, and can load Media QoE history into PostgreSQL.
- `run_vocera_survey_refresh.sh` is an older bundled survey-refresh helper.
  The Study Web workflow is the primary operator interface for new RF studies;
  use this script only when its documented input contract fits the task.
- `rollback_vocera_survey_refresh.sh` rolls back one bundled survey-refresh job.
- `publish_dnac_topology.py` publishes read-only Catalyst Center topology data
  into the canonical topology files; loading is a separate step.
- `topology_psql_in_container.sh`, `vocera_media_qoe_psql_in_container.sh`, and
  `vocera_rf_validation_psql_in_container.sh` provide containerized `psql`
  access when a host client is absent.
- `verify_wireless_rf_cli_parse.py`, `wireless_rf_smoke_test.sh`, and
  `wireless_rf_status.sh` validate the manual WLC CLI evidence parser path.

The WLC capture-session and short-attempt workflows live mainly in
`tools/vocera_media_qoe/`. Their Make targets generate packages, command sheets,
manifests, and reports. The long-session importer is triggered only through the
local Study Web endpoint by `run_vocera_wlc_session_ingest.sh`; it validates and
parses a stable file that the WLC has already SCP-pushed. None of these scripts
automate WLC login, capture creation, export, or SCP password handling.

## Tests and shared libraries

`test_*.py` scripts are dependency-light repository checks run by `make test`.
The small internal `tools/common/` package centralizes reusable config,
dashboard, file, and Prometheus rendering helpers. Domain-specific parser and
data-model logic remains in its own tool package.

## Field bundle

`vocera_iperf_laptop_roles_v5/` is a field bundle for two Windows laptop probes,
a Linux iperf endpoint, and collector-side SCP ingest. It is intentionally kept
as a self-contained operator bundle rather than imported as a service library.
