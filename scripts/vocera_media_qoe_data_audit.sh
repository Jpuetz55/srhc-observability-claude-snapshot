#!/usr/bin/env bash
set -euo pipefail
# Inspect the shape of the Vocera media QoE data set for dashboard/UI design.
#
# Runs a fixed, read-only set of audit queries against the local media QoE
# PostgreSQL container (via scripts/vocera_media_qoe_psql_in_container.sh) and
# prints one labelled section per view. Intended for Phase 6 troubleshooting
# analysis: confirm what each capture/stream/classification view actually
# returns before designing panels.
#
# Usage:
#   sudo bash scripts/vocera_media_qoe_data_audit.sh [options] [-- <extra psql args>]
#
# Options:
#   --study-id ID     Study to scope capture/stream queries (default: study_media_qoe_default)
#   --project-id ID   Project to scope the summary query (default: project_media_qoe_default)
#   --url URL         Connection URL passed to the psql wrapper
#                     (default: $VOCERA_MEDIA_QOE_POSTGRES_URL or the local container URL)
#   --env-file PATH   Environment file to source for connection/secrets
#                     (default: /etc/default/vocera-media-qoe-postgres, sourced if readable)
#   --format csv|table  Output format (default: csv, for easy sharing)
#   -h, --help        Show this help
#
# Anything after `--` is forwarded verbatim to psql (last-wins, so it can
# override --format, add --pset, etc.).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PSQL_WRAPPER="${SCRIPT_DIR}/vocera_media_qoe_psql_in_container.sh"

study_id="study_media_qoe_default"
project_id="project_media_qoe_default"
url="${VOCERA_MEDIA_QOE_POSTGRES_URL:-postgresql://vocera_media_qoe:unused@127.0.0.1:15434/vocera_media_qoe}"
env_file="${VOCERA_MEDIA_QOE_ENV_FILE:-/etc/default/vocera-media-qoe-postgres}"
format="csv"
passthrough=()

usage() { sed -n '3,33p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --study-id) shift; study_id="${1:?--study-id needs a value}" ;;
    --project-id) shift; project_id="${1:?--project-id needs a value}" ;;
    --url) shift; url="${1:?--url needs a value}" ;;
    --env-file) shift; env_file="${1:?--env-file needs a value}" ;;
    --format) shift; format="${1:?--format needs a value}" ;;
    -h|--help) usage; exit 0 ;;
    --) shift; passthrough=("$@"); break ;;
    *) echo "Unknown option: $1 (use -- to forward args to psql)" >&2; exit 2 ;;
  esac
  shift
done

case "$format" in
  csv|table) ;;
  *) echo "Unsupported --format: $format (expected csv or table)" >&2; exit 2 ;;
esac

if [[ ! -x "$PSQL_WRAPPER" ]]; then
  echo "Missing psql wrapper: $PSQL_WRAPPER" >&2
  exit 1
fi

# Mirror the operator workflow: load connection/secret env if it is present.
if [[ -r "$env_file" ]]; then
  # shellcheck disable=SC1090
  set -a; source "$env_file"; set +a
fi

psql_args=(
  -X
  -v ON_ERROR_STOP=1
  -P pager=off
  -v "study_id=${study_id}"
  -v "project_id=${project_id}"
)
[[ "$format" == "csv" ]] && psql_args+=(--csv)
psql_args+=("${passthrough[@]}")

"$PSQL_WRAPPER" "$url" "${psql_args[@]}" <<'SQL'
\echo
\echo ===== 1. project_summary (project KPI band) =====
select *
from v_vocera_media_qoe_project_summary
where project_id = :'project_id';

\echo
\echo ===== 2. study_captures (per-capture inventory + rolled-up QoE) =====
-- The jitter/loss/timing rollups are computed here from the stream view so the
-- audit works against any deployed schema. Once the enhanced study_captures
-- view ships, these columns are available directly on the view.
select
  c.capture_id,
  c.source_name,
  c.capture_status,
  c.parse_success,
  c.stream_count,
  c.rtp_qoe_stream_count,
  c.dscp_mismatch_stream_count,
  r.lossy_stream_count,
  r.jitter_p95_ms,
  r.loss_p95_ratio,
  r.interarrival_p95_ms,
  c.parsed_at
from v_vocera_media_qoe_study_captures c
left join lateral (
  select
    count(*) filter (where coalesce(s.lost_packets, 0) > 0 or coalesce(s.loss_ratio, 0) > 0) as lossy_stream_count,
    percentile_cont(0.95) within group (order by s.jitter_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.jitter_ms is not null) as jitter_p95_ms,
    percentile_cont(0.95) within group (order by s.loss_ratio::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.loss_ratio is not null) as loss_p95_ratio,
    percentile_cont(0.95) within group (order by s.interarrival_p95_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.interarrival_p95_ms is not null) as interarrival_p95_ms
  from v_vocera_media_qoe_study_streams s
  where s.capture_id = c.capture_id
) r on true
where c.study_id = :'study_id'
order by c.parsed_at desc nulls last
limit 20;

\echo
\echo ===== 3. study_streams (per-stream troubleshooting table) =====
select
  capture_id,
  stream_id,
  src_ip,
  src_port,
  dst_ip,
  dst_port,
  payload_type,
  dscp,
  dscp_mismatch,
  measurement_mode,
  direction,
  packet_count,
  loss_ratio,
  jitter_ms,
  interarrival_p95_ms,
  stream_classification,
  review_status,
  accepted
from v_vocera_media_qoe_study_streams
where study_id = :'study_id'
order by
  dscp_mismatch desc nulls last,
  loss_ratio desc nulls last,
  jitter_ms desc nulls last,
  interarrival_p95_ms desc nulls last
limit 50;

\echo
\echo ===== 4. rtp_classification (true RTP vs noise composition) =====
select *
from v_vocera_media_current_rtp_classification
limit 50;

\echo
\echo ===== 5. rtp_rejection_reasons (why RTP candidates were rejected) =====
select *
from v_vocera_media_current_rtp_rejection_reasons
limit 50;

\echo
\echo ===== 6. capture_health (freshness/success by site + capture point) =====
select
  site,
  capture_point,
  capture_count,
  successful_capture_count,
  failed_capture_count,
  latest_capture_time,
  latest_parsed_at,
  future_capture_count,
  packets_read,
  udp_packets_seen,
  stream_count
from v_vocera_media_capture_health
order by latest_parsed_at desc nulls last
limit 20;
SQL
