# Vocera media PCAP QoE architecture and evidence boundary

The media QoE tooling analyzes offline PCAP/PCAPNG evidence visible at one
capture point. It is intentionally separate from WLC MDT, RF validation, and
human-observation timelines.

## Supported ingestion lanes

```text
Completed Catalyst Center ICAP PCAP
  -> generic raw area -> batch parser -> history + textfile health snapshot

Explicit imported PCAP
  -> generic raw area / Study Web registration -> parser -> history + snapshot

Manual WLC EPC session
  -> session incoming/ -> stability check + SHA-256 -> session pcaps/
  -> capture_point=wlc_epc -> parser -> session artifact/history

Legacy WLC attempt package
  -> explicit validation/ingest -> evidence ledger
```

The generic publisher excludes `wlc-sessions/` and `wlc-attempts/`. Study Web
also rejects generic file registration under those roots. That isolation is
required to prevent a manual WLC capture from being double-parsed or mislabeled
as ICAP evidence.

## Output layers

| Layer | Purpose | Not for |
| --- | --- | --- |
| source PCAP + metadata | raw evidence | Git storage or broad sharing |
| JSON/parser detail | flow/stream/SSRC/timestamp diagnostics | Prometheus labels |
| PostgreSQL history | capture-time review, Study Web, evidence lineage | real-time alert labels |
| session artifact record | SCP arrival, hash, final path, parser/retry state | generic batch discovery |
| `.prom` textfile | bounded parser health/current status | packet-forensics detail |
| ZIP run archive | reproducibility inputs/outputs/log | source-control replacement |

## Measurement semantics

The parser can report only what is visible at the capture point:

- packet count, bytes, direction, and DSCP;
- UDP interarrival cadence;
- RTP sequence, jitter, loss, duplicate, and reorder behavior only when RTP is
  plausibly identified with sufficient packets/clock context; and
- capture timestamp integrity and parser rejection reasons.

It cannot prove mouth-to-ear latency, true one-way latency, MOS, receiver-side
quality at a different endpoint, jitter-buffer behavior, or causal
packet-to-attempt correlation. `measurement_mode=udp_interarrival_only` is an
honest downgrade when UDP is useful but RTP cannot be proven.

## Parser safeguards

The checked-in configuration and code guard against future timestamps,
insufficient RTP packet counts, transit discontinuities, invalid/partial ICAP
downloads, duplicate cache work, and unbounded parser execution. The WLC session
importer adds stable-upload detection, pcap magic validation, root-owned
finalization, SHA-256 identity, and idempotent retry behavior.

## Visualization status

The datasource and Study Web workflows are available, but the current tested
Grafana dashboard inventory does **not** provision a Media QoE dashboard. Use
Study Web and database-supported review until a dashboard is intentionally
added to both dashboard trees and the inventory/contract checks.

## Related runbooks

- [`vocera-media-dnac-icap-runbook.md`](vocera-media-dnac-icap-runbook.md)
- [`vocera-wlc-continuous-capture-runbook.md`](vocera-wlc-continuous-capture-runbook.md)
- [`vocera-wlc-phase0-ingest-rehearsal-runbook.md`](vocera-wlc-phase0-ingest-rehearsal-runbook.md)
- [`vocera-media-latency-jitter-methodology.md`](vocera-media-latency-jitter-methodology.md)
- [`../../tools/vocera_media_qoe/README.md`](../../tools/vocera_media_qoe/README.md)
