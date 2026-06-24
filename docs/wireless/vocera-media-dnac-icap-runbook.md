# Vocera Media DNAC ICAP Runbook

This runbook uses Catalyst Center Intelligent Capture packet captures as the
input to the offline Vocera media QoE analyzer:

```text
Catalyst Center / DNAC Intelligent Capture
  -> AP/client/full/OTA capture pcap
  -> download pcap to collectors01 manually or with client-MAC ICAP downloader
  -> tools/vocera_media_qoe/vocera_media_qoe.py
  -> vocera_media_qoe.prom
  -> node_exporter textfile collector
  -> Prometheus
  -> Mimir
  -> Grafana health snapshots
  -> PostgreSQL capture-time history
  -> Grafana QoE time series at packet time
```

The analyzer can prove media arrival quality at the capture point. If RTP
headers are visible, it calculates RTP sequence loss, duplicate packets,
out-of-order packets, and RFC 3550 interarrival jitter. If RTP headers are not
visible, it reports generic UDP interarrival timing, packet rate, bytes, and
DSCP only. Do not label non-RTP UDP as RTP jitter or RTP packet loss.

## Capture Choice

Use this order:

1. Full Packet Capture for the Vocera badge client.
2. OTA Sniffer Capture on the AP and channel.
3. Onboarding Packet Capture only for association, authentication, DHCP, or roam
   join-event troubleshooting.

Full Packet Capture is the first choice for media-path analysis because it has
the best chance of exposing decrypted IP/UDP/RTP headers, depending on where the
AP and Catalyst Center export the capture. OTA Sniffer Capture is better for
802.11, WMM, retry, data-rate, RSSI, channel, and airtime behavior, but WPA2 or
WPA3 payloads may still be encrypted. Onboarding Packet Capture is not a
steady-state RTP media capture.

## Manual Workflow

Start with one controlled badge call before building any API automation.

In Catalyst Center:

```text
Assurance
  -> Client Health
  -> open the Vocera badge Client 360
  -> Intelligent Capture
  -> Full Packet Capture
  -> run capture during a controlled badge call
  -> download pcap
```

Use filenames that preserve capture metadata:

```text
vocera-full-badgeA-to-server-20260521-143000.pcap
vocera-ota-ap-SF1-CathLab-2-ch36-20260521-143000.pcap
```

On collectors01:

```bash
mkdir -p /var/lib/vocera-media-qoe/raw
mkdir -p /var/lib/vocera-media-qoe/out

cp <downloaded-file>.pcap /var/lib/vocera-media-qoe/raw/
```

Create a site config from the example:

```bash
cd /home/appsadmin/grafana-mimir-observability

cp config/vocera-media-qoe.example.yaml config/vocera-media-qoe.yaml
vi config/vocera-media-qoe.yaml
```

Example:

```yaml
site: srhc
capture_point: dnac_icap_full_client_capture
expected_dscp: 46

servers:
  - name: vocera-server
    ip: 10.205.0.20

badge_subnets:
  - 10.16.88.0/22
  - <other_badge_subnet_here>

media_ports:
  - "16384-32767"

payload_clock_rates:
  default: 8000
  0: 8000
  8: 8000
  9: 8000
  18: 8000
```

During discovery, leave `media_ports` broad or empty. After the real Vocera
media ports are known, tighten the range.

Run the analyzer directly when you want to inspect one file without publishing
to node exporter:

```bash
cd /home/appsadmin/grafana-mimir-observability

PYTHONPATH=tools/vocera_media_qoe python3 -m vocera_media_qoe \
  --pcap /var/lib/vocera-media-qoe/raw/<capture-file>.pcap \
  --config config/vocera-media-qoe.yaml \
  --prom-out data/vocera-media-qoe/out/vocera_media_qoe.prom \
  --json-out data/vocera-media-qoe/out/vocera_media_qoe_summary.json
```

Validate output:

