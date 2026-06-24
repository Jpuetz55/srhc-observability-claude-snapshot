import { useEffect, useState } from 'react'
import { listProjects } from '../api/client'
import type { Project, ProjectType } from '../api/types'
import { Card } from './Card'
import { StatusPill } from './StatusPill'

interface ProjectSelectorProps {
  selectedProjectId: string | null
  onSelectProject: (projectId: string) => void
  disabled?: boolean
  projectType?: ProjectType
  projects?: Project[]
  title?: string
  description?: string
  emptyMessage?: string
}

export function ProjectSelector({
  selectedProjectId,
  onSelectProject,
  disabled = false,
  projectType,
  projects: providedProjects,
  title = 'Select Project',
  description = 'Choose a project to begin',
  emptyMessage = 'No projects found'
}: ProjectSelectorProps) {
  const [projects, setProjects] = useState<Project[]>([])
  const [loading, setLoading] = useState(!providedProjects)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (providedProjects) {
      setProjects(providedProjects)
      setLoading(false)
      setError(null)
      return
    }

    const loadProjects = async () => {
      try {
        setLoading(true)
        setError(null)
        const response = await listProjects()
        setProjects(response.projects ?? [])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load projects')
      } finally {
        setLoading(false)
      }
    }

    void loadProjects()
  }, [providedProjects])

  if (loading) {
    return <Card>Loading projects...</Card>
  }

  if (error) {
    return <Card className="border-red-900 bg-red-950/30">{error}</Card>
  }

  const visibleProjects = projectType
    ? projects.filter((project) => project.project_type === projectType || project.project_type === 'mixed')
    : projects

  if (visibleProjects.length === 0) {
    return <Card className="border-yellow-900 bg-yellow-950/30">{emptyMessage}</Card>
  }

  const selectedProject = visibleProjects.find((p) => p.project_id === selectedProjectId)

  return (
    <Card>
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        </div>

        {selectedProject && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-cyan-200">{selectedProject.project_name}</p>
                <p className="mt-1 text-xs text-slate-400">{selectedProject.project_id}</p>
                {(selectedProject.description || selectedProject.notes) && <p className="mt-2 text-xs text-slate-300">{selectedProject.description || selectedProject.notes}</p>}
              </div>
              <StatusPill status="selected" />
            </div>
          </div>
        )}

        <div className="grid gap-2">
          {visibleProjects.map((project) => (
            <button
              key={project.project_id}
              disabled={disabled || project.project_id === selectedProjectId}
              onClick={() => project.project_id && onSelectProject(project.project_id)}
              className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-900/30 p-3 text-left transition-colors hover:border-slate-600 hover:bg-slate-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-200">{project.project_name}</p>
                <p className="mt-1 text-xs text-slate-500">{project.project_id}</p>
              </div>
              {project.project_id === selectedProjectId && <StatusPill status="selected" />}
            </button>
          ))}
        </div>
      </div>
    </Card>
  )
}
