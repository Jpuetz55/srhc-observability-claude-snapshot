# Phase 0 WLC SCP Ingest — Database & Ingest Rehearsal Runbook

Read [`vocera-wlc-phase0-production-contract.md`](vocera-wlc-phase0-production-contract.md)
first. That document defines the production ownership, state-machine,
quarantine, retry, and timer-enable contract. This runbook is the rehearsal
procedure used to prove that contract before production enablement.

This runbook proves the Phase 0 WLC capture-session EPC ingest state machine end
to end against a **restored rehearsal database**, before any production
deployment. It is the gate between merging the Phase 0 implementation and
updating the live `collectors01` checkout to the validated source line.

Run it from a **non-production integration clone** of this repository. Do not
run it against production data and do not enable the timer on a production host
during rehearsal.

Record the exact reviewed commit or tag under test before starting. Do not
assume that an older rehearsal tag still represents the current code line.

## 0. Prerequisites

- A throwaway PostgreSQL database restored from a recent production dump (the
  "rehearsal DB"). Nothing here should touch production.
- A non-production integration clone on the reviewed candidate line:

```bash
cd /path/to/non-production-integration-clone
git remote -v
git fetch origin --prune --tags
git switch main && git pull --ff-only
git rev-parse HEAD
git describe --tags --always
git log -6 --oneline
```

- Environment for this shell (rehearsal values; adjust to your restore):

```bash
export REHEARSAL_DB_URL="postgresql://vocera_media_qoe@127.0.0.1:15434/vocera_media_qoe_rehearsal"
export PSQL="psql $REHEARSAL_DB_URL"
export RAW_DIR="/var/lib/vocera-media-qoe/raw-rehearsal"
export SESSION_ROOT="$RAW_DIR/wlc-sessions"
export STUDY_ID="study_rehearsal_phase0"
export SESSION_ID="rehearsal-$(date -u +%Y%m%dT%H%M%S)"
```

The ingest is owned by Study Web; run a Study Web instance against the rehearsal
DB and raw dir, for example:

```bash
PYTHONPATH=tools \
  STUDY_WEB_MEDIA_QOE_RAW_DIR="$RAW_DIR" \
  VOCERA_MEDIA_QOE_DATABASE_URL="$REHEARSAL_DB_URL" \
  STUDY_WEB_MEDIA_QOE_EXECUTION_ENABLED=true \
  STUDY_WEB_MEDIA_QOE_WLC_INGEST_STABILITY_SECONDS=5 \
  python3 -m uvicorn study_web.main:app --host 127.0.0.1 --port 8097
```

A short stability window (5s here) keeps the rehearsal quick; production uses the
default. The ingest-scan endpoint is **localhost-only**, so run these curls on the
same host.

## 1–4. Schema and idempotency

1. Restore the production dump into the rehearsal DB (out of scope here; use your
   standard restore).
2. Apply the Phase 0 schema:

```bash
$PSQL -v ON_ERROR_STOP=1 -f sql/vocera_media_qoe_schema.sql
```

3. Apply it **again** to prove idempotency — it must succeed with no errors and
   create no duplicates (`create table if not exists`, `create index if not
   exists`, and guarded `do $$ ... $$` blocks):

```bash
$PSQL -v ON_ERROR_STOP=1 -f sql/vocera_media_qoe_schema.sql && echo "IDEMPOTENT OK"
```

4. Confirm the new table and its idempotency guard exist:

```bash
$PSQL -c "\d vocera_media_session_artifacts"
$PSQL -c "select indexname from pg_indexes where indexname = 'uq_vocera_media_session_artifacts_session_sha';"
```

## 5. Test capture session + on-disk package

Create the capture-session record and the matching on-disk package. Either use
the Study Web create endpoint, or the CLI/Make target:

