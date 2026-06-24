# Python Toolkit Refactor Plan

This document is a roadmap for turning the repo's Python scripts from a set of
useful individual tools into a consistent internal toolkit. The intent is to
make scripts easier to run, test, extend, and reason about without changing
domain-specific parser behavior.

The repo already has useful structure under:

```text
tools/wireless_rf/
tools/vocera_rf_validation/
tools/vocera_media_qoe/
tools/vocera_iperf_qoe/
tools/path_probe/
scripts/
```

The main refactor opportunity is repeated infrastructure code: CLI parsing,
config loading, JSON/YAML/file handling, Prometheus metric rendering, SQLite
storage, run archives, Catalyst Center API interaction, dashboard traversal,
and validation output.

## Current Script Inventory

### Repo Validation Scripts

These protect the repo from broken dashboards, invalid metric references, and
bad topology dashboard configuration.

```text
scripts/check_dashboards.py
scripts/check_dashboard_metric_contract.py
scripts/check_contract_schema.py
scripts/check_metric_name_overlap.py
scripts/check_topology_dashboard.py
```

### Dashboard Audit and Mutation Scripts

These inspect or modify dashboard JSON and validate specific dashboard
behavior.

```text
scripts/audit_vocera_dashboard.py
scripts/update_vocera_retry_window_variable.py
scripts/verify_wireless_rf_cli_parse.py
```

### Deployment and Secrets Helpers

This code handles secret material installation and should stay conservative and
isolated.

```text
scripts/install_secrets.py
```

### Topology Tooling

These convert Catalyst Center/DNAC topology data into canonical node and edge
formats for Grafana.

```text
scripts/publish_dnac_topology.py
tools/dnac_topology_bridge/bridge_dnac_to_canonical.py
```

### Wireless RF Tooling

This is one of the more mature areas and already has a package-like structure.

```text
tools/wireless_rf/wireless_rf/cli.py
tools/wireless_rf/wireless_rf/parser.py
tools/wireless_rf/wireless_rf/dnac_client.py
tools/wireless_rf/wireless_rf/prometheus.py
tools/wireless_rf/wireless_rf/storage.py
tools/wireless_rf/wireless_rf/stats_engine.py
tools/wireless_rf/wireless_rf/client_*.py
```

### Vocera RF Validation

This package already has models, config, parser, DB, correlation, stats,
archive, and CLI modules.

```text
tools/vocera_rf_validation/
```

### Vocera Media QoE

This package handles packet capture/media analysis, DNAC ICAP capture
retrieval, batch processing, SQL/history output, and run archives.

```text
tools/vocera_media_qoe/
```

### Vocera Iperf QoE

This converts iperf result JSON into QoE metrics.

```text
tools/vocera_iperf_qoe/vocera_iperf_qoe.py
```

### Path Probe

This parses ping/probe output and emits metrics.

```text
tools/path_probe/path_probe.py
```

## Proposed Shared Package

Add a shared internal package:

```text
tools/common/
  __init__.py
  cli.py
  config.py
  files.py
  logging.py
  prometheus.py
  dashboard.py
  sqlite.py
  archive.py
  dnac.py
  time.py
  validation.py
```

The package should hold infrastructure concerns only. Domain parsers, schemas,
models, and business rules should stay in their domain packages.

### `tools/common/cli.py`

Purpose: standardize command-line behavior.

Common flags to support over time:

```text
--config
--env-file
--output
--prom-output
--json-output
--csv-output
--db
--verbose
--quiet
--dry-run
```

This prevents each tool from reinventing `argparse`.

### `tools/common/config.py`

Purpose: centralize config loading.

Should support:

```text
YAML
JSON
.env files
environment variables
defaults
required-value validation
```

This should replace repeated functions such as `load_env_file()`,
`env_value()`, `env_bool()`, `load_badge_config()`, and `load_config()`.

### `tools/common/files.py`

Purpose: safe file operations.

Shared helpers:

```text
read_text()
write_text_atomic()
read_json()
write_json()
read_yaml()
write_csv()
ensure_dir()
safe_path()
```

These matter because several scripts write `.prom`, JSON, CSV, SQL, archive,
and dashboard files.

### `tools/common/prometheus.py`

Purpose: one official way to render Prometheus textfile metrics.

Centralize:

```text
label escaping
metric line rendering
HELP/TYPE blocks
bool-to-int conversion
timestamp handling
NaN/null handling
```

