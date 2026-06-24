import type { StringRow } from '../api/types'
import { CollapsibleCard } from './CollapsibleCard'

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function numberLabel(value: string | undefined): string {
  if (!value) {
    return '0'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString() : value
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

export function MediaDuplicateCaptures({ duplicates, error }: { duplicates: StringRow[]; error?: string | null }) {
  return (
    <CollapsibleCard title="Duplicate Capture Warnings" eyebrow="Project media evidence" defaultOpen={true}>
      <p className="mb-4 text-sm text-slate-400">
        Duplicate capture warnings flag repeated imports by source hash or source identity. They do not delete evidence or alter stream samples.
      </p>
      {error && <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}
      {!duplicates.length ? (
        <p className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-100">No duplicate captures detected.</p>
      ) : (
        <div className="space-y-3">
          {duplicates.slice(0, 50).map((row) => (
            <article key={`${field(row, 'duplicate_key')}-${field(row, 'capture_id')}`} className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-4">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-amber-100">{field(row, 'source_name', field(row, 'capture_id'))}</p>
                  <p className="mt-1 text-xs text-slate-500">{field(row, 'capture_id')}</p>
                  <p className="mt-2 text-sm text-slate-300">Captured {formatTimestamp(field(row, 'capture_time'))}</p>
                </div>
                <div className="rounded-lg border border-amber-400/20 bg-slate-950/60 px-3 py-2 text-xs text-amber-100">
                  Duplicate count {field(row, 'duplicate_count', '2')} / rank {field(row, 'duplicate_rank', '?')}
                </div>
              </div>

              <div className="mt-4 grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-4">
                <Detail label="Study" value={field(row, 'study_id', 'blank')} />
                <Detail label="Source size" value={numberLabel(field(row, 'source_size_bytes'))} />
                <Detail label="Source identity hash" value={field(row, 'source_sha256', 'blank')} />
                <Detail label="Source path" value={field(row, 'source_path', 'blank')} />
              </div>
            </article>
          ))}
          {duplicates.length > 50 && <p className="text-sm text-slate-500">Showing the first 50 duplicate capture rows.</p>}
        </div>
      )}
    </CollapsibleCard>
  )
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 break-all text-slate-300">{value}</p>
    </div>
  )
}
