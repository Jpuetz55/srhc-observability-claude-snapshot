# Vocera WLC Continuous Capture Runbook

This workflow is for intermittent V5000 to C1000 broadcast failures. It uses a
long-running manual WLC EPC session with a bounded circular file buffer. The
repo generates command sheets and records markers, but it does not log in to
the WLC.

Cisco documents that physical Catalyst 9800 controllers should use the port
channel when one is configured, that circular EPC files act as a ring buffer,
and that continuous capture requires a circular buffer:

https://www.cisco.com/c/en/us/td/docs/wireless/controller/9800/17-18/config-guide/b_wl_17_18_cg/m_embedded_packet_capture.html

## Create the session

Use Study Web:

```text
Vocera multicast -> Vocera Multicast Capture Sessions -> Create Session
```

Or use the CLI package generator:

```bash
make vocera-media-qoe-wlc-session-init \
  STUDY_ID=study_v5000_c1000_multicast \
  SESSION_ID=20260623T160000-v5000-c1000-session-001 \
  WLC_NAME=SRHC-WLC-40G-SEC \
  WLC_INTERFACE=Port-channel1 \
  VOCERA_VLAN=684 \
  COLLECTOR_HOST=10.0.128.107 \
  COLLECTOR_SCP_USERNAME=appsadmin \
  V5000_MAC=00:09:ef:54:5f:46 \
  V5000_IP=10.16.88.228 \
  C1000_MAC=00:09:ef:61:0b:f7 \
  C1000_IP=10.16.88.230
```

The generated package includes:

```text
clock-check.cli
baseline.cli
start-long.cli
start-short-validation.cli
stop-export.cli
active-event.cli
resolved-active-group.cli
post-failure.cli
ap-evidence.cli
cleanup.cli
session.json
session-events.json
```

## Long reproduction mode

Use `start-long.cli` for the real intermittent failure reproduction. It has no
duration limit. It configures:

```text
Port-channel 1, both directions
5 circular files
100 MB per file
500 MB total ring
temporary ACL for 230.230.0.0/20, IGMP, V5000, and C1000 evidence
inner MAC filters for the sender and receiver badges
```

The ring-buffer command uses the documented EPC circular-file syntax:

```text
monitor capture <capture_name> buffer circular file 5 file-size 100
```

Do not estimate retention minutes from the ring size. Retention depends on
packet rate.

## Mark attempts

While the EPC session runs, mark each broadcast in Study Web:

```text
broadcast started
heard
missed
partial
choppy
alert only
session end
```

Each marker stores collector/browser time. Result markers also create
attempt rows tied to the capture session.

## VLAN context

The configured Vocera multicast VLAN defaults to `684`. This is the value used
to generate multicast-group, IGMP, MGID, and source queries unless the operator
changes it before creating the session.

Do not overwrite the configured VLAN from badge client-detail output. The
workflow tracks these as separate facts:

```text
configured Vocera multicast VLAN
sender/receiver client VLAN observations
sender/receiver multicast VLAN observations
resolved active group VLAN
```

If `show wireless multicast group summary` shows an active `230.230.x.x` group,
paste the summary into Study Web and explicitly select the correct row. If the
selected group VLAN differs from the configured VLAN, enter an override reason
before using the resolved-group command sheet.

## Stop and export

When the failure reproduces:

1. Mark the outcome in Study Web.
2. Run `stop-export.cli`.
3. Save candidate active state with `active-event.cli`.
4. Paste `show wireless multicast group summary` into Study Web and select the active group/VLAN row.
5. Run `resolved-active-group.cli` and save that transcript.
6. Run `post-failure.cli`.
7. Confirm the PCAP landed under the session package.
8. Run `cleanup.cli`.

Every session must end with:

```text
show monitor capture <name>
no monitor capture <name>
show monitor capture <name>
```

If the temporary ACL was configured, cleanup also removes it:

```text
no ip access-list extended <temporary-name>
```