Current duplication exists in:

```text
tools/wireless_rf/wireless_rf/prometheus.py
tools/wireless_rf/wireless_rf/client_prometheus.py
tools/path_probe/path_probe.py
tools/vocera_iperf_qoe/vocera_iperf_qoe.py
tools/vocera_media_qoe/
```

### `tools/common/sqlite.py`

Purpose: shared DB connection and migration helpers.

Use for:

```text
wireless_rf storage
badge client storage
vocera_rf_validation db
vocera_media_qoe history
topology publishing if SQLite is used later
```

Provide infrastructure helpers such as:

```python
connect_sqlite(path)
execute_schema(conn, schema)
upsert_rows(conn, table, rows)
```

Domain schemas and domain-specific inserts should remain local.

### `tools/common/archive.py`

Purpose: standard run archive layout.

Several tools create run artifacts. Standardize:

```text
run_id
timestamp
input files
raw output
parsed JSON
metrics output
summary JSON
errors/warnings
```

### `tools/common/dnac.py`

Purpose: shared Catalyst Center client.

The repo already has a wireless RF DNAC client, but Catalyst Center behavior is
also needed by topology publishing, media ICAP tooling, and badge/client
collection. The shared client should eventually own:

```text
authentication token handling
GET/POST helpers
SSL verification toggle
task polling
command runner
pagination
standard error handling
```

This is higher risk and should be migrated slowly.

### `tools/common/dashboard.py`

Purpose: shared Grafana dashboard JSON traversal.

Use for:

```text
scripts/check_dashboards.py
scripts/check_dashboard_metric_contract.py
scripts/audit_vocera_dashboard.py
scripts/check_topology_dashboard.py
scripts/update_vocera_retry_window_variable.py
```

Shared helpers:

```text
load_dashboard()
iter_panels()
iter_targets()
iter_variables()
iter_promql_exprs()
find_panels_by_title()
update_variable()
dashboard_uid()
dashboard_title()
```

### `tools/common/validation.py`

Purpose: consistent validator output.

Use a shared result object:

```python
ValidationIssue(
    severity="error|warning|info",
    file=...,
    location=...,
    message=...,
)
```

Every validator should be able to emit human-readable output, optional JSON
reports, and correct exit codes.

## Safe Refactor Order

Do not refactor everything at once. Each step should be behavior-preserving and
covered by tests before moving on.

### Step 1 - Add `tools/common/prometheus.py`

Why first: low risk and immediately useful.

Target helpers:

```python
def escape_label(value: object) -> str
def format_labels(labels: dict[str, object]) -> str
def emit_metric(name: str, labels: dict[str, object], value: object) -> str
def emit_help(name: str, text: str) -> str
def emit_type(name: str, metric_type: str) -> str
def bool_value(value: bool | None) -> int
```

Then migrate:

```text
tools/wireless_rf/wireless_rf/prometheus.py
tools/wireless_rf/wireless_rf/client_prometheus.py
tools/path_probe/path_probe.py
tools/vocera_iperf_qoe/vocera_iperf_qoe.py
```

### Step 2 - Add `tools/common/files.py`

Why: many scripts read and write JSON, CSV, YAML, and text.

Target helpers:

```python
def read_json(path)
def write_json(path, payload)
def read_yaml(path)
def write_text_atomic(path, content)
def write_csv(path, headers, rows)
def ensure_parent(path)
```

Candidate migrations:

```text
scripts/publish_dnac_topology.py
tools/wireless_rf/wireless_rf/cli.py
tools/vocera_media_qoe/vocera_media_qoe_batch.py
tools/vocera_rf_validation/sql_export.py
```

### Step 3 - Add `tools/common/config.py`

Why: `.env`, config files, and env var handling are repeated.

Target helpers:

```python
def load_env_file(path)
def env_value(name, env_file_values=None, default=None, required=False)
def env_bool(name, default=False)
def load_yaml_config(path)
def require_keys(mapping, keys)
```

Candidate migrations:

```text
scripts/publish_dnac_topology.py
tools/wireless_rf/wireless_rf/client_collector.py
tools/vocera_rf_validation/config.py
tools/vocera_media_qoe/vocera_dnac_icap.py
```

### Step 4 - Add `tools/common/dashboard.py`

Why: dashboard validation and mutation scripts all walk Grafana JSON.

Target helpers:

