# Vocera WLC CLI Media QoE Runbook

This attempt-only workflow is retained for legacy bundles and short validation
captures. For intermittent production failures, prefer
`docs/wireless/vocera-wlc-continuous-capture-runbook.md`, which models one long
capture session with many timestamped attempts.

This workflow is manual by design. The operator enters WLC commands, saves
transcripts, exports PCAPs, and moves the artifacts to the collector. The repo
then validates, parses, stores, and summarizes the evidence.

## Create An Attempt

```bash
make vocera-media-qoe-wlc-attempt-init \
  STUDY_ID=study_v5000_c1000_multicast \
  ATTEMPT_ID=20260623T143015-attempt-002 \
  WLC_NAME=SRHC-WLC-40G-SEC \
  V5000_MAC=<V5000_MAC> \
  V5000_IP=<V5000_IP> \
  C1000_MAC=<C1000_MAC> \
  C1000_IP=<C1000_IP> \
  VOCERA_VLAN=684
```

The generated package contains command sheets, `manifest.json`,
`operator-observation.json`, and directories for `cli/`, `pcaps/`, `notes/`,
and `validation/`.

## Collect Evidence

Enable terminal logging in the WLC terminal before pasting command sheets.

Run in order:

1. `before.cli`
2. `epc-start.cli`
3. Start the V5000 broadcast.
4. `during.cli`, replacing `<VOCERA_GROUP>` after reading the group summary.
5. `epc-stop-export.cli`
6. `after.cli`
7. `cleanup.cli` if any capture session remains.

Save outputs as:

```text
cli/before.txt
cli/during.txt
cli/after.txt
pcaps/wlc-epc.pcap
```

Update `operator-observation.json` or run:

```bash
make vocera-media-qoe-wlc-attempt-record \
  ATTEMPT_DIR=/var/lib/vocera-media-qoe/raw/wlc-attempts/study_v5000_c1000_multicast/20260623T143015-attempt-002 \
  AUDIO_RESULT=missed \
  ALERT_RESULT=true \
  OPERATOR_NOTES="C1000 got alert tone but no voice."
```

## Ingest

```bash
make vocera-media-qoe-wlc-attempt-ingest \
  ATTEMPT_DIR=/var/lib/vocera-media-qoe/raw/wlc-attempts/study_v5000_c1000_multicast/20260623T143015-attempt-002
```

The ingest writes:

```text
validation/ingest-report.json
validation/attempt-import.sql
pcaps/*.pcap.json
```

When `VOCERA_MEDIA_QOE_DATABASE_URL` is set, the ingest command also loads the
attempt ledger into PostgreSQL through `VOCERA_MEDIA_QOE_PSQL_BIN`.

## Safety Rules

- Always run `show monitor capture <session>` before start.
- Always run `no monitor capture <session>` after export.
- Never leave EPC running after the attempt.
- Never treat an undecodable or encrypted capture as proof that multicast was absent.
- Never use AP packet-capture scope changes on shared AP profiles without validating AP impact first.

## Source Basis

Cisco documents the WLC 9800 Vocera flow as multicast group assignment,
IGMP join tracking, WLC multicast group membership, CAPWAP forwarding to APs,
and AP forwarding to subscribed clients. The WLC verification chain includes
`show wireless multicast`, `show ap multicast mom`, group summary/detail, and
multicast source commands.

References:

- https://www.cisco.com/c/en/us/support/docs/wireless/catalyst-9800-series-wireless-controllers/225171-understand-vocera-broadcast-on-wlc-9800.html
- https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-14/config-guide/b_wl_17_14_cg/m_embedded_packet_capture.html
- https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-3/config-guide/b_wl_17_3_cg/m_ap_packet_capture.html
