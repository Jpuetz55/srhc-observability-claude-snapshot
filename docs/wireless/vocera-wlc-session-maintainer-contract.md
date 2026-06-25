# Vocera WLC session-maintainer contract

This document is for maintainers changing the human-operated WLC capture-session
workflow. It is not an operator runbook. The operator entry point remains
[`vocera-wlc-continuous-capture-runbook.md`](vocera-wlc-continuous-capture-runbook.md).

## Non-negotiable boundaries

- **No WLC command runner.** Operators open the WLC SSH session, authenticate,
  paste generated command sheets, confirm SCP export, and run cleanup.
- **No stored WLC or SCP password.** The WLC prompts interactively during the
  outbound SCP export.
- **One owner per ingestion lane.** Generic media discovery must exclude
  `wlc-sessions/` and `wlc-attempts/`. Only the WLC session-ingest workflow may
  process a session EPC.
- **`incoming/` is not evidence yet.** SCP uploads land in `incoming/`; only a
  stable, magic-validated file may be finalized into service-owned `pcaps/`
  evidence. The finalizer must not rename the upload-owned inode into final
  evidence.
- **A finalized artifact is retryable.** A transient DB or parser failure must
  be recoverable from `pcaps/` without an operator moving the file back to
  `incoming/`. The database may still use `promoted` as the lifecycle state name
  for compatibility, but the filesystem action is owner-controlled finalization.
- **The ingest trigger is local-only.** Browser users read status through GET
  endpoints. Only the localhost systemd timer may initiate a filesystem scan or
  parser run.

## Required documentation updates

When changing the WLC session workflow, update every affected document in the
same pull request:

| Change type | Required documents |
| --- | --- |
| Operator steps, WLC command order, SCP destination | `vocera-wlc-continuous-capture-runbook.md`, `vocera-wlc-capture-transfer.md` |
| Failure/retry/cleanup behavior | `vocera-wlc-capture-recovery.md` |
| Schema, timers, parser, or evidence ownership | `vocera-media-pcap-qoe-architecture.md`, `docs/architecture.md`, `docs/repo-map.md` when a service/timer/path changes |
| Database/timer deployment acceptance criteria | `vocera-wlc-phase0-ingest-rehearsal-runbook.md` |
| Secret, SSH, command-runner, or caller-authentication boundary | `vocera-wlc-capture-security.md` |
| New or renamed runbook | `docs/README.md` and the top-level `README.md` Start here table when it affects an operator workflow |

Do not use a docs-only note to describe a behavior the code does not enforce.
Conversely, do not merge a behavioral change without documenting what an
operator must do, what the automation performs, and what evidence it retains.

## Code-commenting rule

Comment the **why** for non-obvious behavior, particularly when a future
maintainer might otherwise simplify away a safety boundary. Required examples:

- why generic discovery excludes WLC package roots;
- why files are finalized only after two stable observations;
- why the ingest endpoint only permits loopback callers;
- why a failed finalized artifact is retried from `pcaps/` instead of
  rescanning `incoming/`;
- why the terminal logger is output-only and never records input.

Use a concise module docstring for each WLC workflow module and docstrings for
public helpers that define a state transition, filesystem contract, or security
boundary. Do not add comments that merely restate obvious syntax.

## Required validation

Run these before opening or merging a change:

```bash
python3 scripts/test_wlc_session_documentation_contract.py
python3 scripts/test_vocera_wlc_session.py
python3 scripts/test_vocera_wlc_session_ingest.py
python3 scripts/test_vocera_wlc_session_console.py
python3 scripts/test_wlc_session_make_safety.py
make test
cd web/study-ui && npm run build
```

For a schema or ingest-state change, also complete the rehearsal in
[`vocera-wlc-phase0-ingest-rehearsal-runbook.md`](vocera-wlc-phase0-ingest-rehearsal-runbook.md)
before production deployment.