```python
def load_dashboard(path)
def iter_panels(dashboard)
def iter_targets(dashboard)
def iter_promql_exprs(dashboard)
def iter_variables(dashboard)
def dashboard_uid(dashboard)
def dashboard_title(dashboard)
```

Candidate migrations:

```text
scripts/check_dashboards.py
scripts/check_dashboard_metric_contract.py
scripts/audit_vocera_dashboard.py
scripts/check_topology_dashboard.py
scripts/update_vocera_retry_window_variable.py
```

### Step 5 - Add `tools/common/dnac.py`

Why: higher risk, but large payoff.

Do not start here. Authentication, pagination, and task polling are easy to
break and should be moved only after lower-risk shared helpers are established.

Migrate slowly from:

```text
tools/wireless_rf/wireless_rf/dnac_client.py
scripts/publish_dnac_topology.py
tools/vocera_media_qoe/vocera_dnac_icap.py
tools/wireless_rf/wireless_rf/client_collector.py
```

### Step 6 - Add Unified CLI Entry Point

Long term, expose one command:

```bash
python -m tools.obsctl <area> <command>
```

Examples:

```bash
python -m tools.obsctl wireless-rf parse
python -m tools.obsctl wireless-rf collect
python -m tools.obsctl vocera-rf correlate
python -m tools.obsctl vocera-media analyze
python -m tools.obsctl topology publish
python -m tools.obsctl dashboards check
python -m tools.obsctl contracts check
```

An installed wrapper could later expose:

```bash
obsctl wireless-rf parse
obsctl topology publish
obsctl dashboards check
```

## Future Repo Layout

Move gradually toward this structure:

```text
tools/
  common/
    cli.py
    config.py
    files.py
    prometheus.py
    dashboard.py
    dnac.py
    sqlite.py
    archive.py
    validation.py

  wireless_rf/
    wireless_rf/
      cli.py
      parser.py
      client_parser.py
      client_collector.py
      storage.py
      prometheus.py

  vocera_rf_validation/
    ...

  vocera_media_qoe/
    ...

  vocera_iperf_qoe/
    ...

  path_probe/
    ...

scripts/
  thin wrappers only
```

Long term, `scripts/` should contain thin entry points rather than large logic.

Example:

```python
#!/usr/bin/env python3
from tools.dashboard_checks import main

raise SystemExit(main())
```

Most reusable implementation should live under `tools/`.

## Usability Improvements

### Standard Command Style

Current commands are inconsistent:

```bash
python tools/wireless_rf/wireless_rf/cli.py parse ...
python scripts/publish_dnac_topology.py ...
python tools/path_probe/path_probe.py ...
```

Move toward:

```bash
make wireless-rf-parse
make topology-publish
make vocera-media-batch
make validate
```

with unified commands behind the scenes:

```bash
obsctl wireless-rf parse
obsctl topology publish
obsctl vocera-media batch
obsctl validate all
```

### Better Help Output

Every command should support useful examples in `--help`.

Example:

```text
Examples:
  obsctl wireless-rf parse --input raw.txt --wlc SRHC-WLC-40G-SEC --prom-output out.prom
  obsctl topology publish --env-file .env.dnac --output-dir data/topology
```

### Config-First Workflow

Prefer config files for recurring jobs:

```bash
obsctl wireless-rf collect --config config/wireless-rf/jobs.yaml
```

Example config shape:

```yaml
jobs:
  - name: srhc_wlc_voice
    wlc: SRHC-WLC-40G-SEC
    source: catalyst_center
    output:
      prom: /var/lib/node_exporter/textfile_collector/wireless_rf.prom
      db: /var/lib/wireless-rf/wireless_rf.sqlite
```

### Dry-Run Support

Every command that writes files, DB rows, dashboards, or runtime paths should
support:

```bash
--dry-run
```

### Consistent Output Modes

Useful modes:

```bash
--output-format text
--output-format json
--quiet
--verbose
```

## Testing Strategy

Existing tests should stay green:

```text
scripts/test_path_probe.py
scripts/test_vocera_iperf_qoe.py
scripts/test_vocera_media_qoe.py
scripts/test_vocera_rf_validation.py
scripts/test_wireless_rf_parsers.py
```

Add tests around shared abstractions:

```text
tests/test_common_prometheus.py
tests/test_common_files.py
tests/test_common_config.py
tests/test_common_dashboard.py
tests/test_common_dnac.py
```