```bash
promtool check metrics < data/vocera-media-qoe/out/vocera_media_qoe.prom

jq '.streams[] | {
  direction,
  measurement_mode,
  src_role,
  dst_role,
  dscp,
  packet_count,
  lost_packets,
  loss_ratio,
  jitter_ms,
  interarrival_p95_ms,
  dscp_mismatch
}' data/vocera-media-qoe/out/vocera_media_qoe_summary.json
```

Publish to node exporter:

```bash
sudo bash ./scripts/install_vocera_media_qoe_textfile.sh --enable --start-now

# After new pcaps are copied into /var/lib/vocera-media-qoe/raw, the timer
# republishes the newest .pcap or .cap every minute. For an immediate one-shot:
make vocera-media-qoe-publish VOCERA_MEDIA_QOE_CONFIG=config/vocera-media-qoe.yaml

curl -s http://127.0.0.1:9100/metrics | grep 'vocera_media_' | head -100
```

The publisher intentionally handles an empty raw directory by publishing
`vocera_media_capture_parse_success` as `0`; that keeps the systemd timer
healthy while still making the missing capture visible.

The textfile publisher does not query Catalyst Center. It scans
`/var/lib/vocera-media-qoe/raw`, parses every `.pcap`, `.cap`, or `.pcapng`
whose cached output is missing or stale, stores per-capture outputs under
`data/vocera-media-qoe/out/captures`, and publishes the newest local capture
snapshot to node_exporter.

Each publisher run also writes a ZIP run archive under
`data/vocera-media-qoe/out/archives` by default. The archive contains the PCAPs
parsed or published by that run, Catalyst Center sidecar JSON when present,
generated outputs, `manifest.json`, and `logs/run.log`. Use
`VOCERA_MEDIA_QOE_ARCHIVE_DIR=/path/to/archives` to change the destination.

The publisher rejects partial Catalyst Center downloads when a sidecar
`capture.fileSize` is present and does not match the local pcap size. That keeps
truncated captures from producing incorrect packet timestamps or QoE samples.

## Capture-Time Grafana History

Prometheus textfile samples are timestamped when node_exporter is scraped, not
when the packet was captured. The QoE time-series panels therefore read
PostgreSQL history from datasource UID `VOCERA_MEDIA_QOE_DS`; each row uses the
stream `last_seen` packet timestamp as `sample_time`.

Install the local history database:

```bash
make vocera-media-qoe-postgres-install
```

Parse local captures, emit SQL, and load the history database:

```bash
set -a; source /etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env; set +a
make vocera-media-qoe-publish \
  VOCERA_MEDIA_QOE_DATABASE_URL="postgresql://vocera_media_qoe:${VOCERA_MEDIA_QOE_POSTGRES_PASSWORD}@127.0.0.1:15434/vocera_media_qoe" \
  VOCERA_MEDIA_QOE_PSQL_BIN=scripts/vocera_media_qoe_psql_in_container.sh
```

For the systemd timer, do *not* hard-code the password into
`/etc/default/vocera-media-qoe-textfile`; instead reference the env file the
sops install writes, and build the URL at run time from
`$VOCERA_MEDIA_QOE_POSTGRES_PASSWORD`:

```bash
# /etc/default/vocera-media-qoe-textfile
VOCERA_MEDIA_QOE_PSQL_BIN=scripts/vocera_media_qoe_psql_in_container.sh
# (password is loaded via systemd EnvironmentFile=-/etc/grafana-mimir-observability/secrets/vocera-media-qoe-postgres.env)
```

## DNAC ICAP Download

After the manual flow proves the capture format, use the existing Catalyst
Center read-only secret for operator-run downloads of completed ICAP captures.
Do not put personal DNAC credentials in `/etc/default/vocera-media-qoe-textfile`.

The DNAC connection values live in:

```bash
/etc/grafana-mimir-observability/secrets/dnac-readonly.env

DNAC_BASE_URL=https://catalyst-center.example.org
DNAC_USERNAME=<api_user>
DNAC_PASSWORD=<api_password>
DNAC_VERIFY_TLS=true
```

Keep ICAP workflow filters in the operator shell or another non-secret config:

