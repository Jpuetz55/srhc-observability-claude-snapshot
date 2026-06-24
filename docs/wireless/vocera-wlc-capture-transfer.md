# Vocera WLC Capture Transfer

The repo does not fetch PCAPs or transcripts from the WLC. Operators move files
manually after capture export.

Recommended layout:

```text
pcaps/wlc-epc.pcap
pcaps/c1000-apcap.pcap
cli/before.txt
cli/during.txt
cli/after.txt
notes/operator-notes.md
```

After files are staged:

```bash
make vocera-media-qoe-wlc-attempt-validate ATTEMPT_DIR=<attempt_dir>
make vocera-media-qoe-wlc-attempt-ingest ATTEMPT_DIR=<attempt_dir>
```

The existing Media QoE batch parser recursively discovers `.pcap`, `.cap`, and
`.pcapng` files under the raw directory, so attempt packages remain compatible
with existing capture parsing.

Transfer checks:

- Verify file sizes after copy.
- Keep WLC-exported filenames in notes if they differ from repo names.
- Do not delete source WLC capture files until `validation/ingest-report.json`
  is written and reviewed.
- Keep failed or partial captures; absence and parser errors are still evidence.
