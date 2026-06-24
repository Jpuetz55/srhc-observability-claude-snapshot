import type { RunComparisonResponse, RunComparisonRow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'

function fmtInt(value: number | null): string {
  return value === null || value === undefined ? '—' : String(value)
}

function fmtDb(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(1)} dB`
}

function fmtPct(value: number | null): string {
  return value === null || value === undefined ? '—' : `${value.toFixed(0)}%`
}

function fmtWindow(value: number | null): string {
  if (value === null || value === undefined) {
    return '—'
  }
  return `±${Number.isInteger(value) ? value : value.toFixed(2)} s`
}

function windowCell(row: RunComparisonRow): string {
  const used = fmtWindow(row.match_window_seconds_used)
  // Show the configured window only when it differs from what actually ran.
  if (
    row.default_match_window_seconds !== null &&
    row.match_window_seconds_used !== null &&
    row.default_match_window_seconds !== row.match_window_seconds_used
  ) {
    return `${used} (cfg ${fmtWindow(row.default_match_window_seconds)})`
  }
  if (row.match_window_seconds_used === null) {
    return fmtWindow(row.default_match_window_seconds)
  }
  return used
}

const COLUMNS: { key: string; label: string; render: (row: RunComparisonRow) => string; tone?: (row: RunComparisonRow) => string }[] = [
  { key: 'run', label: 'Run', render: (row) => row.run_name || row.test_run_id },
  { key: 'status', label: 'Status', render: (row) => row.run_status || '—' },
  { key: 'window', label: 'Window (used)', render: windowCell },
  { key: 'candidates', label: 'Candidates', render: (row) => fmtInt(row.candidate_match_count) },
  { key: 'pending', label: 'Pending', render: (row) => fmtInt(row.pending_candidate_match_count) },
  { key: 'completed', label: 'Completed', render: (row) => fmtInt(row.completed_match_count) },
  { key: 'completion', label: 'Completion', render: (row) => fmtPct(row.completion_percent) },
  { key: 'mean', label: 'Mean Cal Δ', render: (row) => fmtDb(row.mean_cal_delta) },
  { key: 'stddev', label: 'Std dev', render: (row) => fmtDb(row.stddev_cal_delta) },
  { key: 'p95', label: 'p95', render: (row) => fmtDb(row.p95_cal_delta) },
  { key: 'min', label: 'Min', render: (row) => fmtDb(row.min_cal_delta) },
  { key: 'max', label: 'Max', render: (row) => fmtDb(row.max_cal_delta) },
  {
    key: 'outliers',
    label: 'Outliers',
    render: (row) => fmtInt(row.outlier_count),
    tone: (row) => ((row.outlier_count ?? 0) > 0 ? 'text-amber-200' : 'text-slate-200')
  }
]

export function RunComparison({
  data,
  loading,
  error,
  onReload
}: {
  data: RunComparisonResponse | null
  loading: boolean
  error: string | null
  onReload: () => void
}) {
  const rows = data?.rows ?? []
  return (
    <CollapsibleCard title="Run comparison" eyebrow="All runs in this study (read-only)" defaultOpen={false}>
      <div className="space-y-4">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <p className="max-w-3xl text-sm text-slate-400">
            Side-by-side view of every run in the study: match window, candidate/completion counts, and Cal Delta distribution.
            Use it to see how tolerance choices traded off match volume against ambiguity and outliers. This view never changes a run.
          </p>
          <Button variant="secondary" disabled={loading} onClick={onReload}>
            {loading ? 'Loading…' : 'Refresh'}
          </Button>
        </div>

        {error && <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">{error}</div>}

        {!error && data?.interpretation && (
          <div className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-4 text-sm text-cyan-100">{data.interpretation}</div>
        )}

        {!error && !loading && rows.length === 0 && (
          <p className="text-sm text-slate-500">No runs in this study yet.</p>
        )}

        {rows.length > 0 && (
          <div className="overflow-x-auto rounded-2xl border border-slate-800">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900/70 text-left text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  {COLUMNS.map((column) => (
                    <th key={column.key} className="whitespace-nowrap px-3 py-2">{column.label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={row.test_run_id} className="border-t border-slate-800/70">
                    {COLUMNS.map((column) => (
                      <td key={column.key} className={`whitespace-nowrap px-3 py-2 ${column.tone ? column.tone(row) : 'text-slate-200'}`}>
                        {column.render(row)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-slate-500">
          Completion = completed / (completed + pending). Outliers use the floor/band z-score &gt; 2 definition (needs ≥30 samples per group),
          matching the outlier view. Cal Delta is only populated for completed matches.
        </p>
      </div>
    </CollapsibleCard>
  )
}
