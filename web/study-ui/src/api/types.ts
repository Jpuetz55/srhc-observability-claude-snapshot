export type StringRow = Record<string, string | undefined>

export type SourceType = 'badge_log' | 'ekahau_json' | 'manual_csv' | 'ipad_client_detail' | 'other'
export type RunStatus = 'draft' | 'running' | 'complete' | 'failed' | 'deleted'

export type BackendStatus = {
  backend_status?: string
  project_table?: string
  study_table?: string
  input_file_table?: string
  run_input_file_table?: string
  project_view?: string
  study_view?: string
  project_canonical_view?: string
  project_duplicate_view?: string
  input_file_view?: string
  run_view?: string
  run_file_view?: string
  run_delete_function?: string
}

export type GrafanaPanelConfig = {
  dashboardUid: string
  slug: string
  panelId: number
}

export type GrafanaPanelStatus = {
  name: string
  config_key: string
  configured: boolean
  dashboard_uid?: string | null
  dashboard_slug?: string | null
  panel_id?: string | null
  missing?: string[]
  invalid?: string[]
  url?: string
}

export type GrafanaStatusResponse = {
  ok: boolean
  grafana: {
    proxy_enabled: boolean
    base_path: string
    upstream?: string | null
    proxy_strip_base_path: boolean
    org_id: string
    theme: string
    upstream_health: StringRow
    panels: Record<string, GrafanaPanelStatus>
  }
}

export type AppConfig = {
  scope: string
  user: string
  grafana: {
    basePath: string
    orgId: string
    theme: string
    proxyEnabled?: boolean
    panels: {
      apVoiceLatency?: GrafanaPanelConfig | null
      txRetry?: GrafanaPanelConfig | null
      mediaQoe?: GrafanaPanelConfig | null
      mediaQoeSummary?: GrafanaPanelConfig | null
      mediaQoeCaptureInventory?: GrafanaPanelConfig | null
      mediaQoeRtpTrouble?: GrafanaPanelConfig | null
      mediaQoeDscp?: GrafanaPanelConfig | null
      mediaQoeDirection?: GrafanaPanelConfig | null
      mediaQoeClassification?: GrafanaPanelConfig | null
      mediaQoeRejectionReasons?: GrafanaPanelConfig | null
    }
  }
}

export type RfSummary = {
  ok: boolean
  errors: Record<string, string | null | undefined>
  skipped?: string | null
  backend: BackendStatus
  current: StringRow
  runs: StringRow[]
  config: AppConfig
}

export type ApiResult = {
  ok: boolean
  result?: StringRow
  detail?: string
}

export type ProjectType = 'rf_validation' | 'media_qoe' | 'mixed'
export type StudyType = 'rf_validation' | 'media_qoe'
export type StudyScope = 'vocera_badge' | 'ipad' | 'media_qoe'
export type StudyStatus = 'active' | 'complete' | 'archived' | 'deleted'

export type Project = StringRow
export type Study = StringRow
export type RfRun = StringRow
export type RfInputFile = StringRow
export type RfRunFile = StringRow

export type RfRunsResponse = {
  ok: boolean
  runs: RfRun[]
}

export type ProjectsResponse = {
  ok: boolean
  projects: Project[]
}

export type ProjectResponse = {
  ok: boolean
  project: Project
  studies?: Study[]
}

export type StudiesResponse = {
  ok: boolean
  studies: Study[]
}

export type StudyResponse = {
  ok: boolean
  study: Study
  runs?: RfRun[]
}

export type ProjectPayload = {
  project_id?: string
  project_name?: string
  project_type?: ProjectType
  description?: string
  site?: string
}

export type StudyPayload = {
  study_id?: string
  project_id?: string
  study_type?: StudyType
  study_scope?: StudyScope
  study_name?: string
  description?: string
  study_status?: StudyStatus
}

export type ProjectRfResultsResponse = {
  ok: boolean
  results: StringRow[]
}

