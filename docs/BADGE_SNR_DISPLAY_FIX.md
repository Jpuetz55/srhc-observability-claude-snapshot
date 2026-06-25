# Badge SNR display fix

> **Historical implementation record.** This documents the original Badge SNR
> display correction. Current interpretation is governed by
> [`wireless/vocera-badge-ekahau-rf-validation-methodology.md`](wireless/vocera-badge-ekahau-rf-validation-methodology.md).

The Manual Survey Entry table was showing blank Badge SNR values for candidate AP rows because the correlator only attached `Radio signal info` SNR to the selected/connected candidate.

For manual RF validation, Badge SNR is the badge-side associated-link SNR observed at the scan/survey timestamp. Candidate AP scan rows generally do not include per-BSSID SNR, so the correlator now:

1. Preserves direct candidate SNR if it ever appears in a scan candidate record.
2. Prefers a same-channel `Radio signal info` sample near the scan event.
3. Falls back to the nearest event-level associated-link `Radio signal info` sample.
4. Stores `badge_snr_source` so downstream UI/analysis can distinguish exact/direct values from associated-link event-level values.

Existing imported candidate rows will not change automatically. Rerun the RF validation run after deploying this patch to repopulate candidate rows with Badge SNR.
