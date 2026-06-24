# Vocera WLC Capture Security

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
