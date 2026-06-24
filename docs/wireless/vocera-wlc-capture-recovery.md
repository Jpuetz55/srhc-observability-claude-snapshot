# Vocera WLC Capture Recovery

Use this when a capture is abandoned, export fails, or the operator is unsure
whether EPC is still running.

## Check status

```text
show monitor capture <name>
```

If the capture is still active and the test is over:

```text
monitor capture <name> stop
```

## Export if needed

Use the password-free SCP URI from `stop-export.cli`:

```text
monitor capture <name> export scp://<user>@<collector>//absolute/path/to/session.pcap
```

The WLC prompts interactively for the collector account password.

## Cleanup

Always run:

```text
show monitor capture <name>
no monitor capture <name>
show monitor capture <name>
```

If a temporary ACL was created:

```text
configure terminal
no ip access-list extended <temporary-name>
end
```

## Mark session state

In Study Web, mark the session:

```text
stopped
exported
aborted
```

Use `aborted` only when the PCAP is not expected to be usable. Use `stopped`
when the WLC capture was stopped but transfer/import is not complete yet.
