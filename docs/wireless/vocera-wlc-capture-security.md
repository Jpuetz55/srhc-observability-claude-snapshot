# Vocera WLC Capture Security

The production ingest security contract is
[`vocera-wlc-phase0-production-contract.md`](vocera-wlc-phase0-production-contract.md).

The current WLC capture workflow is manual mode only.

The repo and Study Web:

```text
do not SSH to the WLC
do not run WLC commands
do not store WLC credentials
do not store collector SCP credentials
do not include passwords in generated command sheets
```

The only SCP fields modeled by the web app are:

```text
collector host
collector username
optional port
export path
```

The generated export URI is password-free:

```text
scp://appsadmin@10.0.128.107//absolute/path/to/session.pcap
```

The WLC prompts interactively during export. That prompt is handled in the
operator's terminal, not in Study Web.

Future web-assisted SSH, if ever added, must be a separate mode with dedicated
least-privilege credentials, memory-only credential handling, no persistence,
no log echo, short timeout, and a fresh prompt for every session.

## Evidence write boundary

The collector SCP account is allowed to write only staged uploads in a session
`incoming/` directory. It must not be able to modify final EPC evidence.

The ingest service finalizes a stable upload by copying it into a service-owned
temporary file under `pcaps/`, fsyncing the content, setting final ownership and
mode, atomically renaming it into place, and verifying the SHA-256. This avoids
the unsafe pattern of renaming an upload-owned file into the final evidence
directory.

Production finalized EPCs must be:

```text
root:root
0440 or 0400
```

The SCP account write test is part of the Phase 0 production gate:

```bash
sudo -u appsadmin test ! -w "$SESSION_DIR/pcaps/<finalized-file>.pcap"
```

This least-privilege boundary follows the NIST definition of granting only the
minimum authorizations needed for a function:
<https://csrc.nist.gov/glossary/term/least_privilege>.
