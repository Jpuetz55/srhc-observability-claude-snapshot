# Vocera RF Validation

This module compares Vocera badge-side roam scan measurements with Ekahau
survey timestamps. The available Ekahau JSON is treated as timestamp/location
context only; Ekahau RSSI/SNR values are entered manually into the generated
CSV template.

For new work, **Study Web** is the primary operator interface: create/select a
project and study, import staged evidence, complete manual survey entries, and
review statistics. This CLI/Make workflow remains the reproducible backend
path used by Study Web and by controlled batch processing. The current Grafana
dashboard inventory does not include an RF-validation dashboard.

Workflow:

```bash
make vocera-rf-validation-all \
  VOCERA_RF_VALIDATION_TEST_RUN_ID=srhc_basement_vocera_ekahau_2026_05_21_0947 \
  VOCERA_RF_VALIDATION_BADGE_INPUT=/var/lib/vocera-rf-validation/raw/20260521_094721-V5.6.1_Build_25-Test_one-0009ef545f46-udd.tar.gz \
  VOCERA_RF_VALIDATION_EKAHAU_JSON="/var/lib/vocera-rf-validation/raw/floor 5 data.esx" \
  VOCERA_RF_VALIDATION_BADGE_MAC=00:09:ef:54:5f:46
```

Ekahau input can be a single JSON file, an `.esx` archive, `.zip`, or an
extracted directory. For `.esx`/directory input, only `survey-*.json` files are
parsed as survey timestamp sources, with `floorPlans.json` used for floor names.
AP names are derived from the Ekahau `accessPoints.json`,
`measuredRadios.json`, and `accessPointMeasurements.json` mapping and emitted
as `ap_name` in the manual-entry CSV and correlated output.

The parser also captures associated-link `NCI : Radio signal info` samples.
Those samples are attached only to the selected/connected AP candidate. The
badge-perceived noise floor is calculated as `badge_radio_signal_level_dbm -
badge_snr_db`.

Every badge/Ekahau parser, template, correlate, and SQL emit command writes a
ZIP run archive under `data/vocera-rf-validation/out/archives` by default. The
archive contains the input files used by the command, generated outputs,
`manifest.json`, and `logs/run.log`. Override the location with
`VOCERA_RF_VALIDATION_ARCHIVE_DIR` or `--archive-dir`.

Roam scan events are matched to Ekahau datapoints only when the nearest badge
event is on the same local measurement date and within the configured match
window. The default window is 1 second, inclusive.

For the field upload workflow, stage files on Windows under
`C:\rf-validation-data\Pcaps`, `C:\rf-validation-data\survey`, and
`C:\rf-validation-data\badge-log`, then run
`scripts/vocera_rf_validation/windows/Sync-RfValidationDataAndRun.ps1`. The
server-side run records a manifest in `data/vocera-rf-validation/out/jobs` so a
bad upload can be rolled back with:

```bash
make vocera-survey-rollback VOCERA_SURVEY_ROLLBACK_RUN_ID=<run-id>
```

Fill `ekahau_rssi_dbm` and optionally `ekahau_snr_db` in:

```text
data/vocera-rf-validation/out/manual_ekahau_observations_template.csv
```

Then compute calibrated deltas:

```bash
make vocera-rf-validation-correlate
```

Emit PostgreSQL import SQL after correlation:

```bash
make vocera-rf-validation-emit-sql
```

The offset formula is:

```text
expected_badge_rssi_dbm = ekahau_rssi_dbm + vendor_offset_db
calibrated_delta_db = badge_rssi_dbm - expected_badge_rssi_dbm
```

Default offsets are band-based: `-8 dB` for 5 GHz and `-5 dB` for 2.4 GHz.
The 6 GHz offset is intentionally unset. `badge_model` is optional metadata,
not required for calibration.
