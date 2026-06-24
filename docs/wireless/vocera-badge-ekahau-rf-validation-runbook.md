# Vocera Badge vs Ekahau RF Validation Runbook

This workflow validates Ekahau survey readings against what the Vocera badge
actually saw in its brcmfmac roam scan table.

The current Ekahau source available to us exposes survey timestamps/location,
but not the RSSI/SNR measurements directly. The importer therefore creates a
manual-entry CSV from matching badge scan rows.

## 1. Prepare Inputs

Place the badge diagnostic sys file or bundle and Ekahau JSON export under a
local raw directory, for example:

```bash
mkdir -p /var/lib/vocera-rf-validation/raw
```

The badge parser accepts a raw `sys` file, extracted diagnostic directory,
`.zip`, `.tar.gz`, or `.tgz`.

The parser captures associated-link `NCI : Radio signal info` samples. Those
samples are attached only to the selected/connected AP candidate, and the
spreadsheet calculates badge-perceived noise floor as RSSI/level minus SNR.

The Ekahau parser accepts a single JSON file, an `.esx` archive, `.zip`, or an
extracted directory. For `.esx`/directory input it reads every JSON file whose
basename starts with `survey-` and uses `floorPlans.json` to map survey floor
IDs to floor names.

For `.esx`/directory input it also builds a BSSID-to-AP-name lookup from
`accessPoints.json`, `measuredRadios.json`, and `accessPointMeasurements.json`.
The generated manual-entry CSV includes this as `ap_name`.

For Ekahau `.esx`, route point `time` values are treated as relative offsets
after the survey `startTime`; the importer auto-detects seconds, milliseconds,
or nanoseconds per survey. Ekahau survey `name` values are retained as
`ekahau_survey_name` in CSV and dashboard rows because many exports use
timestamp-like names such as `2026-05-26-13:20`.

Badge roam scan events are matched to Ekahau survey datapoints only when the
badge event and Ekahau point are on the same local measurement date and the
nearest badge event timestamp is within the configured match window. The default
window is 1 second, inclusive.

## 2. Windows Field Upload and Refresh

On the Windows device that has the latest survey data, stage files under:

```text
C:\rf-validation-data\Pcaps\
C:\rf-validation-data\survey\
C:\rf-validation-data\badge-log\
```

Put ICAP packet captures in `Pcaps`, the Ekahau `.esx` or export bundle in
`survey`, and the badge diagnostic archive or sys file in `badge-log`. Then run
the Windows upload script:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\vocera_rf_validation\windows\Sync-RfValidationDataAndRun.ps1
```

The script uploads the folder to
`/var/lib/vocera-rf-validation/uploads/<run-id>` on `10.0.128.107`, extracts it,
and runs `scripts/run_vocera_survey_refresh.sh` with those uploaded inputs. It
selects the newest survey and badge-log file recursively from their folders and
uploads every pcap in `Pcaps`. The refresh loads the generated RF validation
SQL into PostgreSQL by default so the pending manual-entry rows appear in
Grafana. Set `VOCERA_SURVEY_RF_LOAD_DB=0` only when you want to inspect the SQL
file before loading it.

Useful overrides:

```powershell
PowerShell -ExecutionPolicy Bypass -File .\scripts\vocera_rf_validation\windows\Sync-RfValidationDataAndRun.ps1 `
  -CollectorHost 10.0.128.107 `
  -CollectorUser appsadmin `
  -LocalRoot C:\rf-validation-data `
  -RunId srhc_vocera_ekahau_2026_06_01_1001
```

Each run writes a job manifest under
`data/vocera-rf-validation/out/jobs/<run-id>.json`. Keep the printed run id; it
is the rollback key if the uploaded data was wrong.

## 3. Parse Badge Diagnostics and Ekahau Timestamps

```bash
make vocera-rf-validation-all \
  VOCERA_RF_VALIDATION_TEST_RUN_ID=srhc_basement_vocera_ekahau_2026_05_21_0947 \
  VOCERA_RF_VALIDATION_BADGE_INPUT=/var/lib/vocera-rf-validation/raw/20260521_094721-V5.6.1_Build_25-Test_one-0009ef545f46-udd.tar.gz \
  VOCERA_RF_VALIDATION_EKAHAU_JSON="/var/lib/vocera-rf-validation/raw/floor 5 data.esx" \
  VOCERA_RF_VALIDATION_BADGE_MAC=00:09:ef:54:5f:46
