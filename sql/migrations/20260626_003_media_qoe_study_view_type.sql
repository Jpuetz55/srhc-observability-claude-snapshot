-- Expose study_type from the Media QoE study view for API predicates and UI selectors.
--
-- Appending the column preserves the existing view column order while allowing
-- CREATE OR REPLACE VIEW to update already-deployed databases safely.

create or replace view v_vocera_media_qoe_studies as
with capture_stats as (
  select
    study_id,
    count(*)::integer as capture_count,
    count(*) filter (where capture_status = 'complete' and parse_success)::integer as successful_capture_count,
    count(*) filter (where capture_status = 'failed' or (capture_status = 'complete' and not parse_success))::integer as failed_capture_count,
    min(capture_time) as first_capture_time,
    max(capture_time) as last_capture_time,
    max(parsed_at) as latest_parsed_at,
    coalesce(sum(packets_read), 0)::bigint as packets_read,
    coalesce(sum(udp_packets_seen), 0)::bigint as udp_packets_seen
  from vocera_media_captures
  where deleted_at is null
  group by study_id
), stream_stats as (
  select
    c.study_id,
    count(*)::integer as stream_count,
    count(*) filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20)::integer as rtp_qoe_stream_count,
    count(*) filter (where s.accepted is true)::integer as accepted_stream_count,
    count(*) filter (where s.accepted is false or s.review_status = 'excluded')::integer as excluded_stream_count,
    count(*) filter (where s.dscp_mismatch)::integer as dscp_mismatch_stream_count,
    count(*) filter (where coalesce(s.lost_packets, 0) > 0 or coalesce(s.loss_ratio, 0) > 0)::integer as lossy_stream_count,
    count(*) filter (where s.jitter_ms is not null and s.jitter_ms > 30)::integer as jitter_stream_count
  from vocera_media_captures c
  join vocera_media_stream_samples s
    on s.capture_id = c.capture_id
  where c.deleted_at is null
  group by c.study_id
)
select
  p.project_id,
  p.project_name,
  s.study_id,
  s.study_name,
  s.study_status,
  s.study_scope,
  coalesce(c.capture_count, 0)::integer as capture_count,
  coalesce(c.successful_capture_count, 0)::integer as successful_capture_count,
  coalesce(c.failed_capture_count, 0)::integer as failed_capture_count,
  coalesce(ss.stream_count, 0)::integer as stream_count,
  coalesce(ss.rtp_qoe_stream_count, 0)::integer as rtp_qoe_stream_count,
  coalesce(ss.accepted_stream_count, 0)::integer as accepted_stream_count,
  coalesce(ss.excluded_stream_count, 0)::integer as excluded_stream_count,
  coalesce(ss.dscp_mismatch_stream_count, 0)::integer as dscp_mismatch_stream_count,
  coalesce(ss.lossy_stream_count, 0)::integer as lossy_stream_count,
  coalesce(ss.jitter_stream_count, 0)::integer as jitter_stream_count,
  c.first_capture_time,
  c.last_capture_time,
  c.latest_parsed_at,
  coalesce(c.packets_read, 0)::bigint as packets_read,
  coalesce(c.udp_packets_seen, 0)::bigint as udp_packets_seen,
  s.created_at,
  s.updated_at,
  s.deleted_at,
  s.study_type
from vocera_studies s
join vocera_projects p
  on p.project_id = s.project_id
left join capture_stats c
  on c.study_id = s.study_id
left join stream_stats ss
  on ss.study_id = s.study_id
where s.study_type = 'media_qoe'
  and s.study_scope = 'media_qoe';
