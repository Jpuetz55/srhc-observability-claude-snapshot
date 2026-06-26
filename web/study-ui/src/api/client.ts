import type { ApiResult, GrafanaStatusResponse, ManualSamplePayload, MediaCaptureExecuteRequest, MediaCaptureExecuteResponse, MediaCaptureRegisterRequest, MediaCaptureRegisterResponse, MediaDnacCaptureDownloadRequest, MediaDnacCaptureDownloadResponse, MediaDnacCaptureQuery, MediaDnacCapturesResponse, MediaDnacStatusResponse, MediaExecutionStatusResponse, MediaParseRunsResponse, MediaQoeCapturesResponse, MediaQoeDuplicatesResponse, MediaQoeProjectSummaryResponse, MediaQoeStreamReviewPayload, MediaQoeStreamReviewResponse, MediaQoeStreamsResponse, MediaQoeSummaryResponse, MediaRawFilesResponse, MediaWlcAttemptActiveGroupRequest, MediaWlcAttemptOutcomeRequest, MediaWlcAttemptResponse, MediaWlcAttemptsResponse, MediaWlcAttemptStartRequest, MediaWlcDefaultsResponse, MediaWlcSessionCreateRequest, MediaWlcSessionDetailResponse, MediaWlcSessionEventRequest, MediaWlcSessionArtifactsResponse, MediaWlcSessionEventResponse, MediaWlcSessionPatchRequest, MediaWlcSessionResponse, MediaWlcSessionsResponse, ProjectPayload, ProjectResponse, ProjectRfDuplicatesResponse, ProjectRfResultsResponse, ProjectsResponse, RfInputFileResponse, RfInputFilesResponse, RfManualEntriesResponse, RfRunBundleResponse, RfRunResponse, RfRunsResponse, RfSummary, RfTimeAlignmentResponse, RunComparisonResponse, RunPayload, SourceType, StudiesResponse, StudyPayload, StudyResponse, StudySamplesResponse } from './types'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init
  })
  const contentType = response.headers.get('content-type') ?? ''
  const body = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? String(body.detail) : String(body)
    throw new Error(detail || `${response.status} ${response.statusText}`)
  }
  return body as T
}

export function getRfSummary(): Promise<RfSummary> {
  return request<RfSummary>('/api/rf/summary')
}

export function getGrafanaStatus(): Promise<GrafanaStatusResponse> {
  return request<GrafanaStatusResponse>('/api/grafana/status')
}

export function getMediaQoeSummary(): Promise<MediaQoeSummaryResponse> {
  return request<MediaQoeSummaryResponse>('/api/media-qoe/summary')
}

export function getMediaQoeExecutionStatus(): Promise<MediaExecutionStatusResponse> {
  return request<MediaExecutionStatusResponse>('/api/media-qoe/execution/status')
}

function mediaDnacQuerySuffix(options: MediaDnacCaptureQuery = {}): string {
  const params = new URLSearchParams()
  if (options.client_mac) {
    params.set('client_mac', options.client_mac)
  }
  if (options.ap_mac) {
    params.set('ap_mac', options.ap_mac)
  }
  if (options.capture_type) {
    params.set('capture_type', options.capture_type)
  }
  if (options.lookback_minutes !== undefined) {
    params.set('lookback_minutes', String(options.lookback_minutes))
  }
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit))
  }
  if (options.offset !== undefined) {
    params.set('offset', String(options.offset))
  }
  const text = params.toString()
  return text ? `?${text}` : ''
}

export function getMediaQoeDnacStatus(options: MediaDnacCaptureQuery = {}): Promise<MediaDnacStatusResponse> {
  return request<MediaDnacStatusResponse>(`/api/media-qoe/dnac/status${mediaDnacQuerySuffix(options)}`)
}

export function listProjects(): Promise<ProjectsResponse> {
  return request<ProjectsResponse>('/api/projects')
}