```bash
make vocera-media-qoe-wlc-session-init \
  VOCERA_MEDIA_QOE_WLC_SESSION_ROOT="$SESSION_ROOT" \
  STUDY_ID="$STUDY_ID" SESSION_ID="$SESSION_ID" \
  WLC_NAME="SRHC-WLC-40G-SEC" WLC_INTERFACE="Port-channel1" \
  COLLECTOR_HOST="10.0.128.107" COLLECTOR_SCP_USERNAME="appsadmin" \
  V5000_MAC="00:09:ef:54:5f:46" V5000_IP="10.16.88.228" \
  C1000_MAC="00:09:ef:61:0b:f7" C1000_IP="10.16.88.230"
```

Leave `WLC_CAPTURE_NAME` blank so a unique name is generated. Insert the matching
session row into the rehearsal DB if you used the CLI directly (the Study Web
create endpoint does both in one step — prefer it).

Confirm the package staging directory exists:

```bash
ls -la "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/incoming/"
```

## 6. Verify the SCP staging ownership contract

Study Web may run as root to access the root-owned PostgreSQL container, but the
WLC SCP export authenticates as the package's `collector_scp_username` (normally
`appsadmin`). Package creation therefore makes **only** `incoming/` owned by
that SCP account with mode `0750`; `pcaps/` remains service-owned so only the
ingest process can finalize a validated file. Before a rehearsal or live export:

```bash
SESSION_DIR="$SESSION_ROOT/$STUDY_ID/$SESSION_ID"
stat -c '%A %U:%G %n' "$SESSION_DIR/incoming" "$SESSION_DIR/pcaps"
sudo -u appsadmin test -w "$SESSION_DIR/incoming"
sudo -u appsadmin test ! -w "$SESSION_DIR/pcaps"
```

Do not work around a failed write by exporting directly to `pcaps/` or by making
the entire package world-writable. A failed ownership check is a deployment
blocker because the WLC cannot create its SCP export.

## 7. Stage a valid EPC in incoming/

Drop a small, valid pcap/pcapng into `incoming/` (a sanitized capture or a tiny
synthetic one — the first 4 bytes must be a real pcap/pcapng magic number):

```bash
cp /path/to/staged-rehearsal.pcap \
  "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/incoming/$SESSION_ID.pcap"
```

## 7–9. Stability wait, then finalization

7. Run the ingest scan once (localhost only):

```bash
curl -fsS -X POST -H 'content-type: application/json' -d '{}' \
  http://127.0.0.1:8097/api/media-qoe/wlc/sessions/ingest-scan | python3 -m json.tool
```

8. The **first** pass must record `upload_detected` (not yet finalized): it has
   only one observation of the file and is waiting for stability.

```bash
$PSQL -c "select ingest_state, sha256, final_path from vocera_media_session_artifacts
          where capture_session_id = '$SESSION_ID';"
# expect: ingest_state = upload_detected, final_path = NULL
ls "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/incoming/"   # file still here
```

   Optional: prove the stability clock resets on change — modify the file
   (append a byte) and rerun the scan; it must stay `upload_detected`.

9. Wait past the stability window, then run the scan again. The file must be
   finalized into `pcaps/`:

```bash
sleep 6
curl -fsS -X POST -H 'content-type: application/json' -d '{}' \
  http://127.0.0.1:8097/api/media-qoe/wlc/sessions/ingest-scan | python3 -m json.tool
ls "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/pcaps/"      # EPC now here
ls "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/incoming/"   # now empty
stat -c '%A %U:%G %n' "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/pcaps/$SESSION_ID.pcap"
sudo -u appsadmin test ! -w "$SESSION_ROOT/$STUDY_ID/$SESSION_ID/pcaps/$SESSION_ID.pcap"
```

The finalized EPC must be service-owned (`root:root` in production) and
non-writable by the SCP upload account. This file-level assertion is required;
checking only the parent `pcaps/` directory is not enough.

## 10–12. Exactly-one assertions

