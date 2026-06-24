import type { RfRun } from '../api/types'
import { Button } from './Button'
import { StatusPill } from './StatusPill'

function field(row: Record<string, string | undefined>, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

export function RunList({
  rows,
  selectedRunId,
  busy,
  onEdit,
  onDelete
}: {
  rows: RfRun[]
  selectedRunId: string
  busy: boolean
  onEdit: (testRunId: string) => void
  onDelete: (testRunId: string) => void
}) {
  if (!rows.length) {
    return <p className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">No runs yet. Create a run to target source files.</p>
  }

  return (
    <div className="mt-4 space-y-3">
      {rows.map((row) => {
        const testRunId = field(row, 'test_run_id')
        const selected = selectedRunId === testRunId
        return (
          <article key={testRunId} className={`rounded-xl border p-4 ${selected ? 'border-cyan-400/40 bg-cyan-400/10' : 'border-slate-800 bg-slate-950/70'}`}>
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <p className="font-semibold text-slate-100">{field(row, 'run_name', testRunId)}</p>
                  <StatusPill status={field(row, 'run_status', 'draft')} />
                </div>
                <code className="mt-1 block break-all text-xs text-slate-500">{testRunId}</code>
                <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
                  <Metric label="Badge MAC" value={field(row, 'badge_mac', 'blank')} />
                  <Metric label="Files" value={field(row, 'selected_file_count', '0')} />
                  <Metric label="Candidates" value={field(row, 'candidate_match_count', '0')} />
                  <Metric label="Completed" value={field(row, 'completed_match_count', '0')} />
                </div>
              </div>
              <div className="flex shrink-0 flex-wrap gap-2">
                <Button variant="secondary" disabled={busy} onClick={() => onEdit(testRunId)}>
                  Edit
                </Button>
                <Button variant="danger" disabled={busy} onClick={() => onDelete(testRunId)}>
                  Delete
                </Button>
              </div>
            </div>

            <details className="mt-3 rounded-lg border border-slate-800 bg-slate-900/60 p-3">
              <summary className="cursor-pointer text-sm font-medium text-slate-300">Source file details</summary>
              <div className="mt-3 grid gap-3 text-sm lg:grid-cols-2">
                <FileValue label="Badge file" value={field(row, 'badge_file', 'No badge file selected')} />
                <FileValue label="Ekahau file" value={field(row, 'ekahau_file', 'No Ekahau file selected')} />
              </div>
            </details>
          </article>
        )
      })}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value || 'blank'}</p>
    </div>
  )
}

function FileValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-1 break-all text-slate-300">{value}</p>
    </div>
  )
}
