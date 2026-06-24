import { FormEvent, useState } from 'react'
import { createProjectStudy, deleteStudy, updateStudy } from '../api/client'
import type { Study, StudyScope, StudyStatus } from '../api/types'
import { Button } from './Button'
import { Card } from './Card'
import { StatusPill } from './StatusPill'

type StudyForm = {
  study_name: string
  study_scope: StudyScope
  study_status: StudyStatus
  description: string
}

const scopeOptions: StudyScope[] = ['vocera_badge', 'ipad']
const statusOptions: StudyStatus[] = ['active', 'complete', 'archived']

function field(row: Study, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

export function StudyManager({
  projectId,
  studies,
  selectedStudyId,
  defaultScope,
  onSelect,
  onChanged,
  onError,
  onToast,
  disabled = false
}: {
  projectId: string | null
  studies: Study[]
  selectedStudyId: string | null
  defaultScope: string
  onSelect: (studyId: string) => void
  onChanged: () => Promise<void> | void
  onError: (message: string | null) => void
  onToast: (message: string) => void
  disabled?: boolean
}) {
  const fallbackScope = (scopeOptions.includes(defaultScope as StudyScope) ? defaultScope : 'vocera_badge') as StudyScope
  const emptyForm: StudyForm = { study_name: '', study_scope: fallbackScope, study_status: 'active', description: '' }
  const [mode, setMode] = useState<'idle' | 'create' | 'edit'>('idle')
  const [editingId, setEditingId] = useState<string | null>(null)
  const [form, setForm] = useState<StudyForm>(emptyForm)
  const [busy, setBusy] = useState(false)

  function openCreate() {
    setMode('create')
    setEditingId(null)
    setForm(emptyForm)
    onError(null)
  }

  function openEdit(study: Study) {
    setMode('edit')
    setEditingId(field(study, 'study_id'))
    setForm({
      study_name: field(study, 'study_name'),
      study_scope: (field(study, 'study_scope', fallbackScope) as StudyScope) || fallbackScope,
      study_status: (field(study, 'study_status', 'active') as StudyStatus) || 'active',
      description: field(study, 'description', field(study, 'notes'))
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
    if (!projectId) {
      onError('Select a project before adding studies.')
      return
    }
    if (!form.study_name.trim()) {
      onError('Name the study before saving.')
      return
    }
    if (mode === 'edit' && editingId) {
      await run('Study updated.', async () => {
        await updateStudy(editingId, {
          study_name: form.study_name.trim(),
          study_scope: form.study_scope,
          study_status: form.study_status,
          description: form.description.trim() || undefined
        })
        await onChanged()
        close()
      })
    } else {
      await run('Study created.', async () => {
        const response = await createProjectStudy(projectId, {
          study_type: 'rf_validation',
          study_scope: form.study_scope,
          study_name: form.study_name.trim(),
          study_status: form.study_status,
          description: form.description.trim() || undefined
        })
        await onChanged()
        const newId = response.study?.study_id
        if (newId) {
          onSelect(newId)
        }
        close()
      })
    }
  }

  async function remove(study: Study) {
    const studyId = field(study, 'study_id')
    if (!studyId) {
      return
    }
    if (!window.confirm(`Delete study "${field(study, 'study_name', studyId)}"?`)) {
      return
    }
    await run('Study deleted.', async () => {
      await deleteStudy(studyId)
      await onChanged()
      if (mode === 'edit') {
        close()
      }
    })
  }

  if (!projectId) {
    return (
      <Card title="Studies" eyebrow="Study CRUD">
        <p className="rounded-xl border border-slate-700 bg-slate-900/30 p-3 text-sm text-slate-400">Select a project to manage its studies.</p>
      </Card>
    )
  }

  return (
    <Card
      title="Studies"
      eyebrow="Study CRUD"
      actions={
        <Button type="button" disabled={disabled || busy} onClick={mode === 'create' ? close : openCreate}>
          {mode === 'create' ? 'Cancel' : 'New Study'}
        </Button>
      }
    >
      {(mode === 'create' || mode === 'edit') && (
        <form className="mb-4 rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4" onSubmit={submit}>
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-cyan-300/80">{mode === 'edit' ? 'Edit study' : 'New study'}</p>
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            <label className="block text-sm font-medium text-slate-300">
              Study name
              <input
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.study_name}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, study_name: event.target.value }))}
                placeholder="June basement survey"
              />
            </label>
            <label className="block text-sm font-medium text-slate-300">
              Scope
              <select
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.study_scope}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, study_scope: event.target.value as StudyScope }))}
              >
                {scopeOptions.map((scope) => (
                  <option key={scope} value={scope}>
                    {scope}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm font-medium text-slate-300">
              Status
              <select
                className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
                value={form.study_status}
                disabled={busy}
                onChange={(event) => setForm((current) => ({ ...current, study_status: event.target.value as StudyStatus }))}
              >
                {statusOptions.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
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
            <Button disabled={busy}>{mode === 'edit' ? 'Save Study' : 'Create Study'}</Button>
            <Button variant="secondary" type="button" disabled={busy} onClick={close}>
              Cancel
            </Button>
          </div>
        </form>
      )}

      {studies.length === 0 ? (
        <p className="rounded-xl border border-yellow-900 bg-yellow-950/30 p-3 text-sm text-yellow-100">
          No studies in this project yet. Use <span className="font-semibold">New Study</span> to add one.
        </p>
      ) : (
        <div className="grid gap-2">
          {studies.map((study) => {
            const studyId = field(study, 'study_id')
            const isSelected = studyId === selectedStudyId
            return (
              <div
                key={studyId}
                className={`flex items-center gap-3 rounded-lg border p-3 transition-colors ${
                  isSelected ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-slate-700 bg-slate-900/30 hover:border-slate-600'
                }`}
              >
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left disabled:cursor-not-allowed"
                  disabled={disabled || busy}
                  onClick={() => studyId && onSelect(studyId)}
                >
                  <p className="text-sm font-medium text-slate-200">{field(study, 'study_name', studyId)}</p>
                  <p className="mt-1 text-xs text-slate-500">
                    {field(study, 'study_scope', 'vocera_badge')} · {field(study, 'study_status', 'active')}
                  </p>
                </button>
                {isSelected && <StatusPill status="selected" />}
                <div className="flex shrink-0 gap-2">
                  <Button variant="secondary" className="px-3 py-1" type="button" disabled={busy} onClick={() => openEdit(study)}>
                    Edit
                  </Button>
                  <Button variant="danger" className="px-3 py-1" type="button" disabled={busy} onClick={() => remove(study)}>
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
