import type { Project, ProjectRfDuplicatesResponse, ProjectRfResultsResponse, Study } from '../api/types'
import { Button } from './Button'

type ResultsMode = 'canonical' | 'raw'

function field(row: Record<string, string | undefined> | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function asNumber(value: string | undefined): number {
  const parsed = Number(value ?? 0)
  return Number.isFinite(parsed) ? parsed : 0
}

function latestTimestamp(rows: Array<Record<string, string | undefined>>): string {
  const timestamps = rows
    .map((row) => field(row, 'entered_at') || field(row, 'match_created_at') || field(row, 'survey_time'))
    .filter(Boolean)
    .sort()
  return timestamps.at(-1) ?? ''
}

export function ProjectResultsSummary({
  project,
  studies,
  canonicalResults,
  rawResults,
  duplicates,
  mode,
  onModeChange,
  error
}: {
  project: Project | null
  studies: Study[]
  canonicalResults: ProjectRfResultsResponse | null
  rawResults: ProjectRfResultsResponse | null
  duplicates: ProjectRfDuplicatesResponse | null
  mode: ResultsMode
  onModeChange: (mode: ResultsMode) => void
  error?: string | null
}) {
  const includedStudies = studies.filter((study) => field(study, 'deleted_at') === '' && field(study, 'study_status') !== 'deleted')
  const runCount = includedStudies.reduce((total, study) => total + asNumber(field(study, 'active_run_count')), 0)
  const canonicalRows = canonicalResults?.results ?? []
  const rawRows = rawResults?.results ?? []
  const duplicateRows = duplicates?.duplicates ?? []
  const lastUpdated = latestTimestamp(rawRows.length ? rawRows : canonicalRows)

  const stats = [
    ['Canonical datapoints', String(canonicalRows.length)],
    ['Raw completed datapoints', String(rawRows.length)],
    ['Duplicate warnings', String(duplicateRows.length)],
    ['Studies included', String(includedStudies.length)],
    ['Runs included', String(runCount)],
    ['Newest match', lastUpdated || 'No completed matches']
  ]

  return (
    <section className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-5">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">Project Analysis</p>
          <h2 className="mt-1 text-lg font-semibold text-slate-100">Project Results</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-300">
            Canonical completed RF validation datapoints across all non-deleted studies in this project. Duplicate Warnings show overlapping datapoints without hiding the raw evidence.
          </p>
          {project ? (
            <p className="mt-2 text-xs text-slate-500">
              Selected project: <span className="text-slate-300">{field(project, 'project_name', field(project, 'project_id'))}</span>
            </p>
          ) : (
            <p className="mt-2 text-xs text-amber-200">No project selected.</p>
          )}
        </div>
        <div className="flex rounded-xl border border-slate-800 bg-slate-950 p-1">
          <Button variant={mode === 'canonical' ? 'primary' : 'ghost'} className="px-3 py-1.5" type="button" onClick={() => onModeChange('canonical')}>
            Canonical
          </Button>
          <Button variant={mode === 'raw' ? 'primary' : 'ghost'} className="px-3 py-1.5" type="button" onClick={() => onModeChange('raw')}>
            Raw
          </Button>
        </div>
      </div>

      {error && <div className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}

      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
        {stats.map(([label, value]) => (
          <div key={label} className="rounded-xl border border-slate-800 bg-slate-950/70 p-3">
            <p className="text-xs uppercase tracking-[0.16em] text-slate-500">{label}</p>
            <p className="mt-2 text-lg font-semibold text-slate-100">{value}</p>
          </div>
        ))}
      </div>
    </section>
  )
}
