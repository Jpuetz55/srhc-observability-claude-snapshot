import { useEffect, useState } from 'react'
import { listProjectStudies } from '../api/client'
import type { Study, StudyType } from '../api/types'
import { Card } from './Card'
import { StatusPill } from './StatusPill'

interface StudySelectorProps {
  projectId: string | null
  selectedStudyId: string | null
  onSelectStudy: (studyId: string) => void
  disabled?: boolean
  studyType?: StudyType
  studies?: Study[]
  title?: string
  description?: string
  emptyMessage?: string
}

export function StudySelector({
  projectId,
  selectedStudyId,
  onSelectStudy,
  disabled = false,
  studyType,
  studies: providedStudies,
  title = 'Select Study',
  description = 'Choose a study to continue',
  emptyMessage = 'No studies found in this project'
}: StudySelectorProps) {
  const [studies, setStudies] = useState<Study[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (providedStudies) {
      setStudies(providedStudies)
      setLoading(false)
      setError(null)
      return
    }

    if (!projectId) {
      setStudies([])
      return
    }

    const loadStudies = async () => {
      try {
        setLoading(true)
        setError(null)
        const response = await listProjectStudies(projectId)
        setStudies(response.studies ?? [])
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load studies')
      } finally {
        setLoading(false)
      }
    }

    void loadStudies()
  }, [projectId, providedStudies])

  if (!projectId && !providedStudies) {
    return <Card className="border-slate-700 bg-slate-900/30 text-slate-400">Select a project to view studies</Card>
  }

  if (loading) {
    return <Card>Loading studies...</Card>
  }

  if (error) {
    return <Card className="border-red-900 bg-red-950/30">{error}</Card>
  }

  const visibleStudies = studyType ? studies.filter((s) => s.study_type === studyType) : studies

  if (visibleStudies.length === 0) {
    return <Card className="border-yellow-900 bg-yellow-950/30">{emptyMessage}</Card>
  }

  const selectedStudy = visibleStudies.find((s) => s.study_id === selectedStudyId)

  return (
    <Card>
      <div className="space-y-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">{title}</h3>
          <p className="mt-1 text-xs text-slate-500">{description}</p>
        </div>

        {selectedStudy && (
          <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
            <div className="flex items-start justify-between">
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-cyan-200">{selectedStudy.study_name}</p>
                <p className="mt-1 text-xs text-slate-400">{selectedStudy.study_id}</p>
                {selectedStudy.study_scope && (
                  <p className="mt-1 text-xs text-slate-500">Scope: {selectedStudy.study_scope}</p>
                )}
                {(selectedStudy.description || selectedStudy.notes) && <p className="mt-2 text-xs text-slate-300">{selectedStudy.description || selectedStudy.notes}</p>}
              </div>
              <StatusPill status="selected" />
            </div>
          </div>
        )}

        <div className="grid gap-2">
          {visibleStudies.map((study) => (
            <button
              key={study.study_id}
              disabled={disabled || study.study_id === selectedStudyId}
              onClick={() => study.study_id && onSelectStudy(study.study_id)}
              className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-900/30 p-3 text-left transition-colors hover:border-slate-600 hover:bg-slate-900/50 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <div className="min-w-0 flex-1">
                <p className="text-sm font-medium text-slate-200">{study.study_name}</p>
                <p className="mt-1 text-xs text-slate-500">{study.study_id}</p>
                {study.study_scope && <p className="mt-1 text-xs text-slate-400">Scope: {study.study_scope}</p>}
              </div>
              {study.study_id === selectedStudyId && <StatusPill status="selected" />}
            </button>
          ))}
        </div>
      </div>
    </Card>
  )
}
