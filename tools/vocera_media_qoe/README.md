# Vocera Media QoE Analyzer

`vocera_media_qoe.py` analyzes offline pcap files for server-side observed
Vocera media quality. It is intentionally separate from WLC/AP RF telemetry.
For the full parser, history, dashboard, and accuracy-guardrail architecture,
see `../../docs/wireless/vocera-media-pcap-qoe-architecture.md`.

The parser emits low-cardinality Prometheus snapshot gauges, writes
high-cardinality stream details to JSON, and can emit/load PostgreSQL history so
Grafana plots each stream sample at the packet timestamp from the capture.
Packets whose pcap timestamps are later than the collector clock plus the
configured `max_capture_future_skew_seconds` tolerance are counted as timestamp
outliers and excluded from stream timing calculations.
RTP QoE metrics are only emitted after at least `min_rtp_qoe_packets` packets
are observed for the same flow, SSRC, and payload type; sparse RTP-looking
fragments remain UDP timing observations.
RTP timestamp/arrival deltas larger than `max_rtp_transit_delta_seconds` reset
the jitter baseline because they indicate a source discontinuity or corrupt RTP
header, not a physically plausible interarrival jitter sample.

## What It Can Prove

- Badge-to-server media arrival quality at the capture point.
- RTP interarrival jitter and estimated packet loss when RTP headers are
  visible.
- UDP interarrival timing, packet rate, bytes, and DSCP marking when RTP headers
  are not visible.

## What It Must Not Claim

- End-to-end call quality.
- MOS.
- One-way latency.
- Server-to-badge receive quality from a server-side capture.
- RTP jitter for non-RTP UDP.

## Run Offline

```bash
PYTHONPATH=tools/vocera_media_qoe python3 -m vocera_media_qoe \
  --pcap data/vocera-media-qoe/raw/example.pcap \
  --config config/vocera-media-qoe.yaml \
  --prom-out data/vocera-media-qoe/out/vocera_media_qoe.prom \
  --json-out data/vocera-media-qoe/out/vocera_media_qoe_summary.json
```

The `.prom` file is safe for node_exporter's textfile collector. The JSON file
keeps exact stream identities for investigation.

To parse local pcaps under `/var/lib/vocera-media-qoe/raw` and publish the
newest capture snapshot into node_exporter's textfile collector:

```bash
sudo bash ./scripts/install_vocera_media_qoe_textfile.sh --enable --start-now
make vocera-media-qoe-publish VOCERA_MEDIA_QOE_CONFIG=config/vocera-media-qoe.yaml
```

The publisher keeps per-capture JSON and Prometheus outputs under
`data/vocera-media-qoe/out/captures` and skips captures whose path, size, and
mtime have already been parsed. Catalyst Center ICAP sidecars are used to reject
partial downloads when the local pcap size does not match `capture.fileSize`.
Each parser run also writes a ZIP run archive under
`data/vocera-media-qoe/out/archives` by default. The archive contains the PCAPs
parsed or published by that run, matching Catalyst Center sidecars when present,
the generated parser outputs, `manifest.json`, and `logs/run.log`. Override the
location with `VOCERA_MEDIA_QOE_ARCHIVE_DIR` or `--archive-dir`.

For capture-time Grafana panels, load the PostgreSQL history:

```bash
make vocera-media-qoe-postgres-install

set -a; source /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env; set +a
make vocera-media-qoe-publish \
  VOCERA_MEDIA_QOE_DATABASE_URL="postgresql://vocera_media_qoe:${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD}@127.0.0.1:15434/vocera_media_qoe" \
  VOCERA_MEDIA_QOE_PSQL_BIN=scripts/vocera_media_qoe_psql_in_container.sh
```

The textfile metrics remain useful as parser health snapshots, but historical
QoE panels should read `vocera_media_stream_samples.sample_time`.

For control/test comparisons, set `devices:` in `config/vocera-media-qoe.yaml`.
Use `role: control` for the production-config badge and `role: test` for the
alternate-config badge. The parser matches these entries by IP address and
stores `device_name`, `device_role`, and `device_config` on each stream sample
so the Grafana comparison row can calculate `test - control` deltas.

The Grafana dashboard treats PostgreSQL rows as the **current study**, not as a
continuous monitoring history. Study lifecycle controls live on the collector in
Grafana/PostgreSQL:

- `vocera_media_archive_current_study()` snapshots the current study into
  `vocera_media_study_archives`.
