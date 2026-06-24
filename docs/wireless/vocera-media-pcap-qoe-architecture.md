# Vocera Media PCAP QoE Architecture

This document explains the Vocera media PCAP QoE pipeline, the measurement
contract, and the accuracy problems fixed while making the dashboard usable.
Use `vocera-media-dnac-icap-runbook.md` for operator steps; this document is
for maintainers who need to understand why the parser and panel behave the way
they do.

## Scope

The pipeline analyzes offline packet captures that contain IP/UDP media traffic
for Vocera badges and servers. When visible RTP headers are present, it reports
receiver-side RTP sequence and jitter metrics. When RTP headers are not visible,
it reports UDP timing, volume, and DSCP only.

It can prove:

- Media arrival quality at the capture point.
- RTP interarrival jitter when RTP timestamp, sequence, SSRC, and payload type
  are visible.
- RTP sequence gaps, duplicates, and out-of-order packets within the capture
  window.
- UDP packet cadence, DSCP, packet count, byte count, and stream direction.

It must not claim:

- End-to-end call quality.
- MOS.
- One-way latency.
- Mouth-to-ear delay.
- RTP jitter or RTP loss for non-RTP UDP.

## Data Flow

```text
DNAC / Catalyst Center ICAP pcap
  or manual WLC capture-session pcap/pcapng
    -> /var/lib/vocera-media-qoe/raw
    -> scripts/run_vocera_media_qoe_textfile.sh
    -> tools/vocera_media_qoe/vocera_media_qoe_batch.py
    -> tools/vocera_media_qoe/vocera_media_qoe.py
    -> per-capture JSON/prom cache under data/vocera-media-qoe/out/captures
    -> latest snapshot .prom for node_exporter textfile collector
    -> Prometheus / Mimir snapshot health metrics
    -> tools/vocera_media_qoe/vocera_media_qoe_sql.py
    -> vocera_media_captures and vocera_media_stream_samples PostgreSQL tables
    -> Grafana "Vocera Media PCAP QoE" capture-time panels
```

Manual WLC sessions add a session and attempt ledger beside the per-capture
stream tables:

```text
manual WLC capture session
  -> operator runs long EPC ring buffer and marks attempts
  -> tools/vocera_media_qoe/vocera_wlc_session.py
  -> vocera_media_capture_sessions and session events
  -> exported PCAP plus saved CLI transcripts
  -> optional legacy tools/vocera_media_qoe/vocera_wlc_attempt.py ingest
  -> validation/ingest-report.json and PCAP sidecars
  -> vocera_media_broadcast_attempts, artifacts, snapshots, findings
```

The first WLC session implementation generates bounded ring-buffer commands,
tracks operator markers, stores dynamic multicast group metadata, and parses
multicast membership evidence. It does not decode CAPWAP or claim RTP quality
from outer CAPWAP-only captures.

Prometheus textfile output is a freshness and parser-health snapshot. The
capture-time Grafana panels use PostgreSQL because packet captures have their
own timestamps and should not be plotted at scrape time.

## Components

### Config

Primary config: `config/vocera-media-qoe.yaml`.

Important fields:

- `site` and `capture_point`: low-cardinality labels.
- `expected_dscp`: DSCP value considered correct for media, normally EF `46`.
- `servers`: named Vocera server IPs.
- `badge_subnets`: networks classified as badge endpoints.
- `devices`: optional named endpoint IPs used for controlled A/B comparison.
  Use `role: control` for the production-config badge and `role: test` for
  the alternate-config badge. The `config` label should describe the applied
  configuration, for example `production` or `test`.
- `media_ports`: optional UDP port filter. Empty means discovery mode.
- `payload_clock_rates`: RTP payload type to clock-rate mapping.
- `max_capture_future_skew_seconds`: future pcap timestamp tolerance.
- `min_rtp_qoe_packets`: minimum same-flow/same-SSRC packet count before RTP
  QoE metrics are emitted.
- `max_rtp_transit_delta_seconds`: maximum plausible RTP arrival/timestamp
  transit delta used in jitter math.

### Parser

Primary file: `tools/vocera_media_qoe/vocera_media_qoe.py`.

The parser reads classic pcap and pcapng, supports Ethernet and unencrypted
radiotap 802.11 frames, extracts IPv4 UDP packets, classifies endpoint roles,
and groups packets by flow. RTP groups are further keyed by SSRC and payload
type.

RTP stream output includes:

- `jitter_ms`
- `expected_packets`
- `lost_packets`
- `loss_ratio`
- `duplicate_packets`
- `out_of_order_packets`
- `interarrival_p50_ms`
- `interarrival_p95_ms`
- `interarrival_max_ms`
- `packet_rate_pps`
- `clock_rate_known`

Generic UDP output omits RTP-specific fields and uses
`measurement_mode=udp_interarrival_only`.

