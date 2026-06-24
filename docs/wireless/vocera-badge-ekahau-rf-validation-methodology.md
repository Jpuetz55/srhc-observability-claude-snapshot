# Vocera Badge vs Ekahau RF Validation Methodology

Primary truth source:

```text
Vocera badge diagnostic sys file / brcmfmac roam scan table
```

Comparison source:

```text
Ekahau survey timestamp/location JSON plus manually entered Ekahau RSSI/SNR
```

Calibration anchor:

```text
2.4 GHz: -5 dB
5 GHz:   -8 dB
6 GHz:   null until validated
```

The system keeps detailed per-BSSID/per-second validation data in PostgreSQL.
Prometheus/Mimir should only receive low-cardinality health and summary metrics.

## Matching

Required match:

```text
same validation run
same local measurement date
nearest badge scan event to Ekahau survey timestamp
abs(time_delta_seconds) <= configured match window
```

The manual-entry template includes every badge scan candidate from the nearest
same-date matching event. After Ekahau RSSI/SNR is entered, correlation
computes:

```text
raw_delta_db = badge_rssi_dbm - ekahau_rssi_dbm
expected_badge_rssi_dbm = ekahau_rssi_dbm + vendor_offset_db
calibrated_delta_db = badge_rssi_dbm - expected_badge_rssi_dbm
absolute_calibrated_delta_db = abs(calibrated_delta_db)
```

Use calibrated deltas for decisions. Raw deltas are retained for auditability.

## Badge SNR

`NCI : Radio signal info` is associated-link telemetry. Badge SNR is populated
only for the selected/connected AP candidate when a nearby same-channel radio
signal sample is available.

```text
badge_noise_floor_dbm = badge_radio_signal_level_dbm - badge_snr_db
```

Rows for non-associated candidates keep badge SNR blank and identify the reason
in `badge_snr_source`.