```bash
# 10. Exactly one session artifact row for the EPC.
$PSQL -c "select count(*) from vocera_media_session_artifacts
          where capture_session_id = '$SESSION_ID' and artifact_kind = 'wlc_epc';"   # 1
$PSQL -c "select ingest_state, parser_status, visibility_class
          from vocera_media_session_artifacts where capture_session_id = '$SESSION_ID';"
# expect ingest_state = parsed (or imported if execution was disabled)

# 11. Exactly one capture registered as wlc_epc for this session.
$PSQL -c "select count(*) from vocera_media_captures
          where capture_point = 'wlc_epc' and source_path like '%/$SESSION_ID/pcaps/%';"   # 1

# 12. Exactly one parser run for that capture.
$PSQL -c "select count(*) from vocera_media_capture_parse_runs r
          join vocera_media_captures c on c.capture_id = r.capture_id
          where c.capture_point = 'wlc_epc' and c.source_path like '%/$SESSION_ID/pcaps/%';"   # 1
```

## 13. Generic publisher must ignore the finalized EPC

The generic ICAP batch publisher must not discover the finalized session EPC:

```bash
PYTHONPATH=tools/vocera_media_qoe python3 - <<PY
from pathlib import Path
import vocera_media_qoe_batch as b
found = b.discover_pcaps(Path("$RAW_DIR"))
hit = [str(p) for p in found if "/wlc-sessions/" in str(p) or "/wlc-attempts/" in str(p)]
print("discovered:", [str(p) for p in found])
assert not hit, f"REGRESSION: generic publisher discovered WLC evidence: {hit}"
print("OK: generic publisher ignores wlc-sessions/wlc-attempts")
PY
```

Also confirm the textfile service env carries the exclusion
(`VOCERA_MEDIA_QOE_BATCH_EXCLUDE_DIRS=wlc-sessions,wlc-attempts`).

## 14. Forced-failure retry must not duplicate

Force a parse failure, confirm the artifact lands `failed`, then let the retry
recover it — without duplicating files, artifacts, or captures.

```bash
# Induce a failure (pick one): point the parser config at a bad path, or
# temporarily revoke parse permissions, then stage + finalize a second EPC.
# After the failing run:
$PSQL -c "select ingest_state, parser_status,
                 coalesce((metadata->>'retry_count')::int,0) as retries
          from vocera_media_session_artifacts where capture_session_id = '$SESSION_ID';"
# expect ingest_state = failed (or imported), final_path set, file still in pcaps/

# Remove the fault, then rerun the scan; the retry pass re-drives it:
curl -fsS -X POST -H 'content-type: application/json' -d '{}' \
  http://127.0.0.1:8097/api/media-qoe/wlc/sessions/ingest-scan | python3 -m json.tool

# Invariants after recovery:
#  * exactly ONE file in pcaps/, NONE re-created in incoming/
#  * exactly ONE session-artifact row (now parsed)
#  * exactly ONE wlc_epc capture
#  * parse_runs MAY be >1 (one failed + one success) — that is correct lineage,
#    not duplication. captures/artifacts/files must stay at one each.
```

Re-run the count queries from steps 10–12 and confirm artifacts and captures are
still exactly one each.

## Acceptance

The rehearsal passes when, with no manual file movement, hashing, or parser
launch:

- the schema applies twice cleanly (idempotent),
- a growing/incomplete upload is never finalized,
- a stable valid EPC is finalized as service-owned `pcaps/` evidence,
- exactly one artifact, one `wlc_epc` capture, and one successful parse exist,
- the generic publisher never sees the EPC, and
- a forced failure recovers via retry without duplicating files, artifacts, or
  captures.

## After the rehearsal passes

1. Record the validated commit/tag and the rehearsal results.
2. Update the live `collectors01` deployment checkout to that validated line.
3. Install the timer on `collectors01`:
   `make vocera-media-qoe-wlc-session-ingest-install` (omit `--no-enable` to
   enable the one-minute timer).
4. Run the **90-second WLC EPC smoke export** from a real session and confirm the
   exported EPC is imported and parsed automatically, with Study Web showing the
   artifact state.

Only after the smoke passes is Phase 0 production-validated.
