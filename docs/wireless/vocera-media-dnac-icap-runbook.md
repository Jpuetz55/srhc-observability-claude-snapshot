# Completed Catalyst Center ICAP PCAP workflow

This runbook analyzes **already completed** Catalyst Center Intelligent Capture
(ICAP) files. The repository's Catalyst Center integration is read-only:

- authenticate with the approved read-only service account;
- list eligible completed capture files;
- download a selected completed file to the collector; and
- register/parse that file as media evidence.

It cannot start a capture, alter ICAP settings, deploy controller configuration,
invoke Command Runner, or SSH to a WLC.

## Choose the correct evidence lane

| Evidence source | Use this runbook? | Correct location |
| --- | --- | --- |
| completed Catalyst Center ICAP PCAP | yes | generic media raw area / ICAP page |
| PCAP copied from another approved capture point | yes, after explicit registration | generic media raw area / Imported PCAP path |
| manual WLC EPC ring-buffer export | no | WLC capture-session package / Vocera multicast page |
| WLC CLI transcript | no | session `cli/` evidence |

A WLC EPC is not an ICAP capture. Keep it in `wlc-sessions/`; the Phase 0
session importer owns it and the generic ICAP batch scan excludes it.

## Prerequisites

The runtime read-only credential file normally lives outside Git:

```text
/etc/grafana-mimir-observability/secrets/dnac-readonly.env
```

It must contain the endpoint/account/token-or-password/TLS policy expected by
the existing read-only client. Do not place this file or its contents in the
repository.

Verify API readiness without changing Catalyst Center:

```bash
make vocera-media-qoe-dnac-check-api \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46
```

Success proves completed-capture discovery for the supplied filter. It does not
prove the assurance pipeline is healthy for a future capture request.

## Download a completed capture

```bash
make vocera-media-qoe-dnac-download \
  VOCERA_MEDIA_QOE_ENV_FILE=/etc/grafana-mimir-observability/secrets/dnac-readonly.env \
  VOCERA_MEDIA_QOE_DNAC_CLIENT_MAC=00:09:ef:54:5f:46 \
  VOCERA_MEDIA_QOE_DNAC_CAPTURE_TYPE=FULL
```

The downloader stores the file and metadata sidecar under the configured
generic raw area. Study Web provides the equivalent read-only discovery,
download, registration, parser execution, and review workflow.

## Parse and retain history

Install the DB and generic media publisher only after the raw-data paths and
runtime secret material are correct:

```bash
make vocera-media-qoe-postgres-install
make vocera-media-qoe-install
make vocera-media-qoe-publish VOCERA_MEDIA_QOE_CONFIG=config/vocera-media-qoe.yaml
```

The parser stores detailed capture/stream history in PostgreSQL when configured
and emits a low-cardinality health snapshot through node_exporter. The current
tracked Grafana inventory does not include a Media QoE dashboard; use Study Web
or database-supported review rather than assuming one is provisioned.

## Interpret results correctly

Read `measurement_mode` before interpreting any stream:

```text
rtp
  RTP headers were plausibly visible for enough packets. Sequence/jitter
  calculations describe this capture point only.

udp_interarrival_only
  RTP was not proven. Use cadence, bytes, packet count, direction, and DSCP;
  do not call the result RTP jitter or packet loss.
```

Neither mode proves mouth-to-ear latency, one-way latency, endpoint receive
quality at another point, jitter-buffer behavior, or MOS.
