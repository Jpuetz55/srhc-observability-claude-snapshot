import { FormEvent, useEffect, useMemo, useState } from 'react'
import {
  addRunFile,
  createRun,
  createStudyRun,
  deleteRun,
  executeRun,
  getRfSummary,
  getRun,
  getRunTimeAlignment,
  getStudyRunComparison,
  getProjectRfDuplicates,
  getProjectRfRawResults,
  getProjectRfResults,
  listInputFiles,
  listProjects,
  listProjectStudies,
  listRuns,
  listStudyRuns,
  removeRunFile,
  resetManualEntryMatch,
  scanInputFiles,
  submitManualEntry,
  updateRun,
  uploadInputFile,
  uploadRunBundle
} from '../api/client'
import type { RfInputFile, RfManualEntries, RfSummary, RfRun, RfRunFile, SourceType, StringRow, RfRunAlignment, RfTimeAlignmentResponse, RunComparisonResponse, ProjectRfDuplicatesResponse, ProjectRfResultsResponse, Project, Study } from '../api/types'
import { Button } from '../components/Button'
import { CollapsibleCard } from '../components/CollapsibleCard'
import { DataTable } from '../components/DataTable'
import { DuplicateWarningsList } from '../components/DuplicateWarningsList'
import { GrafanaDiagnostics } from '../components/GrafanaDiagnostics'
import { ManualEntryWorkbench } from '../components/ManualEntryWorkbench'
import { ProjectManager } from '../components/ProjectManager'
import { ProjectResultsSummary } from '../components/ProjectResultsSummary'
import { ProjectResultsTable } from '../components/ProjectResultsTable'
import { RunList } from '../components/RunList'
import { RunResultSummary } from '../components/RunResultSummary'
import { TimeAlignmentLab } from '../components/TimeAlignmentLab'
import { RunComparison } from '../components/RunComparison'
import { RunStatusMessage } from '../components/RunStatusMessage'
import { StatCard } from '../components/StatCard'
import { StatusPill } from '../components/StatusPill'
import { StudiesIncludedList } from '../components/StudiesIncludedList'
import { StudyManager } from '../components/StudyManager'
import { StudyStatisticsWorkbench } from '../components/StudyStatisticsWorkbench'

const emptySummary: RfSummary = {
  ok: false,
  errors: {},
  backend: {},
  current: {},
  runs: [],
  config: {
    scope: 'vocera_badge',
    user: 'study_web',
    grafana: { basePath: '/grafana', orgId: '1', theme: 'dark', proxyEnabled: true, panels: {} }
  }
}

const fileRoles = [
  { role: 'badge_log', label: 'Badge log archive' },
  { role: 'ekahau_json', label: 'Ekahau .esx survey' }
] as const

type RunFileRole = (typeof fileRoles)[number]['role']
type FileSelections = Record<RunFileRole, string>
type RunForm = {
  run_name: string
  badge_mac: string
  site: string
  building: string
  floor: string
  area: string
  ssid: string
  badge_model: string
  default_match_window_seconds: string
  notes: string
}

type ManualEntryForm = {
  candidate_match_id: string
  match_id: string
  survey_point_id: string
  bssid: string
  survey_time: string
  ekahau_rssi_dbm: string
  ekahau_snr_db: string
  notes: string
}

type ManualEntryDraft = {
  ekahau_rssi_dbm: string
  ekahau_snr_db: string
  notes: string
}

const emptyFileSelections: FileSelections = {
  badge_log: '',
  ekahau_json: ''
}

const emptyRunForm: RunForm = {
  run_name: '',
  badge_mac: '',
  site: '',
  building: '',
  floor: '',
  area: '',
  ssid: '',
  badge_model: '',
  default_match_window_seconds: '',
  notes: ''
}

const emptyManualEntryForm: ManualEntryForm = {
  candidate_match_id: '',
  match_id: '',
  survey_point_id: '',
  bssid: '',
  survey_time: '',
  ekahau_rssi_dbm: '',
  ekahau_snr_db: '',
  notes: ''
}

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function errorList(errors: Record<string, string | null | undefined>): string[] {
  return Object.entries(errors)
    .filter(([, value]) => Boolean(value))
    .map(([key, value]) => `${key}: ${value}`)
}

function runFormFromRun(row: StringRow): RunForm {
  return {
    run_name: field(row, 'run_name'),
    badge_mac: field(row, 'badge_mac'),
    site: field(row, 'site'),
    building: field(row, 'building'),
    floor: field(row, 'floor'),
    area: field(row, 'area'),
    ssid: field(row, 'ssid'),
    badge_model: field(row, 'badge_model'),
    default_match_window_seconds: field(row, 'default_match_window_seconds'),
    notes: field(row, 'run_notes', field(row, 'notes'))
  }
}

function selectionsFromRunFiles(files: RfRunFile[]): FileSelections {
  const next = { ...emptyFileSelections }
  for (const item of files) {
    const role = field(item, 'source_role') as RunFileRole
    if (role in next && !next[role]) {
      next[role] = field(item, 'input_file_id')
    }
  }
  return next
}

function displayFile(row: StringRow): string {
  const name = field(row, 'display_name', field(row, 'file_name', field(row, 'file_path')))
  const path = field(row, 'file_path')
  return path && path !== name ? `${name} — ${path}` : name
}

function fileByRole(files: RfInputFile[], role: SourceType): RfInputFile[] {
  return files.filter((row) => field(row, 'source_type') === role)
}

