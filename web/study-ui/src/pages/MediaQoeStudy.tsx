import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  downloadStudyMediaQoeDnacCapture,
  executeMediaQoeCapture,
  getMediaQoeDnacStatus,
  getMediaQoeExecutionStatus,
  getMediaQoeSummary,
  getProjectMediaQoeSummary,
  listMediaQoeProjectStudies,
  listMediaQoeProjects,
  listMediaQoeCaptureParseRuns,
  listProjectMediaQoeCaptures,
  listProjectMediaQoeDuplicates,
  listProjectMediaQoeStreams,
  listStudyMediaQoeDnacCaptures,
  listStudyMediaQoeCaptures,
  listStudyMediaQoeRawFiles,
  listStudyMediaQoeStreams,
  registerStudyMediaQoeCapture,
  updateMediaQoeStreamReview
} from '../api/client'
import type { AppConfig, MediaDnacCapture, MediaDnacCaptureQuery, MediaDnacStatusResponse, MediaExecutionStatusResponse, MediaQoeStreamReviewPayload, MediaQoeSummaryResponse, MediaRawFile, Project, StringRow, Study } from '../api/types'
import { Card } from '../components/Card'
import { CollapsibleCard } from '../components/CollapsibleCard'
import { GrafanaDiagnostics } from '../components/GrafanaDiagnostics'
import { GrafanaPanel } from '../components/GrafanaPanel'
import { MediaCaptureExecution } from '../components/MediaCaptureExecution'
import { DEFAULT_MEDIA_CAPTURE_FILTERS, filterAndSortMediaCaptures, MediaCaptureFilters } from '../components/MediaCaptureFilters'
import { MediaCaptureList } from '../components/MediaCaptureList'
import { MediaDnacCaptureList } from '../components/MediaDnacCaptureList'
import { MediaDnacCaptureSearch, type MediaDnacCaptureSearchState } from '../components/MediaDnacCaptureSearch'
import { MediaDnacStatus } from '../components/MediaDnacStatus'
import { MediaDuplicateCaptures } from '../components/MediaDuplicateCaptures'
import { MediaExecutionStatus } from '../components/MediaExecutionStatus'
import { MediaQoeSummary } from '../components/MediaQoeSummary'
import { MediaRawFileList } from '../components/MediaRawFileList'
import { DEFAULT_MEDIA_STREAM_FILTERS, filterAndSortMediaStreams, isAdvancedMediaStream, isTrustedRtpStream, MediaStreamFilters, sortTrustedRtpStreams } from '../components/MediaStreamFilters'
import { MediaStreamList } from '../components/MediaStreamList'
import { MediaTriageSummary } from '../components/MediaTriageSummary'
import { streamKey } from '../components/mediaQoeSeverity'
import { ProjectSelector } from '../components/ProjectSelector'
import { StudySelector } from '../components/StudySelector'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function replaceStream(rows: StringRow[], updated: StringRow): StringRow[] {
  const captureId = field(updated, 'capture_id')
  const streamId = field(updated, 'stream_id')
  return rows.map((row) => (field(row, 'capture_id') === captureId && field(row, 'stream_id') === streamId ? updated : row))
}