- `vocera_media_archive_and_clear_current_study()` snapshots the current study
  and clears the live capture/stream rows.
- `vocera_media_clear_current_study()` clears the live capture/stream rows
  without writing an archive.
- `vocera_media_update_study_archive()` and
  `vocera_media_delete_study_archive()` maintain archive metadata.

The Windows upload script only transports PCAPs and triggers parse/load. After
a successful uploaded parse/load, `scripts/run_vocera_survey_refresh.sh`
deletes uploaded `.pcap`, `.pcapng`, and `.cap` files from the per-run upload
directory. The archive is a compact JSONB DB snapshot of the current capture
and stream rows. The dashboard shows study-level summaries, control/test
deltas, capture inventory, and archive inventory; it intentionally does not
include worst-stream drilldowns.

## Capture Guidance

Start with a short controlled call capture near the Vocera Voice Server:

```bash
tcpdump -i <interface> -nn -s 256 \
  -w /var/spool/vocera-media-qoe/vocera-%Y%m%d-%H%M%S.pcap \
  'udp and host <vocera_server_ip> and net <badge_subnet>'
```

After confirming RTP headers are visible and the media ports are known, reduce
the filter and snaplen:

```bash
tcpdump -i <interface> -nn -s 96 \
  -w /var/spool/vocera-media-qoe/vocera-%Y%m%d-%H%M%S.pcap \
  'udp and host <vocera_server_ip> and net <badge_subnet> and portrange <start>-<end>'
```

Avoid full-payload capture unless there is a specific approved troubleshooting
need.

Catalyst Center / DNAC Intelligent Capture pcaps can also be used as offline
input. Start with a Full Packet Capture for the badge client, then use OTA
Sniffer Capture for RF/WMM validation if needed.

After the manual capture format is proven, download the newest completed ICAP
capture for a specific client MAC:

```bash
PYTHONPATH=tools/vocera_media_qoe:tools/wireless_rf python3 -m vocera_dnac_icap \
  --env-file /etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  --client-mac 00:09:ef:54:5f:46 \
  --capture-type FULL \
  --out-dir /var/lib/vocera-media-qoe/raw
```

This helper is read/download-only. It can check client-detail and
completed-capture listing through the Catalyst Center read-only env file, then
download a selected completed capture:

```bash
make vocera-media-qoe-dnac-check-api \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
```

Catalyst Center capture start and settings deployment are intentionally
unavailable in this repo. Start captures in Catalyst Center or another approved
Cisco-supported workflow, then download the completed capture here.

## Manual WLC Capture Sessions

For intermittent V5000 to C1000 multicast broadcast investigations, use a
manual WLC capture session. One long EPC ring-buffer capture can contain many
timestamped heard/missed/partial/choppy attempts. The repo generates command
sheets and tracks markers, but never connects to the WLC.

```bash
make vocera-media-qoe-wlc-session-init \
  STUDY_ID=study_v5000_c1000_multicast \
  SESSION_ID=20260623T160000-v5000-c1000-session-001 \
  WLC_NAME=SRHC-WLC-40G-SEC \
  WLC_INTERFACE=Port-channel1 \
  VOCERA_VLAN=684 \
  COLLECTOR_HOST=10.0.128.107 \
  COLLECTOR_SCP_USERNAME=appsadmin \
  V5000_MAC=<V5000_MAC> \
  V5000_IP=<V5000_IP> \
  C1000_MAC=<C1000_MAC> \
  C1000_IP=<C1000_IP>
```

Study Web exposes the same workflow under Vocera multicast -> Vocera
Multicast Capture Sessions. ICAP QoE remains a separate page for completed
Catalyst Center ICAP download, capture registration, parsing, and stream
review.
The configured Vocera multicast VLAN defaults to 684 and remains separate from
badge-side client or multicast VLAN observations. Select the active 230.230.x.x
group/VLAN row from the WLC group summary before using the resolved-group
command sheet.
The app stores only host/user/port/path for SCP export. It does not store WLC
or SCP passwords.

After a session is exported, register and parse the PCAP through the normal raw
file workflow. Attempt-only packages are still supported for older evidence:

```bash
make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=<attempt_dir>
```

The ingest writes `validation/ingest-report.json`, PCAP metadata sidecars, and
`validation/attempt-import.sql`. See
`docs/wireless/vocera-wlc-continuous-capture-runbook.md`.

See `docs/wireless/vocera-media-dnac-icap-runbook.md` for the service
configuration and measurement boundaries.