Configured device comparison fields are attached to every stream:

- `device_name`
- `device_role`
- `device_config`
- `peer_device_name`
- `peer_device_role`
- `peer_device_config`

The parser matches configured devices by IP address because stream records are
decoded from IPv4/UDP payloads. MAC addresses may be kept in config for human
reference, but the comparison labels are assigned from IPs. If exactly one side
of a stream matches a configured device, that endpoint is the primary device.
If both sides match, the source endpoint is primary and the destination endpoint
is recorded as the peer. This keeps direct device-to-device captures usable
without hiding which endpoint transmitted the stream.

### Batch Publisher And Cache

Primary file: `tools/vocera_media_qoe/vocera_media_qoe_batch.py`.

The batch publisher scans the raw directory, parses missing or stale captures,
publishes the newest capture snapshot, and writes run archives. Cache identity
includes source path, size, mtime, DNAC sidecar size, analyzer config, and an
analyzer cache version. The version is bumped when parser semantics change so
old JSON cannot silently poison new dashboard behavior.

### SQL History

Primary files:

- `tools/vocera_media_qoe/vocera_media_qoe_sql.py`
- `sql/vocera_media_qoe_schema.sql`
- `sql/vocera_media_qoe_views.sql`

The SQL loader truncates and reloads the current capture cache into:

- `vocera_media_captures`: one row per parsed capture.
- `vocera_media_stream_samples`: one row per stream sample, including
  control/test device labels when configured.

The dashboard reads `sample_time`, `first_seen`, and `last_seen` from packet
timestamps. The views defensively ignore future capture timestamps beyond five
minutes when selecting latest capture health.

### Grafana

Dashboard files:

- `grafana/dashboards-prod/Platform - Wireless RF/vocera-media-pcap-qoe__vocera_media_pcap_qoe.json`
- `grafana/dashboards-dev/Platform - Wireless RF/vocera-media-pcap-qoe__vocera_media_pcap_qoe.json`

The dashboard separates:

- Parser health and capture age.
- Control/test device comparison.
- RTP-visible streams.
- RFC 3550 jitter and bounded sequence loss.
- RTP packet interarrival cadence.
- DSCP and volume.
- Detailed stream table.

RTP panels require `measurement_mode='rtp'`, sane sample time, and
`packet_count >= 20`. Sparse UDP/control traffic remains visible in the stream
table without driving QoE charts.

The control/test row groups RTP streams by configured `device_role` and
`device_config`. It plots per-capture p95 jitter and p95 packet loss for
`control` and `test`, then provides a summary table where `delta` is
`test_value - control_value`. Positive jitter or loss delta means the test
configuration performed worse for the selected time range; negative delta means
the test configuration performed better.

## Accuracy Guardrails

### Future Capture Timestamp Quarantine

Problem: Some captures contained mostly June 2026 packet timestamps plus a
small number of packet records dated months in the future. The dashboard used
`max(capture_time)`, so capture age became negative and graph ranges stretched
into the future.

Fix:

- `max_capture_future_skew_seconds` defaults to `300`.
- UDP packets later than collector time plus that tolerance are counted as
  `timestamp_outlier_packets` and excluded from stream timing.
- Capture-age SQL also ignores future timestamps defensively.
- Cache version was bumped so old parsed JSON is regenerated.

Why this is correct: pcap and pcapng timestamps are packet-capture timestamps,
but a packet timestamp later than the collector clock is not a valid historical
QoE sample for this dashboard. Preserving the count makes the corruption
auditable without letting it define freshness or chart scale.

### Sparse RTP-Looking Fragments

Problem: Two RTP-looking packets could be classified as RTP and produce 100%
packet loss or large jitter. These were not enough evidence for a real media
stream.

Fix:

- RTP QoE requires at least `min_rtp_qoe_packets`, default `20`.
- Sparse RTP-looking groups fall back to UDP timing only.
- Grafana RTP panels also require `packet_count >= 20`.

Why this is correct: RTP headers can be syntactically present in tiny fragments
or misclassified packets. QoE metrics should be emitted only when there is
enough sequence and timestamp evidence to establish a stream.

### Large RTP Sequence Jumps

Problem: A large sequence jump was treated as thousands of missing packets,
creating 100% loss rows. This is wrong for corrupt headers, capture artifacts,
or source restarts.

Fix:

- RTP loss now uses RFC 3550 Appendix A.1 boundary values:
  `RTP_MAX_DROPOUT=3000`, `RTP_MAX_MISORDER=100`, and `RTP_SEQ_MOD=65536`.
- Small forward gaps count as loss.
- Small backward movement counts as misorder.
- Large jumps are ignored unless a restart is confirmed by the next sequence.

Why this is correct: RFC 3550 treats large sequence jumps as invalid/restart
candidates, not ordinary packet loss.

### RTP Timestamp Discontinuities

