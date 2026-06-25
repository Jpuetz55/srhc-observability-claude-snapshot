# Vocera WLC evidence contract

## Capture-session package (canonical)

Every intermittent multicast reproduction uses one session directory:

```text
/var/lib/vocera-media-qoe/raw/wlc-sessions/<study-id>/<session-id>/
```

Expected structure:

```text
session.json                         immutable capture context; no passwords
session-events.json                  operator event timeline
attempts/attempt-markers.json        attempt/result lineage
clock-check.cli                      generated command sheet
baseline.cli
start-long.cli
start-short-validation.cli
active-event.cli
resolved-active-group.cli
post-failure.cli
ap-evidence.cli
stop-export.cli
cleanup.cli
cli/                                 preserved WLC transcripts when available
incoming/                            WLC SCP landing area; never final evidence
pcaps/                               stable, service-owned finalized EPC artifacts
```

`session.json` records study/session identity, WLC, capture name/interface,
filter mode, collector SCP host/user/port/path, ring sizing, sender/receiver,
expected DSCP, multicast pool, and configured VLAN. It must never contain a
password or secret token.

Allowed event/result values include:

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

Result events create attempt records tied to the session. The event says what
the operator observed; it is not a packet-level causality conclusion.

## Managed EPC artifact lifecycle

```text
WLC SCP upload -> incoming/
stable upload -> validated (container magic + SHA-256)
validated -> copied into root-owned, non-writable pcaps/ evidence
pcaps artifact -> SHA-256 verified -> registered capture_point=wlc_epc -> parsed or retryable failure
```

The artifact record retains file identity, size, SHA-256, ingest state, parser
state, final path, finalization metadata, and retry lineage. A retry must reuse
the same finalized file and capture record; it must not duplicate an
artifact/capture or reclassify the EPC as ICAP.

## Legacy attempt-only package

Older short-validation bundles remain supported under:

```text
/var/lib/vocera-media-qoe/raw/wlc-attempts/<study-id>/<attempt-id>/
```

Required legacy inputs:

```text
manifest.json
operator-observation.json
cli/before.txt
cli/during.txt
cli/after.txt
pcaps/wlc-epc.pcap
```

The legacy manifest owns WLC, study, sender/receiver, VLAN, and artifact
context. `operator-observation.json` owns human truth: alert/audio result,
operator, time, and notes. It is validated and ingested explicitly; it is not
part of the automatic long-session SCP importer.

Allowed `audio_result` values:

```text
heard
missed
partial
choppy
unknown
not_tested
```

PCAP sidecars use generic capture metadata. Catalyst Center ICAP sidecars are
separate and must remain distinguishable from manual WLC EPC evidence.
