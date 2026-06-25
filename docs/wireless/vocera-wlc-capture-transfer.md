# Vocera WLC capture transfer and ingest boundary

## Long capture-session transfer (current workflow)

A WLC session package lives under:

```text
/var/lib/vocera-media-qoe/raw/wlc-sessions/<study-id>/<session-id>/
```

The generated `stop-export.cli` sends the EPC from the **WLC** to the collector
through outbound SCP. Its target must be the session package's `incoming/`
directory:

```text
.../<study-id>/<session-id>/incoming/<exported-name>.pcap
```

The WLC prompts interactively for the collector account password. The repo does
not fetch the file from the WLC and does not store either endpoint's password.

When the Phase 0 ingest timer is installed and enabled, do not manually move
that file to `pcaps/`. The timer performs the required lifecycle:

```text
incoming/ (upload pending)
  -> stable size/mtime
  -> pcap magic-byte check + SHA-256
  -> atomic promotion
pcaps/ (validated final artifact)
  -> capture registration as wlc_epc
  -> parser run / artifact state in Study Web
```

Check the import service rather than rerunning a generic batch scan:

```bash
systemctl status vocera-media-qoe-wlc-session-ingest.service --no-pager -l
journalctl -u vocera-media-qoe-wlc-session-ingest.service -n 100 --no-pager
```

`wlc-sessions/` and `wlc-attempts/` are intentionally excluded from generic
media discovery. A session EPC must not become an ordinary ICAP or Imported
PCAP record.

## Legacy attempt-only transfer

Short, single-attempt compatibility packages live under:

```text
/var/lib/vocera-media-qoe/raw/wlc-attempts/<study-id>/<attempt-id>/
```

For these older bundles, the operator manually stages artifacts in the package
and then validates/ingests explicitly:

```bash
make vocera-media-qoe-wlc-attempt-validate ATTEMPT_DIR=<attempt-dir>
make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=<attempt-dir>
```

This does not replace the long-session `incoming/` → `pcaps/` importer.

## Transfer checks

- Preserve the WLC-exported filename and terminal output in the session evidence
  where relevant.
- Keep partial or failed exports; an ingest error is evidence, not a reason to
  erase the original.
- Verify final path, size, SHA-256, ingest state, and parser status in Study
  Web before deleting any source capture object or attempting another capture.
- Never copy raw PCAPs, transcripts, or generated parser output into Git.
