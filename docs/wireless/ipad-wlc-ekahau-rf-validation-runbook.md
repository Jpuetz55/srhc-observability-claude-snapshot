# iPad WLC Client vs Ekahau RF Validation Runbook

This workflow validates iPad-side RF readings from manually collected Cisco WLC
client scan reports against Ekahau survey timestamps. It is separate from:

- Vocera badge RF validation, which parses Vocera diagnostic badge logs.
- Vocera media PCAP QoE, which uses control/test badge packet captures.
- Catalyst Center device-command workflows, which are intentionally unavailable
  in this repo.

## Field Workflow

Collect WLC client-detail snapshots by an approved operational process outside
this repo. Each snapshot should include the `Client Scan Reports` section for
the iPad client.

Stage the snapshots under the run output directory:

```text
data/ipad-rf-validation/out/<ipad_run_id>/client-detail-snapshots/
  client_detail_1_20260608T120000-0500.txt
  client_detail_2_20260608T120005-0500.txt
```

Then process and load the run:

```bash
sudo make ipad-rf-validation-process \
  IPAD_RF_VALIDATION_RUN_ID='ipad_wlc_ekahau_YYYY_MM_DD_HHMMSS' \
  IPAD_RF_VALIDATION_CLIENT_MAC='aa:bb:cc:dd:ee:ff' \
  IPAD_RF_VALIDATION_EKAHAU_PROJECT='/var/lib/ipad-rf-validation/raw/main-campus.esx'
```

`ipad-rf-validation-run` uses the same process-only path. It does not collect
from Catalyst Center; the staged `client_detail_*.txt` files must already
exist.

## Parser Boundary

The parser imports rows from `Client Scan Reports` only. `Nearby AP Statistics`
and AP-side `Client Statistics` RSSI/SNR are ignored so the run stays scoped to
client-observed scan candidates.

The run id defaults to:

```text
ipad_wlc_ekahau_YYYY_MM_DD_HHMMSS
```

Custom run ids must start with `ipad_` so the iPad dashboard and Vocera badge
dashboard stay separated.

## Outputs

For a run id like `ipad_wlc_ekahau_2026_06_08_120000`, outputs are written to:

```text
data/ipad-rf-validation/out/ipad_wlc_ekahau_2026_06_08_120000/
  client-detail-snapshots/
    client_detail_1_*.txt
    client_detail_2_*.txt
  ipad_scan_events.json
  ekahau_survey_points.json
  manual_ekahau_observations_template.csv
  ipad_rf_validation_import.sql
```

The dashboard is:

```text
iPad WLC Client vs Ekahau RF Validation
```

It only shows `test_run_id like 'ipad_%'`. The existing Vocera badge RF
validation dashboard excludes those runs.
