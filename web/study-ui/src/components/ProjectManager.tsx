import { FormEvent, useState } from 'react'
import { createProject, deleteProject, updateProject } from '../api/client'
import type { Project, ProjectType } from '../api/types'
import { Button } from './Button'
import { Card } from './Card'
import { StatusPill } from './StatusPill'

type ProjectForm = {
  project_name: string
  project_type: ProjectType
  site: string
  description: string
}

const emptyForm: ProjectForm = { project_name: '', project_type: 'rf_validation', site: '', description: '' }

function field(row: Project, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

export function ProjectManager({
  projects,
  selectedProjectId,
  onSelect,
  onChanged,
  onError,
  onToast,
  disabled = false
}: {
  projects: Project[]
  selectedProjectId: string | null
  onSelect: (projectId: string) => void
  onChanged: () => Promise<void> | void
  onError: (message: string | null) => void
  onToast: (message: string) => void
  disabled?: boolean
}) {
  const [mode, setMode] = useState<'idle' | 'create' | 'edit'>('idle')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<ProjectForm>(emptyForm)
  const [busy, setBusy] = useState(false)

  function openCreate() {
    setMode('create')
    setEditingId(null)
    setForm(emptyForm)
    onError(null)
  }

  function openEdit(project: Project) {
    setMode('edit')
    setEditingId(field(project, 'project_id'))
    setForm({
      project_name: field(project, 'project_name'),
      project_type: (field(project, 'project_type', 'rf_validation') as ProjectType) || 'rf_validation',
      site: field(project, 'site'),
      description: field(project, 'description', field(project, 'notes'))
    })
    onError(null)
  }

  function close() {
    setMode('idle')
    setEditingId(null)
    setForm(emptyForm)
  }

  async function run(label: string, action: () => Promise<void>) {
    setBusy(true)
    onError(null)
    try {
      await action()
      onToast(label)
    } catch (err) {
      onError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault()
    if (!form.project_name.trim()) {
      onError('Name the project before saving.')
      return
    }
    const payload = {
      project_name: form.project_name.trim(),
      project_type: form.project_type,
      site: form.site.trim() || undefined,
      description: form.description.trim() || undefined
    }
    if (mode === 'edit' && editingId) {
      await run('Project updated.', async () => {
        await updateProject(editingId, payload)
        await onChanged()
        close()
      })
    } else {
      await run('Project created.', async () => {
        const response = await createProject(payload)
        await onChanged()
        const newId = response.project?.project_id
        if (newId) {
          onSelect(newId)
        }
        close()
      })
    }
  }

  async function remove(project: Project) {
    const projectId = field(project, 'project_id')
    if (!projectId) {
      return
    }
    if (!window.confirm(`Delete project "${field(project, 'project_name', projectId)}"? Active studies must be removed first.`)) {
      return
    }
    await run('Project deleted.', async () => {
      await deleteProject(projectId)
      await onChanged()
      if (mode === 'edit') {
        close()
      }
    })
  }

  return (
    <Card
      title="Projects"
      eyebrow="Project CRUD"
      actions={
        <Button type="button" disabled={disabled || busy} onClick={mode === 'create' ? close : openCreate}>
          {mode === 'create' ? 'Cancel' : 'New Project'}
        </Button>
      }
    >
      {(mode === 'create' || mode === 'edit') && (
        <form className="mb-4 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4" onSubmit={submit}>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300/80">{mode === 'edit' ? 'Edit project' : 'New project'}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="block text-sm font-medium text-slate-300">
              Project name
              <input
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.project_name}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, project_name: event.target.value }))}
                placeholder="SRHC RF validation"
              />
            </label>
            <label className="block text-sm font-medium text-slate-300">
              Project type
              <select
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.project_type}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, project_type: event.target.value as ProjectType }))}
              >
                <option value="rf_validation">rf_validation</option>
                <option value="mixed">mixed</option>
              </select>
            </label>
            <label className="block text-sm font-medium text-slate-300">
              Site (optional)
              <input
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.site}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, site: event.target.value }))}
                placeholder="SRHC"
              />
            </label>
            <label className="block text-sm font-medium text-slate-300">
              Description (optional)
              <input
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.description}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
              />
            </label>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button disabled={busy}>{mode === 'edit' ? 'Save Project' : 'Create Project'}</Button>
            <Button variant="secondary" type="button" disabled={busy} onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {projects.length === 0 ? (
        <p className="rounded-xl border border-yellow-900 bg-yellow-950/30 p-3 text-sm text-yellow-100">
          No projects yet. Use <span className="font-semibold">New Project</span> to create one.
        </p>
      ) : (
        <div className="grid gap-2">
          {projects.map((project) => {
            const projectId = field(project, 'project_id')
            const isSelected = projectId === selectedProjectId
            return (
              <div
                key={projectId}
                className={`flex items-center gap-3 rounded-lg border p-3 transition-colors ${
                  isSelected ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-slate-700 bg-slate-900/30 hover:border-slate-600'
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left disabled:cursor-not-allowed"
                  disabled={disabled || busy}
                  onClick={() => projectId && onSelect(projectId)}
                >
                  <p className="text-sm font-medium text-slate-200">{field(project, 'project_name', projectId)}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {projectId} · {field(project, 'project_type', 'rf_validation')} · {field(project, 'active_study_count', '0')} studies
                  </p>
                </button>
                {isSelected && <StatusPill status="selected" />}
                <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" className="px-3 py-1" type="button" disabled={busy} onClick={() => openEdit(project)}>
                    Edit
                  </Button>
                  <Button variant="danger" className="px-3 py-1" type="button" disabled={busy} onClick={() => remove(project)}>
                    Delete
                  </Button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}
