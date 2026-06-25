# Python toolkit architecture and consolidation status

> **Status: current architecture note, not an unstarted refactor proposal.**
> Several shared helpers are already implemented in `tools/common/`. This
> document records the intended boundary for further consolidation without
> implying that every script has been migrated.

## Why the repository has several Python packages

The collector performs materially different jobs:

- parse staged WLC CLI text into RF evidence;
- parse offline media PCAPs and produce QoE evidence;
- correlate Vocera badge diagnostics with Ekahau survey context;
- prepare manual WLC EPC capture-session packages and import metadata;
- publish read-only Catalyst Center topology data; and
- expose research/study workflows through Study Web.

Those workflows share configuration, files, Prometheus exposition, and some
dashboard inspection code. They must **not** share domain assumptions such as
PCAP packet semantics, RF correlation rules, Postgres schema names, or WLC
operator steps.

## Current shared package

`tools/common/` currently contains the small, dependency-light helpers that are
safe to reuse:

| Module | Responsibility |
| --- | --- |
| `config.py` | predictable configuration loading/validation helpers |
| `files.py` | safe file/path and staged-artifact utilities |
| `prometheus.py` | Prometheus text exposition helpers |
| `dashboard.py` | dashboard JSON traversal helpers used by repository checks |

Keep these helpers generic. A utility belongs here only when it has no
source-specific metric naming, database schema, API endpoint, capture format,
or operator workflow attached to it.

## Domain packages and their ownership

| Package | Owns | Must remain domain-specific |
| --- | --- | --- |
| `tools/wireless_rf/` | WLC CLI parsing, RF snapshot/statistics, manual evidence publishing | Cisco command/output grammar and RF metric interpretation |
| `tools/vocera_media_qoe/` | PCAP parsing, RTP/UDP semantics, ICAP download, WLC session/attempt packages, media database output | packet/capture semantics and all manual WLC command-sheet behavior |
| `tools/vocera_rf_validation/` | badge/Ekahau correlation, candidate/manual-entry lifecycle, statistics, RF database logic | correlation model and study data model |
| `tools/vocera_iperf_qoe/` | iperf JSON parsing and QoE metrics | iperf-specific data semantics |
| `tools/path_probe/` | bounded RTT probe parsing and metrics | probe execution and RTT semantics |
| topology tools | read-only Catalyst Center topology normalization/load files | topology graph model and source adapters |

## Current operator boundary

Refactoring must preserve the architecture documented in
[`architecture.md`](architecture.md): code may prepare and validate evidence,
but it must not quietly gain WLC command execution, WLC credential storage, or
capture-start authority. WLC incident captures remain manual EPC plus WLC-side
SCP export. Catalyst Center access remains read-only for completed ICAP and
topology retrieval.

## Consolidation rules for new code

1. Add a helper to `tools/common/` only after at least two packages need the
   same behavior with the same contract.
2. Keep public CLIs stable. Existing Make targets and runbooks are the operator
   API and require tests when changed.
3. Use a package-local adapter for database schema, file layout, API semantics,
   and metric-name ownership.
4. Prefer pure functions for parsing/calculation and isolate filesystem/network
   actions behind narrow adapters.
5. Add a focused `scripts/test_*.py` regression test before moving an existing
   helper across package boundaries.
6. Do not create a generic “Cisco client” or “capture runner” that blurs the
   read-only/manual operational boundary.

## Suggested next increments

- Normalize archive-manifest validation where the media and RF validators truly
  share the same on-disk contract.
- Consolidate CLI error formatting only after preserving each tool’s exit-code
  behavior and documented flags.
- Create shared typed result/error structures only for repository checks; do
  not force parser domains into a single model.
- Remove superseded one-off scripts only after their Make target, docs, and
  tests have been migrated together.

Use `make test` plus the package-specific test target after a shared-helper
change. A code cleanup is incomplete until the canonical documentation and
operator interfaces remain accurate.
