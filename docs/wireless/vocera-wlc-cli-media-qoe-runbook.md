# Legacy short-attempt WLC media evidence runbook

> **Status:** legacy compatibility workflow. For intermittent production
> failures, use the canonical long-running capture-session workflow in
> [`vocera-wlc-continuous-capture-runbook.md`](vocera-wlc-continuous-capture-runbook.md).

This workflow creates one self-contained attempt package for a short,
single-attempt validation. It remains useful when importing older evidence
bundles, but it does not replace the Study Web session + attempt-marker model.

## Create a package

```bash
make vocera-media-qoe-wlc-attempt-init \
  STUDY_ID=study_v5000_c1000_multicast \
  ATTEMPT_ID=20260624T143015-attempt-002 \
  WLC_NAME=SRHC-WLC-40G-SEC \
  V5000_MAC=<V5000_MAC> \
  V5000_IP=<V5000_IP> \
  C1000_MAC=<C1000_MAC> \
  C1000_IP=<C1000_IP> \
  VOCERA_VLAN=684
```

The generated tree contains `manifest.json`, command sheets, `cli/`, `pcaps/`,
`notes/`, and `validation/` directories.

## Collect manually

Run the generated before/start/during/stop-export/after/cleanup sheets from an
approved interactive WLC terminal. Export the final PCAP by outbound SCP into
that package's `pcaps/` directory, then preserve terminal output as:

```text
cli/before.txt
cli/during.txt
cli/after.txt
pcaps/wlc-epc.pcap
notes/operator-notes.md
```

Record the observed audio result:

```bash
make vocera-media-qoe-wlc-attempt-record \
  ATTEMPT_DIR=/var/lib/vocera-media-qoe/raw/wlc-attempts/<study>/<attempt> \
  AUDIO_RESULT=missed \
  ALERT_RESULT=true \
  OPERATOR_NOTES='C1000 received alert tone but no voice.'
```

## Validate and ingest explicitly

```bash
make vocera-media-qoe-wlc-attempt-validate \
  ATTEMPT_DIR=/var/lib/vocera-media-qoe/raw/wlc-attempts/<study>/<attempt>

make vocera-media-qoe-wlc-attempt-ingest \
  ATTEMPT_DIR=/var/lib/vocera-media-qoe/raw/wlc-attempts/<study>/<attempt>
```

Ingest writes evidence sidecars, validation report, and import SQL. It can load
the ledger when the media-QoE database URL is configured. It does not make the
bundle part of the generic ICAP scan path.

## Safety rules

- Confirm capture status before start and after cleanup.
- Stop/export/clean up every capture object deliberately.
- Do not interpret an encrypted/undecodable PCAP as proof that multicast was
  absent.
- Do not treat an attempt package as a packet-to-attempt correlation engine.
- Never place WLC or SCP passwords in generated package files.
