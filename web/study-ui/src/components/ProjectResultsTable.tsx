import type { StringRow } from '../api/types'
import { CollapsibleCard } from './CollapsibleCard'

type ResultsMode = 'canonical' | 'raw'

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

export function ProjectResultsTable({ rows, mode, error }: { rows: StringRow[]; mode: ResultsMode; error?: string | null }) {
  const visibleRows = rows.slice(0, 100)

  return (
    <CollapsibleCard title={mode === 'canonical' ? 'Canonical Project Results' : 'Raw Project Results'} eyebrow="Completed project datapoints" defaultOpen={false}>
      <p className="mb-4 text-sm text-slate-400">
        {mode === 'canonical'
          ? 'Canonical rows are deduped project-wide completed matches. Use this as the default project-level output.'
          : 'Raw rows show every completed match before canonical deduplication. Use this for audits and duplicate investigations.'}
      </p>
      {error && <div className="mb-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}
      {!rows.length ? (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">No completed project results yet. Complete manual entries to populate project results.</p>
      ) : (
        <div className="space-y-3">
          {visibleRows.map((row) => (
            <article key={`${field(row, 'match_id')}-${field(row, 'canonical_rank')}`} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
              <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(260px,0.8fr)_minmax(260px,0.8fr)]">
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-slate-100">{field(row, 'ap_name', 'Unnamed AP')}</p>
                  <p className="mt-1 break-all font-mono text-xs text-slate-500">{field(row, 'bssid')}</p>
                  <p className="mt-2 text-sm text-slate-400">
                    {formatCentralTimestamp(field(row, 'survey_time'))} · Channel {field(row, 'channel', 'unknown')} · {field(row, 'band', 'unknown band')}
                  </p>
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Metric label="Badge RSSI" value={formatDecimal(field(row, 'badge_rssi_dbm'), 1, ' dBm')} />
                  <Metric label="Ekahau RSSI" value={formatDecimal(field(row, 'ekahau_rssi_dbm'), 1, ' dBm')} />
                  <Metric label="Expected Badge" value={formatDecimal(field(row, 'expected_badge_rssi_dbm'), 1, ' dBm')} />
                  <Metric label="Cal Delta" value={formatDecimal(field(row, 'calibrated_delta_db'), 1, ' dB')} />
                </div>

                <div className="grid grid-cols-2 gap-3">
                  <Metric label="Study" value={field(row, 'study_name', field(row, 'study_id'))} />
                  <Metric label="Run" value={field(row, 'run_name', field(row, 'test_run_id'))} />
                  <Metric label="Badge MAC" value={field(row, 'badge_mac', 'blank')} />
                  <Metric label="Dup Count" value={field(row, 'duplicate_count', '1')} />
                </div>
              </div>
            </article>
          ))}
          {rows.length > visibleRows.length && <p className="text-sm text-slate-500">Showing the first {visibleRows.length} of {rows.length} rows.</p>}
        </div>
      )}
    </CollapsibleCard>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value || 'blank'}</p>
    </div>
  )
}
