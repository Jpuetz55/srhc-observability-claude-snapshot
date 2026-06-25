# Vocera WLC capture and session-ingest recovery

Use this runbook when a manual EPC is abandoned, SCP export fails, a stable
upload does not import, or the operator is unsure whether the WLC capture still
exists.

## 1. Check the controller before changing anything

From the approved WLC terminal:

```text
show monitor capture <capture-name>
```

If the capture is still active and the reproduction window is finished:

```text
monitor capture <capture-name> stop
```

Collect the relevant active-group/client context before teardown when it is
still visible. Dynamic multicast state may disappear immediately after the
broadcast ends.

## 2. Export once, to the session incoming directory

Use the password-free URI generated in `stop-export.cli`:

```text
monitor capture <capture-name> export scp://<user>@<collector>//absolute/session/path/incoming/<file>.pcap
```

The WLC prompts for the collector password interactively. Do not add it to the
command line, Study Web, session manifest, or a committed file.

Do not export directly to `pcaps/`. `incoming/` means an upload that still
requires stability validation; `pcaps/` is reserved for importer-promoted
artifacts.

## 3. Check collector-side state

```bash
session_dir=/var/lib/vocera-media-qoe/raw/wlc-sessions/<study-id>/<session-id>
find "$session_dir" -maxdepth 2 -type f -printf '%TY-%Tm-%Td %TT %s %p\n' | sort
systemctl status vocera-media-qoe-wlc-session-ingest.timer --no-pager -l
systemctl status vocera-media-qoe-wlc-session-ingest.service --no-pager -l
journalctl -u vocera-media-qoe-wlc-session-ingest.service -n 150 --no-pager
```

Interpret the result:

| Situation | Correct action |
| --- | --- |
| File is still changing in `incoming/` | Wait for a stable upload; do not move it. |
| Stable valid file remains in `incoming/` | Verify the timer/service and Study Web availability; run the documented rehearsal/diagnostic path, not a generic media scan. |
| File is in `pcaps/` with `failed` parser/DB state | Preserve it. The importer retries safely after the dependency is restored. |
| No file arrived | Investigate WLC SCP reachability/credentials and the exact export destination from the generated command sheet. |
| No timer intentionally installed | Handle the package through the Phase 0/rehearsal procedure before enabling automation; do not improvise a generic import. |

## 4. Clean up controller objects

After export is confirmed or the capture is intentionally abandoned:

```text
show monitor capture <capture-name>
no monitor capture <capture-name>
show monitor capture <capture-name>
```

If the generated workflow created a temporary ACL, remove it only after the
capture object is gone:

```text
configure terminal
no ip access-list extended <temporary-name>
end
```

Mark the session state in Study Web (`stopped`, `exported`, or `aborted`) and
record what happened. Use `aborted` only when the EPC is not expected to be
usable; retain failure context rather than deleting it.