```

This writes:

```text
data/vocera-rf-validation/out/badge_scan_events.json
data/vocera-rf-validation/out/ekahau_survey_points.json
data/vocera-rf-validation/out/manual_ekahau_observations_template.csv
data/vocera-rf-validation/out/archives/*.zip
```

Each ZIP archive contains the command inputs, generated outputs,
`manifest.json`, and `logs/run.log`. Use
`VOCERA_RF_VALIDATION_ARCHIVE_DIR=/path/to/archives` to change the destination.

## 4. Enter Ekahau RSSI/SNR

Open the generated CSV and fill only these columns from the Ekahau survey data:

```text
ekahau_rssi_dbm
ekahau_snr_db
notes
```

The badge columns should remain unchanged. They are the badge-side truth table
for the matched survey timestamp. `ap_name` is generated from the Ekahau AP
mapping and should normally be left unchanged. `badge_snr_db` comes from the
matched associated-link `NCI : Radio signal info` sample, and
`badge_noise_floor_dbm` is calculated as `badge_radio_signal_level_dbm -
badge_snr_db`.

The Grafana dashboard can also write these values directly when the Business
Table panel plugin (`volkovlabs-table-panel`) is installed. In `Vocera Badge vs
Ekahau RF Validation`, edit `Ekahau RSSI`, optionally edit `Ekahau SNR` and
`Notes`, then save the row in the `Pending Manual Entry` table. The dashboard
calls the PostgreSQL `vocera_rf_validation_submit_candidate_match` function,
stores the manual observation, and materializes the calibrated match row.
Use the row trash action to remove an unwanted pending entry; that calls
`vocera_rf_validation_delete_candidate_match` and deletes the selected candidate
row plus any match rows tied to it.
Use the trash action in `Completed Manual Entries` to remove an entry that was
already submitted. That calls
`vocera_rf_validation_clear_candidate_manual_entry`, deletes the materialized
match/manual-observation rows, and returns the candidate to pending entry.

## Current Study Workflow

The dashboard treats the live PostgreSQL RF validation rows as the **current
study**. Each current study can have a name and notes. This is the same
lifecycle model used by the media PCAP QoE dashboard: you can keep adding
parsed runs to the current study, archive a checkpoint, or archive and clear the
current study before starting a new one.

Use the collector-hosted web UI for study lifecycle work:

```bash
cd /home/appsadmin/grafana-mimir-observability
make vocera-rf-validation-study-web-install
```

Then open:

```text
http://collectors01:8097/
```

or:

```text
http://10.0.128.107:8097/
```

The web UI shows the backend/schema readiness, the current live study, live
parser runs, archived studies, selected source archives, and combined-study
status. It uses normal server-side form posts against the existing PostgreSQL
functions, so database errors are shown directly instead of Grafana plugin
errors.

Use the web UI before uploading evidence from the laptop:

- `Save Study Name` to name or rename the current live study.
- `Archive Current` to write a JSONB checkpoint while leaving the live rows
  visible.
- `Archive + Clear Current` to checkpoint the live study and clear it before a
  new study.
- `Clear Current` only when you intentionally want to discard the live rows
  without archiving.
- In `RF Study Archives`, edit labels/notes, select archives for a combined
  study, or delete archive metadata.
- In `Combine Archived Studies`, create a new combined archive from two or more
  selected archives. The source archives remain intact.

If the web UI shows `schema update required`, apply the RF validation schema and
views:

```bash
sudo sh -lc 'cd /home/appsadmin/grafana-mimir-observability; . /etc/grafana-mimir-observability/secrets/vocera-rf-validation-postgres.env; url="postgresql://vocera_rf_validation:${VOCERA_RF_VALIDATION_POSTGRES_PASSWORD}@127.0.0.1:15433/vocera_rf_validation"; PYTHONPATH=. python3 -m tools.vocera_rf_validation.cli --config config/vocera-rf-validation.yaml install-db --postgres-url "$url" --psql-bin scripts/vocera_rf_validation_psql_in_container.sh'
```

The shell manager remains available for SSH-only maintenance:

```bash
cd /home/appsadmin/grafana-mimir-observability
make vocera-rf-validation-study
```

Choose:

- `Add next parser/upload run to current study` to keep the existing live rows
  and name/rename the study before the next upload.
- `Start a new named study` to archive+clear the current live rows first, then
  set the new study name.
- `Start a new named study (clear current without archive)` only when you
  intentionally want to discard the current live rows.

The same script also supports direct commands:

```bash
sudo bash scripts/manage_vocera_rf_validation_study.sh --show
sudo bash scripts/manage_vocera_rf_validation_study.sh --add "June basement Vocera validation"
sudo bash scripts/manage_vocera_rf_validation_study.sh --new "June 10 retest" --notes "post-radio-policy change"
```

The `Current RF Study` panel shows the active study name, notes, and current
row counts. Grafana should be treated as the reporting surface. The web UI is
the preferred surface for study CRUD and lifecycle actions.

These actions are scoped to the Vocera badge dashboard only
(`test_run_id not like 'ipad_%'`). iPad WLC/Ekahau validation rows use the same
database tables, but they are excluded from the badge dashboard's study actions.

## 5. Correlate

```bash
make vocera-rf-validation-correlate
```

Outputs:

```text
data/vocera-rf-validation/out/badge_ekahau_matches.json
data/vocera-rf-validation/out/badge_ekahau_matches.csv
```

Rows with `manual_entry_status=complete` have calibrated deltas. Rows with
`pending_manual_entry` still need Ekahau RSSI.

If the manual template has only a header row, check the dashboard `Run
Alignment` panel or the CLI warning. `no_same_date_overlap` means the badge
diagnostic and Ekahau survey project are from different dates; those rows are
intentionally not compared even when the clock time looks similar.

## 6. Load PostgreSQL

Install the schema once:

```bash
make vocera-rf-validation-postgres-install

make vocera-rf-validation-install-db
```

After parsing/correlation, emit run-scoped SQL and load it:

```bash
make vocera-rf-validation-emit-sql

make vocera-rf-validation-load-db
```

The default `VOCERA_RF_VALIDATION_PSQL_BIN` runs `psql` inside the local
Podman PostgreSQL container, so host-level `psql` is not required.

The dashboard reads the PostgreSQL views and tables through datasource UID
`VOCERA_RF_VALIDATION_DS`.

## 7. Roll Back a Bad Parser Run

Use the run id printed by the upload script or recorded in
`data/vocera-rf-validation/out/jobs/`:

```bash
make vocera-survey-rollback VOCERA_SURVEY_ROLLBACK_RUN_ID=srhc_vocera_ekahau_2026_06_01_1001
```

Rollback deletes RF validation rows for that `test_run_id`, deletes media QoE
captures whose source pcap path was under the uploaded job `Pcaps` directory,
and moves the uploaded bundle to `/var/lib/vocera-rf-validation/rolled-back`.
Parser ZIP archives are retained for audit.

To preview the rollback:

```bash
sudo bash ./scripts/rollback_vocera_survey_refresh.sh \
  --run-id srhc_vocera_ekahau_2026_06_01_1001 \
  --dry-run
```

If the bad run is still the current generated output, add
`--remove-current-outputs`. Output files are only removed when their SHA-256
still matches the job manifest, so a later refresh is not removed by accident.

## 8. Offset Interpretation

The formula is:

```text
expected_badge_rssi_dbm = ekahau_rssi_dbm + vendor_offset_db
calibrated_delta_db = badge_rssi_dbm - expected_badge_rssi_dbm
```

Default offsets:

```text
2.4 GHz: -5 dB
5 GHz:   -8 dB
6 GHz:   unset
```

Do not apply the 5 GHz offset to 6 GHz until a validated Stryker/Vocera offset
or a local calibration value exists. Badge model is optional metadata; it is not
required for offset selection because the default policy is band-based.
