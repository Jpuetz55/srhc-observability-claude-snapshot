import type { StringRow } from '../api/types'
import { StatusPill } from './StatusPill'

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function formatTimestamp(value: string | undefined): string {
  if (!value) {
    return 'blank'
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

function numberLabel(value: string | undefined): string {
  if (!value) {
    return '0'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString() : value
}

function parserMessage(run: StringRow): string {
  if (field(run, 'error')) {
    return field(run, 'error')
  }
  const stdout = field(run, 'stdout')
  const lines = stdout.split(/\r?\n/).map((line) => line.trim()).filter(Boolean)
  return lines.find((line) => /parsed|imported|capture|stream/i.test(line) && !/create table|create view|notice:|alter table/i.test(line)) ?? ''
}

export function MediaParseRunList({ parseRuns, loading, error }: { parseRuns: StringRow[]; loading?: boolean; error?: string | null }) {
  if (loading) {
    return <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">Loading parse history...</p>
  }
  if (error) {
    return <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</div>
  }
  if (!parseRuns.length) {
    return <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">No parser execution history for this capture.</p>
  }

  return (
    <div className="space-y-3">
      {parseRuns.map((run) => (
        <article key={field(run, 'parse_run_id')} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
          <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="break-all text-sm font-semibold text-slate-100">{field(run, 'parse_run_id')}</h3>
                <StatusPill status={field(run, 'status', 'unknown')} />
              </div>
              <p className="mt-1 text-xs text-slate-500">Requested {formatTimestamp(field(run, 'requested_at'))} by {field(run, 'requested_by', 'unknown')}</p>
            </div>
            <p className="text-sm text-slate-400">{field(run, 'duration_seconds') ? `${field(run, 'duration_seconds')} sec` : 'duration blank'}</p>
          </div>

          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <Metric label="Exit" value={field(run, 'exit_code', 'blank')} />
            <Metric label="Streams" value={numberLabel(field(run, 'streams_imported'))} />
            <Metric label="RTP QoE" value={numberLabel(field(run, 'rtp_qoe_streams'))} />
            <Metric label="DSCP mismatch" value={numberLabel(field(run, 'dscp_mismatch_streams'))} />
            <Metric label="Lossy" value={numberLabel(field(run, 'lossy_streams'))} />
          </div>

          {parserMessage(run) && (
            <div className="mt-4 rounded-lg border border-slate-800 bg-slate-900/70 p-3">
              <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">Parser message</p>
              <p className="mt-2 break-words text-sm text-slate-200">{parserMessage(run)}</p>
            </div>
          )}

          {(field(run, 'error') || field(run, 'stderr') || field(run, 'stdout')) && (
            <details className="mt-4 rounded-lg border border-slate-800 bg-slate-900/70 p-3">
              <summary className="cursor-pointer text-sm font-semibold text-slate-300">Advanced logs</summary>
              {field(run, 'error') && <pre className="mt-3 whitespace-pre-wrap break-words rounded bg-rose-950/30 p-3 text-xs text-rose-100">{field(run, 'error')}</pre>}
              {field(run, 'stderr') && (
                <details className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.16em] text-amber-200">stderr</summary>
                  <pre className="mt-3 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs text-amber-100">{field(run, 'stderr')}</pre>
                </details>
              )}
              {field(run, 'stdout') && (
                <details className="mt-3 rounded border border-slate-800 bg-slate-950 p-3">
                  <summary className="cursor-pointer text-xs font-semibold uppercase tracking-[0.16em] text-slate-400">stdout</summary>
                  <pre className="mt-3 max-h-60 overflow-auto whitespace-pre-wrap break-words text-xs text-slate-300">{field(run, 'stdout')}</pre>
                </details>
              )}
            </details>
          )}
        </article>
      ))}
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value}</p>
    </div>
  )
}
