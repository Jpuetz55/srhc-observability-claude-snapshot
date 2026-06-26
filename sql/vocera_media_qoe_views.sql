create or replace view v_vocera_media_latest_capture as
select *
from (
  select
    c.*,
    row_number() over (
      order by coalesce(
        case when c.capture_time <= now() + interval '5 minutes' then c.capture_time end,
        c.parsed_at
      ) desc,
      c.source_name desc
    ) as rn
  from vocera_media_captures c
) ranked
where rn = 1;

create or replace view v_vocera_media_capture_health as
select
  site,
  capture_point,
  max(capture_time) filter (where capture_time <= now() + interval '5 minutes') as latest_capture_time,
  max(capture_time) filter (where capture_time > now() + interval '5 minutes') as latest_future_capture_time,
  count(*) filter (where capture_time > now() + interval '5 minutes') as future_capture_count,
  max(parsed_at) as latest_parsed_at,
  count(*) as capture_count,
  count(*) filter (where capture_status = 'complete' and parse_success) as successful_capture_count,
  count(*) filter (where capture_status = 'failed' or (capture_status = 'complete' and not parse_success)) as failed_capture_count,
  sum(packets_read) as packets_read,
  sum(udp_packets_seen) as udp_packets_seen,
  sum(stream_count) as stream_count
from vocera_media_captures
group by site, capture_point;

create or replace view v_vocera_media_stream_samples as
select
  s.*,
  c.study_id,
  c.source_name,
  c.source_path,
  c.source_size_bytes,
  c.source_sha256,
  c.source_mtime,
  c.source_mtime_ns,
  c.capture_time,
  c.capture_status,
  c.deleted_at,
  c.parse_success,
  c.parse_started_at,
  c.parse_finished_at,
  c.parse_duration_seconds,
  c.parse_exit_code,
  c.parse_error,
  case
    when s.device_role <> 'unmapped' then s.device_role
    else coalesce(source_device.device_role, s.device_role)
  end as effective_device_role,
  case
    when s.device_role <> 'unmapped' then s.device_name
    else coalesce(source_device.device_name, s.device_name)
  end as effective_device_name,
  case
    when s.device_role <> 'unmapped' then s.device_config
    else coalesce(source_device.device_config, s.device_config)
  end as effective_device_config
from vocera_media_stream_samples s
join vocera_media_captures c
  on c.capture_id = s.capture_id
