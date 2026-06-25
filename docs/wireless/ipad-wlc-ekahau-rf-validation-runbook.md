# iPad WLC Client vs Ekahau RF Validation Runbook

This workflow correlates **manually collected WLC client scan reports** with
Ekahau survey timestamps. It is separate from Vocera badge RF validation,
media-PCAP QoE, and live MDT telemetry. The repository does not collect these
WLC reports, issue WLC commands, or provide a dedicated iPad Grafana dashboard.

## Field workflow

Collect WLC client-detail output through an approved manual process. Each file
must include the `Client Scan Reports` section for the target iPad client.
Stage the snapshots under the intended run output directory:

```text
data/ipad-rf-validation/out/<ipad_run_id>/client-detail-snapshots/
  client_detail_1_20260608T120000-0500.txt
  client_detail_2_20260608T120005-0500.txt
```

Process and load the run:

```bash
sudo make ipad-rf-validation-process \
  IPAD_RF_VALIDATION_RUN_ID='ipad_wlc_ekahau_YYYY_MM_DD_HHMMSS' \
  IPAD_RF_VALIDATION_CLIENT_MAC='aa:bb:cc:dd:ee:ff' \
  IPAD_RF_VALIDATION_EKAHAU_PROJECT='/var/lib/ipad-rf-validation/raw/main-campus.esx'
```

`ipad-rf-validation-run` uses the same staged-input path. Neither target
contacts Catalyst Center or the WLC.

## Parser boundary

The parser imports `Client Scan Reports` only. It intentionally ignores
`Nearby AP Statistics` and AP-side `Client Statistics` RSSI/SNR so results
remain scoped to client-observed scan candidates.

Use a stable run ID beginning with `ipad_`:

```text
ipad_wlc_ekahau_YYYY_MM_DD_HHMMSS
```

This prefix keeps iPad records distinguishable from Vocera badge validation
records in shared data stores and Study Web queries.

## Outputs

For a run such as `ipad_wlc_ekahau_2026_06_08_120000`, the process writes:

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

The current tested Grafana dashboard inventory contains only **WLC Control
Plane** and **Vocera Iperf QoE**. Review iPad validation through the generated
artifacts, PostgreSQL/Study Web where applicable, or a temporary Explore/query
view. Adding a permanent iPad dashboard requires dashboard JSON in both
managed trees and an inventory-validation change.