Main requirement:

```text
Every refactor should be behavior-preserving.
```

Tests should prove that old output equals new output before and after each
migration.

## Concrete First Implementation Sprint

Start with the lowest-risk abstraction: `tools/common/prometheus.py`.

### Task 1 - Create `tools/common/prometheus.py`

Add shared helpers:

```python
escape_label()
format_labels()
emit_metric()
bool_value()
emit_help()
emit_type()
```

### Task 2 - Migrate `wireless_rf/prometheus.py`

Keep the public function:

```python
render_prometheus()
```

Internally use `tools.common.prometheus`.

### Task 3 - Migrate `wireless_rf/client_prometheus.py`

Use the same shared label formatting.

### Task 4 - Migrate `path_probe.py`

Replace local metric formatting with shared helpers.

### Task 5 - Migrate `vocera_iperf_qoe.py`

Replace local metric formatting with shared helpers.

### Task 6 - Add Tests

Add tests for:

```text
label escaping
empty labels
bool conversion
metric rendering
quotes/backslashes/newlines
None/NaN handling
```

### Task 7 - Run Repo Validation

Run:

```bash
make test
make validate
promtool check rules prometheus/rules/**/*.yml
```

Expected outcome:

```text
No behavior changes.
Less duplicate Prometheus rendering code.
Foundation created for more refactors.
```

## Abstraction Map by Script

### `scripts/check_dashboard_metric_contract.py`

Move to common:

```text
metric extraction logic -> common/dashboard.py or common/promql.py
dashboard walking -> common/dashboard.py
contract loading -> common/config.py
validation output -> common/validation.py
```

### `scripts/check_dashboards.py`

Move to common:

```text
JSON loading -> common/files.py
dashboard uniqueness checks -> common/dashboard.py
```

### `scripts/audit_vocera_dashboard.py`

Move to common:

```text
dashboard traversal -> common/dashboard.py
Prometheus query helper -> common/prometheus_http.py
metric extraction -> common/promql.py
```

### `scripts/publish_dnac_topology.py`

Move to common:

```text
env loading -> common/config.py
CSV/JSON writes -> common/files.py
DNAC client -> common/dnac.py
```

### `tools/wireless_rf/wireless_rf/dnac_client.py`

Eventually move reusable behavior to:

```text
tools/common/dnac.py
```

or:

```text
tools/common/catalyst_center.py
```

### `tools/wireless_rf/wireless_rf/storage.py`

Move common DB patterns to:

```text
tools/common/sqlite.py
```

Keep wireless-specific schema and inserts in the wireless module.

### `tools/vocera_rf_validation/db.py`

Use common DB connection and migration helpers, but keep domain-specific schema
local.

### `tools/vocera_media_qoe/run_archive.py`

Merge common archive concepts with `tools/vocera_rf_validation/run_archive.py`
into:

```text
tools/common/archive.py
```

## What Not To Abstract Yet

### Do Not Merge All Parsers

Keep these domain-specific:

```text
tools/wireless_rf/wireless_rf/parser.py
tools/vocera_rf_validation/badge_diag_parser.py
tools/vocera_media_qoe/
tools/path_probe/path_probe.py parser functions
```

Parsing is where domain-specific edge cases live.

### Do Not Over-Generalize DB Schemas

Keep schemas local to each domain tool.

Only abstract:

```text
connect
transaction
migration execution
safe write
```

### Do Not Centralize Every CLI Immediately

Start by standardizing common flags and helpers. A unified `obsctl` can come
later.

## Success Criteria

The refactor is working when:

1. Existing commands still work.
2. Existing tests still pass.
3. New scripts have less boilerplate.
4. Prometheus text output is consistent.
5. Dashboard validation uses shared traversal.
6. Catalyst Center auth and pagination are implemented once.
7. The command flow can be explained without tracing many unrelated helpers.
8. Adding a collector is mostly:

```text
define parser
define model
define renderer
register CLI command
```

## Recommended Immediate Next Step

Start with:

```text
tools/common/prometheus.py
```

Then migrate:

```text
tools/wireless_rf/wireless_rf/prometheus.py
tools/wireless_rf/wireless_rf/client_prometheus.py
tools/path_probe/path_probe.py
tools/vocera_iperf_qoe/vocera_iperf_qoe.py
```

This creates a concrete first win without touching DNAC, Grafana, systemd, or
dashboard provisioning.
