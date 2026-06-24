import type { Study } from '../api/types'
import { StatusPill } from './StatusPill'

function field(row: Record<string, string | undefined>, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function includedLabel(study: Study): string {
  if (field(study, 'deleted_at') || field(study, 'study_status') === 'deleted') {
    return 'excluded'
  }
  if (field(study, 'study_status') === 'archived') {
    return 'included archived'
  }
  return 'included'
}

export function StudiesIncludedList({ studies }: { studies: Study[] }) {
  const rfStudies = studies.filter((study) => field(study, 'study_type') === 'rf_validation')

  return (
    <section className="rounded-2xl border border-slate-800 bg-slate-900/80 p-5 shadow-xl shadow-black/10">
      <div className="mb-4">
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">Project scope</p>
        <h2 className="mt-1 text-lg font-semibold text-slate-100">Studies Included In Project Results</h2>
        <p className="mt-2 text-sm text-slate-400">Project Results include all non-deleted RF validation studies in this project. Archived studies remain included but are visually muted.</p>
      </div>

      {!rfStudies.length ? (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">No RF validation studies exist in this project yet.</p>
      ) : (
        <div className="space-y-3">
          {rfStudies.map((study) => {
            const status = field(study, 'study_status', 'active')
            const included = includedLabel(study)
            const muted = status === 'archived' || included === 'excluded'
            return (
              <div key={field(study, 'study_id')} className={`rounded-xl border border-slate-800 bg-slate-950/70 p-4 ${muted ? 'opacity-70' : ''}`}>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <p className="font-semibold text-slate-100">{field(study, 'study_name', field(study, 'study_id'))}</p>
                      <StatusPill status={status} />
                      <span className={included === 'excluded' ? 'rounded-full border border-rose-400/30 bg-rose-400/10 px-2 py-1 text-xs font-semibold text-rose-100' : 'rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs font-semibold text-emerald-100'}>
                        {included}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-slate-500">{field(study, 'study_id')}</p>
                    {field(study, 'description') && <p className="mt-2 text-sm text-slate-400">{field(study, 'description')}</p>}
                  </div>
                  <div className="grid min-w-0 grid-cols-2 gap-3 text-sm sm:grid-cols-4 lg:min-w-[460px]">
                    <Metric label="Scope" value={field(study, 'study_scope', 'unknown')} />
                    <Metric label="Runs" value={field(study, 'active_run_count', '0')} />
                    <Metric label="Completed" value={field(study, 'completed_match_count', '0')} />
                    <Metric label="Manual" value={field(study, 'manual_observation_count', '0')} />
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </section>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate font-semibold text-slate-200">{value || '0'}</p>
    </div>
  )
}