export function createProject(payload: ProjectPayload): Promise<ProjectResponse> {
  return request<ProjectResponse>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getProject(projectId: string): Promise<ProjectResponse> {
  return request<ProjectResponse>(`/api/projects/${encodeURIComponent(projectId)}`)
}

export function updateProject(projectId: string, payload: ProjectPayload): Promise<ProjectResponse> {
  return request<ProjectResponse>(`/api/projects/${encodeURIComponent(projectId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function deleteProject(projectId: string): Promise<ProjectResponse> {
  return request<ProjectResponse>(`/api/projects/${encodeURIComponent(projectId)}`, { method: 'DELETE' })
}

export function listProjectStudies(projectId: string): Promise<StudiesResponse> {
  return request<StudiesResponse>(`/api/projects/${encodeURIComponent(projectId)}/studies`)
}

export function createProjectStudy(projectId: string, payload: StudyPayload): Promise<StudyResponse> {
  return request<StudyResponse>(`/api/projects/${encodeURIComponent(projectId)}/studies`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getStudy(studyId: string): Promise<StudyResponse> {
  return request<StudyResponse>(`/api/studies/${encodeURIComponent(studyId)}`)
}

export function updateStudy(studyId: string, payload: StudyPayload): Promise<StudyResponse> {
  return request<StudyResponse>(`/api/studies/${encodeURIComponent(studyId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function deleteStudy(studyId: string): Promise<StudyResponse> {
  return request<StudyResponse>(`/api/studies/${encodeURIComponent(studyId)}`, { method: 'DELETE' })
}

export function listStudyRuns(studyId: string): Promise<RfRunsResponse> {
  return request<RfRunsResponse>(`/api/studies/${encodeURIComponent(studyId)}/runs`)
}

export function getStudyRunComparison(studyId: string): Promise<RunComparisonResponse> {
  return request<RunComparisonResponse>(`/api/studies/${encodeURIComponent(studyId)}/run-comparison`)
}

export function createStudyRun(studyId: string, payload: RunPayload): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/studies/${encodeURIComponent(studyId)}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function listStudySamples(studyId: string, zThreshold?: number): Promise<StudySamplesResponse> {
  const suffix = zThreshold !== undefined ? `?z_threshold=${encodeURIComponent(String(zThreshold))}` : ''
  return request<StudySamplesResponse>(`/api/studies/${encodeURIComponent(studyId)}/samples${suffix}`)
}

function zThresholdSuffix(zThreshold?: number): string {
  return zThreshold !== undefined ? `?z_threshold=${encodeURIComponent(String(zThreshold))}` : ''
}

export function createStudySample(
  studyId: string,
  payload: ManualSamplePayload,
  zThreshold?: number
): Promise<StudySamplesResponse> {
  return request<StudySamplesResponse>(`/api/studies/${encodeURIComponent(studyId)}/samples${zThresholdSuffix(zThreshold)}`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function createStudySamplesBulk(
  studyId: string,
  samples: ManualSamplePayload[],
  zThreshold?: number
): Promise<StudySamplesResponse> {
  return request<StudySamplesResponse>(`/api/studies/${encodeURIComponent(studyId)}/samples/bulk${zThresholdSuffix(zThreshold)}`, {
    method: 'POST',
    body: JSON.stringify({ samples })
  })
}

export function updateStudySample(
  sampleId: string,
  payload: ManualSamplePayload,
  zThreshold?: number
): Promise<StudySamplesResponse> {
  return request<StudySamplesResponse>(`/api/samples/${encodeURIComponent(sampleId)}${zThresholdSuffix(zThreshold)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function deleteStudySample(sampleId: string, zThreshold?: number): Promise<StudySamplesResponse> {
  return request<StudySamplesResponse>(`/api/samples/${encodeURIComponent(sampleId)}${zThresholdSuffix(zThreshold)}`, { method: 'DELETE' })
}

export function getProjectRfResults(projectId: string): Promise<ProjectRfResultsResponse> {
  return request<ProjectRfResultsResponse>(`/api/projects/${encodeURIComponent(projectId)}/rf-results`)
}

export function getProjectRfRawResults(projectId: string): Promise<ProjectRfResultsResponse> {
  return request<ProjectRfResultsResponse>(`/api/projects/${encodeURIComponent(projectId)}/rf-results/raw`)
}

export function getProjectRfDuplicates(projectId: string): Promise<ProjectRfDuplicatesResponse> {
  return request<ProjectRfDuplicatesResponse>(`/api/projects/${encodeURIComponent(projectId)}/duplicates`)
}

export function getProjectMediaQoeSummary(projectId: string): Promise<MediaQoeProjectSummaryResponse> {
  return request<MediaQoeProjectSummaryResponse>(`/api/projects/${encodeURIComponent(projectId)}/media-qoe/summary`)
}

export function listProjectMediaQoeCaptures(projectId: string): Promise<MediaQoeCapturesResponse> {
  return request<MediaQoeCapturesResponse>(`/api/projects/${encodeURIComponent(projectId)}/media-qoe/captures`)
}

export function listProjectMediaQoeStreams(projectId: string): Promise<MediaQoeStreamsResponse> {
  return request<MediaQoeStreamsResponse>(`/api/projects/${encodeURIComponent(projectId)}/media-qoe/streams`)
}

export function listProjectMediaQoeDuplicates(projectId: string): Promise<MediaQoeDuplicatesResponse> {
  return request<MediaQoeDuplicatesResponse>(`/api/projects/${encodeURIComponent(projectId)}/media-qoe/duplicates`)
}

export function listStudyMediaQoeCaptures(studyId: string): Promise<MediaQoeCapturesResponse> {
  return request<MediaQoeCapturesResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/captures`)
}

export function listStudyMediaQoeStreams(studyId: string): Promise<MediaQoeStreamsResponse> {
  return request<MediaQoeStreamsResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/streams`)
}

export function listStudyMediaQoeRawFiles(studyId: string, options: { includeRegistered?: boolean; limit?: number } = {}): Promise<MediaRawFilesResponse> {
  const params = new URLSearchParams()
  if (options.includeRegistered !== undefined) {
    params.set('include_registered', String(options.includeRegistered))
  }
  if (options.limit !== undefined) {
    params.set('limit', String(options.limit))
  }
  const suffix = params.toString() ? `?${params.toString()}` : ''
  return request<MediaRawFilesResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/raw-files${suffix}`)
}

export function listStudyMediaQoeDnacCaptures(studyId: string, options: MediaDnacCaptureQuery = {}): Promise<MediaDnacCapturesResponse> {
  return request<MediaDnacCapturesResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/dnac/captures${mediaDnacQuerySuffix(options)}`)
}

export function downloadStudyMediaQoeDnacCapture(studyId: string, payload: MediaDnacCaptureDownloadRequest): Promise<MediaDnacCaptureDownloadResponse> {
  return request<MediaDnacCaptureDownloadResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/dnac/captures/download`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function registerStudyMediaQoeCapture(studyId: string, payload: MediaCaptureRegisterRequest): Promise<MediaCaptureRegisterResponse> {
  return request<MediaCaptureRegisterResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/captures/register`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function executeMediaQoeCapture(captureId: string, payload: MediaCaptureExecuteRequest = {}): Promise<MediaCaptureExecuteResponse> {
  return request<MediaCaptureExecuteResponse>(`/api/media-qoe/captures/${encodeURIComponent(captureId)}/execute`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function listMediaQoeCaptureParseRuns(captureId: string): Promise<MediaParseRunsResponse> {
  return request<MediaParseRunsResponse>(`/api/media-qoe/captures/${encodeURIComponent(captureId)}/parse-runs`)
}

export function updateMediaQoeStreamReview(captureId: string, streamId: string, payload: MediaQoeStreamReviewPayload): Promise<MediaQoeStreamReviewResponse> {
  return request<MediaQoeStreamReviewResponse>(`/api/media-qoe/streams/${encodeURIComponent(captureId)}/${encodeURIComponent(streamId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function getMediaQoeWlcDefaults(): Promise<MediaWlcDefaultsResponse> {
  return request<MediaWlcDefaultsResponse>('/api/media-qoe/wlc/defaults')
}

export function listStudyMediaQoeWlcSessions(studyId: string): Promise<MediaWlcSessionsResponse> {
  return request<MediaWlcSessionsResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/wlc/sessions`)
}

export function createStudyMediaQoeWlcSession(studyId: string, payload: MediaWlcSessionCreateRequest): Promise<MediaWlcSessionResponse> {
  return request<MediaWlcSessionResponse>(`/api/studies/${encodeURIComponent(studyId)}/media-qoe/wlc/sessions`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function getMediaQoeWlcSession(sessionId: string): Promise<MediaWlcSessionDetailResponse> {
  return request<MediaWlcSessionDetailResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}`)
}

export function updateMediaQoeWlcSession(sessionId: string, payload: MediaWlcSessionPatchRequest): Promise<MediaWlcSessionResponse> {
  return request<MediaWlcSessionResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function createMediaQoeWlcSessionEvent(sessionId: string, payload: MediaWlcSessionEventRequest): Promise<MediaWlcSessionEventResponse> {
  return request<MediaWlcSessionEventResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}/events`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function listMediaQoeWlcSessionAttempts(sessionId: string): Promise<MediaWlcAttemptsResponse> {
  return request<MediaWlcAttemptsResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}/attempts`)
}

export function listMediaQoeWlcSessionArtifacts(sessionId: string): Promise<MediaWlcSessionArtifactsResponse> {
  return request<MediaWlcSessionArtifactsResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}/artifacts`)
}

export function startMediaQoeWlcAttempt(sessionId: string, payload: MediaWlcAttemptStartRequest = {}): Promise<MediaWlcAttemptResponse> {
  return request<MediaWlcAttemptResponse>(`/api/media-qoe/wlc/sessions/${encodeURIComponent(sessionId)}/attempts/start`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function setMediaQoeWlcAttemptOutcome(attemptId: string, payload: MediaWlcAttemptOutcomeRequest): Promise<MediaWlcAttemptResponse> {
  return request<MediaWlcAttemptResponse>(`/api/media-qoe/wlc/attempts/${encodeURIComponent(attemptId)}/outcome`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function setMediaQoeWlcAttemptActiveGroup(attemptId: string, payload: MediaWlcAttemptActiveGroupRequest): Promise<MediaWlcAttemptResponse> {
  return request<MediaWlcAttemptResponse>(`/api/media-qoe/wlc/attempts/${encodeURIComponent(attemptId)}/active-group`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function listRuns(): Promise<RfRunsResponse> {
  return request<RfRunsResponse>('/api/rf/runs')
}

export function getRun(testRunId: string): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}`)
}

export function getRunManualEntries(testRunId: string): Promise<RfManualEntriesResponse> {
  return request<RfManualEntriesResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}/manual-entry`)
}

export function getRunTimeAlignment(testRunId: string): Promise<RfTimeAlignmentResponse> {
  return request<RfTimeAlignmentResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}/time-alignment`)
}

export function createRun(payload: RunPayload): Promise<RfRunResponse> {
  return request<RfRunResponse>('/api/rf/runs', {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function updateRun(testRunId: string, payload: RunPayload): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload)
  })
}

export function deleteRun(testRunId: string): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}`, { method: 'DELETE' })
}

export function listInputFiles(sourceType?: SourceType): Promise<RfInputFilesResponse> {
  const suffix = sourceType ? `?source_type=${encodeURIComponent(sourceType)}` : ''
  return request<RfInputFilesResponse>(`/api/rf/input-files${suffix}`)
}

export function scanInputFiles(): Promise<RfInputFilesResponse> {
  return request<RfInputFilesResponse>('/api/rf/input-files/scan', {
    method: 'POST',
    body: JSON.stringify({ max_files: 500, include_other: false })
  })
}

export async function uploadInputFile(sourceType: SourceType, file: File, displayName?: string, notes?: string): Promise<RfInputFileResponse> {
  const formData = new FormData()
  formData.append('source_type', sourceType)
  formData.append('file', file)
  if (displayName) {
    formData.append('display_name', displayName)
  }
  if (notes) {
    formData.append('notes', notes)
  }

  const response = await fetch('/api/rf/input-files/upload', {
    method: 'POST',
    body: formData
  })
  const contentType = response.headers.get('content-type') ?? ''
  const body = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? String(body.detail) : String(body)
    throw new Error(detail || `${response.status} ${response.statusText}`)
  }
  return body as RfInputFileResponse
}


export async function uploadRunBundle(file: File, options: { testRunId?: string; runName?: string; badgeMac?: string; notes?: string } = {}): Promise<RfRunBundleResponse> {
  const formData = new FormData()
  formData.append('file', file)
  if (options.testRunId) {
    formData.append('test_run_id', options.testRunId)
  }
  if (options.runName) {
    formData.append('run_name', options.runName)
  }
  if (options.badgeMac) {
    formData.append('badge_mac', options.badgeMac)
  }
  if (options.notes) {
    formData.append('notes', options.notes)
  }

  const response = await fetch('/api/rf/run-bundles/upload', {
    method: 'POST',
    body: formData
  })
  const contentType = response.headers.get('content-type') ?? ''
  const body = contentType.includes('application/json') ? await response.json() : await response.text()
  if (!response.ok) {
    const detail = typeof body === 'object' && body !== null && 'detail' in body ? String(body.detail) : String(body)
    throw new Error(detail || `${response.status} ${response.statusText}`)
  }
  return body as RfRunBundleResponse
}

export function addRunFile(testRunId: string, inputFileId: string, sourceRole: SourceType): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}/files`, {
    method: 'POST',
    body: JSON.stringify({ input_file_id: inputFileId, source_role: sourceRole })
  })
}

export function removeRunFile(testRunId: string, inputFileId: string): Promise<RfRunResponse> {
  return request<RfRunResponse>(`/api/rf/runs/${encodeURIComponent(testRunId)}/files/${encodeURIComponent(inputFileId)}`, { method: 'DELETE' })
}

export function executeRun(testRunId: string): Promise<ApiResult> {
  return request<ApiResult>(`/api/rf/runs/${encodeURIComponent(testRunId)}/execute`, { method: 'POST' })
}

export function submitManualEntry(candidateMatchId: string, payload: { ekahau_rssi_dbm: string; ekahau_snr_db?: string; notes?: string }): Promise<ApiResult> {
  return request<ApiResult>(`/api/rf/candidates/${encodeURIComponent(candidateMatchId)}/manual-entry`, {
    method: 'POST',
    body: JSON.stringify(payload)
  })
}

export function resetManualEntryMatch(matchId: string): Promise<ApiResult> {
  return request<ApiResult>(`/api/rf/matches/${encodeURIComponent(matchId)}`, { method: 'DELETE' })
}
