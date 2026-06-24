# Vocera WLC Evidence Contract

Each long-running manual WLC reproduction is one capture-session directory under:

```text
/var/lib/vocera-media-qoe/raw/wlc-sessions/<study_id>/<session_id>/
```

Required files for a complete session:

```text
session.json
session-events.json
attempts/attempt-markers.json
cli/*.txt
pcaps/<session>.pcap
```

Generated command sheets:

```text
clock-check.cli
start-long.cli
start-short-validation.cli
stop-export.cli
active-state-snapshot.cli
cleanup.cli
```

`session.json` owns capture context: study, WLC, capture name, WLC interface,
ring sizing, collector SCP host/user/path, sender, receiver, expected DSCP, and
the Vocera multicast pool. It must not contain passwords.

`session-events.json` stores immutable operator markers:

```text
broadcast_started
heard
missed
partial
choppy
alert_only
session_end
note
```

Result markers create attempt rows tied to the capture session.

Legacy attempt-only bundles remain supported under:

```text
/var/lib/vocera-media-qoe/raw/wlc-attempts/<study_id>/<attempt_id>/
```

Required files for a complete legacy attempt:

```text
manifest.json
operator-observation.json
cli/before.txt
cli/during.txt
cli/after.txt
pcaps/wlc-epc.pcap
```

Generated files:

```text
before.cli
during.cli
after.cli
epc-start.cli
epc-stop-export.cli
cleanup.cli
validation/ingest-report.json
validation/attempt-import.sql
pcaps/*.pcap.json
```

`manifest.json` owns attempt context: WLC, study, sender, receiver, VLAN, and
artifact list. `operator-observation.json` owns human truth: alert heard, audio
heard/missed/partial/choppy, operator, time, and notes.

Allowed `audio_result` values:

```text
heard
missed
partial
choppy
unknown
not_tested
```

The PCAP sidecar uses generic `capture_metadata`, not DNAC-only assumptions.
DNAC ICAP sidecars remain supported separately.