export type ProjectRfDuplicatesResponse = {
  ok: boolean
  duplicates: StringRow[]
}

export type MediaQoeSummaryResponse = {
  ok: boolean
  project: Project
  summary: StringRow
  studies: Study[]
}

export type MediaQoeProjectSummaryResponse = {
  ok: boolean
  summary: StringRow
}

export type MediaExecutionStatusResponse = {
  ok: boolean
  execution_enabled: boolean
  archive_enabled: boolean
  raw_dir: string
  allowed_extensions: string[]
  max_scan_files: number
  max_parse_bytes: number
  parse_timeout_seconds: number
  raw_dir_exists: boolean
  raw_dir_readable: boolean
  parse_running?: boolean
  active_parse?: StringRow | null
}

export type MediaDnacStatusResponse = {
  ok: boolean
  configured: boolean
  dnac_client_available?: boolean
  base_url_configured: boolean
  username_configured: boolean
  password_configured: boolean
  tls_verify: boolean
  raw_dir: string
  raw_dir_exists: boolean
  raw_dir_readable: boolean
  default_client_mac?: string | null
  default_ap_mac?: string | null
  default_capture_type?: string | null
  lookback_minutes?: number | null
  limit?: number | null
  start_capture_available: boolean
  start_capture_unavailable_reason?: string | null
  download_enabled: boolean
  missing_config: string[]
  auth_ok?: boolean | null
  client_detail_ok?: boolean | null
  capture_files_api_ok?: boolean | null
  capture_files_returned?: number | null
  resolved?: StringRow | null
  error_summary?: string | null
}

export type MediaDnacCapture = {
  dnac_capture_id?: string | null
  file_name: string
  file_size?: number | null
  created_at?: string | null
  updated_at?: string | null
  client_mac?: string | null
  ap_mac?: string | null
  capture_type?: string | null
  local_path?: string | null
  already_downloaded?: boolean
  already_registered?: boolean
  registered_in_other_study?: boolean
  already_parsed?: boolean
  registered_capture_id?: string | null
  capture_status?: string | null
  parse_success?: string | boolean | null
  stream_count?: string | number | null
  rtp_qoe_stream_count?: string | number | null
  dscp_mismatch_stream_count?: string | number | null
  trusted_rtp_dscp_mismatch_stream_count?: string | number | null
  non_rtp_dscp_mismatch_stream_count?: string | number | null
  lossy_stream_count?: string | number | null
  jitter_p95_ms?: string | number | null
  loss_p95_ratio?: string | number | null
  interarrival_p95_ms?: string | number | null
}

export type MediaDnacCapturesResponse = {
  ok: boolean
  study_id: string
  client_mac: string
  ap_mac?: string | null
  capture_type: string
  lookback_minutes: number
  limit: number
  offset: number
  raw_dir: string
  captures: MediaDnacCapture[]
}

export type MediaDnacCaptureQuery = {
  client_mac?: string
  ap_mac?: string
  capture_type?: string
  lookback_minutes?: number
  limit?: number
  offset?: number
}

export type MediaDnacCaptureDownloadRequest = MediaDnacCaptureQuery & {
  capture_id?: string
  file_name?: string
  register?: boolean
}

export type MediaDnacCaptureDownloadResponse = {
  ok: boolean
  downloaded: boolean
  registered: boolean
  registration_created?: boolean
  local_path: string
  sidecar_path: string
  capture_id?: string | null
  source_name: string
  dnac_capture_id?: string | null
  file_size?: number | null
  message?: string
}

export type MediaQoeCapturesResponse = {
  ok: boolean
  captures: StringRow[]
}

export type MediaRawFile = {
  source_path: string
  source_name: string
  source_size_bytes?: string | number
  source_mtime?: string
  source_sha256?: string
  registered?: boolean
  capture_id?: string
  capture_status?: string
  parse_success?: string | boolean
  stream_count?: string | number
  rtp_qoe_stream_count?: string | number
  dscp_mismatch_stream_count?: string | number
  trusted_rtp_dscp_mismatch_stream_count?: string | number
  non_rtp_dscp_mismatch_stream_count?: string | number
  lossy_stream_count?: string | number
  jitter_p95_ms?: string | number
  loss_p95_ratio?: string | number
  interarrival_p95_ms?: string | number
}

