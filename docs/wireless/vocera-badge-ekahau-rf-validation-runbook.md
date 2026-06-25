# Vocera Badge and Ekahau RF Validation Runbook

This runbook validates **badge-observed roaming scan evidence** against Ekahau
survey time/location context. It is an evidence study workflow, not continuous
wireless monitoring and not a Grafana dashboard. The primary operator interface
is the collector-hosted **Study Web** application on port `8097`.

Measurement interpretation is defined in
[`vocera-badge-ekahau-rf-validation-methodology.md`](vocera-badge-ekahau-rf-validation-methodology.md).
Use this runbook for the repeatable input, processing, review, and retention
flow.

## Boundaries

- Badge diagnostic archives are the source for roam scans and badge-side
  signal/SNR context.
- Ekahau survey files supply timestamp/location context. Actual Ekahau
  RSSI/SNR values are manually entered when the file does not expose the
  required measurement.
- The repo does not use Catalyst Center Command Runner or WLC SSH to collect
  this data.
- The current tracked Grafana dashboards are **WLC Control Plane** and
  **Vocera Iperf QoE**. RF validation results are reviewed in Study Web,
  generated artifacts, and PostgreSQL—not a dedicated Grafana dashboard.

## Prepare a study

1. Open Study Web and create or select a **Project** and **Study**.
2. Define the badge/client scope, site/floor context, and the intended survey.
3. Stage or upload the badge diagnostic archive and Ekahau `.esx`, `.zip`,
   extracted directory, or compatible JSON source through the study workflow.
4. Preserve the original source files outside Git. They are operational
   evidence and are referenced by generated run manifests/archives.

The server service is `vocera-rf-validation-study-web.service`. See
[`../study-workflow-web-ui.md`](../study-workflow-web-ui.md) for service,
frontend, and application details.

## Process a reproducible run

The CLI/Make path is the repeatable backend workflow and is useful for a
controlled batch run or troubleshooting Study Web execution:

```bash
make vocera-rf-validation-all \
  VOCERA_RF_VALIDATION_TEST_RUN_ID='srhc_basement_vocera_ekahau_YYYY_MM_DD_HHMM' \
  VOCERA_RF_VALIDATION_BADGE_INPUT='/var/lib/vocera-rf-validation/raw/<badge-diagnostic>.tar.gz' \
  VOCERA_RF_VALIDATION_EKAHAU_JSON='/var/lib/vocera-rf-validation/raw/<survey>.esx' \
  VOCERA_RF_VALIDATION_BADGE_MAC='00:09:ef:54:5f:46'
```

The `all` target parses badge data and survey context, produces the manual
entry template, correlates eligible events, emits PostgreSQL import SQL, and
writes a run archive. Use a stable, descriptive run ID; do not reuse an ID for
a materially different input set.

Typical outputs are written under:

```text
data/vocera-rf-validation/out/<run-id>/
  badge_scan_events.json
  ekahau_survey_points.json
  candidate_matches.json
  manual_ekahau_observations_template.csv
  correlation_results.json
  vocera_rf_validation_import.sql

data/vocera-rf-validation/out/archives/
  <run-id>.zip
```

Exact filenames vary by command/version; the run archive manifest is the
record of what was used and produced.

## Complete manual survey values

Use Study Web’s manual-entry workflow for candidate matches that need actual
Ekahau RSSI/SNR. It preserves candidate state, records the entered values,
materializes the final match, recalculates deltas, and makes the change
reviewable. Avoid editing database tables directly except during documented
recovery.

For a file-first workflow, fill the generated template with `ekahau_rssi_dbm`
and optional `ekahau_snr_db`, then run the documented correlate/SQL-load
sequence from `tools/vocera_rf_validation/README.md`. Do not fabricate values
for AP candidates where the survey measurement was not observed.

## Review and decision rules

Review, in this order:

1. input/run timestamps and same-local-date alignment;
2. candidate BSSID/AP/channel association;
3. badge scan RSSI/SNR provenance and missing-value reason;
4. manually entered Ekahau values and their audit trail;
5. calibrated delta rather than raw RSSI delta; and
6. aggregate statistics only after checking sample count and outliers.

Default calibration anchors are currently `-5 dB` for 2.4 GHz and `-8 dB` for
5 GHz. The 6 GHz offset remains intentionally unset until it is validated.
Treat all comparison conclusions as a statement about the captured evidence and
these calibration assumptions, not a general claim about all badge behavior.

## Retention and recovery

Keep source archives, generated manifests, and study/run metadata according to
your approved operational retention policy. Do not commit PCAPs, diagnostic
archives, user exports, database passwords, or generated secrets to Git.

For study service troubleshooting, verify the PostgreSQL service, Study Web
health endpoint, raw-source permissions, and the relevant run archive before
rerunning a job. A rerun should be a new run unless the original run has been
explicitly cleared or recovered.
