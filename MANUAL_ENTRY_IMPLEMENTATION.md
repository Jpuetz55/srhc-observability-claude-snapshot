# Manual Survey Entry workflow

This patch makes the RF validation web workflow candidate-first:

1. Run execution parses badge and Ekahau files.
2. Matching timestamp/BSSID rows are imported as `badge_ekahau_candidate_matches` with `manual_entry_status = 'pending'`.
3. `badge_ekahau_matches` rows are not created during run import unless a legacy/manual CSV already provides Ekahau RSSI.
4. A human enters Ekahau RSSI/SNR in the Study Web manual-entry section.
5. The manual-entry endpoint inserts `manual_ekahau_observations`, materializes `badge_ekahau_matches`, recalculates deltas, and marks the candidate complete.

## Backend/API changes

- `GET /api/rf/runs/{test_run_id}/manual-entry` returns pending and completed manual-entry rows.
- `POST /api/rf/candidates/{candidate_match_id}/manual-entry` now uses the candidate-specific SQL function.
- `DELETE /api/rf/matches/{match_id}` resets a completed manual entry back to pending.

## UI changes

The selected run now has a Manual Survey Entry section with pending candidate rows and inline Ekahau RSSI/SNR inputs:

`Survey time | BSSID | AP name | Channel | Badge RSSI | Badge SNR | Ekahau RSSI | Ekahau SNR | Save`

Completed rows show saved values and allow Edit or Reset.

## Import behavior change

`tools/vocera_rf_validation/sql_export.py` no longer auto-materializes completed `badge_ekahau_matches` from matching timestamps alone. Blank/manual-pending correlated rows stay in candidate-only state.

## Deploy notes

After copying this patch into the repo, rebuild the UI and apply the SQL schema/views to the database before restarting the web service.