export type MediaRawFilesResponse = {
  ok: boolean
  raw_dir: string
  files: MediaRawFile[]
}

export type MediaCaptureRegisterRequest = {
  source_path: string
  source_name?: string
  site?: string
  capture_point?: string
  notes?: string
}

export type MediaCaptureRegisterResponse = {
  ok: boolean
  capture: StringRow
  registered?: boolean
}

export type MediaCaptureExecuteRequest = {
  reparse?: boolean
  timeout_seconds?: number
}

export type MediaCaptureExecuteResponse = {
  ok: boolean
  capture_id: string
  parse_run_id?: string
  status: string
  duration_seconds?: number
  summary?: Record<string, unknown>
  error?: string | null
}

export type MediaParseRunsResponse = {
  ok: boolean
  parse_runs: StringRow[]
}

export type MediaQoeStreamsResponse = {
  ok: boolean
  streams: StringRow[]
}

export type MediaQoeDuplicatesResponse = {
  ok: boolean
  duplicates: StringRow[]
}

export type MediaWlcDefaultsResponse = {
  ok: boolean
  defaults: {
    site?: string
    wlc_name?: string
    wlc_ssh_host?: string
    wlc_ssh_port?: number
    capture_name?: string
    wlc_interface?: string
    capture_filter_mode?: string
    collector_host?: string
    collector_scp_username?: string
    collector_scp_port?: number
    ring_file_count?: number
    ring_file_size_mb?: number
    continuous_export_enabled?: boolean
    short_validation_duration_seconds?: number
    expected_dscp?: number
    vocera_vlan?: number
    vocera_multicast_pool?: string
    vocera_first_usable?: string
    vocera_last_usable?: string
    sender?: StringRow
    receiver?: StringRow
  }
  session_root: string
  password_policy: {
    collects_passwords: boolean
    message: string
  }
}

export type MediaWlcSessionCreateRequest = {
  session_id?: string
  site?: string
  wlc_name?: string
  capture_name?: string
  wlc_interface?: string
  capture_filter_mode?: string
  capture_mode?: 'long_reproduction' | 'short_validation'
  short_validation_duration_seconds?: number
  collector_host?: string
  collector_scp_username?: string
  collector_scp_port?: number
  collector_scp_path?: string
  ring_file_count?: number
  ring_file_size_mb?: number
  continuous_export_enabled?: boolean
  sender_name?: string
  sender_model?: string
  sender_mac?: string
  sender_ip?: string
  receiver_name?: string
  receiver_model?: string
  receiver_mac?: string
  receiver_ip?: string
  expected_dscp?: number
  vocera_vlan?: number
  vocera_multicast_pool?: string
  vocera_first_usable?: string
  vocera_last_usable?: string
  notes?: string
}

export type MediaWlcSessionsResponse = {
  ok: boolean
  sessions: StringRow[]
}

export type MediaWlcSessionArtifactsResponse = {
  ok: boolean
  artifacts: StringRow[]
}

export type MediaWlcSessionResponse = {
  ok: boolean
  session: StringRow
  package_path?: string
  command_sheets?: Record<string, string>
  message?: string
}

export type MediaWlcSessionDetailResponse = {
  ok: boolean
  session: StringRow
  attempts: StringRow[]
  events: StringRow[]
  artifacts: StringRow[]
  capture_legs?: StringRow[]
  ap_ota_preflight?: Record<string, unknown>
  command_sheets: Record<string, string>
  ingest_status?: Record<string, unknown>
  open_attempt_id?: string | null
  selected_attempt_id?: string | null
  next_operator_action?: StringRow
}