function WorkflowStep({ number, title, detail }: { number: string; title: string; detail: string }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-cyan-400/40 bg-cyan-400/10 text-sm font-semibold text-cyan-100">
        {number}
      </span>
      <div className="min-w-0">
        <p className="text-sm font-semibold uppercase tracking-[0.18em] text-cyan-300/80">{title}</p>
        <p className="mt-1 text-sm text-slate-400">{detail}</p>
      </div>
    </div>
  )
}

export function RfValidationStudy() {
  // Project/Study Selection
  const [projects, setProjects] = useState<Project[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedProject, setSelectedProject] = useState<Project | null>(null)
  const [studies, setStudies] = useState<Study[]>([])
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(null)
  const [selectedStudy, setSelectedStudy] = useState<Study | null>(null)
  const [projectResults, setProjectResults] = useState<ProjectRfResultsResponse | null>(null)
  const [projectRawResults, setProjectRawResults] = useState<ProjectRfResultsResponse | null>(null)
  const [projectDuplicates, setProjectDuplicates] = useState<ProjectRfDuplicatesResponse | null>(null)
  const [projectAnalysisError, setProjectAnalysisError] = useState<string | null>(null)
  const [projectResultMode, setProjectResultMode] = useState<'canonical' | 'raw'>('canonical')

  // Existing state
  const [summary, setSummary] = useState<RfSummary>(emptySummary)
  const [runs, setRuns] = useState<RfRun[]>([])
  const [inputFiles, setInputFiles] = useState<RfInputFile[]>([])
  const [selectedRunId, setSelectedRunId] = useState('')
  const [selectedRunAlignment, setSelectedRunAlignment] = useState<RfRunAlignment | undefined>()
  const [timeAlignment, setTimeAlignment] = useState<RfTimeAlignmentResponse | null>(null)
  const [timeAlignmentLoading, setTimeAlignmentLoading] = useState(false)
  const [timeAlignmentError, setTimeAlignmentError] = useState<string | null>(null)
  const [runComparison, setRunComparison] = useState<RunComparisonResponse | null>(null)
  const [runComparisonLoading, setRunComparisonLoading] = useState(false)
  const [runComparisonError, setRunComparisonError] = useState<string | null>(null)
  const [runEditorOpen, setRunEditorOpen] = useState(false)
  const [selectedRunFiles, setSelectedRunFiles] = useState<RfRunFile[]>([])
  const [runForm, setRunForm] = useState<RunForm>(emptyRunForm)
  const [manualEntries, setManualEntries] = useState<RfManualEntries>({ pending: [], completed: [] })
  const [manualEntryForm, setManualEntryForm] = useState<ManualEntryForm>(emptyManualEntryForm)
  const [manualEntryDrafts, setManualEntryDrafts] = useState<Record<string, ManualEntryDraft>>({})
  const [fileSelections, setFileSelections] = useState<FileSelections>(emptyFileSelections)
  const [uploadFiles, setUploadFiles] = useState<Record<RunFileRole, File | null>>({
    badge_log: null,
    ekahau_json: null
  })
  const [uploadInputKeys, setUploadInputKeys] = useState<Record<RunFileRole, number>>({
    badge_log: 0,
    ekahau_json: 0
  })
  const [uploadingRole, setUploadingRole] = useState<RunFileRole | null>(null)
  const [bundleFile, setBundleFile] = useState<File | null>(null)
  const [uploadingBundle, setUploadingBundle] = useState(false)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [toast, setToast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function refresh() {
    setError(null)
    const data = await getRfSummary()
    setSummary(data)
  }

  async function loadProjects() {
    try {
      const response = await listProjects()
      const allProjects = response.projects ?? []
      const rfProjects = allProjects.filter((project) => {
        const type = field(project, 'project_type', 'rf_validation')
        return type === 'rf_validation' || type === 'mixed'
      })
      setProjects(allProjects)
      const currentProject = selectedProjectId
        ? rfProjects.find((project) => project.project_id === selectedProjectId) ?? null
        : null
      if (selectedProjectId) {
        setSelectedProject(currentProject)
        if (!currentProject) {
          setSelectedProjectId(null)
          setSelectedStudyId(null)
          setSelectedStudy(null)
          setStudies([])
          setRuns([])
        }
      }
      if ((!selectedProjectId || !currentProject) && rfProjects.length > 0) {
        const firstProject = rfProjects[0]
        const firstProjectId = firstProject.project_id
        if (firstProjectId) {
          setSelectedProjectId(firstProjectId)
          setSelectedProject(firstProject)
          await Promise.all([loadProjectStudies(firstProjectId, true), loadProjectResults(firstProjectId)])
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load projects')
    }
  }

  async function selectProject(projectId: string) {
    setSelectedProjectId(projectId)
    const project = projects.find((p) => p.project_id === projectId)
    setSelectedProject(project ?? null)
    setSelectedStudyId(null)
    setSelectedStudy(null)
    setRuns([])
    setProjectResults(null)
    setProjectRawResults(null)
    setProjectDuplicates(null)
    await Promise.all([loadProjectStudies(projectId, true), loadProjectResults(projectId)])
  }

  async function loadProjectStudies(projectId: string, selectFirst = false) {
    try {
      const response = await listProjectStudies(projectId)
      const rfStudies = (response.studies ?? []).filter((s) => s.study_type === 'rf_validation')
      setStudies(rfStudies)
      if (selectFirst && rfStudies.length > 0) {
        const firstStudy = rfStudies[0]
        const firstStudyId = firstStudy.study_id
        if (firstStudyId) {
          setSelectedStudyId(firstStudyId)
          setSelectedStudy(firstStudy)
          await loadStudyRuns(firstStudyId)
        }
      } else if (selectedStudyId) {
        const currentStudy = rfStudies.find((study) => study.study_id === selectedStudyId) ?? null
        setSelectedStudy(currentStudy)
        if (!currentStudy) {
          setSelectedStudyId(null)
          setRuns([])
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load studies')
    }
  }

  async function selectStudy(studyId: string) {
    setSelectedStudyId(studyId)
    const study = studies.find((s) => s.study_id === studyId)
    setSelectedStudy(study ?? null)
    setSelectedRunId('')
    setRunEditorOpen(false)
    await loadStudyRuns(studyId)
  }

  async function loadStudyRuns(studyId: string) {
    try {
      const data = await listStudyRuns(studyId)
      setRuns(data.runs)
      void loadRunComparison(studyId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load study runs')
    }
  }

  async function loadProjectResults(projectId: string) {
    setProjectAnalysisError(null)
    try {
      const [resultsData, rawResultsData, duplicatesData] = await Promise.all([
        getProjectRfResults(projectId),
        getProjectRfRawResults(projectId),
        getProjectRfDuplicates(projectId)
      ])
      setProjectResults(resultsData)
      setProjectRawResults(rawResultsData)
      setProjectDuplicates(duplicatesData)
    } catch (err) {
      console.error('Failed to load project results/duplicates:', err)
      setProjectAnalysisError(err instanceof Error ? err.message : 'Project analysis unavailable. Backend may need schema update.')
    }
  }

  async function refreshRuns() {
    if (selectedStudyId) {
      await loadStudyRuns(selectedStudyId)
    } else {
      const data = await listRuns()
      setRuns(data.runs)
    }
  }

  async function refreshInputFiles() {
    const data = await listInputFiles()
    setInputFiles(data.input_files)
  }

  async function refreshAll() {
    await Promise.all([
      refresh(),
      loadProjects(),
      selectedProjectId ? loadProjectStudies(selectedProjectId) : Promise.resolve(),
      selectedProjectId ? loadProjectResults(selectedProjectId) : Promise.resolve(),
      refreshInputFiles()
    ])
  }

  useEffect(() => {
    refreshAll()
      .catch((err: unknown) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false))
  }, [])

  async function runAction(label: string, action: () => Promise<unknown>) {
    setBusy(true)
    setToast(null)
    setError(null)
    try {
      await action()
      setToast(label)
      await refresh()
      if (selectedProjectId) {
        await loadProjectResults(selectedProjectId)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function openRun(testRunId: string) {
    const detail = await getRun(testRunId)
    setSelectedRunId(testRunId)
    setRunForm(runFormFromRun(detail.run))
    setSelectedRunFiles(detail.files ?? [])
    setFileSelections(selectionsFromRunFiles(detail.files ?? []))
    setSelectedRunAlignment(detail.alignment)
    const entries = detail.manual_entries ?? { pending: [], completed: [] }
    setManualEntries(entries)
    setManualEntryDrafts(
      Object.fromEntries(
        entries.pending.map((row) => [
          field(row, 'candidate_match_id'),
          { ekahau_rssi_dbm: '', ekahau_snr_db: '', notes: '' }
        ])
      )
    )
    setManualEntryForm(emptyManualEntryForm)
    void loadTimeAlignment(testRunId)
  }

  function selectManualEntryRow(row: StringRow) {
    setManualEntryForm({
      candidate_match_id: field(row, 'candidate_match_id'),
      match_id: field(row, 'match_id'),
      survey_point_id: field(row, 'survey_point_id'),
      bssid: field(row, 'bssid'),
      survey_time: field(row, 'survey_time'),
      ekahau_rssi_dbm: field(row, 'ekahau_rssi_dbm'),
      ekahau_snr_db: field(row, 'ekahau_snr_db'),
      notes: field(row, 'notes')
    })
  }

  async function refreshRunDetails() {
    if (!selectedRunId) {
      return
    }
    await openRun(selectedRunId)
    // Manual-entry save/reset flow through here and change pending/completed
    // counts, Cal Delta stats, and outliers — keep Run Comparison in sync.
    if (selectedStudyId) {
      void loadRunComparison(selectedStudyId)
    }
  }

  function updateManualEntryDraft(candidateMatchId: string, key: keyof ManualEntryDraft, value: string) {
    setManualEntryDrafts((current) => ({
      ...current,
      [candidateMatchId]: {
        ...(current[candidateMatchId] ?? { ekahau_rssi_dbm: '', ekahau_snr_db: '', notes: '' }),
        [key]: value
      }
    }))
  }

  function nextPendingManualEntryRow(candidateMatchId: string): StringRow | null {
    const currentIndex = manualEntries.pending.findIndex((item) => field(item, 'candidate_match_id') === candidateMatchId)
    if (currentIndex < 0) {
      return manualEntries.pending.find((item) => field(item, 'candidate_match_id') !== candidateMatchId) ?? null
    }

    const ordered = [...manualEntries.pending.slice(currentIndex + 1), ...manualEntries.pending.slice(0, currentIndex)]
    return ordered.find((item) => field(item, 'candidate_match_id') !== candidateMatchId) ?? null
  }

  async function saveManualEntryDraft(row: StringRow, selectNext = false) {
    const candidateMatchId = field(row, 'candidate_match_id')
    const draft = manualEntryDrafts[candidateMatchId] ?? { ekahau_rssi_dbm: '', ekahau_snr_db: '', notes: '' }
    if (!candidateMatchId) {
      setError('Missing candidate row id.')
      return
    }
    if (!draft.ekahau_rssi_dbm.trim()) {
      setError('Enter Ekahau RSSI before saving manual entry.')
      return
    }
    const nextRow = selectNext ? nextPendingManualEntryRow(candidateMatchId) : null
    await runAction('Manual entry saved.', async () => {
      await submitManualEntry(candidateMatchId, {
        ekahau_rssi_dbm: draft.ekahau_rssi_dbm,
        ekahau_snr_db: draft.ekahau_snr_db || undefined,
        notes: draft.notes || undefined
      })
      await refreshRunDetails()
      if (nextRow) {
        selectManualEntryRow(nextRow)
      }
    })
  }

  async function saveManualEntry(event: FormEvent) {
    event.preventDefault()
    if (!manualEntryForm.candidate_match_id) {
      setError('Select a pending or completed manual entry row before saving.')
      return
    }
    if (!manualEntryForm.ekahau_rssi_dbm.trim()) {
      setError('Enter Ekahau RSSI before saving manual entry.')
      return
    }
    await runAction('Manual entry saved.', async () => {
      await submitManualEntry(manualEntryForm.candidate_match_id, {
        ekahau_rssi_dbm: manualEntryForm.ekahau_rssi_dbm,
        ekahau_snr_db: manualEntryForm.ekahau_snr_db || undefined,
        notes: manualEntryForm.notes || undefined
      })
      await refreshRunDetails()
    })
  }

  async function resetManualEntry(matchId: string) {
    const confirmed = window.confirm('Reset this manual entry and return it to pending?')
    if (!confirmed) {
      return
    }
    await runAction('Manual entry reset.', async () => {
      await resetManualEntryMatch(matchId)
      await refreshRunDetails()
    })
  }

  function updateManualEntryForm(key: keyof ManualEntryForm, value: string) {
    setManualEntryForm((current) => ({ ...current, [key]: value }))
  }

  async function createDraftRun() {
    await runAction('Run created.', async () => {
      let created
      if (selectedStudyId) {
        // Use study-scoped endpoint
        created = await createStudyRun(selectedStudyId, { run_name: 'New draft run', run_status: 'draft' })
      } else {
        // Fallback to global endpoint
        created = await createRun({ run_name: 'New draft run', run_status: 'draft' })
      }
      await refreshRuns()
      await openRun(field(created.run, 'test_run_id'))
      setRunEditorOpen(true)
    })
  }

  async function editRun(testRunId: string) {
    setRunEditorOpen(true)
    await runAction('Run loaded.', () => openRun(testRunId))
  }

  async function persistSelectedRun() {
    if (!selectedRunId) {
      throw new Error('Create or select a run before saving.')
    }

    // Only send the match window when it parses to a valid whole second >= 1;
    // omitting it leaves the stored value unchanged (backend uses fields_set).
    const parsedWindow = Number.parseInt(runForm.default_match_window_seconds, 10)
    const matchWindowPayload = Number.isFinite(parsedWindow) && parsedWindow >= 1 ? parsedWindow : undefined

    await updateRun(selectedRunId, {
      run_name: runForm.run_name,
      badge_mac: runForm.badge_mac,
      site: runForm.site,
      building: runForm.building,
      floor: runForm.floor,
      area: runForm.area,
      ssid: runForm.ssid,
      badge_model: runForm.badge_model,
      ...(matchWindowPayload !== undefined ? { default_match_window_seconds: matchWindowPayload } : {}),
      notes: runForm.notes
    })

    for (const { role } of fileRoles) {
      const selectedInputFileId = fileSelections[role]
      const existingForRole = selectedRunFiles.filter((item) => field(item, 'source_role') === role)

      for (const existing of existingForRole) {
        const existingInputFileId = field(existing, 'input_file_id')
        if (existingInputFileId && existingInputFileId !== selectedInputFileId) {
          await removeRunFile(selectedRunId, existingInputFileId)
        }
      }

      if (selectedInputFileId && !existingForRole.some((item) => field(item, 'input_file_id') === selectedInputFileId)) {
        await addRunFile(selectedRunId, selectedInputFileId, role)
      }
    }

    await refreshRuns()
    await openRun(selectedRunId)
  }

  async function saveRun(event: FormEvent) {
    event.preventDefault()

    if (!selectedRunId) {
      setError('Create or select a run before saving.')
      return
    }

    await runAction('Run saved.', persistSelectedRun)
  }

  async function deleteSelectedRun(testRunId: string) {
    const confirmed = window.confirm(`Delete run ${testRunId}? This hides the run from the working study. Parsed data is preserved unless you hard-delete it separately.`)
    if (!confirmed) {
      return
    }

    await runAction('Run deleted.', async () => {
      await deleteRun(testRunId)
      if (selectedRunId === testRunId) {
        setSelectedRunId('')
        setRunEditorOpen(false)
        setSelectedRunFiles([])
        setRunForm(emptyRunForm)
        setFileSelections(emptyFileSelections)
        setUploadFiles({ badge_log: null, ekahau_json: null })
      }
      await refreshRuns()
    })
  }

  async function executeSelectedRun() {
    if (!selectedRunId) {
      setError('Create or select a run before executing.')
      return
    }

    if (!fileSelections.badge_log || !fileSelections.ekahau_json) {
      setError('Select one badge log archive and one Ekahau .esx survey before executing the run.')
      return
    }

    await runAction('Run executed.', async () => {
      await persistSelectedRun()
      await executeRun(selectedRunId)
      await refreshRuns()
      await openRun(selectedRunId)
      setRunEditorOpen(false)
    })
  }

  async function loadTimeAlignment(testRunId: string) {
    setTimeAlignmentLoading(true)
    setTimeAlignmentError(null)
    try {
      const data = await getRunTimeAlignment(testRunId)
      setTimeAlignment(data)
    } catch (err) {
      setTimeAlignment(null)
      setTimeAlignmentError(err instanceof Error ? err.message : 'Time Alignment Lab data is unavailable. The backend may need a schema update or restart.')
    } finally {
      setTimeAlignmentLoading(false)
    }
  }

  async function loadRunComparison(studyId: string) {
    setRunComparisonLoading(true)
    setRunComparisonError(null)
    try {
      const data = await getStudyRunComparison(studyId)
      setRunComparison(data)
    } catch (err) {
      setRunComparison(null)
      setRunComparisonError(err instanceof Error ? err.message : 'Run comparison is unavailable. The backend may need a schema update or restart.')
    } finally {
      setRunComparisonLoading(false)
    }
  }

  async function applyMatchWindowAndRerun(windowSeconds: number) {
    if (!selectedRunId) {
      return
    }
    const confirmed = window.confirm(`Set the match tolerance to ±${windowSeconds}s and re-run? This regenerates candidate matches for this run.`)
    if (!confirmed) {
      return
    }
    await runAction(`Re-ran at ±${windowSeconds}s tolerance.`, async () => {
      await updateRun(selectedRunId, { default_match_window_seconds: windowSeconds })
      await executeRun(selectedRunId)
      await refreshRuns()
      await openRun(selectedRunId)
    })
  }

  async function refreshFilesFromDisk() {
    await runAction('Source files refreshed.', async () => {
      await scanInputFiles()
      await refreshInputFiles()
    })
  }

  function updateRunForm(key: keyof RunForm, value: string) {
    setRunForm((current) => ({ ...current, [key]: value }))
  }

  function updateFileSelection(role: RunFileRole, inputFileId: string) {
    setFileSelections((current) => ({ ...current, [role]: inputFileId }))
  }

  function updateUploadFile(role: RunFileRole, file: File | null) {
    setUploadFiles((current) => ({ ...current, [role]: file }))
  }

  async function uploadSourceFile(role: RunFileRole) {
    const file = uploadFiles[role]
    if (!file) {
      setError('Choose a file before uploading.')
      return
    }

    setUploadingRole(role)
    try {
      await runAction('File uploaded.', async () => {
        const uploaded = await uploadInputFile(role, file)
        const inputFileId = field(uploaded.input_file, 'input_file_id')
        await refreshInputFiles()
        if (inputFileId) {
          updateFileSelection(role, inputFileId)
          if (selectedRunId) {
            await addRunFile(selectedRunId, inputFileId, role)
            await refreshRuns()
            await openRun(selectedRunId)
          }
        }
        setUploadFiles((current) => ({ ...current, [role]: null }))
        setUploadInputKeys((current) => ({ ...current, [role]: current[role] + 1 }))
      })
    } finally {
      setUploadingRole(null)
    }
  }

  async function uploadBundleFile() {
    if (!bundleFile) {
      setError('Choose a field bundle .zip before uploading.')
      return
    }

    setUploadingBundle(true)
    await runAction('Field bundle uploaded.', async () => {
      const uploaded = await uploadRunBundle(bundleFile, {
        testRunId: selectedRunId || undefined,
        runName: runForm.run_name || undefined,
        badgeMac: runForm.badge_mac || undefined,
        notes: runForm.notes || undefined
      })
      setBundleFile(null)
      await refreshInputFiles()
      await refreshRuns()
      await openRun(field(uploaded.run, 'test_run_id'))
      setRunEditorOpen(true)
    })
    setUploadingBundle(false)
  }

  const errors = useMemo(() => errorList(summary.errors), [summary.errors])
  const backendStatus = summary.backend.backend_status ?? 'unknown'

  // Only show RF-relevant projects on this page (rf_validation or mixed)
  const visibleProjects = useMemo(
    () =>
      projects.filter((row) => {
        const type = field(row, 'project_type', 'rf_validation')
        return type === 'rf_validation' || type === 'mixed'
      }),
    [projects]
  )

  // Filter out deleted runs
  const visibleRuns = useMemo(() => runs.filter((row) => field(row, 'run_status') !== 'deleted'), [runs])
  const selectedRun = useMemo(() => visibleRuns.find((row) => field(row, 'test_run_id') === selectedRunId) ?? null, [visibleRuns, selectedRunId])
  const matchWindowSeconds = useMemo(() => {
    const raw = selectedRun ? field(selectedRun, 'default_match_window_seconds') : ''
    const parsed = Number(raw)
    return Number.isFinite(parsed) && parsed > 0 ? parsed : 1
  }, [selectedRun])
  const selectedRunHasExecution = Boolean(selectedRun && field(selectedRun, 'run_status', 'draft') !== 'draft')
  const manualEntryAvailable = Boolean(selectedRunHasExecution && selectedRun && (manualEntries.pending.length > 0 || manualEntries.completed.length > 0))
  const activeProjectResultRows = projectResultMode === 'raw' ? projectRawResults?.results ?? [] : projectResults?.results ?? []
  const hasBadgeLogSelection = Boolean(fileSelections.badge_log)
  const hasEkahauSelection = Boolean(fileSelections.ekahau_json)
  const sourceFilesReady = Boolean(selectedRunId && hasBadgeLogSelection && hasEkahauSelection)
  const canAttemptExecution = Boolean(selectedRunId && !busy)
  const fileCounts = useMemo(() => {
    return fileRoles.reduce<Record<string, number>>((acc, { role }) => {
      acc[role] = fileByRole(inputFiles, role).length
      return acc
    }, {})
  }, [inputFiles])

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="text-sm font-semibold uppercase tracking-[0.28em] text-cyan-300/80">RF validation</p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-50">Vocera RF Validation Study Manager</h1>
          <p className="mt-2 text-sm text-slate-400">
            Scope <code className="rounded bg-slate-900 px-1.5 py-0.5 text-cyan-200">{summary.config.scope}</code> · Owner{' '}
            <code className="rounded bg-slate-900 px-1.5 py-0.5 text-cyan-200">{summary.config.user}</code>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusPill status={backendStatus} />
          <Button variant="secondary" disabled={busy || loading} onClick={() => runAction('Refreshed.', refreshAll)}>
            Refresh
          </Button>
        </div>
      </div>

      {toast && <div className="rounded-2xl border border-emerald-400/30 bg-emerald-400/10 p-4 text-sm text-emerald-100">{toast}</div>}
      {error && (
        <RunStatusMessage status="failed" error={error} />
      )}
      {errors.map((item) => (
        <div key={item} className="whitespace-pre-wrap rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">
          {item}
        </div>
      ))}
      {summary.skipped && <div className="rounded-2xl border border-slate-700 bg-slate-900 p-4 text-sm text-slate-300">Skipped compatibility checks: {summary.skipped}</div>}

      <WorkflowStep number="1" title="Project and study" detail="Choose the container for RF validation runs and project-level results." />
      <div className="grid gap-4 xl:grid-cols-2">
        <ProjectManager
          projects={visibleProjects}
          selectedProjectId={selectedProjectId}
          onSelect={selectProject}
          onChanged={async () => {
            await loadProjects()
          }}
          onError={setError}
          onToast={setToast}
          disabled={loading || busy}
        />
        <StudyManager
          projectId={selectedProjectId}
          studies={studies}
          selectedStudyId={selectedStudyId}
          defaultScope={selectedStudy ? field(selectedStudy, 'study_scope', summary.config.scope) : summary.config.scope}
          onSelect={selectStudy}
          onChanged={async () => {
            if (selectedProjectId) {
              await Promise.all([loadProjectStudies(selectedProjectId), loadProjectResults(selectedProjectId)])
            }
          }}
          onError={setError}
          onToast={setToast}
          disabled={loading || busy}
        />
      </div>

      {(selectedProject || selectedStudy || selectedRun) && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Selected project" value={selectedProject ? field(selectedProject, 'project_name', field(selectedProject, 'project_id')) : 'No project selected'} />
          <StatCard label="Selected study" value={selectedStudy ? field(selectedStudy, 'study_name', field(selectedStudy, 'study_id')) : 'No study selected'} />
          <StatCard label="Selected run" value={selectedRun ? field(selectedRun, 'run_name', field(selectedRun, 'test_run_id')) : 'No run selected'} />
          <StatCard label="Run status" value={selectedRun ? field(selectedRun, 'run_status', 'draft') : selectedStudy ? field(selectedStudy, 'study_status', 'active') : 'Not ready'} />
        </div>
      )}

      <WorkflowStep number="2" title="Runs and source files" detail="Create or select a run, attach one badge log archive and one Ekahau .esx survey, then execute parsing." />
      <CollapsibleCard title="RF Validation Runs" eyebrow="Source files + parser execution" defaultOpen={true}>
        <p className="mb-4 text-sm text-slate-400">
          A run is created from exactly two source inputs: one Vocera badge log archive and one Ekahau <code className="text-cyan-200">.esx</code> survey.
          Execute the run to parse both files and generate candidate matches <span className="text-slate-300">by timestamp proximity only</span> — a badge reading is
          a candidate for an Ekahau survey point when their timestamps fall within the match window (BSSID, AP, channel, RSSI and SNR are review context, not match
          criteria). Then use <span className="text-slate-300">Complete candidate matches</span> to fill in the Ekahau RSSI/SNR for each measured BSSID. The match
          window and clock settings come from the validation config.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" disabled={busy || loading} onClick={() => runAction('Runs refreshed.', refreshRuns)}>
            Refresh Runs
          </Button>
          <Button variant="secondary" disabled={busy || loading} onClick={refreshFilesFromDisk}>
            Refresh Files
          </Button>
          <Button disabled={busy || loading || !selectedStudyId} onClick={createDraftRun}>
            New Run
          </Button>
        </div>

        <div className="mt-4 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-sm font-semibold text-cyan-100">Upload Windows field bundle</p>
              <p className="mt-1 text-sm text-slate-400">
                Upload the ZIP created by the Windows field collection script. The app extracts survey/ and badge-log/, registers the Ekahau and badge files, and attaches them to the selected run. If no run is selected, it creates one.
              </p>
            </div>
            <div className="grid min-w-0 gap-2 lg:min-w-[480px] lg:grid-cols-[1fr_auto]">
              <input
                className="block w-full rounded-xl border border-dashed border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-slate-100 hover:file:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                type="file"
                accept=".zip,application/zip,application/x-zip-compressed"
                disabled={busy || uploadingBundle}
                onChange={(event) => setBundleFile(event.target.files?.[0] ?? null)}
              />
              <Button variant="secondary" type="button" disabled={busy || uploadingBundle || !bundleFile} onClick={uploadBundleFile}>
                Upload Bundle
              </Button>
            </div>
          </div>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-2">
          {fileRoles.map(({ role, label }) => (
            <StatCard key={role} label={label} value={String(fileCounts[role] ?? 0)} />
          ))}
        </div>

        <RunList rows={visibleRuns} selectedRunId={selectedRunId} busy={busy} onEdit={editRun} onDelete={deleteSelectedRun} />

        {runEditorOpen && selectedRunId ? (
          <form className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4" onSubmit={saveRun}>
            <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300/80">Run editor</p>
                <p className="mt-1 text-sm text-slate-500">
                  {selectedRunId ? (
                    <>
                      Editing <code className="text-cyan-200">{selectedRunId}</code>
                    </>
                  ) : (
                    'Create or select a run to edit metadata and source files.'
                  )}
                </p>
              </div>
              {selectedRun && <StatusPill status={field(selectedRun, 'run_status', 'draft')} />}
            </div>

            <div className="mt-4 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {(
                [
                  ['run_name', 'Run name', 'June Basement Run 001'],
                  ['badge_mac', 'Badge MAC', '00:09:ef:xx:xx:xx'],
                  ['site', 'Site', 'SRHC'],
                  ['building', 'Building', 'Basement'],
                  ['floor', 'Floor', 'B'],
                  ['area', 'Area', 'North hallway'],
                  ['ssid', 'SSID', 'srhcvoice2'],
                  ['badge_model', 'Badge model', 'C1000']
                ] as Array<[keyof RunForm, string, string]>
              ).map(([key, label, placeholder]) => (
                <label key={key} className="block text-sm font-medium text-slate-300">
                  {label}
                  <input
                    className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                    value={runForm[key]}
                    disabled={!selectedRunId || busy}
                    onChange={(event) => updateRunForm(key, event.target.value)}
                    placeholder={placeholder}
                  />
                </label>
              ))}
            </div>

            <div className="mt-4 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4">
              <label className="block text-sm font-medium text-slate-300">
                Timestamp match tolerance (± seconds)
                <input
                  className="mt-2 w-full max-w-[200px] rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                  type="number"
                  min={1}
                  step={1}
                  value={runForm.default_match_window_seconds}
                  disabled={!selectedRunId || busy}
                  onChange={(event) => updateRunForm('default_match_window_seconds', event.target.value)}
                  placeholder="1"
                />
              </label>
              <p className="mt-2 text-xs text-slate-400">
                A badge reading becomes a candidate for an Ekahau survey point when their timestamps fall within this window. Whole seconds, minimum 1.
                Changing it does not alter existing candidates — it takes effect on the next execution, so <span className="text-cyan-100">re-run to regenerate candidates</span>.
              </p>
            </div>

            <label className="mt-4 block text-sm font-medium text-slate-300">
              Notes
              <textarea
                className="mt-2 min-h-20 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={runForm.notes}
                disabled={!selectedRunId || busy}
                onChange={(event) => updateRunForm('notes', event.target.value)}
              />
            </label>
  
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              {fileRoles.map(({ role, label }) => (
                <div key={role} className="rounded-2xl border border-slate-800 bg-slate-900/50 p-4">
                  <label className="block text-sm font-medium text-slate-300">
                    {label}
                    <select
                      className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                      value={fileSelections[role]}
                      disabled={!selectedRunId || busy}
                      onChange={(event) => updateFileSelection(role, event.target.value)}
                    >
                      <option value="">No {label.toLowerCase()} selected</option>
                      {fileByRole(inputFiles, role).map((file) => (
                        <option key={field(file, 'input_file_id')} value={field(file, 'input_file_id')}>
                          {displayFile(file)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className="mt-3 grid gap-2 lg:grid-cols-[1fr_auto]">
                    <input
                      key={`${role}-${uploadInputKeys[role]}`}
                      className="block w-full rounded-xl border border-dashed border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-300 file:mr-3 file:rounded-lg file:border-0 file:bg-slate-800 file:px-3 file:py-1.5 file:text-sm file:font-semibold file:text-slate-100 hover:file:bg-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
                      type="file"
                      accept={role === 'ekahau_json' ? '.esx,.zip,.json,application/zip,application/json' : '.tar.gz,.tgz,.zip,.txt,.log,.sys,application/gzip,application/zip,text/plain'}
                      disabled={busy}
                      onChange={(event) => updateUploadFile(role, event.target.files?.[0] ?? null)}
                    />
                    <Button
                      variant={uploadFiles[role] ? 'primary' : 'secondary'}
                      type="button"
                      disabled={busy || uploadingRole === role || !uploadFiles[role]}
                      onClick={() => uploadSourceFile(role)}
                    >
                      {uploadingRole === role ? 'Uploading...' : `Upload ${label}`}
                    </Button>
                  </div>
                  <p className="mt-2 text-xs text-slate-500">
                    Upload stores this file in the correct incoming folder and selects it for this run.
                  </p>
                </div>
              ))}
            </div>
  
            <div className="mt-4 flex flex-wrap gap-2">
              <Button disabled={busy || !selectedRunId}>Save Run</Button>
              <Button variant="danger" type="button" disabled={busy || !selectedRunId} onClick={() => deleteSelectedRun(selectedRunId)}>
                Delete Run
              </Button>
              <Button variant={sourceFilesReady ? 'primary' : 'secondary'} type="button" disabled={!canAttemptExecution} onClick={executeSelectedRun}>
                Save & Execute Run
              </Button>
            </div>
            <p className="mt-3 text-sm text-slate-500">Save & Execute first saves the selected badge log and Ekahau file, then parses/imports the run and updates the run status to complete or failed.</p>
            {!sourceFilesReady && selectedRunId && (
              <p className="mt-2 text-sm text-amber-200">
                Save & Execute is clickable now, but execution still requires one Badge log and one Ekahau JSON/ESX source file. Current editor state:{' '}
                Badge log archive={hasBadgeLogSelection ? 'selected' : 'missing'}, Ekahau .esx survey={hasEkahauSelection ? 'selected' : 'missing'}.
              </p>
            )}
          </form>
        ) : (
          <div className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
            Click <span className="font-semibold text-slate-200">New Run</span> to create a run, or use <span className="font-semibold text-slate-200">Edit</span> on an existing run when you need to change metadata or source files.
          </div>
        )}

        {selectedRun && <div className="mt-6"><RunResultSummary run={selectedRun} alignment={selectedRunAlignment} /></div>}
      </CollapsibleCard>

      {selectedRun && (
        <TimeAlignmentLab
          data={timeAlignment}
          loading={timeAlignmentLoading}
          error={timeAlignmentError}
          busy={busy}
          onApplyWindow={applyMatchWindowAndRerun}
          onReload={() => {
            if (selectedRunId) {
              void loadTimeAlignment(selectedRunId)
            }
          }}
        />
      )}

      {manualEntryAvailable && (
        <>
          <WorkflowStep number="3" title="Complete candidate matches" detail="Enter Ekahau RSSI/SNR only for candidate rows that were actually measured." />
          <ManualEntryWorkbench
            pending={manualEntries.pending}
            completed={manualEntries.completed}
            drafts={manualEntryDrafts}
            selectedCandidateId={manualEntryForm.candidate_match_id}
            form={manualEntryForm}
            busy={busy}
            windowSeconds={matchWindowSeconds}
            onDraftChange={updateManualEntryDraft}
            onSaveDraft={saveManualEntryDraft}
            onSaveDraftAndNext={(row) => saveManualEntryDraft(row, true)}
            onSelectRow={selectManualEntryRow}
            onFormChange={updateManualEntryForm}
            onSubmitForm={saveManualEntry}
            onClearForm={() => setManualEntryForm(emptyManualEntryForm)}
            onResetMatch={resetManualEntry}
          />
        </>
      )}

      <WorkflowStep number="4" title="Project analysis" detail="Review canonical project results and duplicate datapoint warnings across included studies." />
      <ProjectResultsSummary
        project={selectedProject}
        studies={studies}
        canonicalResults={projectResults}
        rawResults={projectRawResults}
        duplicates={projectDuplicates}
        mode={projectResultMode}
        onModeChange={setProjectResultMode}
        error={projectAnalysisError}
      />

      <StudiesIncludedList studies={studies} />

      <DuplicateWarningsList duplicates={projectDuplicates} error={projectAnalysisError} />

      <ProjectResultsTable rows={activeProjectResultRows} mode={projectResultMode} error={projectAnalysisError} />

      <WorkflowStep number="5" title="Cal Delta statistics" detail="Use completed matches to evaluate badge-to-Ekahau calibration behavior." />
      <StudyStatisticsWorkbench study={selectedStudy} onError={setError} onToast={setToast} />

      {selectedStudyId && (
        <RunComparison
          data={runComparison}
          loading={runComparisonLoading}
          error={runComparisonError}
          onReload={() => {
            if (selectedStudyId) {
              void loadRunComparison(selectedStudyId)
            }
          }}
        />
      )}

      <WorkflowStep number="6" title="Diagnostics" detail="Inspect parser history and Grafana embedding only when troubleshooting." />
      <CollapsibleCard title="Run history" eyebrow="Parser output" defaultOpen={false}>
        <DataTable
          rows={visibleRuns.length ? visibleRuns : summary.runs}
          columns={[
            ['test_run_id', 'Run ID'],
            ['run_name', 'Run Name'],
            ['run_status', 'Status'],
            ['created_at', 'Created'],
            ['badge_mac', 'Badge MAC'],
            ['selected_file_count', 'Files'],
            ['badge_event_count', 'Badge Events'],
            ['survey_point_count', 'Survey Points'],
            ['candidate_match_count', 'Candidates'],
            ['pending_candidate_match_count', 'Pending'],
            ['completed_match_count', 'Completed'],
          ]}
        />
      </CollapsibleCard>

      <GrafanaDiagnostics />
    </div>
  )
}