Problem: Some long RTP streams had RTP timestamp jumps of hundreds or thousands
of seconds between packets that arrived milliseconds apart. The RFC jitter
formula is correct, but feeding it corrupt timestamp discontinuities caused
large non-physical jitter values.

Fix:

- `max_rtp_transit_delta_seconds` defaults to `1.0`.
- Packet pairs whose RTP transit delta exceeds that threshold reset the jitter
  baseline and do not update the smoothed jitter estimate.

Why this is correct: receiver-side RTP jitter measures variation in sender
packet spacing versus receiver arrival spacing. A timestamp jump far outside
the live packet cadence is a source discontinuity or corrupt header, not a
valid jitter sample.

### Unknown RTP Clock Rates

Problem: RTP payload types not listed in `payload_clock_rates` used the default
8 kHz clock silently. For a 16 kHz or other dynamic codec, jitter would be
scaled incorrectly.

Fix:

- `clock_rate_known` is written into JSON/SQL stream output.
- Prometheus emits `vocera_media_rtp_unknown_clock_streams` when fallback clock
  rates are used.

Operational rule: Treat unknown-clock jitter as suspect until the payload type
is mapped or verified.

### Raw UDP Max Gaps

Problem: The dashboard plotted maximum interarrival gaps across all UDP streams.
Low-rate DNS/control traffic and idle gaps produced large values that scaled
the chart away from media behavior.

Fix:

- RTP timing charts plot only RTP streams with enough packets.
- Raw UDP and sparse/control flows stay visible in the detailed stream table.
- `interarrival_max_ms` is preserved for investigation but is not treated as
  the primary QoE signal.

Operational rule: Use RFC 3550 jitter for RTP QoE. Use UDP interarrival stats
only as packet-cadence evidence, especially when RTP headers are not visible.

### Partial Downloads

Problem: Catalyst Center can expose a pcap before the local download is
complete. Parsing a partial file can produce invalid timestamps and misleading
QoE samples.

Fix:

- If DNAC sidecar metadata includes `capture.fileSize`, the batch parser
  rejects local files whose size does not match.

### Cache Staleness

Problem: Parser fixes do not help if old per-capture JSON remains trusted.

Fix:

- Cache identity includes `analyzer_cache_version`.
- Cache identity includes the configured device map, so swapping which badge is
  `control` or `test` forces a reparse.
- The SQL history loader rejects cache files whose analyzer version does not
  match the current parser.

Operational rule: After parser math changes, deploy the new code and run the
publisher. It should reparse old captures automatically because the cache
version changed.

## Operational Problems Solved

These were not measurement math bugs, but they were required to make the
pipeline work reliably.

- Grafana datasource passwords were moved out of source-controlled datasource
  YAML and into materialized secret env files.
- PostgreSQL role passwords can be synchronized from materialized secrets so
  Grafana and the DB agree.
- Grafana datasource provisioning reads secrets through systemd
  `EnvironmentFile` drop-ins.
- The textfile publisher must run with permission to write the node_exporter
  textfile directory.
- Capture-time panels use PostgreSQL history instead of Prometheus scrape time,
  so stale or historical captures remain visible at their packet time.

## Interpreting Remaining High Values

After the guardrails above, remaining high RTP jitter or loss should be treated
as evidence, not parser corruption, but it still needs context:

- High jitter with duplicate/out-of-order counters usually means arrival-order
  disruption inside the capture.
- High loss on a long stream means bounded RTP sequence gaps were observed.
- Unknown payload clock means the jitter value may be scaled wrong.
- Large `interarrival_max_ms` in the table may be an idle gap, not voice jitter.
- A nonzero `timestamp_outlier_packets` means the pcap file contains invalid
  future packet records.

## Validation

Regression coverage lives in `scripts/test_vocera_media_qoe.py`.

Key tests cover:

- RFC jitter/loss/duplicate/out-of-order basics.
- Control/test device labeling through parser, JSON, Prometheus, and SQL input.
- Unknown RTP clock visibility.
- Sparse RTP candidates falling back to UDP timing.
- Large RTP sequence jumps not becoming massive loss.
- Large RTP timestamp jumps not poisoning jitter.
- Future pcap timestamps being quarantined.
- pcapng timestamp decoding.
- Partial DNAC download rejection and SQL history emission.

Run:

```bash
PYTHONPATH=tools/vocera_media_qoe:tools/wireless_rf python3 scripts/test_vocera_media_qoe.py
python3 scripts/check_dashboards.py
```

## References

- RFC 3550 RTP jitter and sequence validation:
  https://www.rfc-editor.org/rfc/rfc3550
- Classic pcap timestamp format:
  https://www.ietf.org/archive/id/draft-ietf-opsawg-pcap-00.html
- pcapng enhanced packet timestamps:
  https://datatracker.ietf.org/doc/html/draft-tuexen-opsawg-pcapng-03
