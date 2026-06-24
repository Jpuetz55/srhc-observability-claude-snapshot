import type { Project, StringRow, Study } from '../api/types'
import { StatCard } from './StatCard'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function numberValue(value: string | undefined): number | null {
  if (!value) {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function integer(value: string | undefined): string {
  const parsed = numberValue(value)
  return parsed === null ? '0' : parsed.toLocaleString()
}

function decimal(value: string | undefined, digits = 2, suffix = ''): string {
  const parsed = numberValue(value)
  return parsed === null ? 'blank' : `${parsed.toFixed(digits)}${suffix}`
}

function percent(value: string | undefined): string {
  const parsed = numberValue(value)
  return parsed === null ? 'blank' : `${(parsed * 100).toFixed(2)}%`
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return 'No captures'
  }
  const normalized = value.includes('T') ? value : value.replace(' ', 'T')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    timeZoneName: 'short'
  }).format(date)
}

export function MediaQoeSummary({ project, study, summary, error }: { project: Project | null; study: Study | null; summary: StringRow | null; error?: string | null }) {
  return (
    <section className="rounded-2xl border border-cyan-400/20 bg-cyan-400/5 p-5">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">Media Project Analysis</p>
        <h2 className="mt-1 text-lg font-semibold text-slate-100">Media QoE Summary</h2>
        <p className="mt-2 max-w-3xl text-sm text-slate-300">
          Project-level ICAP QoE results across the selected media study set. Use stream review to classify detected traffic without changing parser evidence.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Project: <span className="text-slate-300">{field(project, 'project_name', field(project, 'project_id', 'none selected'))}</span>
          {study && (
            <>
              {' '}
              / Study: <span className="text-slate-300">{field(study, 'study_name', field(study, 'study_id'))}</span>
            </>
          )}
        </p>
      </div>

      {error && <div className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}

      <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Captures" value={integer(field(summary, 'capture_count'))} />
        <StatCard label="Streams" value={integer(field(summary, 'stream_count'))} />
        <StatCard label="RTP QoE Streams" value={integer(field(summary, 'rtp_qoe_stream_count'))} />
        <StatCard label="Accepted Streams" value={integer(field(summary, 'accepted_stream_count'))} />
        <StatCard label="DSCP Mismatches" value={integer(field(summary, 'dscp_mismatch_stream_count'))} />
        <StatCard label="Lossy Streams" value={integer(field(summary, 'lossy_stream_count'))} />
        <StatCard label="Jitter P95" value={decimal(field(summary, 'jitter_p95_ms'), 2, ' ms')} />
        <StatCard label="Loss P95" value={percent(field(summary, 'loss_p95_ratio'))} />
        <StatCard label="Interarrival P95" value={decimal(field(summary, 'interarrival_p95_ms'), 2, ' ms')} />
        <StatCard label="Last Capture" value={formatTimestamp(field(summary, 'last_capture_time'))} />
      </div>
    </section>
  )
}
