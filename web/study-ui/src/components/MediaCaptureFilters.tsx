import type { StringRow } from '../api/types'

export type MediaCaptureFilterState = {
  status: 'all' | 'registered' | 'queued' | 'running' | 'complete' | 'failed'
  parseState: 'all' | 'success' | 'failed' | 'not_parsed'
  search: string
  sort: 'newest_capture' | 'newest_parsed' | 'largest_file' | 'most_streams' | 'most_rtp_qoe_streams' | 'most_dscp_mismatches'
}

export const DEFAULT_MEDIA_CAPTURE_FILTERS: MediaCaptureFilterState = {
  status: 'all',
  parseState: 'all',
  search: '',
  sort: 'newest_parsed'
}

const captureStatusOptions: Array<{ value: MediaCaptureFilterState['status']; label: string }> = [
  { value: 'all', label: 'All statuses' },
  { value: 'registered', label: 'Registered' },
  { value: 'queued', label: 'Queued' },
  { value: 'running', label: 'Running' },
  { value: 'complete', label: 'Complete' },
  { value: 'failed', label: 'Failed' }
]

const parseStateOptions: Array<{ value: MediaCaptureFilterState['parseState']; label: string }> = [
  { value: 'all', label: 'All parse states' },
  { value: 'success', label: 'Parse success' },
  { value: 'failed', label: 'Parse failed' },
  { value: 'not_parsed', label: 'Not parsed' }
]

const captureSortOptions: Array<{ value: MediaCaptureFilterState['sort']; label: string }> = [
  { value: 'newest_capture', label: 'Newest capture' },
  { value: 'newest_parsed', label: 'Newest parsed' },
  { value: 'largest_file', label: 'Largest file' },
  { value: 'most_streams', label: 'Most streams' },
  { value: 'most_rtp_qoe_streams', label: 'Most RTP QoE streams' },
  { value: 'most_dscp_mismatches', label: 'Most DSCP mismatches' }
]

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function numberValue(row: StringRow, key: string): number {
  const parsed = Number(field(row, key))
  return Number.isFinite(parsed) ? parsed : 0
}

function dateValue(row: StringRow, key: string): number {
  const value = field(row, key)
  if (!value) {
    return 0
  }
  const parsed = Date.parse(value.includes('T') ? value : value.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}

function boolState(value: string): 'success' | 'failed' | 'not_parsed' {
  if (value === 'true' || value === 't' || value === '1') {
    return 'success'
  }
  if (value === 'false' || value === 'f' || value === '0') {
    return 'failed'
  }
  return 'not_parsed'
}

export function filterAndSortMediaCaptures(captures: StringRow[], filters: MediaCaptureFilterState): StringRow[] {
  const query = filters.search.trim().toLowerCase()
  return captures
    .filter((capture) => {
      if (filters.status !== 'all' && field(capture, 'capture_status', 'registered').toLowerCase() !== filters.status) {
        return false
      }
      if (filters.parseState !== 'all' && boolState(field(capture, 'parse_success')) !== filters.parseState) {
        return false
      }
      if (!query) {
        return true
      }
      return ['source_name', 'capture_id', 'source_path'].some((key) => field(capture, key).toLowerCase().includes(query))
    })
    .sort((left, right) => {
      if (filters.sort === 'newest_capture') {
        return dateValue(right, 'capture_time') - dateValue(left, 'capture_time')
      }
      if (filters.sort === 'largest_file') {
        return numberValue(right, 'source_size_bytes') - numberValue(left, 'source_size_bytes')
      }
      if (filters.sort === 'most_streams') {
        return numberValue(right, 'stream_count') - numberValue(left, 'stream_count')
      }
      if (filters.sort === 'most_rtp_qoe_streams') {
        return numberValue(right, 'rtp_qoe_stream_count') - numberValue(left, 'rtp_qoe_stream_count')
      }
      if (filters.sort === 'most_dscp_mismatches') {
        return numberValue(right, 'dscp_mismatch_stream_count') - numberValue(left, 'dscp_mismatch_stream_count')
      }
      return Math.max(dateValue(right, 'parse_finished_at'), dateValue(right, 'parsed_at')) - Math.max(dateValue(left, 'parse_finished_at'), dateValue(left, 'parsed_at'))
    })
}

export function MediaCaptureFilters({
  filters,
  totalCount,
  resultCount,
  onChange
}: {
  filters: MediaCaptureFilterState
  totalCount: number
  resultCount: number
  onChange: (filters: MediaCaptureFilterState) => void
}) {
  const update = (patch: Partial<MediaCaptureFilterState>) => onChange({ ...filters, ...patch })
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/80">Capture Filters</p>
          <p className="mt-1 text-sm text-slate-400">{resultCount.toLocaleString()} of {totalCount.toLocaleString()} captures</p>
        </div>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(150px,0.7fr)_minmax(150px,0.7fr)_minmax(160px,0.8fr)_minmax(220px,1.2fr)]">
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Capture status</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.status} onChange={(event) => update({ status: event.target.value as MediaCaptureFilterState['status'] })}>
            {captureStatusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Parse success</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.parseState} onChange={(event) => update({ parseState: event.target.value as MediaCaptureFilterState['parseState'] })}>
            {parseStateOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Sort</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.sort} onChange={(event) => update({ sort: event.target.value as MediaCaptureFilterState['sort'] })}>
            {captureSortOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Search</span>
          <input className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600" value={filters.search} onChange={(event) => update({ search: event.target.value })} placeholder="source name, path, capture id" />
        </label>
      </div>
    </div>
  )
}
