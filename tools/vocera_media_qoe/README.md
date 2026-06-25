# Vocera media QoE tooling

This package analyzes offline PCAP/PCAPNG files and preserves detailed
capture/stream evidence outside Prometheus. It supports three distinct lanes:

1. **Completed Catalyst Center ICAP** — discovered/downloaded read-only into the
   generic raw area.
2. **Explicit Imported PCAP** — another approved capture point, registered
   intentionally as imported evidence.
3. **Manual WLC EPC session** — a WLC outbound SCP export into a dedicated
   session package, ingested only by the session importer.

Do not blur these lanes. A manual WLC EPC must not be shown as an ICAP capture,
and a generic batch scan must not discover WLC session/attempt directories.

## Evidence boundary

The parser measures packets visible in the supplied capture. It can produce
UDP cadence/DSCP facts and, only when RTP plausibility criteria are satisfied,
RTP sequence/jitter/loss/duplicate/reorder facts. It cannot prove MOS,
mouth-to-ear latency, one-way latency, or receiver-side experience at a
different capture point.

## Generic PCAP parsing

```bash
make vocera-media-qoe-parse \
  VOCERA_MEDIA_QOE_PCAP=/path/to/capture.pcap \
  VOCERA_MEDIA_QOE_CONFIG=config/vocera-media-qoe.yaml
```

For the scheduled generic publisher, configure the raw area and keep WLC
package roots excluded:

```text
VOCERA_MEDIA_QOE_RAW_DIR=/var/lib/vocera-media-qoe/raw
VOCERA_MEDIA_QOE_BATCH_EXCLUDE_DIRS=wlc-sessions,wlc-attempts
```

The output includes bounded `.prom` health/current metrics plus detailed JSON,
optional PostgreSQL lineage, and optional run artifacts.

## Completed ICAP files

The read-only Catalyst Center path can list/download completed ICAP files but
cannot request a capture or change device/controller settings:

```bash
make vocera-media-qoe-dnac-check-api \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46

make vocera-media-qoe-dnac-download \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
```

See [`../../docs/wireless/vocera-media-dnac-icap-runbook.md`](../../docs/wireless/vocera-media-dnac-icap-runbook.md).

## Manual WLC capture session

Create a session through Study Web or the CLI package generator. The WLC
operator runs generated command sheets and exports to the package `incoming/`
directory. When installed/enabled after rehearsal,
`vocera-media-qoe-wlc-session-ingest.timer` owns the rest:

```text
incoming/ -> stable upload -> pcap validation + SHA-256 -> pcaps/
         -> capture_point=wlc_epc -> parser -> Study Web artifact status
```

```bash
make vocera-media-qoe-wlc-session-init \
  STUDY_ID=study_v5000_c1000_multicast \
  SESSION_ID=<session-id> \
  WLC_NAME=SRHC-WLC-40G-SEC \
  WLC_INTERFACE=Port-channel1 \
  COLLECTOR_HOST=10.0.128.107 \
  COLLECTOR_SCP_USERNAME=appsadmin \
  V5000_MAC=00:09:ef:54:5f:46 V5000_IP=<sender-ip> \
  C1000_MAC=00:09:ef:61:0b:f7 C1000_IP=<receiver-ip>
```

Do not run the generic publisher against session packages or manually move a
pending file from `incoming/` to `pcaps/`. See
[`../../docs/wireless/vocera-wlc-continuous-capture-runbook.md`](../../docs/wireless/vocera-wlc-continuous-capture-runbook.md)
and [`../../docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md`](../../docs/wireless/vocera-wlc-phase0-ingest-rehearsal-runbook.md).

## Legacy short attempts

`vocera_wlc_attempt` remains for older, self-contained single-attempt bundles.
It is explicit/manual and does not replace the long-session automated importer:

```bash
make vocera-media-qoe-wlc-attempt-validate ATTEMPT_DIR=<attempt-dir>
make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=<attempt-dir>
```

## Current visualization status

The Media QoE datasource and Study Web review are available, but the current
tracked Grafana inventory does not include a Media QoE dashboard. Use Study Web
or PostgreSQL-supported review until a dashboard is deliberately added and
validated.