left join lateral (
  select
    device.value->>'name' as device_name,
    device.value->>'role' as device_role,
    device.value->>'config' as device_config
  from jsonb_each(coalesce(c.raw_metadata #> '{source_pcap,analyzer_config,devices}', '{}'::jsonb)) as device(key, value)
  where nullif(regexp_replace(lower(coalesce(device.value->>'mac', '')), '[^0-9a-f]', '', 'g'), '') is not null
    and regexp_replace(lower(coalesce(c.source_path, '') || ' ' || coalesce(c.source_name, '')), '[^0-9a-f]', '', 'g')
      like '%' || regexp_replace(lower(coalesce(device.value->>'mac', '')), '[^0-9a-f]', '', 'g') || '%'
  order by device.key
  limit 1
) source_device on true;

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

create or replace view v_vocera_media_qoe_projects as
select
  p.project_id,
  p.project_name,
  p.project_type,
  p.description,
  p.site,
  count(s.study_id)::integer as study_count,
  count(s.study_id) filter (where s.deleted_at is null)::integer as active_study_count,
  coalesce(sum(s.capture_count) filter (where s.deleted_at is null), 0)::integer as capture_count,
  coalesce(sum(s.stream_count) filter (where s.deleted_at is null), 0)::integer as stream_count,
  coalesce(sum(s.rtp_qoe_stream_count) filter (where s.deleted_at is null), 0)::integer as rtp_qoe_stream_count,
  coalesce(sum(s.accepted_stream_count) filter (where s.deleted_at is null), 0)::integer as accepted_stream_count,
  coalesce(sum(s.dscp_mismatch_stream_count) filter (where s.deleted_at is null), 0)::integer as dscp_mismatch_stream_count,
  min(s.first_capture_time) filter (where s.deleted_at is null) as first_capture_time,
  max(s.last_capture_time) filter (where s.deleted_at is null) as last_capture_time,
  max(s.latest_parsed_at) filter (where s.deleted_at is null) as latest_parsed_at,
  p.created_at,
  p.updated_at,
  p.deleted_at
from vocera_projects p
left join v_vocera_media_qoe_studies s
  on s.project_id = p.project_id
where p.project_type in ('media_qoe', 'mixed')
group by
  p.project_id,
  p.project_name,
  p.project_type,
  p.description,
  p.site,
  p.created_at,
  p.updated_at,
  p.deleted_at;

create or replace view v_vocera_media_qoe_study_captures as
select
  p.project_id,
  c.study_id,
  c.capture_id,
  c.source_name,
  c.source_path,
  c.source_size_bytes,
  c.source_sha256,
  c.source_mtime,
  c.source_mtime_ns,
  c.source_discovered_at,
  c.source_registered_at,
  c.capture_time,
  c.parsed_at,
  c.site,
  c.capture_point,
  c.capture_status,
  c.parse_success,
  c.parse_started_at,
  c.parse_finished_at,
  c.parse_duration_seconds,
  c.parse_exit_code,
  c.parse_stdout,
  c.parse_stderr,
  c.parse_error,
  c.parse_requested_by,
  c.parse_requested_at,
  c.packets_read,
  c.udp_packets_seen,
  c.stream_count,
  coalesce(ss.rtp_qoe_stream_count, 0)::integer as rtp_qoe_stream_count,
  coalesce(ss.dscp_mismatch_stream_count, 0)::integer as dscp_mismatch_stream_count,
  coalesce(ss.lossy_stream_count, 0)::integer as lossy_stream_count,
  ss.jitter_p95_ms,
  ss.loss_p95_ratio,
  ss.interarrival_p95_ms,
  c.deleted_at,
  coalesce(ss.trusted_rtp_dscp_mismatch_stream_count, 0)::integer as trusted_rtp_dscp_mismatch_stream_count,
  coalesce(ss.non_rtp_dscp_mismatch_stream_count, 0)::integer as non_rtp_dscp_mismatch_stream_count
from vocera_media_captures c
join vocera_studies st
  on st.study_id = c.study_id
join vocera_projects p
  on p.project_id = st.project_id
left join lateral (
  select
    count(*) filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20)::integer as rtp_qoe_stream_count,
    count(*) filter (where s.dscp_mismatch)::integer as dscp_mismatch_stream_count,
    count(*) filter (where s.dscp_mismatch is true and s.measurement_mode = 'rtp')::integer as trusted_rtp_dscp_mismatch_stream_count,
    count(*) filter (where s.dscp_mismatch is true and coalesce(s.measurement_mode, '') <> 'rtp')::integer as non_rtp_dscp_mismatch_stream_count,
    count(*) filter (where coalesce(s.lost_packets, 0) > 0 or coalesce(s.loss_ratio, 0) > 0)::integer as lossy_stream_count,
    percentile_cont(0.95) within group (order by s.jitter_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.jitter_ms is not null) as jitter_p95_ms,
    percentile_cont(0.95) within group (order by s.loss_ratio::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.loss_ratio is not null) as loss_p95_ratio,
    percentile_cont(0.95) within group (order by s.interarrival_p95_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.interarrival_p95_ms is not null) as interarrival_p95_ms
  from vocera_media_stream_samples s
  where s.capture_id = c.capture_id
) ss on true;

create or replace view v_vocera_media_qoe_parse_runs as
select
  p.project_id,
  r.study_id,
  r.capture_id,
  c.source_name,
  r.parse_run_id,
  r.source_path,
  r.requested_by,
  r.requested_at,
  r.started_at,
  r.finished_at,
  r.duration_seconds,
  r.status,
  r.exit_code,
  r.stdout,
  r.stderr,
  r.error,
  r.captures_imported,
  r.streams_imported,
  r.rtp_qoe_streams,
  r.dscp_mismatch_streams,
  r.lossy_streams
from vocera_media_capture_parse_runs r
left join vocera_media_captures c
  on c.capture_id = r.capture_id
left join vocera_studies st
  on st.study_id = coalesce(r.study_id, c.study_id)
left join vocera_projects p
  on p.project_id = st.project_id;

create or replace view v_vocera_media_qoe_study_streams as
select
  p.project_id,
  c.study_id,
  c.capture_id,
  c.source_name,
  s.stream_id,
  s.sample_time,
  s.first_seen,
  s.last_seen,
  s.src_ip,
  s.src_port,
  s.dst_ip,
  s.dst_port,
  s.ssrc,
  s.payload_type,
  s.dscp,
  s.measurement_mode,
  s.direction,
  s.server,
  s.device_name,
  s.device_role,
  s.device_config,
  s.peer_device_name,
  s.peer_device_role,
  s.peer_device_config,
  s.packet_count,
  s.byte_count,
  s.expected_packets,
  s.lost_packets,
  s.loss_ratio,
  s.duplicate_packets,
  s.out_of_order_packets,
  s.jitter_ms,
  s.interarrival_p50_ms,
  s.interarrival_p95_ms,
  s.interarrival_max_ms,
  s.dscp_mismatch,
  s.accepted,
  s.stream_classification,
  s.review_status,
  s.review_notes,
  s.reviewed_at,
  s.reviewed_by
from vocera_media_stream_samples s
join vocera_media_captures c
  on c.capture_id = s.capture_id
join vocera_studies st
  on st.study_id = c.study_id
join vocera_projects p
  on p.project_id = st.project_id
where c.deleted_at is null;

create or replace view v_vocera_media_qoe_project_summary as
with stream_stats as (
  select
    p.project_id,
    percentile_cont(0.95) within group (order by s.jitter_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.jitter_ms is not null) as jitter_p95_ms,
    percentile_cont(0.95) within group (order by s.loss_ratio::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.loss_ratio is not null) as loss_p95_ratio,
    percentile_cont(0.95) within group (order by s.interarrival_p95_ms::double precision)
      filter (where s.measurement_mode = 'rtp' and s.packet_count >= 20 and s.interarrival_p95_ms is not null) as interarrival_p95_ms
  from vocera_projects p
  join vocera_studies st
    on st.project_id = p.project_id
  join vocera_media_captures c
    on c.study_id = st.study_id
   and c.deleted_at is null
  join vocera_media_stream_samples s
    on s.capture_id = c.capture_id
  where p.project_type in ('media_qoe', 'mixed')
    and st.study_type = 'media_qoe'
    and st.deleted_at is null
  group by p.project_id
)
select
  p.project_id,
  p.project_name,
  p.study_count,
  p.capture_count,
  p.stream_count,
  p.rtp_qoe_stream_count,
  p.accepted_stream_count,
  p.dscp_mismatch_stream_count,
  coalesce(sum(s.lossy_stream_count) filter (where s.deleted_at is null), 0)::integer as lossy_stream_count,
  ss.jitter_p95_ms,
  ss.loss_p95_ratio,
  ss.interarrival_p95_ms,
  p.first_capture_time,
  p.last_capture_time,
  p.latest_parsed_at
from v_vocera_media_qoe_projects p
left join v_vocera_media_qoe_studies s
  on s.project_id = p.project_id
left join stream_stats ss
  on ss.project_id = p.project_id
group by
  p.project_id,
  p.project_name,
  p.study_count,
  p.capture_count,
  p.stream_count,
  p.rtp_qoe_stream_count,
  p.accepted_stream_count,
  p.dscp_mismatch_stream_count,
  ss.jitter_p95_ms,
  ss.loss_p95_ratio,
  ss.interarrival_p95_ms,
  p.first_capture_time,
  p.last_capture_time,
  p.latest_parsed_at;

create or replace view v_vocera_media_qoe_duplicate_captures as
with normalized as (
  select
    p.project_id,
    c.study_id,
    c.capture_id,
    c.source_name,
    c.source_path,
    c.source_size_bytes,
    c.source_sha256,
    c.source_mtime_ns,
    c.capture_time,
    coalesce(
      nullif(c.source_sha256, ''),
      'path:' || coalesce(c.source_path, '') || '|size:' || coalesce(c.source_size_bytes::text, '') || '|mtime:' || coalesce(c.source_mtime_ns::text, '')
    ) as duplicate_key
  from vocera_media_captures c
  join vocera_studies st
    on st.study_id = c.study_id
  join vocera_projects p
    on p.project_id = st.project_id
  where c.deleted_at is null
), duplicate_keys as (
  select
    project_id,
    duplicate_key,
    count(*)::integer as duplicate_count
  from normalized
  where duplicate_key <> 'path:|size:|mtime:'
  group by project_id, duplicate_key
  having count(*) > 1
)
select
  n.project_id,
  n.study_id,
  n.capture_id,
  n.source_name,
  n.source_path,
  n.source_size_bytes,
  n.source_sha256,
  n.source_mtime_ns,
  n.capture_time,
  d.duplicate_key,
  d.duplicate_count,
  row_number() over (
    partition by n.project_id, n.duplicate_key
    order by n.capture_time desc nulls last, n.capture_id desc
  ) as duplicate_rank
from normalized n
join duplicate_keys d
  on d.project_id = n.project_id
 and d.duplicate_key = n.duplicate_key;

create or replace view v_vocera_media_current_study as
with captures as (
  select
    count(*)::integer as capture_count,
    count(*) filter (where capture_status = 'complete' and parse_success)::integer as successful_capture_count,
    count(*) filter (where capture_status = 'failed' or (capture_status = 'complete' and not parse_success))::integer as failed_capture_count,
    min(capture_time) as first_capture_time,
    max(capture_time) as last_capture_time,
    max(parsed_at) as latest_parsed_at,
    sum(packets_read)::bigint as packets_read,
    sum(udp_packets_seen)::bigint as udp_packets_seen
  from vocera_media_captures
), streams as (
  select
    count(*)::integer as stream_count,
    count(*) filter (where measurement_mode = 'rtp' and packet_count >= 20)::integer as rtp_qoe_stream_count,
    count(*) filter (where measurement_mode = 'rtp_candidate_rejected')::integer as rtp_candidate_rejected_stream_count,
    sum(packet_count)::bigint as packet_count,
    sum(packet_count) filter (where measurement_mode = 'rtp_candidate_rejected')::bigint as rtp_candidate_rejected_packet_count,
    sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20)::bigint as rtp_packet_count,
    sum(expected_packets) filter (where measurement_mode = 'rtp' and packet_count >= 20)::bigint as rtp_expected_packets,
    sum(coalesce(lost_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20)::bigint as rtp_lost_packets,
    sum(coalesce(duplicate_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20)::bigint as rtp_duplicate_packets,
    sum(coalesce(out_of_order_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20)::bigint as rtp_out_of_order_packets,
    sum(coalesce(lost_packets, 0))::bigint as lost_packets,
    sum(coalesce(duplicate_packets, 0))::bigint as duplicate_packets,
    sum(coalesce(out_of_order_packets, 0))::bigint as out_of_order_packets,
    count(distinct effective_device_role) filter (where effective_device_role in ('control', 'test'))::integer as tested_device_role_count
  from v_vocera_media_stream_samples
)
select
  'current'::text as study_id,
  c.capture_count,
  c.successful_capture_count,
  c.failed_capture_count,
  s.stream_count,
  s.rtp_qoe_stream_count,
  s.tested_device_role_count,
  c.first_capture_time,
  c.last_capture_time,
  c.latest_parsed_at,
  c.packets_read,
  c.udp_packets_seen,
  s.packet_count,
  s.lost_packets,
  s.duplicate_packets,
  s.out_of_order_packets,
  s.rtp_candidate_rejected_stream_count,
  coalesce(s.rtp_candidate_rejected_packet_count, 0)::bigint as rtp_candidate_rejected_packet_count,
  coalesce(s.rtp_packet_count, 0)::bigint as rtp_packet_count,
  coalesce(s.rtp_expected_packets, 0)::bigint as rtp_expected_packets,
  coalesce(s.rtp_lost_packets, 0)::bigint as rtp_lost_packets,
  coalesce(s.rtp_duplicate_packets, 0)::bigint as rtp_duplicate_packets,
  coalesce(s.rtp_out_of_order_packets, 0)::bigint as rtp_out_of_order_packets,
  case
    when coalesce(s.rtp_expected_packets, 0) = 0 then null
    else s.rtp_lost_packets::double precision / s.rtp_expected_packets
  end as rtp_loss_total_ratio,
  case
    when coalesce(s.rtp_packet_count, 0) = 0 then null
    else s.rtp_duplicate_packets::double precision / s.rtp_packet_count
  end as rtp_duplicate_packet_ratio,
  case
    when coalesce(s.rtp_packet_count, 0) = 0 then null
    else s.rtp_out_of_order_packets::double precision / s.rtp_packet_count
  end as rtp_out_of_order_packet_ratio
from captures c
cross join streams s;

create or replace view v_vocera_media_current_device_summary as
select
  effective_device_role as device_role,
  effective_device_name as device_name,
  effective_device_config as device_config,
  count(distinct capture_id)::integer as capture_count,
  count(*)::integer as stream_count,
  count(*) filter (where measurement_mode = 'rtp' and packet_count >= 20)::integer as rtp_qoe_stream_count,
  min(sample_time) as first_sample_time,
  max(sample_time) as last_sample_time,
  sum(packet_count)::bigint as packet_count,
  sum(byte_count)::bigint as byte_count,
  sum(coalesce(lost_packets, 0))::bigint as lost_packets,
  sum(coalesce(duplicate_packets, 0))::bigint as duplicate_packets,
  sum(coalesce(out_of_order_packets, 0))::bigint as out_of_order_packets,
  percentile_cont(0.95) within group (order by jitter_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and jitter_ms is not null) as jitter_p95_ms,
  percentile_cont(0.95) within group (order by loss_ratio::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and loss_ratio is not null) as loss_p95_ratio,
  percentile_cont(0.95) within group (order by interarrival_p95_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and interarrival_p95_ms is not null) as interarrival_p95_ms,
  max(interarrival_max_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and interarrival_max_ms is not null) as interarrival_max_ms,
  count(*) filter (where dscp_mismatch)::integer as dscp_mismatch_stream_count,
  count(*) filter (where measurement_mode = 'rtp_candidate_rejected')::integer as rtp_candidate_rejected_stream_count,
  coalesce(sum(packet_count) filter (where measurement_mode = 'rtp_candidate_rejected'), 0)::bigint as rtp_candidate_rejected_packet_count,
  coalesce(sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::bigint as rtp_packet_count,
  coalesce(sum(expected_packets) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::bigint as rtp_expected_packets,
  coalesce(sum(coalesce(lost_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::bigint as rtp_lost_packets,
  coalesce(sum(coalesce(duplicate_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::bigint as rtp_duplicate_packets,
  coalesce(sum(coalesce(out_of_order_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::bigint as rtp_out_of_order_packets,
  case
    when coalesce(sum(expected_packets) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0) = 0 then null
    else coalesce(sum(coalesce(lost_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::double precision
      / nullif(sum(expected_packets) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)
  end as rtp_loss_total_ratio,
  case
    when coalesce(sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0) = 0 then null
    else coalesce(sum(coalesce(duplicate_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::double precision
      / nullif(sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)
  end as rtp_duplicate_packet_ratio,
  case
    when coalesce(sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0) = 0 then null
    else coalesce(sum(coalesce(out_of_order_packets, 0)) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)::double precision
      / nullif(sum(packet_count) filter (where measurement_mode = 'rtp' and packet_count >= 20), 0)
  end as rtp_out_of_order_packet_ratio,
  percentile_cont(0.05) within group (order by jitter_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and jitter_ms is not null) as jitter_p05_ms,
  avg(jitter_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and jitter_ms is not null) as jitter_mean_ms,
  percentile_cont(0.05) within group (order by interarrival_p95_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and interarrival_p95_ms is not null) as interarrival_p05_ms,
  avg(interarrival_p95_ms::double precision)
    filter (where measurement_mode = 'rtp' and packet_count >= 20 and interarrival_p95_ms is not null) as interarrival_mean_ms
from v_vocera_media_stream_samples
where effective_device_role in ('control', 'test')
group by effective_device_role, effective_device_name, effective_device_config;

create or replace view v_vocera_media_current_rtp_classification as
select
  effective_device_role as device_role,
  effective_device_name as device_name,
  effective_device_config as device_config,
  measurement_mode as classification,
  count(distinct capture_id)::integer as capture_count,
  count(*)::integer as stream_count,
  coalesce(sum(packet_count), 0)::bigint as packet_count,
  min(sample_time) as first_sample_time,
  max(sample_time) as last_sample_time
from v_vocera_media_stream_samples
where measurement_mode in ('rtp', 'rtp_candidate_rejected', 'udp_interarrival_only', 'unknown_udp')
group by effective_device_role, effective_device_name, effective_device_config, measurement_mode;

create or replace view v_vocera_media_current_rtp_rejection_reasons as
select
  s.effective_device_role as device_role,
  s.effective_device_name as device_name,
  s.effective_device_config as device_config,
  coalesce(nullif(reason.value, ''), 'unspecified') as reason,
  s.payload_type,
  s.dscp,
  count(distinct s.capture_id)::integer as capture_count,
  count(*)::integer as stream_count,
  coalesce(sum(s.packet_count), 0)::bigint as packet_count,
  min(s.sample_time) as first_sample_time,
  max(s.sample_time) as last_sample_time
from v_vocera_media_stream_samples s
left join lateral jsonb_array_elements_text(coalesce(s.raw_stream->'rtp_rejection_reasons', '[]'::jsonb)) as reason(value)
  on true
where s.measurement_mode = 'rtp_candidate_rejected'
group by
  s.effective_device_role,
  s.effective_device_name,
  s.effective_device_config,
  coalesce(nullif(reason.value, ''), 'unspecified'),
  s.payload_type,
  s.dscp;

create or replace view v_vocera_media_current_control_test_delta as
with pivot as (
  select
    max(jitter_p05_ms) filter (where device_role = 'control') as control_jitter_p05_ms,
    max(jitter_p05_ms) filter (where device_role = 'test') as test_jitter_p05_ms,
    max(jitter_mean_ms) filter (where device_role = 'control') as control_jitter_mean_ms,
    max(jitter_mean_ms) filter (where device_role = 'test') as test_jitter_mean_ms,
    max(jitter_p95_ms) filter (where device_role = 'control') as control_jitter_p95_ms,
    max(jitter_p95_ms) filter (where device_role = 'test') as test_jitter_p95_ms,
    max(loss_p95_ratio) filter (where device_role = 'control') as control_loss_p95_ratio,
    max(loss_p95_ratio) filter (where device_role = 'test') as test_loss_p95_ratio,
    max(rtp_loss_total_ratio) filter (where device_role = 'control') as control_loss_total_ratio,
    max(rtp_loss_total_ratio) filter (where device_role = 'test') as test_loss_total_ratio,
    max(rtp_duplicate_packet_ratio) filter (where device_role = 'control') as control_duplicate_packet_ratio,
    max(rtp_duplicate_packet_ratio) filter (where device_role = 'test') as test_duplicate_packet_ratio,
    max(rtp_out_of_order_packet_ratio) filter (where device_role = 'control') as control_out_of_order_packet_ratio,
    max(rtp_out_of_order_packet_ratio) filter (where device_role = 'test') as test_out_of_order_packet_ratio,
    max(interarrival_p05_ms) filter (where device_role = 'control') as control_interarrival_p05_ms,
    max(interarrival_p05_ms) filter (where device_role = 'test') as test_interarrival_p05_ms,
    max(interarrival_mean_ms) filter (where device_role = 'control') as control_interarrival_mean_ms,
    max(interarrival_mean_ms) filter (where device_role = 'test') as test_interarrival_mean_ms,
    max(interarrival_p95_ms) filter (where device_role = 'control') as control_interarrival_p95_ms,
    max(interarrival_p95_ms) filter (where device_role = 'test') as test_interarrival_p95_ms,
    max(interarrival_max_ms) filter (where device_role = 'control') as control_interarrival_max_ms,
    max(interarrival_max_ms) filter (where device_role = 'test') as test_interarrival_max_ms,
    max(lost_packets) filter (where device_role = 'control') as control_lost_packets,
    max(lost_packets) filter (where device_role = 'test') as test_lost_packets,
    max(duplicate_packets) filter (where device_role = 'control') as control_duplicate_packets,
    max(duplicate_packets) filter (where device_role = 'test') as test_duplicate_packets,
    max(out_of_order_packets) filter (where device_role = 'control') as control_out_of_order_packets,
    max(out_of_order_packets) filter (where device_role = 'test') as test_out_of_order_packets,
    max(packet_count) filter (where device_role = 'control') as control_packets,
    max(packet_count) filter (where device_role = 'test') as test_packets,
    max(rtp_packet_count) filter (where device_role = 'control') as control_rtp_packets,
    max(rtp_packet_count) filter (where device_role = 'test') as test_rtp_packets
  from v_vocera_media_current_device_summary
)
select 'RTP jitter p05 ms'::text as metric, control_jitter_p05_ms as control_value, test_jitter_p05_ms as test_value, test_jitter_p05_ms - control_jitter_p05_ms as delta
from pivot
union all
select 'RTP jitter mean ms', control_jitter_mean_ms, test_jitter_mean_ms, test_jitter_mean_ms - control_jitter_mean_ms
from pivot
union all
select 'RTP jitter p95 ms', control_jitter_p95_ms, test_jitter_p95_ms, test_jitter_p95_ms - control_jitter_p95_ms
from pivot
union all
select 'RTP packet loss p95 %', control_loss_p95_ratio * 100, test_loss_p95_ratio * 100, (test_loss_p95_ratio - control_loss_p95_ratio) * 100
from pivot
union all
select 'RTP packet loss total %', control_loss_total_ratio * 100, test_loss_total_ratio * 100, (test_loss_total_ratio - control_loss_total_ratio) * 100
from pivot
union all
select 'RTP duplicate packet %', control_duplicate_packet_ratio * 100, test_duplicate_packet_ratio * 100, (test_duplicate_packet_ratio - control_duplicate_packet_ratio) * 100
from pivot
union all
select 'RTP out-of-order packet %', control_out_of_order_packet_ratio * 100, test_out_of_order_packet_ratio * 100, (test_out_of_order_packet_ratio - control_out_of_order_packet_ratio) * 100
from pivot
union all
select 'RTP interarrival p05 ms', control_interarrival_p05_ms, test_interarrival_p05_ms, test_interarrival_p05_ms - control_interarrival_p05_ms
from pivot
union all
select 'RTP interarrival mean ms', control_interarrival_mean_ms, test_interarrival_mean_ms, test_interarrival_mean_ms - control_interarrival_mean_ms
from pivot
union all
select 'RTP interarrival p95 ms', control_interarrival_p95_ms, test_interarrival_p95_ms, test_interarrival_p95_ms - control_interarrival_p95_ms
from pivot
union all
select 'RTP interarrival max ms', control_interarrival_max_ms, test_interarrival_max_ms, test_interarrival_max_ms - control_interarrival_max_ms
from pivot
union all
select 'Trusted RTP lost packets', control_lost_packets::double precision, test_lost_packets::double precision, (test_lost_packets - control_lost_packets)::double precision
from pivot
union all
select 'Trusted RTP duplicate packets', control_duplicate_packets::double precision, test_duplicate_packets::double precision, (test_duplicate_packets - control_duplicate_packets)::double precision
from pivot
union all
select 'Trusted RTP out-of-order packets', control_out_of_order_packets::double precision, test_out_of_order_packets::double precision, (test_out_of_order_packets - control_out_of_order_packets)::double precision
from pivot
union all
select 'Trusted RTP packets', control_rtp_packets::double precision, test_rtp_packets::double precision, (test_rtp_packets - control_rtp_packets)::double precision
from pivot
union all
select 'Total packets', control_packets::double precision, test_packets::double precision, (test_packets - control_packets)::double precision
from pivot;

create or replace view v_vocera_media_current_capture_inventory as
select
  c.capture_id,
  c.source_name,
  c.source_path,
  c.capture_time,
  c.parsed_at,
  c.site,
  c.capture_point,
  c.parse_success,
  c.parse_error,
  c.packets_read,
  c.udp_packets_seen,
  c.stream_count,
  coalesce(string_agg(distinct s.effective_device_role, ', ' order by s.effective_device_role), 'unmapped') as device_roles
from vocera_media_captures c
left join v_vocera_media_stream_samples s
  on s.capture_id = c.capture_id
group by
  c.capture_id,
  c.source_name,
  c.source_path,
  c.capture_time,
  c.parsed_at,
  c.site,
  c.capture_point,
  c.parse_success,
  c.parse_error,
  c.packets_read,
  c.udp_packets_seen,
  c.stream_count;

create or replace view v_vocera_media_capture_sessions as
select
  s.*,
  coalesce(attempt_stats.attempt_count, 0)::integer as attempt_count,
  coalesce(attempt_stats.heard_attempt_count, 0)::integer as heard_attempt_count,
  coalesce(attempt_stats.missed_attempt_count, 0)::integer as missed_attempt_count,
  coalesce(attempt_stats.degraded_attempt_count, 0)::integer as degraded_attempt_count,
  coalesce(event_stats.event_count, 0)::integer as event_count,
  event_stats.latest_event_time,
  -- Latest resolved active group, derived from the most recently resolved broadcast
  -- attempt. Resolution is attempt-scoped; the session-level resolved_* columns are
  -- deprecated, so prefer these derived columns for any "current group" display.
  latest_resolved_attempt.attempt_id as latest_resolved_attempt_id,
  latest_resolved_attempt.resolved_group_ip as latest_resolved_group_ip,
  latest_resolved_attempt.resolved_group_vlan as latest_resolved_group_vlan,
  latest_resolved_attempt.resolved_mgid as latest_resolved_mgid,
  latest_resolved_attempt.vlan_context_state as latest_resolved_vlan_context_state,
  latest_resolved_attempt.active_group_selected_at as latest_resolved_at
from vocera_media_capture_sessions s
left join lateral (
  select
    count(*) as attempt_count,
    count(*) filter (where audio_result = 'heard') as heard_attempt_count,
    count(*) filter (where audio_result = 'missed') as missed_attempt_count,
    count(*) filter (where audio_result in ('partial', 'choppy')) as degraded_attempt_count
  from vocera_media_broadcast_attempts attempt
  where attempt.capture_session_id = s.session_id
) attempt_stats on true
left join lateral (
  select
    count(*) as event_count,
    max(event_time) as latest_event_time
  from vocera_media_capture_session_events event
  where event.capture_session_id = s.session_id
) event_stats on true
left join lateral (
  select
    attempt.attempt_id,
    attempt.resolved_group_ip,
    attempt.resolved_group_vlan,
    attempt.resolved_mgid,
    attempt.vlan_context_state,
    attempt.active_group_selected_at
  from vocera_media_broadcast_attempts attempt
  where attempt.capture_session_id = s.session_id
    and attempt.resolved_group_ip is not null
  order by coalesce(
    attempt.active_group_selected_at,
    attempt.attempt_started_at,
    attempt.started_at,
    attempt.created_at
  ) desc
  limit 1
) latest_resolved_attempt on true;

create or replace view v_vocera_media_capture_session_events as
select *
from vocera_media_capture_session_events;

-- Compatibility migration:
-- The legacy version of this view expanded `a.*`. Adding new attempt-table
-- columns would insert them ahead of legacy computed columns such as
-- artifact_count, and PostgreSQL does not allow CREATE OR REPLACE VIEW to
-- rename or reorder existing output columns. Recreate this one view object
-- before defining its expanded current shape.
--
-- Intentionally no CASCADE: any unexpected dependent database object must
-- block this migration so it can be reviewed explicitly.
drop view if exists v_vocera_media_broadcast_attempts;

create or replace view v_vocera_media_broadcast_attempts as
select
  a.*,
  session.capture_name,
  session.wlc_interface,
  session.capture_filter_mode,
  session.ring_total_size_mb,
  session.session_state,
  coalesce(artifact_stats.artifact_count, 0)::integer as artifact_count,
  coalesce(artifact_stats.pcap_artifact_count, 0)::integer as pcap_artifact_count,
  coalesce(snapshot_stats.snapshot_count, 0)::integer as snapshot_count,
  snapshot_stats.receiver_ap,
  snapshot_stats.receiver_bssid,
  snapshot_stats.receiver_channel,
  snapshot_stats.receiver_band,
  snapshot_stats.receiver_rssi,
  snapshot_stats.receiver_snr,
  -- `a.*` already exposes the attempt-level receiver_group_member. Keep the
  -- WLC during-snapshot derivation separately so the recreated view has unique
  -- output names and callers can distinguish stored attempt evidence from the
  -- latest snapshot evidence.
  snapshot_stats.receiver_group_member as snapshot_receiver_group_member,
  snapshot_stats.receiver_group_status,
  snapshot_stats.mgid,
  coalesce(finding_stats.critical_finding_count, 0)::integer as critical_finding_count,
  coalesce(finding_stats.warning_finding_count, 0)::integer as warning_finding_count
from vocera_media_broadcast_attempts a
left join vocera_media_capture_sessions session
  on session.session_id = a.capture_session_id
left join lateral (
  select
    count(*) as artifact_count,
    count(*) filter (where artifact_type in ('wlc_epc', 'ap_packet_capture')) as pcap_artifact_count
  from vocera_media_attempt_artifacts artifact
  where artifact.attempt_id = a.attempt_id
) artifact_stats on true
left join lateral (
  select
    count(*) as snapshot_count,
    max(receiver_ap) filter (where phase = 'during') as receiver_ap,
    max(receiver_bssid) filter (where phase = 'during') as receiver_bssid,
    max(receiver_channel) filter (where phase = 'during') as receiver_channel,
    max(receiver_band) filter (where phase = 'during') as receiver_band,
    max(receiver_rssi) filter (where phase = 'during') as receiver_rssi,
    max(receiver_snr) filter (where phase = 'during') as receiver_snr,
    bool_or(receiver_group_member) filter (where phase = 'during') as receiver_group_member,
    max(receiver_group_status) filter (where phase = 'during') as receiver_group_status,
    max(mgid) filter (where phase = 'during') as mgid
  from vocera_media_wlc_snapshots snapshot
  where snapshot.attempt_id = a.attempt_id
) snapshot_stats on true
left join lateral (
  select
    count(*) filter (where severity = 'critical') as critical_finding_count,
    count(*) filter (where severity = 'warning') as warning_finding_count
  from vocera_media_attempt_findings finding
  where finding.attempt_id = a.attempt_id
) finding_stats on true;

create or replace view v_vocera_media_attempt_artifacts as
select *
from vocera_media_attempt_artifacts;

create or replace view v_vocera_media_attempt_findings as
select *
from vocera_media_attempt_findings;

create or replace view v_vocera_media_multicast_observations as
select *
from vocera_media_multicast_observations;

create or replace view v_vocera_media_vocera_group_explorer as
select
  vocera_group_ip,
  vocera_group_mac,
  min(observed_at) as first_seen,
  max(observed_at) as last_seen,
  array_remove(array_agg(distinct source_ip::text), null) as source_ips,
  array_remove(array_agg(distinct vocera_vlan), null) as vlans,
  array_remove(array_agg(distinct mgid), null) as mgids,
  array_remove(array_agg(distinct attempt_id), null) as associated_attempts,
  bool_or(receiver_member) as receiver_membership_seen,
  array_remove(array_agg(distinct ap_name), null) as aps_involved,
  array_remove(array_agg(distinct evidence_source), null) as evidence_sources,
  max(capture_confidence) as capture_confidence,
  count(*)::integer as observation_count
from vocera_media_multicast_observations
where vocera_group_ip is not null
group by vocera_group_ip, vocera_group_mac;

create or replace view v_vocera_media_attempt_timeline as
select
  attempt_id,
  study_id,
  started_at as event_time,
  'attempt_started'::text as event_kind,
  verdict as event_value,
  raw_context as event_context
from vocera_media_broadcast_attempts
where started_at is not null
union all
select
  coalesce(attempt_id, event_id) as attempt_id,
  study_id,
  event_time,
  'session_' || event_kind as event_kind,
  coalesce(audio_result, notes, event_kind) as event_value,
  raw_context as event_context
from vocera_media_capture_session_events
union all
select
  attempt_id,
  null::text as study_id,
  null::timestamptz as event_time,
  'wlc_snapshot_' || coalesce(phase, 'unknown') as event_kind,
  coalesce(receiver_ap, vocera_group::text, receiver_group_status) as event_value,
  jsonb_build_object(
    'receiver_group_member', receiver_group_member,
    'receiver_ap', receiver_ap,
    'receiver_bssid', receiver_bssid,
    'receiver_channel', receiver_channel,
    'receiver_rssi', receiver_rssi,
    'receiver_snr', receiver_snr,
    'vocera_group', vocera_group,
    'vocera_vlan', vocera_vlan,
    'configured_vocera_vlan', configured_vocera_vlan,
    'resolved_group_vlan', resolved_group_vlan,
    'vlan_context_state', vlan_context_state,
    'mgid', mgid
  ) as event_context
from vocera_media_wlc_snapshots;

create or replace view v_vocera_media_multicast_attempt_matrix as
select
  a.study_id,
  a.capture_session_id,
  a.attempt_id,
  a.attempt_marked_at,
  a.audio_result,
  a.configured_vocera_vlan,
  a.resolved_group_vlan,
  a.vlan_context_state,
  max(o.vocera_group_ip::text) as vocera_group_ip,
  max(o.vocera_group_mac) as vocera_group_mac,
  max(o.vocera_vlan) as vocera_vlan,
  max(o.mgid) as mgid,
  bool_or(o.receiver_member) as receiver_member_seen,
  bool_or(o.receiver_blocklisted) as receiver_blocklisted_seen,
  max(o.receiver_membership_mode) as receiver_membership_mode,
  max(o.wlc_capwap_group::text) as wlc_capwap_group,
  max(o.wlc_capwap_mode) as wlc_capwap_mode,
  max(o.ap_mom_status) as ap_mom_status,
  max(o.ap_delivery_mode) as ap_delivery_mode,
  max(o.ap_tx_packets) as ap_tx_packets,
  max(o.ap_rx_packets) as ap_rx_packets,
  array_remove(array_agg(distinct o.evidence_source), null) as evidence_sources,
  a.verdict,
  a.verdict_confidence
from vocera_media_broadcast_attempts a
left join vocera_media_multicast_observations o
  on o.attempt_id = a.attempt_id
group by
  a.study_id,
  a.capture_session_id,
  a.attempt_id,
  a.attempt_marked_at,
  a.audio_result,
  a.configured_vocera_vlan,
  a.resolved_group_vlan,
  a.vlan_context_state,
  a.verdict,
  a.verdict_confidence;

-- Compatibility migration:
-- The legacy attempt-summary view exposed attempt_count immediately after
-- study_id. Adding capture_session_id changes the view's output shape, which
-- PostgreSQL will not permit through CREATE OR REPLACE VIEW alone.
--
-- Intentionally no CASCADE: unexpected dependent objects must block the
-- migration for explicit review.
drop view if exists v_vocera_media_attempt_summary;

create or replace view v_vocera_media_attempt_summary as
select
  study_id,
  capture_session_id,
  count(*)::integer as attempt_count,
  count(*) filter (where audio_result = 'heard')::integer as heard_attempt_count,
  count(*) filter (where audio_result = 'missed')::integer as missed_attempt_count,
  count(*) filter (where audio_result in ('partial', 'choppy'))::integer as degraded_attempt_count,
  count(*) filter (where verdict = 'membership_failure')::integer as membership_failure_count,
  count(*) filter (where verdict = 'media_degraded')::integer as media_degraded_count,
  count(*) filter (where verdict = 'inconclusive')::integer as inconclusive_count,
  min(started_at) as first_attempt_at,
  max(started_at) as latest_attempt_at
from vocera_media_broadcast_attempts
group by study_id, capture_session_id;

create or replace view v_vocera_media_attempt_ap_distribution as
select
  a.study_id,
  s.receiver_ap,
  s.receiver_channel,
  s.receiver_band,
  count(*)::integer as attempt_count,
  count(*) filter (where a.audio_result = 'missed')::integer as missed_audio_count,
  count(*) filter (where a.verdict = 'membership_failure')::integer as membership_failure_count
from vocera_media_broadcast_attempts a
join vocera_media_wlc_snapshots s
  on s.attempt_id = a.attempt_id
where s.phase = 'during'
group by
  a.study_id,
  s.receiver_ap,
  s.receiver_channel,
  s.receiver_band;
