#!/usr/bin/env bash
# Thin trigger for the WLC capture-session SCP ingest.
#
# Study Web owns the ingest pipeline: it validates a completed SCP upload under
# <session>/incoming/, hashes it, atomically promotes it into <session>/pcaps/,
# registers it as a wlc_epc capture, and runs the existing parser -- all
# in-process so it reuses the same parser executor and capture registration the
# generic raw-file path uses. This script only asks the local Study Web service
# to run one ingest-scan pass on a timer, so an exported EPC is imported without
# any operator action. It stores no WLC or SCP secrets and never SSHes anywhere.
set -euo pipefail

host="${STUDY_WEB_INGEST_HOST:-127.0.0.1}"
port="${STUDY_WEB_INGEST_PORT:-${VOCERA_RF_STUDY_WEB_PORT:-8097}}"
timeout="${STUDY_WEB_INGEST_TIMEOUT:-120}"
url="http://${host}:${port}/api/media-qoe/wlc/sessions/ingest-scan"

curl -fsS -m "${timeout}" -X POST -H 'content-type: application/json' -d '{}' "${url}"
echo