export type MediaWlcSessionPatchRequest = {
  session_state?: 'prepared_not_started' | 'running' | 'stopped' | 'exported' | 'imported' | 'aborted'
  capture_started_at?: string
  capture_stopped_at?: string
  resolved_group_ip?: string
  resolved_group_vlan?: number
  resolved_mgid?: number
  resolved_at?: string
  vlan_selection_source?: 'default' | 'operator_override' | 'observed_confirmation'
  vlan_override_reason?: string
  notes?: string
}

export type MediaWlcSessionEventRequest = {
  attempt_id?: string
  event_kind: 'broadcast_started' | 'heard' | 'missed' | 'partial' | 'choppy' | 'alert_only' | 'session_end' | 'note'
  event_time?: string
  browser_event_time?: string
  operator_name?: string
  audio_result?: 'heard' | 'missed' | 'partial' | 'choppy' | 'unknown' | 'not_tested'
  alert_received?: boolean
  audio_received?: boolean
  notes?: string
}

export type MediaWlcSessionEventResponse = {
  ok: boolean
  session: StringRow
  event: StringRow
  attempt_id?: string | null
}

export type MediaWlcAttemptsResponse = {
  ok: boolean
  attempts: StringRow[]
  open_attempt_id?: string | null
}

export type MediaWlcAttemptResponse = {
  ok: boolean
  attempt: StringRow
  session?: StringRow
}

export type MediaWlcAttemptStartRequest = {
  attempt_id?: string
  started_at?: string
  browser_event_time?: string
  operator_name?: string
  notes?: string
}

export type MediaWlcAttemptOutcomeRequest = {
  audio_result: 'heard' | 'missed' | 'partial' | 'choppy' | 'alert_only'
  alert_received?: boolean
  audio_received?: boolean
  ended_at?: string
  browser_event_time?: string
  operator_name?: string
  notes?: string
}

export type MediaWlcAttemptActiveGroupRequest = {
  group_ip: string
  group_vlan: number
  mgid?: number
  selection_source?: 'operator_override' | 'observed_confirmation'
  vlan_override_reason?: string
  group_summary_raw?: string
  selected_row?: string
  selected_at?: string
  operator_name?: string
}

export type MediaStreamReviewStatus = 'unreviewed' | 'accepted' | 'excluded' | 'needs_review'

export type MediaStreamClassification =
  | 'vocera_rtp'
  | 'server_to_badge'
  | 'badge_to_server'
  | 'badge_to_badge'
  | 'non_rtp_udp'
  | 'unknown_udp'
  | 'control'
  | 'noise'
  | 'exclude'

export type MediaQoeStreamReviewPayload = {
  accepted?: boolean | null
  stream_classification?: MediaStreamClassification | null
  review_status?: MediaStreamReviewStatus
  review_notes?: string | null
}

export type MediaQoeStreamReviewResponse = {
  ok: boolean
  stream: StringRow
}

export type RfRunAlignment = StringRow

export type RfManualEntries = {
  pending: StringRow[]
  completed: StringRow[]
}

export type RfRunResponse = {
  ok: boolean
  run: RfRun
  files?: RfRunFile[]
  alignment?: RfRunAlignment
  manual_entries?: RfManualEntries
}

export type RfManualEntriesResponse = {
  ok: boolean
  manual_entries: RfManualEntries
}

export type ToleranceSweepWindow = {
  window_seconds: number
  matched_points: number
  near_edge_points: number
  ambiguous_points: number
}

export type ToleranceSweep = {
  survey_point_count_with_same_date_badge: number
  windows: ToleranceSweepWindow[]
  abs_delta_min_seconds: number | null
  abs_delta_median_seconds: number | null
  abs_delta_p90_seconds: number | null
  signed_delta_median_seconds: number | null
  signed_deltas: number[]
}

