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
Vocera multicast -> Create or open investigation -> New WLC capture session
```

The WLC command sheets and event buttons are hidden until a Media QoE
investigation study is selected. After the session is created, open that
specific session before recording WLC state, attempts, active-group selection,
or artifact status; Study Web does not send actions to an implicit "latest"
session.

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

## Logged WLC console

Open the WLC from the session page command or from the Make target:

```bash
make vocera-media-qoe-wlc-session-console \
  SESSION_DIR=/var/lib/vocera-media-qoe/raw/wlc-sessions/<study>/<session> \
  WLC_SSH_HOST=10.16.59.252 \
  WLC_SSH_PORT=22 \
  WLC_SSH_USER=<operator-wlc-user>
```

This starts a normal interactive SSH session through `script(1)` output-only
logging. The operator still authenticates, pastes commands, enters the SCP
password at export time, and runs cleanup manually. The recorder writes:

```text
cli/terminal/wlc-terminal-<timestamp>.out
cli/terminal/wlc-terminal-<timestamp>.timing
cli/terminal/wlc-terminal-<timestamp>.json
```

The recorder must not use input logging (`--log-in` or `--log-io`) and must not
automate SSH. Password input is not echoed, but anything visibly printed on the
terminal becomes recorded evidence.

The collector keeps the full `.out` file as one terminal artifact, then parses it
into command-sheet blocks. Blocks are split at pasted `terminal length 0`
boundaries and classified independently as `baseline`, `capture_start`,
`active_event`, `resolved_group`, `capture_stop_export`, `post_failure`,
`ap_evidence`, `cleanup`, or `unassigned`. Only blocks with an explicit
`! Attempt: <attempt-id>` marker are automatically attached to an attempt; all
ambiguous blocks remain session-scoped evidence.

## Short validation smoke mode

Before a long incident reproduction, create a short-validation session package:

```bash
make vocera-media-qoe-wlc-session-smoke-init \
  STUDY_ID=study_v5000_c1000_multicast \
  SESSION_ID=<unique-session-id> \
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

Use `start-short-validation.cli`; it keeps the documented circular ring syntax
but adds a 90-second duration limit. The smoke test validates WLC command
syntax, SCP export to `incoming/`, automatic collector ingest, parser launch,
and Study Web artifact status. It is not an intermittent-failure diagnosis.