function numberFromText(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function dnacQueryFromSearch(value: MediaDnacCaptureSearchState): MediaDnacCaptureQuery {
  return {
    client_mac: value.client_mac.trim() || undefined,
    ap_mac: value.ap_mac.trim() || undefined,
    capture_type: value.capture_type || 'FULL',
    lookback_minutes: Math.max(0, numberFromText(value.lookback_minutes, 0)),
    limit: Math.min(100, Math.max(1, numberFromText(value.limit, 20)))
  }
}

export function MediaQoeStudy({ config }: { config: AppConfig }) {
  const grafana = config.grafana
  const [summaryResponse, setSummaryResponse] = useState<MediaQoeSummaryResponse | null>(null)
  const [executionStatus, setExecutionStatus] = useState<MediaExecutionStatusResponse | null>(null)
  const [dnacStatus, setDnacStatus] = useState<MediaDnacStatusResponse | null>(null)
  const [dnacCaptures, setDnacCaptures] = useState<MediaDnacCapture[]>([])
  const [dnacRawDir, setDnacRawDir] = useState<string>('')
  const [dnacSearch, setDnacSearch] = useState<MediaDnacCaptureSearchState>({
    client_mac: '',
    ap_mac: '',
    capture_type: '',
    lookback_minutes: '120',
    limit: '20'
  })
  const [projects, setProjects] = useState<Project[]>([])
  const [studies, setStudies] = useState<Study[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(null)
  const [selectedCaptureId, setSelectedCaptureId] = useState<string | null>(null)
  const [selectedStreamKey, setSelectedStreamKey] = useState<string | null>(null)
  const [projectSummary, setProjectSummary] = useState<StringRow | null>(null)
  const [projectCaptures, setProjectCaptures] = useState<StringRow[]>([])
  const [projectStreams, setProjectStreams] = useState<StringRow[]>([])
  const [duplicateCaptures, setDuplicateCaptures] = useState<StringRow[]>([])
  const [studyCaptures, setStudyCaptures] = useState<StringRow[]>([])
  const [studyStreams, setStudyStreams] = useState<StringRow[]>([])
  const [rawDir, setRawDir] = useState<string>('')
  const [rawFiles, setRawFiles] = useState<MediaRawFile[]>([])
  const [parseRuns, setParseRuns] = useState<StringRow[]>([])
  const [loadingInitial, setLoadingInitial] = useState(true)
  const [loadingProject, setLoadingProject] = useState(false)
  const [loadingStudy, setLoadingStudy] = useState(false)
  const [loadingStudyOptions, setLoadingStudyOptions] = useState(false)
  const [loadingExecutionStatus, setLoadingExecutionStatus] = useState(false)
  const [loadingDnacStatus, setLoadingDnacStatus] = useState(false)
  const [loadingDnacCaptures, setLoadingDnacCaptures] = useState(false)
  const [loadingRawFiles, setLoadingRawFiles] = useState(false)
  const [loadingParseRuns, setLoadingParseRuns] = useState(false)
  const [reviewBusy, setReviewBusy] = useState(false)
  const [mediaActionBusy, setMediaActionBusy] = useState(false)
  const [executingCaptureId, setExecutingCaptureId] = useState<string | null>(null)
  const [dnacDownloadCaptureKey, setDnacDownloadCaptureKey] = useState<string | null>(null)
  const [bootstrapError, setBootstrapError] = useState<string | null>(null)
  const [executionStatusError, setExecutionStatusError] = useState<string | null>(null)
  const [dnacStatusError, setDnacStatusError] = useState<string | null>(null)
  const [dnacCapturesError, setDnacCapturesError] = useState<string | null>(null)
  const [projectError, setProjectError] = useState<string | null>(null)
  const [studyError, setStudyError] = useState<string | null>(null)
  const [rawError, setRawError] = useState<string | null>(null)
  const [parseRunsError, setParseRunsError] = useState<string | null>(null)
  const [mediaActionError, setMediaActionError] = useState<string | null>(null)
  const [captureFilters, setCaptureFilters] = useState(DEFAULT_MEDIA_CAPTURE_FILTERS)
  const [streamFilters, setStreamFilters] = useState(DEFAULT_MEDIA_STREAM_FILTERS)

  const refreshProjectData = useCallback(async (projectId: string) => {
    try {
      setLoadingProject(true)
      setProjectError(null)
      const [summary, captures, streams, duplicates] = await Promise.all([
        getProjectMediaQoeSummary(projectId),
        listProjectMediaQoeCaptures(projectId),
        listProjectMediaQoeStreams(projectId),
        listProjectMediaQoeDuplicates(projectId)
      ])
      setProjectSummary(summary.summary)
      setProjectCaptures(captures.captures ?? [])
      setProjectStreams(streams.streams ?? [])
      setDuplicateCaptures(duplicates.duplicates ?? [])
    } catch (err) {
      setProjectError(err instanceof Error ? err.message : 'Failed to load project Media QoE data')
    } finally {
      setLoadingProject(false)
    }
  }, [])

  const refreshStudyData = useCallback(async (studyId: string) => {
    try {
      setLoadingStudy(true)
      setStudyError(null)
      const [captures, streams] = await Promise.all([
        listStudyMediaQoeCaptures(studyId),
        listStudyMediaQoeStreams(studyId)
      ])
      setStudyCaptures(captures.captures ?? [])
      setStudyStreams(streams.streams ?? [])
    } catch (err) {
      setStudyError(err instanceof Error ? err.message : 'Failed to load study Media QoE data')
    } finally {
      setLoadingStudy(false)
    }
  }, [])

  const refreshExecutionStatus = useCallback(async () => {
    try {
      setLoadingExecutionStatus(true)
      setExecutionStatusError(null)
      const response = await getMediaQoeExecutionStatus()
      setExecutionStatus(response)
    } catch (err) {
      setExecutionStatusError(err instanceof Error ? err.message : 'Failed to load Media QoE execution guardrails')
    } finally {
      setLoadingExecutionStatus(false)
    }
  }, [])

  const applyDnacDefaults = useCallback((response: MediaDnacStatusResponse) => {
    setDnacSearch((current) => ({
      ...current,
      client_mac: current.client_mac || response.default_client_mac || '',
      ap_mac: current.ap_mac || response.default_ap_mac || '',
      capture_type: current.capture_type || response.default_capture_type || 'FULL',
      lookback_minutes: current.lookback_minutes || String(response.lookback_minutes ?? 120),
      limit: current.limit || String(response.limit ?? 20)
    }))
    setDnacRawDir(response.raw_dir || '')
  }, [])

  const refreshDnacStatus = useCallback(async (query: MediaDnacCaptureQuery = {}) => {
    try {
      setLoadingDnacStatus(true)
      setDnacStatusError(null)
      const response = await getMediaQoeDnacStatus(query)
      setDnacStatus(response)
      applyDnacDefaults(response)
    } catch (err) {
      setDnacStatusError(err instanceof Error ? err.message : 'Failed to load DNAC/iCAP readiness')
    } finally {
      setLoadingDnacStatus(false)
    }
  }, [applyDnacDefaults])

  useEffect(() => {
    const load = async () => {
      try {
        setLoadingInitial(true)
        setBootstrapError(null)
        const [response, projectResponse] = await Promise.all([getMediaQoeSummary(), listMediaQoeProjects()])
        setSummaryResponse(response)
        const loadedProjects = projectResponse.projects ?? []
        setProjects(loadedProjects)
        const visibleProjects = loadedProjects.filter((project) => field(project, 'project_type') === 'media_qoe' || field(project, 'project_type') === 'mixed')
        const defaultProjectId = field(response.project, 'project_id')
        const initialProjectId = visibleProjects.some((project) => field(project, 'project_id') === defaultProjectId)
          ? defaultProjectId
          : field(visibleProjects[0], 'project_id')
        setSelectedProjectId((current) => current || initialProjectId || null)
      } catch (err) {
        setBootstrapError(err instanceof Error ? err.message : 'Failed to load Media QoE summary')
      } finally {
        setLoadingInitial(false)
      }
    }

    void load()
  }, [])

  useEffect(() => {
    void refreshExecutionStatus()
  }, [refreshExecutionStatus])

  useEffect(() => {
    void refreshDnacStatus()
  }, [refreshDnacStatus])

  useEffect(() => {
    if (!selectedProjectId) {
      setProjectSummary(null)
      setProjectCaptures([])
      setProjectStreams([])
      setDuplicateCaptures([])
      setStudies([])
      return
    }

    void refreshProjectData(selectedProjectId)
  }, [refreshProjectData, selectedProjectId])

  useEffect(() => {
    if (!selectedProjectId) {
      setStudies([])
      setSelectedStudyId(null)
      return
    }

    const loadProjectStudies = async () => {
      try {
        setLoadingStudyOptions(true)
        setStudyError(null)
        const response = await listMediaQoeProjectStudies(selectedProjectId)
        const mediaStudies = (response.studies ?? []).filter((study) => field(study, 'study_type') === 'media_qoe')
        setStudies(mediaStudies)
        setSelectedStudyId((current) => {
          if (current && mediaStudies.some((study) => field(study, 'study_id') === current)) {
            return current
          }
          return field(mediaStudies[0], 'study_id') || null
        })
      } catch (err) {
        setStudies([])
        setSelectedStudyId(null)
        setStudyError(err instanceof Error ? err.message : 'Failed to load media studies')
      } finally {
        setLoadingStudyOptions(false)
      }
    }

    void loadProjectStudies()
  }, [selectedProjectId])

  useEffect(() => {
    if (!selectedCaptureId) {
      setParseRuns([])
      setParseRunsError(null)
      return
    }

    const load = async () => {
      try {
        setLoadingParseRuns(true)
        setParseRunsError(null)
        const response = await listMediaQoeCaptureParseRuns(selectedCaptureId)
        setParseRuns(response.parse_runs ?? [])
      } catch (err) {
        setParseRunsError(err instanceof Error ? err.message : 'Failed to load parser execution history')
      } finally {
        setLoadingParseRuns(false)
      }
    }

    void load()
  }, [selectedCaptureId])

  const refreshRawFiles = useCallback(async () => {
    if (!selectedStudyId) {
      return
    }
    try {
      setLoadingRawFiles(true)
      setRawError(null)
      const response = await listStudyMediaQoeRawFiles(selectedStudyId, { includeRegistered: true, limit: 100 })
      setRawDir(response.raw_dir)
      setRawFiles(response.files ?? [])
    } catch (err) {
      setRawError(err instanceof Error ? err.message : 'Failed to scan raw capture directory')
    } finally {
      setLoadingRawFiles(false)
    }
  }, [selectedStudyId])

  const refreshDnacCaptures = useCallback(async () => {
    if (!selectedStudyId) {
      setDnacCapturesError('Select a Media QoE study before listing ICAP captures.')
      return
    }
    try {
      setLoadingDnacCaptures(true)
      setDnacCapturesError(null)
      const response = await listStudyMediaQoeDnacCaptures(selectedStudyId, dnacQueryFromSearch(dnacSearch))
      setDnacCaptures(response.captures ?? [])
      setDnacRawDir(response.raw_dir || dnacRawDir)
    } catch (err) {
      setDnacCapturesError(err instanceof Error ? err.message : 'Failed to list completed ICAP captures')
    } finally {
      setLoadingDnacCaptures(false)
    }
  }, [dnacRawDir, dnacSearch, selectedStudyId])

  useEffect(() => {
    if (!selectedStudyId) {
      setStudyCaptures([])
      setStudyStreams([])
      setRawFiles([])
      setRawDir('')
      setDnacCaptures([])
      return
    }

    void refreshStudyData(selectedStudyId)
    void refreshRawFiles()
  }, [refreshRawFiles, refreshStudyData, selectedStudyId])

  const refreshSelectedMedia = useCallback(async () => {
    const tasks: Promise<unknown>[] = [getMediaQoeSummary().then(setSummaryResponse)]
    if (selectedProjectId) {
      tasks.push(refreshProjectData(selectedProjectId))
    }
    if (selectedStudyId) {
      tasks.push(refreshStudyData(selectedStudyId))
    }
    if (selectedCaptureId) {
      tasks.push(listMediaQoeCaptureParseRuns(selectedCaptureId).then((response) => setParseRuns(response.parse_runs ?? [])))
    }
    await Promise.all(tasks)
  }, [refreshProjectData, refreshStudyData, selectedCaptureId, selectedProjectId, selectedStudyId])

  const refreshDnacWorkflowData = useCallback(async (captureId?: string | null) => {
    const tasks: Promise<unknown>[] = [getMediaQoeSummary().then(setSummaryResponse)]
    if (selectedProjectId) {
      tasks.push(refreshProjectData(selectedProjectId))
    }
    if (selectedStudyId) {
      tasks.push(refreshStudyData(selectedStudyId))
      tasks.push(refreshRawFiles())
      tasks.push(refreshDnacCaptures())
    }
    await Promise.all(tasks)
    if (captureId) {
      const parseRunResponse = await listMediaQoeCaptureParseRuns(captureId)
      setParseRuns(parseRunResponse.parse_runs ?? [])
    }
  }, [refreshDnacCaptures, refreshProjectData, refreshRawFiles, refreshStudyData, selectedProjectId, selectedStudyId])

  const registerRawFile = async (file: MediaRawFile) => {
    if (!selectedStudyId) {
      return
    }
    try {
      setMediaActionBusy(true)
      setMediaActionError(null)
      const response = await registerStudyMediaQoeCapture(selectedStudyId, {
        source_path: file.source_path,
        source_name: file.source_name,
        capture_point: 'Imported PCAP'
      })
      setSelectedCaptureId(field(response.capture, 'capture_id') || selectedCaptureId)
      setSelectedStreamKey(null)
      await refreshSelectedMedia()
      await refreshRawFiles()
    } catch (err) {
      setMediaActionError(err instanceof Error ? err.message : 'Failed to register capture')
    } finally {
      setMediaActionBusy(false)
    }
  }

  const registerRawFiles = async (files: MediaRawFile[]) => {
    if (!selectedStudyId || !files.length) {
      return
    }
    try {
      setMediaActionBusy(true)
      setMediaActionError(null)
      let lastCaptureId = selectedCaptureId
      for (const file of files) {
        const response = await registerStudyMediaQoeCapture(selectedStudyId, {
          source_path: file.source_path,
          source_name: file.source_name,
          capture_point: 'Imported PCAP'
        })
        lastCaptureId = field(response.capture, 'capture_id') || lastCaptureId
      }
      setSelectedCaptureId(lastCaptureId)
      setSelectedStreamKey(null)
      await refreshSelectedMedia()
      await refreshRawFiles()
    } catch (err) {
      setMediaActionError(err instanceof Error ? err.message : 'Failed to register selected captures')
    } finally {
      setMediaActionBusy(false)
    }
  }

  const downloadDnacCapture = async (capture: MediaDnacCapture, parseAfterRegister = false) => {
    if (!selectedStudyId) {
      setDnacCapturesError('Select a Media QoE study before downloading an ICAP capture.')
      return
    }
    const captureKey = capture.dnac_capture_id || capture.file_name
    let registeredCaptureId: string | null = null
    let parseError: string | null = null
    try {
      setMediaActionBusy(true)
      setDnacDownloadCaptureKey(captureKey)
      setDnacCapturesError(null)
      setMediaActionError(null)
      const response = await downloadStudyMediaQoeDnacCapture(selectedStudyId, {
        ...dnacQueryFromSearch(dnacSearch),
        capture_id: capture.dnac_capture_id || undefined,
        file_name: capture.file_name,
        register: true
      })
      registeredCaptureId = response.capture_id ?? null
      if (registeredCaptureId) {
        setSelectedCaptureId(registeredCaptureId)
        setSelectedStreamKey(null)
      }

      if (parseAfterRegister) {
        if (!registeredCaptureId) {
          parseError = 'Downloaded ICAP capture, but no registered capture ID was returned for parsing.'
        } else {
          try {
            setExecutingCaptureId(registeredCaptureId)
            const parseResponse = await executeMediaQoeCapture(registeredCaptureId, { reparse: false })
            if (parseResponse.status === 'failed') {
              parseError = parseResponse.error || 'Parser execution failed after DNAC download/register.'
            }
          } catch (err) {
            parseError = err instanceof Error ? err.message : 'Parser execution failed after DNAC download/register.'
          } finally {
            setExecutingCaptureId(null)
          }
        }
      }

      await refreshDnacWorkflowData(registeredCaptureId)
      if (parseError) {
        const message = `Downloaded and registered ICAP capture, but parser did not complete: ${parseError}`
        setDnacCapturesError(message)
        setMediaActionError(message)
      }
    } catch (err) {
      setDnacCapturesError(err instanceof Error ? err.message : 'Failed to download and register ICAP capture')
    } finally {
      setDnacDownloadCaptureKey(null)
      setExecutingCaptureId(null)
      setMediaActionBusy(false)
    }
  }

  const executeCapture = async (captureOrId: StringRow | string, reparse: boolean) => {
    const captureId = typeof captureOrId === 'string' ? captureOrId : field(captureOrId, 'capture_id')
    if (!captureId) {
      return
    }
    if (reparse) {
      const confirmed = window.confirm('Reparse this capture? This will add/update parser rows for this capture.')
      if (!confirmed) {
        return
      }
    }
    try {
      setMediaActionBusy(true)
      setMediaActionError(null)
      setExecutingCaptureId(captureId)
      setSelectedCaptureId(captureId)
      setSelectedStreamKey(null)
      const response = await executeMediaQoeCapture(captureId, { reparse })
      if (response.status === 'failed') {
        setMediaActionError(response.error || 'Parser execution failed')
      }
      await refreshSelectedMedia()
      if (rawFiles.length) {
        await refreshRawFiles()
      }
      const parseRunResponse = await listMediaQoeCaptureParseRuns(captureId)
      setParseRuns(parseRunResponse.parse_runs ?? [])
    } catch (err) {
      setMediaActionError(err instanceof Error ? err.message : 'Failed to execute parser')
    } finally {
      setExecutingCaptureId(null)
      setMediaActionBusy(false)
    }
  }

  const selectedProject = projects.find((project) => field(project, 'project_id') === selectedProjectId) ?? null
  const selectedStudy = studies.find((study) => field(study, 'study_id') === selectedStudyId) ?? null
  const selectedCapture = selectedCaptureId
    ? studyCaptures.find((capture) => field(capture, 'capture_id') === selectedCaptureId) ?? projectCaptures.find((capture) => field(capture, 'capture_id') === selectedCaptureId) ?? null
    : null
  const selectedStream = selectedStreamKey
    ? studyStreams.find((stream) => streamKey(stream) === selectedStreamKey) ?? projectStreams.find((stream) => streamKey(stream) === selectedStreamKey) ?? null
    : null
  const filteredProjectCaptures = useMemo(() => filterAndSortMediaCaptures(projectCaptures, captureFilters), [captureFilters, projectCaptures])
  const filteredStudyCaptures = useMemo(() => filterAndSortMediaCaptures(studyCaptures, captureFilters), [captureFilters, studyCaptures])
  const filteredProjectStreams = useMemo(() => filterAndSortMediaStreams(projectStreams, { ...streamFilters, selectedCaptureOnly: false }, null), [projectStreams, streamFilters])
  const filteredStudyStreams = useMemo(() => filterAndSortMediaStreams(studyStreams, streamFilters, selectedCaptureId), [selectedCaptureId, streamFilters, studyStreams])
  const trustedRtpStudyStreams = useMemo(() => sortTrustedRtpStreams(filteredStudyStreams.filter(isTrustedRtpStream)), [filteredStudyStreams])
  const advancedStudyStreams = useMemo(() => filteredStudyStreams.filter(isAdvancedMediaStream), [filteredStudyStreams])

  const grafanaCaptureId = selectedCaptureId || field(selectedStream, 'capture_id') || '__all__'
  const grafanaVariables = {
    project_id: selectedProjectId,
    study_id: selectedStudyId,
    study_scope: 'media_qoe',
    capture_id: grafanaCaptureId,
    stream_id: field(selectedStream, 'stream_id') || null,
    src_ip: field(selectedStream, 'src_ip') || null,
    dst_ip: field(selectedStream, 'dst_ip') || null,
    measurement_mode: '__all__',
    direction: '__all__'
  }
  const mediaGrafanaPanels = [
    { title: 'Study QoE Summary', config: grafana.panels.mediaQoeSummary },
    { title: 'Capture QoE Inventory', config: grafana.panels.mediaQoeCaptureInventory },
    { title: 'Trusted RTP Trouble Streams', config: grafana.panels.mediaQoeRtpTrouble },
    { title: 'DSCP Mismatch by Mode and Direction', config: grafana.panels.mediaQoeDscp },
    { title: 'Direction Split by Packet Volume', config: grafana.panels.mediaQoeDirection },
    { title: 'RTP Classification Mix', config: grafana.panels.mediaQoeClassification },
    { title: 'RTP Candidate Rejection Reasons', config: grafana.panels.mediaQoeRejectionReasons }
  ].filter((panel) => Boolean(panel.config))
  const configuredMediaGrafanaPanels = mediaGrafanaPanels.length ? mediaGrafanaPanels : [{ title: 'Media QoE', config: grafana.panels.mediaQoe }]
  const fallbackSummary = field(summaryResponse?.summary, 'project_id') === selectedProjectId ? summaryResponse?.summary ?? null : null

  useEffect(() => {
    if (selectedStreamKey && !studyStreams.some((stream) => streamKey(stream) === selectedStreamKey)) {
      setSelectedStreamKey(null)
    }
  }, [selectedStreamKey, studyStreams])

  const selectCapture = (captureId: string | null) => {
    setSelectedCaptureId(captureId)
    setSelectedStreamKey(null)
    setStreamFilters((current) => ({ ...current, selectedCaptureOnly: true }))
  }

  const selectStream = (stream: StringRow | null) => {
    setSelectedStreamKey(stream ? streamKey(stream) : null)
    if (stream) {
      setSelectedCaptureId(field(stream, 'capture_id') || selectedCaptureId)
    }
  }

  const openRegisteredDnacCapture = (capture: MediaDnacCapture) => {
    const captureId = capture.registered_capture_id || null
    if (!captureId) {
      setDnacCapturesError('This ICAP capture does not have a registered Media QoE capture ID.')
      return
    }
    setDnacCapturesError(null)
    selectCapture(captureId)
    void listMediaQoeCaptureParseRuns(captureId)
      .then((response) => setParseRuns(response.parse_runs ?? []))
      .catch((err) => setParseRunsError(err instanceof Error ? err.message : 'Failed to load parser execution history'))
  }

  const parseRegisteredDnacCapture = async (capture: MediaDnacCapture, reparse: boolean) => {
    const captureId = capture.registered_capture_id || null
    if (!captureId) {
      setDnacCapturesError('This ICAP capture does not have a registered Media QoE capture ID.')
      return
    }
    setDnacCapturesError(null)
    await executeCapture(captureId, reparse)
    await refreshDnacCaptures()
  }

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId)
    setStudies([])
    setSelectedStudyId(null)
    setSelectedCaptureId(null)
    setSelectedStreamKey(null)
    setProjectSummary(null)
    setProjectCaptures([])
    setProjectStreams([])
    setDuplicateCaptures([])
    setStudyCaptures([])
    setStudyStreams([])
    setRawFiles([])
    setRawDir('')
    setDnacCaptures([])
    setDnacCapturesError(null)
  }

  const selectStudy = (studyId: string) => {
    setSelectedStudyId(studyId)
    setSelectedCaptureId(null)
    setSelectedStreamKey(null)
    setStudyCaptures([])
    setStudyStreams([])
    setRawFiles([])
    setRawDir('')
    setDnacCaptures([])
    setDnacCapturesError(null)
  }

  const saveStreamReview = async (stream: StringRow, payload: MediaQoeStreamReviewPayload) => {
    setReviewBusy(true)
    try {
      const response = await updateMediaQoeStreamReview(field(stream, 'capture_id'), field(stream, 'stream_id'), payload)
      setStudyStreams((rows) => replaceStream(rows, response.stream))
      setProjectStreams((rows) => replaceStream(rows, response.stream))
      if (selectedProjectId) {
        const refreshedSummary = await getProjectMediaQoeSummary(selectedProjectId)
        setProjectSummary(refreshedSummary.summary)
      }
    } finally {
      setReviewBusy(false)
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.28em] text-violet-300/80">ICAP QoE</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-50">ICAP QoE Study Workspace</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-400">
          Review completed Catalyst Center ICAP captures and imported PCAPs through the same Project to Study model used by RF validation. Multicast delivery investigation lives on the separate Vocera Multicast page.
        </p>
      </div>

      {loadingInitial && <Card>Loading Media QoE project...</Card>}
      {bootstrapError && <Card className="border-red-900 bg-red-950/30">{bootstrapError}</Card>}

      <div className="grid gap-4 xl:grid-cols-2">
        <ProjectSelector
          selectedProjectId={selectedProjectId}
          onSelectProject={selectProject}
          disabled={loadingInitial || loadingProject || loadingStudyOptions || reviewBusy}
          projectType="media_qoe"
          projects={projects}
          description="Choose a Media QoE project for project-wide analysis"
          emptyMessage="No Media QoE projects found"
        />
        {loadingStudyOptions ? (
          <Card>Loading Media QoE studies...</Card>
        ) : (
          <StudySelector
            projectId={selectedProjectId}
            selectedStudyId={selectedStudyId}
            onSelectStudy={selectStudy}
            disabled={loadingInitial || loadingStudy || reviewBusy}
            studyType="media_qoe"
            studies={studies}
            description="Choose a Media QoE study for capture and stream review"
            emptyMessage="No Media QoE studies found in this project"
          />
        )}
      </div>

      <MediaQoeSummary project={selectedProject} study={selectedStudy} summary={projectSummary ?? fallbackSummary} error={projectError} />
      <MediaExecutionStatus status={executionStatus} loading={loadingExecutionStatus} error={executionStatusError} onRefresh={() => { void refreshExecutionStatus() }} />
      <CollapsibleCard title="Catalyst Center ICAP" eyebrow="Optional completed captures" defaultOpen={false}>
        <div className="space-y-5">
          <MediaDnacStatus
            status={dnacStatus}
            loading={loadingDnacStatus}
            error={dnacStatusError}
            onRefresh={() => { void refreshDnacStatus(dnacQueryFromSearch(dnacSearch)) }}
          />
          <MediaDnacCaptureSearch
            value={dnacSearch}
            loading={loadingDnacStatus || loadingDnacCaptures}
            disabled={!selectedStudyId}
            onChange={setDnacSearch}
            onCheckStatus={() => { void refreshDnacStatus(dnacQueryFromSearch(dnacSearch)) }}
            onListCaptures={() => { void refreshDnacCaptures() }}
          />
          <MediaDnacCaptureList
            captures={dnacCaptures}
            loading={loadingDnacCaptures}
            error={dnacCapturesError}
            rawDir={dnacRawDir || dnacStatus?.raw_dir}
            busyCaptureKey={dnacDownloadCaptureKey}
            executingCaptureId={executingCaptureId}
            onDownloadRegister={(capture, parseAfterRegister) => { void downloadDnacCapture(capture, parseAfterRegister) }}
            onParseRegistered={(capture, reparse) => { void parseRegisteredDnacCapture(capture, reparse) }}
            onOpenRegistered={openRegisteredDnacCapture}
          />
        </div>
      </CollapsibleCard>
      {mediaActionError && <Card className="border-rose-900 bg-rose-950/30">{mediaActionError}</Card>}

      <MediaRawFileList
        rawDir={rawDir}
        files={rawFiles}
        loading={loadingRawFiles}
        busy={mediaActionBusy}
        error={rawError}
        executingCaptureId={executingCaptureId}
        onScan={() => { void refreshRawFiles() }}
        onRegister={(file) => { void registerRawFile(file) }}
        onRegisterSelected={(files) => { void registerRawFiles(files) }}
        onParse={(captureId, reparse) => { void executeCapture(captureId, reparse) }}
      />

      <MediaCaptureFilters filters={captureFilters} totalCount={projectCaptures.length + studyCaptures.length} resultCount={filteredProjectCaptures.length + filteredStudyCaptures.length} onChange={setCaptureFilters} />

      <div className="space-y-4">
        <MediaDuplicateCaptures duplicates={duplicateCaptures} error={projectError} />
        <MediaCaptureList
          captures={filteredProjectCaptures}
          title="Project Captures"
          eyebrow={loadingProject ? 'Loading project media' : 'Project media evidence'}
          emptyMessage="No captures found for this project."
          selectedCaptureId={selectedCaptureId}
          onSelectCapture={selectCapture}
          onExecuteCapture={(capture, reparse) => { void executeCapture(capture, reparse) }}
          executingCaptureId={executingCaptureId}
          defaultOpen={false}
        />
        <MediaStreamList
          streams={filteredProjectStreams}
          title="Project Streams"
          eyebrow={loadingProject ? 'Loading project streams' : 'Project media QoE streams'}
          emptyMessage="No streams found for this project."
          selectedStreamKey={selectedStreamKey}
          onSelectStream={selectStream}
          defaultOpen={false}
        />
      </div>

      <section className="space-y-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">Selected Study Workflow</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-100">Study Captures and Stream Review</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-400">
            These rows are scoped to the selected media study. Use review controls to accept, exclude, classify, or flag streams for follow-up.
          </p>
          {studyError && <div className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{studyError}</div>}
        </div>

        <MediaCaptureList
          captures={filteredStudyCaptures}
          title="Study Captures"
          eyebrow={loadingStudy ? 'Loading study media' : 'Selected study media evidence'}
          emptyMessage="No captures found for this study."
          selectedCaptureId={selectedCaptureId}
          onSelectCapture={selectCapture}
          onExecuteCapture={(capture, reparse) => { void executeCapture(capture, reparse) }}
          executingCaptureId={executingCaptureId}
        />
        <MediaCaptureExecution
          capture={selectedCapture}
          parseRuns={parseRuns}
          loading={loadingParseRuns}
          error={parseRunsError}
          executing={executingCaptureId === field(selectedCapture, 'capture_id')}
          onExecute={(capture, reparse) => { void executeCapture(capture, reparse) }}
        />
        <MediaStreamFilters filters={streamFilters} selectedCaptureId={selectedCaptureId} totalCount={studyStreams.length} resultCount={filteredStudyStreams.length} onChange={setStreamFilters} />
        <MediaTriageSummary streams={filteredStudyStreams} />
        <MediaStreamList
          streams={trustedRtpStudyStreams}
          title="Trusted RTP Streams"
          eyebrow={loadingStudy ? 'Loading trusted RTP streams' : 'Primary media QoE stream review'}
          emptyMessage={selectedCaptureId ? 'No trusted RTP streams found for the selected capture. If this capture shows No usable RTP, collect a new ICAP window during an active call.' : 'No trusted RTP streams found for this study.'}
          reviewDisabled={reviewBusy}
          onReviewSave={saveStreamReview}
          selectedStreamKey={selectedStreamKey}
          onSelectStream={selectStream}
        />
        <MediaStreamList
          streams={advancedStudyStreams}
          title="Advanced Streams"
          eyebrow={loadingStudy ? 'Loading advanced streams' : 'Rejected candidates, UDP timing, unknown UDP, and control/noise rows'}
          emptyMessage={selectedCaptureId ? 'No advanced/non-RTP streams found for the selected capture.' : 'No advanced/non-RTP streams found for this study.'}
          reviewDisabled={reviewBusy}
          onReviewSave={saveStreamReview}
          selectedStreamKey={selectedStreamKey}
          onSelectStream={selectStream}
          defaultOpen={false}
        />
      </section>

      <section className="space-y-4">
        <GrafanaDiagnostics />
        <Card title="Media QoE Grafana context" eyebrow="Embedded Grafana">
          <div className="grid gap-4 2xl:grid-cols-2">
            {configuredMediaGrafanaPanels.map((panel) => (
              <GrafanaPanel
                key={panel.title}
                title={panel.title}
                config={panel.config}
                basePath={grafana.basePath}
                orgId={grafana.orgId}
                theme={grafana.theme}
                variables={grafanaVariables}
              />
            ))}
          </div>
        </Card>
      </section>
    </div>
  )
}