export type RfTimeAlignmentResponse = {
  ok: boolean
  test_run_id: string
  current_window_seconds: number
  sweep: ToleranceSweep
  timeline: {
    badge_event_epochs: number[]
    survey_point_epochs: number[]
    badge_event_count: number
    survey_point_count: number
    window_start_epoch: number | null
    window_end_epoch: number | null
    badge_truncated: boolean
    survey_truncated: boolean
  }
  cal_delta_points: { abs_time_delta_seconds: number; calibrated_delta_db: number }[]
}

export type RunComparisonRow = {
  test_run_id: string
  run_name: string | null
  run_status: string | null
  default_match_window_seconds: number | null
  match_window_seconds_used: number | null
  candidate_match_count: number | null
  pending_candidate_match_count: number | null
  completed_match_count: number | null
  completion_percent: number | null
  mean_cal_delta: number | null
  stddev_cal_delta: number | null
  p95_cal_delta: number | null
  min_cal_delta: number | null
  max_cal_delta: number | null
  outlier_count: number | null
}

export type RunComparisonResponse = {
  ok: boolean
  study_id: string
  rows: RunComparisonRow[]
  interpretation: string
}

export type RfInputFilesResponse = {
  ok: boolean
  input_files: RfInputFile[]
  scanned_count?: number
}

export type RfInputFileResponse = {
  ok: boolean
  input_file: RfInputFile
}

export type RfRunBundleResponse = {
  ok: boolean
  run: RfRun
  files: RfRunFile[]
  badge_file: RfInputFile
  ekahau_file: RfInputFile
  bundle_path?: string
  extract_dir?: string
}

export type StudySample = {
  sample_id: string
  study_id?: string
  study_name?: string
  test_run_id?: string
  run_name?: string
  match_id?: string
  candidate_match_id?: string
  survey_time?: string
  bssid?: string
  ap_name?: string
  channel?: string
  badge_rssi_dbm?: string | null
  badge_snr_db?: string | null
  calibrated_delta_db?: string | null
  label?: string | null
  ekahau_rssi_dbm?: string | null
  ekahau_snr_db?: string | null
  notes?: string | null
  created_at?: string
  updated_at?: string
  rssi_z_score?: number | null
  rssi_is_outlier?: boolean
  snr_z_score?: number | null
  snr_is_outlier?: boolean
  cal_delta_z_score?: number | null
  cal_delta_is_outlier?: boolean
  is_outlier?: boolean
}

export type SampleMetricStats = {
  count: number
  mean: number | null
  stddev: number | null
  variance: number | null
  min: number | null
  max: number | null
  range: number | null
  p05: number | null
  p25: number | null
  p50: number | null
  p75: number | null
  p95: number | null
  iqr: number | null
  sem: number | null
  ci95_low: number | null
  ci95_high: number | null
  outlier_count?: number
}

export type SampleStatistics = {
  cal_delta: SampleMetricStats
}

export type StudySamplesResponse = {
  ok: boolean
  study_id: string
  error?: string
  detail?: string
  z_threshold: number
  sample_count: number
  statistics: SampleStatistics
  samples: StudySample[]
  inserted?: number
}

export type ManualSamplePayload = {
  label?: string | null
  ekahau_rssi_dbm?: number | null
  ekahau_snr_db?: number | null
  notes?: string | null
}

export type RunPayload = {
  test_run_id?: string
  study_id?: string
  run_name?: string
  run_status?: RunStatus
  site?: string
  building?: string
  floor?: string
  area?: string
  ssid?: string
  badge_mac?: string
  badge_model?: string
  ekahau_device?: string
  ekahau_project?: string
  timezone?: string
  badge_time_offset_seconds?: number
  ekahau_time_offset_seconds?: number
  default_match_window_seconds?: number
  vendor_offset_source?: string
  notes?: string
}


export interface TimeAlignmentPayload {
  runId?: string
  run_id?: string
  matchWindowSeconds?: number | string | null
  match_window_seconds?: number | string | null
  toleranceSeconds?: number | string | null
  tolerance_seconds?: number | string | null
  apply?: boolean
  previewOnly?: boolean
  preview_only?: boolean
  [key: string]: unknown
}