Before enabling the automatic session-ingest timer on a production collector,
pass the database and idempotency gate in
[`vocera-wlc-phase0-ingest-rehearsal-runbook.md`](vocera-wlc-phase0-ingest-rehearsal-runbook.md).
For a controlled non-production installation, use the installer with
`WLC_SESSION_INGEST_INSTALL_ARGS=--no-enable`; do not replace the rehearsal with
a generic ICAP scan or manual movement into `pcaps/`.

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
Start broadcast attempt
Heard clearly
Missed
Partial
Choppy
Alert only
```

Each marker stores collector/browser time. Outcome markers close or update the
currently open attempt for the selected capture session only.

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
2. Keep the broadcast/group state active a few seconds if operationally possible.
3. Save candidate active state with `active-event.cli`.
4. Paste `show wireless multicast group summary` into Study Web and select the active group/VLAN row.
5. Run the generated attempt-scoped resolved-group command sheet.
6. Run `stop-export.cli`.
7. Run `post-failure.cli`.
8. Confirm the EPC landed under the session package `incoming/` folder. The
   collector imports it automatically (see *Automatic EPC ingest and isolation*
   below); no manual move, hash, register, or parse step is required.
9. Run `cleanup.cli`.

Gather the live group evidence (steps 3-5) **before** `stop-export.cli` whenever
operationally possible: a dynamic Vocera multicast group can disappear within
seconds of a broadcast ending, and that group/VLAN/MGID evidence cannot be
recovered from the controller afterward.

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

## Automatic EPC ingest and isolation

`stop-export.cli` SCP-pushes the exported EPC into the session package
`incoming/` folder, never directly into `pcaps/`. Study Web makes `incoming/`
owned by the configured local `COLLECTOR_SCP_USERNAME` (normally `appsadmin`)
with mode `0750`, because the root-owned ingest service and the unprivileged
SCP account have different duties. Before a live export, verify that account can
write the exact `incoming/` path; do not loosen the whole package or export
directly to `pcaps/`. A file in `incoming/` means
"upload in progress or pending validation"; `pcaps/` means "stable, validated,
service-owned session evidence". See
[`vocera-wlc-phase0-production-contract.md`](vocera-wlc-phase0-production-contract.md)
for the production ownership and timer-enable contract.

A one-minute collector timer (`vocera-media-qoe-wlc-session-ingest.timer`) runs
the import with no operator action:

1. Detect a completed upload (size and mtime unchanged across timer ticks).
2. Validate filesystem safety and the pcap/pcapng container.
3. Copy into a service-created temp file, hash it, fsync it, set final
   ownership/mode, atomically rename it into `pcaps/`, and verify SHA-256.
4. Register it as a capture with `capture_point=wlc_epc`.
5. Run the existing media QoE parser once.
6. Classify what the EPC can and cannot prove (`inner_voice_visible`,
   `inner_multicast_visible`, `outer_capwap_only`, `control_plane_only`,
   `unsupported_link_or_decode`, or `empty_or_unusable`).
7. Surface status in Study Web (file, size, SHA-256, ingest state, parser
   result, and visibility class) for the session.

The trigger endpoint (`POST /api/media-qoe/wlc/sessions/ingest-scan`) is
**localhost-only**: only the local systemd timer may start a scan. The Study Web
UI reads artifact status through the `GET` route; it never triggers a scan.

### Isolation from the generic ICAP path

The WLC session ingest is the **only** automated path that processes WLC session
EPCs. The generic Vocera media ICAP pipeline must never re-discover a finalized
session EPC, or it would be double-parsed and mislabeled as ordinary ICAP
evidence. Two guards enforce this and must stay in place:

- The batch publisher excludes the WLC package roots from recursive discovery
  (`DEFAULT_EXCLUDED_SCAN_DIRS = ("wlc-sessions", "wlc-attempts")`), and the
  textfile service passes `VOCERA_MEDIA_QOE_BATCH_EXCLUDE_DIRS=wlc-sessions,wlc-attempts`.
- Study Web's generic raw-file register/scan endpoints reject any path under the
  `wlc-sessions`/`wlc-attempts` roots.

Manual raw-file imports register with the neutral capture point `Imported PCAP`
(not `ICAP`), reserving `ICAP` for genuine Catalyst Center ICAP captures.

### Capture names

Leave the capture name blank when creating a session; Study Web (and the CLI)
generate a unique, WLC-safe name (`PREFIX_YYMMDD_HHMM_XXXX`). A static name
eventually collides on the controller, so Study Web also rejects reuse of a
capture name by any non-terminal session.

### Recovery

Finalization to `pcaps/` happens before registration and parsing. If a transient
database or parser error fails after finalization, the artifact is left in
`promoted`, `registered`, `retry_pending`, or `failed` state with its `pcaps/`
path recorded, and the same timer automatically retries it (reusing the existing
capture, never moving files or re-importing) until it parses or a bounded retry
limit is reached.

### Timeout ordering

A valid large-EPC parse must never be killed mid-flight, so the deployed
timeouts satisfy:

```text
systemd TimeoutStartSec (660s)
  > curl max-time / STUDY_WEB_INGEST_TIMEOUT (600s)
    > Study Web parser timeout STUDY_WEB_MEDIA_QOE_PARSE_TIMEOUT_SECONDS (480s)
```

## Source anchors

- Cisco Catalyst 9800 EPC documentation: validates port-channel attachment,
  circular-file buffers, `file-size`, match filters, and export workflow.
- Cisco Catalyst 9800 Vocera broadcast guidance: separates the Vocera
  `230.230.x.x` application group from the WLC-to-AP CAPWAP multicast group and
  identifies WLC group summary/detail evidence as the receiver-membership check.
- Cisco Catalyst 9800 multicast troubleshooting guidance: identifies AP-side
  `show capwap mcast mgid clients` and `show capwap mcast mgid all` as AP MGID
  evidence.
- Vocera Infrastructure Planning Guide: documents badge multicast use, the
  fixed `230.230.0.1` plus 4096-address range, IGMPv2 default for B3000n/V5000/
  C1000, and DTIM/beacon multicast-delay risk.
- RFC 1112: IPv4 multicast-to-Ethernet mapping uses only the low-order 23 bits,
  so multicast MAC evidence is corroborating, not globally unique.
- util-linux `script(1)`: use `--log-out` and `--log-timing`; never use
  `--log-in` or `--log-io` for WLC console evidence because those modes can log
  hidden password input.
