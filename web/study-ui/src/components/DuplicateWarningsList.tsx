import type { ProjectRfDuplicatesResponse, StringRow } from '../api/types'
import { CollapsibleCard } from './CollapsibleCard'

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function formatDecimal(value: string, digits = 1, suffix = ''): string {
  if (!value) {
    return ''
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return value
  }
  return `${parsed.toFixed(digits)}${suffix}`
}

function formatCentralTimestamp(value: string): string {
  if (!value) {
    return ''
  }
  const normalized = (value.includes('T') ? value : value.replace(' ', 'T'))
    .replace(/([+-]\d{2})$/, '$1:00')
    .replace(/([+-]\d{2})(\d{2})$/, '$1:$2')
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
    second: '2-digit',
    hourCycle: 'h23',
    timeZoneName: 'short'
  }).format(date)
}

function duplicateKey(row: StringRow): string {
  return [
    field(row, 'survey_time'),
    field(row, 'bssid').toLowerCase(),
    field(row, 'channel'),
    field(row, 'badge_mac').toLowerCase(),
    field(row, 'badge_rssi_dbm'),
    field(row, 'ekahau_rssi_dbm')
  ].join('|')
}

function groupedDuplicates(rows: StringRow[]): StringRow[][] {
  const groups = new Map<string, StringRow[]>()
  for (const row of rows) {
    const key = duplicateKey(row)
    groups.set(key, [...(groups.get(key) ?? []), row])
  }
  return [...groups.values()].map((items) => [...items].sort((a, b) => Number(field(a, 'duplicate_rank', '999')) - Number(field(b, 'duplicate_rank', '999'))))
}

export function DuplicateWarningsList({ duplicates, error }: { duplicates: ProjectRfDuplicatesResponse | null; error?: string | null }) {
  const rows = duplicates?.duplicates ?? []
  const groups = groupedDuplicates(rows)

  return (
    <CollapsibleCard title="Duplicate Warnings" eyebrow="Project-wide conflict review" defaultOpen={true}>
      <p className="mb-4 text-sm text-slate-400">
        Duplicate Warnings show where multiple studies in this project produced the same datapoint and which row the canonical result view keeps.
      </p>
      {error && <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}
      {!rows.length ? (
        <p className="rounded-xl border border-emerald-400/20 bg-emerald-400/10 p-4 text-sm text-emerald-100">No duplicate datapoints detected.</p>
      ) : (
        <div className="space-y-4">
          {groups.slice(0, 50).map((group) => {
            const kept = group.find((row) => field(row, 'duplicate_rank') === '1') ?? group[0]
            const others = group.filter((row) => row !== kept)
            return (
              <div key={duplicateKey(kept)} className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-4">
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <p className="text-sm font-semibold text-amber-100">Duplicate datapoint detected</p>
                    <p className="mt-1 text-sm text-slate-300">
                      {formatCentralTimestamp(field(kept, 'survey_time'))} · {field(kept, 'ap_name', 'Unnamed AP')} · {field(kept, 'bssid')}
                    </p>
                    <p className="mt-1 text-xs text-slate-500">
                      Channel {field(kept, 'channel', 'unknown')} · Badge {field(kept, 'badge_mac', 'unknown')} · Count {field(kept, 'duplicate_count', String(group.length))}
                    </p>
                  </div>
                  <div className="rounded-lg border border-amber-400/20 bg-slate-950/60 px-3 py-2 text-xs text-amber-100">{field(kept, 'duplicate_reason', 'duplicate project datapoint')}</div>
                </div>

                <DuplicateRow label="Kept canonical row" row={kept} />
                {others.map((row) => (
                  <DuplicateRow key={`${field(row, 'match_id')}-${field(row, 'duplicate_rank')}`} label="Also found" row={row} muted />
                ))}
              </div>
            )
          })}
          {groups.length > 50 && <p className="text-sm text-slate-500">Showing the first 50 duplicate groups. Narrow this project or inspect the raw API for the full list.</p>}
        </div>
      )}
    </CollapsibleCard>
  )
}

function DuplicateRow({ label, row, muted = false }: { label: string; row: StringRow; muted?: boolean }) {
  return (
    <div className={`mt-3 rounded-lg border border-slate-800 bg-slate-950/70 p-3 ${muted ? 'opacity-75' : ''}`}>
      <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{label}</p>
      <div className="mt-2 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-5">
        <Value label="Study" value={field(row, 'study_name', field(row, 'study_id'))} />
        <Value label="Run" value={field(row, 'run_name', field(row, 'test_run_id'))} />
        <Value label="Badge RSSI" value={formatDecimal(field(row, 'badge_rssi_dbm'), 1, ' dBm')} />
        <Value label="Ekahau RSSI" value={formatDecimal(field(row, 'ekahau_rssi_dbm'), 1, ' dBm')} />
        <Value label="Rank" value={field(row, 'duplicate_rank', '?')} />
      </div>
    </div>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-slate-200">{value || 'blank'}</p>
    </div>
  )
}
