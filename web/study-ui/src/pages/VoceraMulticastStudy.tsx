import { useEffect, useMemo, useState } from 'react'
import { getMediaQoeSummary, listProjectStudies, listProjects } from '../api/client'
import type { Project, StringRow, Study } from '../api/types'
import { Card } from '../components/Card'
import { MediaWlcCaptureSessions } from '../components/MediaWlcCaptureSessions'
import { ProjectSelector } from '../components/ProjectSelector'
import { StudySelector } from '../components/StudySelector'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

export function VoceraMulticastStudy() {
  const [projects, setProjects] = useState<Project[]>([])
  const [studies, setStudies] = useState<Study[]>([])
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null)
  const [selectedStudyId, setSelectedStudyId] = useState<string | null>(null)
  const [loadingInitial, setLoadingInitial] = useState(true)
  const [loadingStudies, setLoadingStudies] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const selectedProject = useMemo(
    () => projects.find((project) => field(project, 'project_id') === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  )
  const selectedStudy = useMemo(
    () => studies.find((study) => field(study, 'study_id') === selectedStudyId) ?? null,
    [studies, selectedStudyId]
  )

  useEffect(() => {
    const load = async () => {
      try {
        setLoadingInitial(true)
        setError(null)
        const [summaryResponse, projectResponse] = await Promise.all([getMediaQoeSummary(), listProjects()])
        const loadedProjects = projectResponse.projects ?? []
        setProjects(loadedProjects)
        const visibleProjects = loadedProjects.filter((project) => field(project, 'project_type') === 'media_qoe' || field(project, 'project_type') === 'mixed')
        const defaultProjectId = field(summaryResponse.project, 'project_id')
        const initialProjectId = visibleProjects.some((project) => field(project, 'project_id') === defaultProjectId)
          ? defaultProjectId
          : field(visibleProjects[0], 'project_id')
        setSelectedProjectId(initialProjectId || null)
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
          return field(mediaStudies[0], 'study_id') || null
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
  }

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

      <div className="grid gap-4 xl:grid-cols-2">
        <ProjectSelector
          selectedProjectId={selectedProjectId}
          onSelectProject={selectProject}
          disabled={loadingInitial || loadingStudies}
          projectType="media_qoe"
          projects={projects}
          description="Choose the project that owns multicast investigation sessions"
          emptyMessage="No Media QoE projects found for multicast investigations"
        />
        {loadingStudies ? (
          <Card>Loading multicast investigation studies...</Card>
        ) : (
          <StudySelector
            projectId={selectedProjectId}
            selectedStudyId={selectedStudyId}
            onSelectStudy={setSelectedStudyId}
            disabled={loadingInitial}
            studyType="media_qoe"
            studies={studies}
            description="Choose the study that owns WLC capture sessions and broadcast markers"
            emptyMessage="No Media QoE studies found in this project"
          />
        )}
      </div>

      {(selectedProject || selectedStudy) && (
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

      <MediaWlcCaptureSessions studyId={selectedStudyId} />
    </div>
  )
}
