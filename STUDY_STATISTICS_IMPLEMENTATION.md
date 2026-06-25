# Study statistics workbench

> **Historical implementation record.** This captures a study-statistics feature
> change. Current user workflow and operational boundaries are documented in
> [`docs/study-workflow-web-ui.md`](docs/study-workflow-web-ui.md).

This change makes the RF validation page study-centric and adds manual Ekahau
sample entry with central-limit statistics.

## What changed (UX)

- **Projects and studies are now fully CRUD-able from the UI.** The page shows a
  **Projects** card (create / edit / delete, select) and a **Studies** card
  (create / edit / delete, select) instead of read-only selectors. A study is the
  unit of work; "runs" are demoted to an optional, collapsed advanced importer.
- **New Statistics workbench (the primary feature).** With a study selected, you
  can type Ekahau RSSI (dBm) and/or SNR (dB) values directly into the study
  (single entry or bulk paste). The app computes and displays, per metric:
  count, mean, standard deviation, variance, min/max/range, p05, p25, median
  (p50), p75, p95, IQR, standard error of the mean (SEM), and a 95% confidence
  interval for the mean (central limit theorem). Samples whose z-score magnitude
  exceeds a configurable threshold (default 2.0) are flagged as outliers and
  highlighted in the table.
- **Time-based graphs removed.** The "Run trend" study-signal chart and the two
  embedded Grafana time-series panels (AP voice latency, Tx retry) were removed
  as irrelevant to this use case.

## Backend / API

New endpoints in `tools/study_web/main.py` (study-scoped manual samples):

- `GET    /api/studies/{study_id}/samples?z_threshold=2.0` — list samples plus
  computed statistics and per-sample outlier flags.
- `POST   /api/studies/{study_id}/samples` — add one sample
  (`label`, `ekahau_rssi_dbm`, `ekahau_snr_db`, `notes`; at least one value).
- `POST   /api/studies/{study_id}/samples/bulk` — add many samples at once.
- `PATCH  /api/samples/{sample_id}` — edit a sample.
- `DELETE /api/samples/{sample_id}` — soft-delete a sample.

Statistics are computed in `tools/study_web/sample_statistics.py` (standard
library only, unit-tested in `scripts/test_vocera_rf_validation.py`). If the new
table has not been migrated yet, the list endpoint returns `ok: false` with a
"schema update required" message and the workbench shows it inline; the rest of
the page keeps working.

## Database

New table `vocera_rf_manual_samples` and view `v_vocera_rf_manual_samples` were
appended to the idempotent `sql/vocera_rf_validation_schema.sql` and
`sql/vocera_rf_validation_views.sql`.

Apply with the existing target:

```
make vocera-rf-validation-install-db
```

## Build / test

```
cd web/study-ui && npm install && npm run build   # tsc -b && vite build
python3 ./scripts/test_vocera_rf_validation.py     # includes sample-statistics tests
```
