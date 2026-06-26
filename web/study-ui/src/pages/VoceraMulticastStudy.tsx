import { useEffect, useMemo, useState } from 'react'
import { createProject, createProjectStudy, getMediaQoeSummary, listProjectStudies, listProjects } from '../api/client'
import type { Project, StringRow, Study } from '../api/types'
import { Card } from '../components/Card'
import { MediaWlcCaptureSessions } from '../components/MediaWlcCaptureSessions'
import { ProjectSelector } from '../components/ProjectSelector'
import { StudySelector } from '../components/StudySelector'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

type Purpose = 'controlled_validation' | 'active_incident' | 'post_incident_review'

type InvestigationForm = {
  projectMode: 'new' | 'existing'
  existingProjectId: string
  projectName: string
  studyName: string
  purpose: Purpose
  notes: string
}

const EMPTY_INVESTIGATION_FORM: InvestigationForm = {
  projectMode: 'new',
  existingProjectId: '',
  projectName: 'Vocera Multicast Investigations',
  studyName: '',
  purpose: 'controlled_validation',
  notes: ''
}

function inputClass(): string {
  return 'w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400'
}

function textareaClass(): string {
  return 'min-h-24 w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400'
}

function purposeLabel(value: Purpose): string {
  if (value === 'active_incident') {
    return 'Active incident'
  }
  if (value === 'post_incident_review') {
    return 'Post-incident review'
  }
  return 'Controlled validation'
}

function visibleMediaProjects(projects: Project[]): Project[] {
  return projects.filter((project) => field(project, 'project_type') === 'media_qoe' || field(project, 'project_type') === 'mixed')
}