```bash
VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE=FULL
VOCERA_MEDIA_QOE_DNAC_LIMIT=20
```

Then run one download by hand:

```bash
cd /home/appsadmin/grafana-mimir-observability

make vocera-media-qoe-dnac-download \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
```

The downloader uses Catalyst Center's ICAP capture-file API to list capture
files by `type` and `clientMac`, selects the newest match, downloads it under
`/var/lib/vocera-media-qoe/raw`, and writes a JSON sidecar beside the PCAP. The
scheduled publisher will pick it up from the raw directory on its next run.

Check API exposure without starting a capture:

```bash
make vocera-media-qoe-dnac-check-api \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
```

The check validates client-detail lookup and the ICAP capture-file list API
through the read-only client. `icap_capture_files.ok=true` means
completed-capture download automation is exposed. Starting captures through
this repo is intentionally unavailable; start ICAP captures in Catalyst Center
or another approved Cisco-supported workflow, then use this repo to list and
download the completed capture.

## Grafana Checks

Use the `Vocera Media PCAP QoE` dashboard for this pipeline. Keep it separate
from `Vocera Iperf QoE`.

Interpret `measurement_mode` first:

```text
measurement_mode="rtp":
  RTP headers were visible. RTP jitter, sequence loss, duplicates, and
  out-of-order packet metrics are valid for the capture point.

measurement_mode="udp_interarrival_only":
  RTP headers were not visible. Use UDP interarrival timing, packet counts,
  bytes, and DSCP. Do not call these RTP jitter or RTP packet loss.
```

The JSON summary is the investigation artifact for exact IPs, ports, SSRCs, and
stream IDs. Prometheus intentionally keeps lower-cardinality labels only.

## Latency Boundary

A single AP/Catalyst Center capture can show arrival timing at that capture
point, RTP sequence behavior when RTP is visible, DSCP marking, and possibly
over-the-air QoS treatment when OTA headers are useful.

It cannot prove mouth-to-ear latency, true one-way latency, server-to-badge
receive quality from a badge-side perspective, badge jitter-buffer behavior, or
MOS. For true one-way latency, use synchronized capture points, endpoint RTP or
RTCP statistics, application timestamps, or a separately labeled synthetic
probe.

## Automation Boundary

The repo downloader handles completed capture-file discovery and download:

```text
dnac_icap_downloader.py
  -> authenticate to Catalyst Center
  -> list completed ICAP capture files for a specified client MAC
  -> download newest pcap to /var/lib/vocera-media-qoe/raw/
  -> publisher scans /var/lib/vocera-media-qoe/raw/
  -> parse unprocessed pcaps and cache per-capture outputs
  -> publish newest local capture as vocera_media_qoe.prom
```

Catalyst Center capture start, settings deployment, and device-command
workflows are intentionally outside this repo.

Cisco DevNet documents ICAP capture file list, detail, and download endpoints
under `/dna/data/api/v1/icap/captureFiles`. The Ansible Catalyst Center ICAP
workflow module also exposes capture types such as `FULL`, `ONBOARDING`, `OTA`,
`RFSTATS`, and `ANOMALY`.

## Sources

- Cisco Catalyst Assurance User Guide, Manage Intelligent Capture:
  https://www.cisco.com/c/en/us/td/docs/cloud-systems-management/network-automation-and-management/catalyst-center-assurance/2-3-7/b_cisco_catalyst_assurance_2_3_7_ug/b_cisco_catalyst_assurance_2_3_6_ug_chapter_01110.html
- Cisco DevNet Catalyst Center ICAP capture file details:
  https://developer.cisco.com/docs/catalyst-center/2-3-7-9/retrieves-details-of-a-specific-icap-packet-capture-file/
- Cisco DevNet Catalyst Center ICAP capture file list:
  https://developer.cisco.com/docs/dna-center/lists-icap-packet-capture-files-matching-specified-criteria/
- Cisco DevNet Catalyst Center ICAP capture file download:
  https://developer.cisco.com/docs/dna-center/downloads-a-specific-icap-packet-capture-file/