export function VoceraMulticastStudy() {
  const [projects, setProjects] = useState<Project[]>([])
  const [studies, setStudies] = useState<Study[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(null)
  const [loadingInitial, setLoadingInitial] = useState(true)
  const [loadingStudies, setLoadingStudies] = useState(false)
  const [creatingInvestigation, setCreatingInvestigation] = useState(false)
  const [showCreateInvestigation, setShowCreateInvestigation] = useState(false)
  const [showOpenInvestigation, setShowOpenInvestigation] = useState(false)
  const [investigationForm, setInvestigationForm] = useState<InvestigationForm>(EMPTY_INVESTIGATION_FORM)
  const [error, setError] = useState<string | null>(null)

  const selectedProject = useMemo(
    () => projects.find((project) => field(project, 'project_id') === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  )
  const selectedStudy = useMemo(
    () => studies.find((study) => field(study, 'study_id') === selectedStudyId) ?? null,
    [studies, selectedStudyId]
  )
  const mediaProjects = useMemo(() => visibleMediaProjects(projects), [projects])

  useEffect(() => {
    const load = async () => {
      try {
        setLoadingInitial(true)
        setError(null)
        const [summaryResponse, projectResponse] = await Promise.all([getMediaQoeSummary(), listProjects()])
        const loadedProjects = projectResponse.projects ?? []
        setProjects(loadedProjects)
        const visibleProjects = visibleMediaProjects(loadedProjects)
        const url = new URL(window.location.href)
        const requestedProjectId = url.searchParams.get('project')
        const requestedStudyId = url.searchParams.get('study')
        const defaultProjectId = field(summaryResponse.project, 'project_id')
        const initialProjectId = visibleProjects.some((project) => field(project, 'project_id') === requestedProjectId)
          ? requestedProjectId
          : visibleProjects.some((project) => field(project, 'project_id') === defaultProjectId)
            ? defaultProjectId
            : null
        setSelectedProjectId(initialProjectId || null)
        setSelectedStudyId(requestedStudyId)
        setInvestigationForm((current) => ({
          ...current,
          existingProjectId: initialProjectId || field(visibleProjects[0], 'project_id')
        }))
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load Vocera multicast projects')
      } finally {
        setLoadingInitial(false)
      }
    }

    void load()
  }, [])

  useEffect(() => {
    if (!selectedProjectId) {
      setStudies([])
      setSelectedStudyId(null)
      return
    }

    const loadStudies = async () => {
      try {
        setLoadingStudies(true)
        setError(null)
        const response = await listProjectStudies(selectedProjectId)
        const mediaStudies = (response.studies ?? []).filter((study) => field(study, 'study_type') === 'media_qoe')
        setStudies(mediaStudies)
        setSelectedStudyId((current) => {
          if (current && mediaStudies.some((study) => field(study, 'study_id') === current)) {
            return current
          }
          return null
        })
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load Vocera multicast studies')
      } finally {
        setLoadingStudies(false)
      }
    }

    void loadStudies()
  }, [selectedProjectId])

  const selectProject = (projectId: string) => {
    setSelectedProjectId(projectId)
    setSelectedStudyId(null)
    setStudies([])
    setInvestigationForm((current) => ({ ...current, existingProjectId: projectId }))
    const url = new URL(window.location.href)
    url.searchParams.set('project', projectId)
    url.searchParams.delete('study')
    url.searchParams.delete('session')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }

  const selectStudy = (studyId: string) => {
    setSelectedStudyId(studyId)
    const url = new URL(window.location.href)
    if (selectedProjectId) {
      url.searchParams.set('project', selectedProjectId)
    }
    url.searchParams.set('study', studyId)
    url.searchParams.delete('session')
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }

  const createInvestigation = async () => {
    const projectName = investigationForm.projectName.trim()
    const studyName = investigationForm.studyName.trim()
    if (!studyName) {
      setError('Enter a study name for the multicast investigation.')
      return
    }
    if (investigationForm.projectMode === 'new' && !projectName) {
      setError('Enter a project name or use an existing Media QoE project.')
      return
    }
    if (investigationForm.projectMode === 'existing' && !investigationForm.existingProjectId) {
      setError('Select an existing Media QoE project.')
      return
    }

    setCreatingInvestigation(true)
    setError(null)
    try {
      const projectResponse = investigationForm.projectMode === 'new'
        ? await createProject({
            project_name: projectName,
            project_type: 'media_qoe',
            site: 'srhc',
            description: 'Vocera multicast delivery investigations'
          })
        : { project: projects.find((project) => field(project, 'project_id') === investigationForm.existingProjectId) ?? {} }
      const projectId = field(projectResponse.project, 'project_id', investigationForm.existingProjectId)
      const purpose = purposeLabel(investigationForm.purpose)
      const description = [
        `Purpose: ${purpose}.`,
        investigationForm.notes.trim()
      ].filter(Boolean).join('\n\n')
      const studyResponse = await createProjectStudy(projectId, {
        study_name: studyName,
        study_type: 'media_qoe',
        study_scope: 'media_qoe',
        study_status: 'active',
        description
      })
      const [projectReload, studyReload] = await Promise.all([
        listProjects(),
        listProjectStudies(projectId)
      ])
      setProjects(projectReload.projects ?? [])
      setStudies((studyReload.studies ?? []).filter((study) => field(study, 'study_type') === 'media_qoe'))
      setSelectedProjectId(projectId)
      setSelectedStudyId(field(studyResponse.study, 'study_id'))
      setShowCreateInvestigation(false)
      setShowOpenInvestigation(false)
      setInvestigationForm({
        ...EMPTY_INVESTIGATION_FORM,
        existingProjectId: projectId,
        projectMode: 'existing'
      })
      const url = new URL(window.location.href)
      url.searchParams.set('project', projectId)
      url.searchParams.set('study', field(studyResponse.study, 'study_id'))
      url.searchParams.delete('session')
      window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create multicast investigation')
    } finally {
      setCreatingInvestigation(false)
    }
  }

  const investigationSelected = Boolean(selectedStudyId && selectedStudy)

  return (
    <div className="space-y-6">
      <div>
        <p className="text-sm font-semibold uppercase tracking-[0.28em] text-emerald-300/80">Vocera multicast</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-slate-50">Multicast Delivery Investigation</h1>
        <p className="mt-2 max-w-3xl text-sm text-slate-400">
          Manage manual WLC EPC capture sessions, operator broadcast markers, and multicast evidence for V5000 to C1000 delivery troubleshooting. ICAP capture QoE remains on its own page.
        </p>
      </div>

      {loadingInitial && <Card>Loading Vocera multicast workspace...</Card>}
      {error && <Card className="border-red-900 bg-red-950/30">{error}</Card>}

      {!loadingInitial && !investigationSelected && (
        <Card>
          <div className="mx-auto max-w-3xl space-y-5 text-center">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Investigation required</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">No multicast investigation is selected</h2>
              <p className="mt-2 text-sm text-slate-400">
                Create or open a Media QoE investigation before any WLC command sheets, event buttons, or artifact controls are shown.
              </p>
            </div>
            <div className="flex flex-wrap justify-center gap-3">
              <button className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950" onClick={() => { setShowCreateInvestigation(true); setShowOpenInvestigation(false) }}>
                Create new investigation
              </button>
              <button
                className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200 disabled:opacity-50"
                disabled={mediaProjects.length === 0}
                onClick={() => { setShowOpenInvestigation(true); setShowCreateInvestigation(false) }}
              >
                Open existing investigation
              </button>
            </div>
          </div>
        </Card>
      )}

      {showCreateInvestigation && !investigationSelected && (
        <Card>
          <div className="space-y-4">
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">Create investigation</p>
              <h2 className="mt-1 text-xl font-semibold text-slate-50">Vocera multicast investigation</h2>
            </div>
            <div className="grid gap-3 md:grid-cols-2">
              <label className="rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">
                <input
                  className="mr-2"
                  type="radio"
                  checked={investigationForm.projectMode === 'new'}
                  onChange={() => setInvestigationForm((current) => ({ ...current, projectMode: 'new' }))}
                />
                Create new Media QoE project
              </label>
              <label className="rounded-md border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">
                <input
                  className="mr-2"
                  type="radio"
                  checked={investigationForm.projectMode === 'existing'}
                  disabled={mediaProjects.length === 0}
                  onChange={() => setInvestigationForm((current) => ({
                    ...current,
                    projectMode: 'existing',
                    existingProjectId: current.existingProjectId || field(mediaProjects[0], 'project_id')
                  }))}
                />
                Use existing Media QoE project
              </label>
            </div>
            {investigationForm.projectMode === 'new' ? (
              <label className="block space-y-1 text-sm text-slate-300">
                <span>Project</span>
                <input className={inputClass()} value={investigationForm.projectName} onChange={(event) => setInvestigationForm((current) => ({ ...current, projectName: event.target.value }))} />
              </label>
            ) : (
              <label className="block space-y-1 text-sm text-slate-300">
                <span>Project</span>
                <select className={inputClass()} value={investigationForm.existingProjectId} onChange={(event) => setInvestigationForm((current) => ({ ...current, existingProjectId: event.target.value }))}>
                  {mediaProjects.map((project) => (
                    <option key={field(project, 'project_id')} value={field(project, 'project_id')}>{field(project, 'project_name')}</option>
                  ))}
                </select>
              </label>
            )}
            <label className="block space-y-1 text-sm text-slate-300">
              <span>Study name</span>
              <input className={inputClass()} value={investigationForm.studyName} placeholder="WLC EPC Smoke - June 2026" onChange={(event) => setInvestigationForm((current) => ({ ...current, studyName: event.target.value }))} />
            </label>
            <label className="block space-y-1 text-sm text-slate-300">
              <span>Purpose</span>
              <select className={inputClass()} value={investigationForm.purpose} onChange={(event) => setInvestigationForm((current) => ({ ...current, purpose: event.target.value as Purpose }))}>
                <option value="controlled_validation">Controlled validation</option>
                <option value="active_incident">Active incident</option>
                <option value="post_incident_review">Post-incident review</option>
              </select>
            </label>
            <label className="block space-y-1 text-sm text-slate-300">
              <span>Optional notes</span>
              <textarea className={textareaClass()} value={investigationForm.notes} onChange={(event) => setInvestigationForm((current) => ({ ...current, notes: event.target.value }))} />
            </label>
            <div className="flex flex-wrap gap-2">
              <button className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50" disabled={creatingInvestigation} onClick={() => { void createInvestigation() }}>
                Create investigation
              </button>
              <button className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-200" onClick={() => setShowCreateInvestigation(false)}>
                Cancel
              </button>
            </div>
          </div>
        </Card>
      )}

      {showOpenInvestigation && !investigationSelected && (
        <div className="grid gap-4 xl:grid-cols-2">
          <ProjectSelector
            selectedProjectId={selectedProjectId}
            onSelectProject={selectProject}
            disabled={loadingInitial || loadingStudies}
            projectType="media_qoe"
            projects={projects}
            title="Open Project"
            description="Choose the Media QoE project that owns multicast investigation studies"
            emptyMessage="No Media QoE projects found for multicast investigations"
          />
          {loadingStudies ? (
            <Card>Loading multicast investigation studies...</Card>
          ) : (
            <StudySelector
              projectId={selectedProjectId}
              selectedStudyId={selectedStudyId}
              onSelectStudy={selectStudy}
              disabled={loadingInitial}
              studyType="media_qoe"
              studies={studies}
              title="Open Investigation"
              description="Choose the study that owns WLC capture sessions and broadcast markers"
              emptyMessage="No Media QoE studies found in this project"
            />
          )}
        </div>
      )}

      {investigationSelected && (
        <div className="grid gap-3 md:grid-cols-2">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Selected project</p>
            <p className="mt-2 text-sm font-semibold text-slate-100">{field(selectedProject, 'project_name', 'No project selected')}</p>
            <p className="mt-1 break-all font-mono text-xs text-slate-500">{field(selectedProject, 'project_id')}</p>
          </Card>
          <Card>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Selected study</p>
            <p className="mt-2 text-sm font-semibold text-slate-100">{field(selectedStudy, 'study_name', 'No study selected')}</p>
            <p className="mt-1 break-all font-mono text-xs text-slate-500">{field(selectedStudy, 'study_id')}</p>
          </Card>
        </div>
      )}

      {investigationSelected && <MediaWlcCaptureSessions studyId={selectedStudyId} />}
    </div>
  )
}
