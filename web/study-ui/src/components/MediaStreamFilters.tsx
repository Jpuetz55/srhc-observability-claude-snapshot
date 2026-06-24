import type { StringRow } from '../api/types'
import { MEDIA_QOE_THRESHOLDS, field, isTruthy, numberValue } from './mediaQoeSeverity'

export type MediaStreamFilterState = {
  selectedCaptureOnly: boolean
  reviewStatus: 'all' | 'unreviewed' | 'accepted' | 'excluded' | 'needs_review'
  classification: 'all' | 'vocera_rtp' | 'server_to_badge' | 'badge_to_server' | 'badge_to_badge' | 'non_rtp_udp' | 'unknown_udp' | 'control' | 'noise' | 'exclude'
  qoeFlag: 'all' | 'rtp_qoe' | 'dscp_mismatch' | 'lossy' | 'jitter_warning' | 'interarrival_warning'
  search: string
  sort: 'highest_loss' | 'highest_jitter' | 'highest_interarrival_p95' | 'most_packets' | 'newest_first'
}

export const DEFAULT_MEDIA_STREAM_FILTERS: MediaStreamFilterState = {
  selectedCaptureOnly: true,
  reviewStatus: 'all',
  classification: 'all',
  qoeFlag: 'all',
  search: '',
  sort: 'highest_loss'
}

const reviewStatusOptions: Array<{ value: MediaStreamFilterState['reviewStatus']; label: string }> = [
  { value: 'all', label: 'All review states' },
  { value: 'unreviewed', label: 'Unreviewed' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'excluded', label: 'Excluded' },
  { value: 'needs_review', label: 'Needs review' }
]

const classificationOptions: Array<{ value: MediaStreamFilterState['classification']; label: string }> = [
  { value: 'all', label: 'All classifications' },
  { value: 'vocera_rtp', label: 'Vocera RTP' },
  { value: 'server_to_badge', label: 'Server -> badge' },
  { value: 'badge_to_server', label: 'Badge -> server' },
  { value: 'badge_to_badge', label: 'Badge -> badge' },
  { value: 'non_rtp_udp', label: 'Non-RTP UDP' },
  { value: 'unknown_udp', label: 'Unknown UDP' },
  { value: 'control', label: 'Control' },
  { value: 'noise', label: 'Noise' },
  { value: 'exclude', label: 'Exclude' }
]

const qoeFlagOptions: Array<{ value: MediaStreamFilterState['qoeFlag']; label: string }> = [
  { value: 'all', label: 'All QoE flags' },
  { value: 'rtp_qoe', label: 'RTP QoE streams only' },
  { value: 'dscp_mismatch', label: 'DSCP mismatch only' },
  { value: 'lossy', label: 'Lossy only' },
  { value: 'jitter_warning', label: 'Jitter warning only' },
  { value: 'interarrival_warning', label: 'High interarrival P95 only' }
]

const sortOptions: Array<{ value: MediaStreamFilterState['sort']; label: string }> = [
  { value: 'highest_loss', label: 'Highest loss' },
  { value: 'highest_jitter', label: 'Highest jitter' },
  { value: 'highest_interarrival_p95', label: 'Highest interarrival P95' },
  { value: 'most_packets', label: 'Most packets' },
  { value: 'newest_first', label: 'Newest first' }
]

function metric(stream: StringRow, key: string): number {
  return numberValue(field(stream, key)) ?? 0
}

function dateMetric(stream: StringRow, key: string): number {
  const value = field(stream, key)
  if (!value) {
    return 0
  }
  const parsed = Date.parse(value.includes('T') ? value : value.replace(' ', 'T'))
  return Number.isFinite(parsed) ? parsed : 0
}

export function isTrustedRtpStream(stream: StringRow): boolean {
  return field(stream, 'measurement_mode').toLowerCase() === 'rtp'
}

export function isAdvancedMediaStream(stream: StringRow): boolean {
  return !isTrustedRtpStream(stream)
}

export function sortTrustedRtpStreams(streams: StringRow[]): StringRow[] {
  return streams.slice().sort((left, right) => (
    metric(right, 'loss_ratio') - metric(left, 'loss_ratio')
    || metric(right, 'jitter_ms') - metric(left, 'jitter_ms')
    || metric(right, 'interarrival_p95_ms') - metric(left, 'interarrival_p95_ms')
    || metric(right, 'packet_count') - metric(left, 'packet_count')
  ))
}

function hasQoeFlag(stream: StringRow, qoeFlag: MediaStreamFilterState['qoeFlag']): boolean {
  if (qoeFlag === 'all') {
    return true
  }
  if (qoeFlag === 'rtp_qoe') {
    return isTrustedRtpStream(stream) && metric(stream, 'packet_count') >= 20
  }
  if (qoeFlag === 'dscp_mismatch') {
    return isTruthy(field(stream, 'dscp_mismatch'))
  }
  if (qoeFlag === 'lossy') {
    return metric(stream, 'lost_packets') > 0 || metric(stream, 'loss_ratio') > 0
  }
  if (qoeFlag === 'jitter_warning') {
    return metric(stream, 'jitter_ms') >= MEDIA_QOE_THRESHOLDS.jitterWarningMs
  }
  return metric(stream, 'interarrival_p95_ms') >= MEDIA_QOE_THRESHOLDS.interarrivalWarningMs
}

export function filterAndSortMediaStreams(streams: StringRow[], filters: MediaStreamFilterState, selectedCaptureId?: string | null): StringRow[] {
  const query = filters.search.trim().toLowerCase()
  return streams
    .filter((stream) => {
      if (filters.selectedCaptureOnly && selectedCaptureId && field(stream, 'capture_id') !== selectedCaptureId) {
        return false
      }
      if (filters.reviewStatus !== 'all' && field(stream, 'review_status', 'unreviewed') !== filters.reviewStatus) {
        return false
      }
      if (filters.classification !== 'all' && field(stream, 'stream_classification') !== filters.classification) {
        return false
      }
      if (!hasQoeFlag(stream, filters.qoeFlag)) {
        return false
      }
      if (!query) {
        return true
      }
      return ['src_ip', 'dst_ip', 'src_port', 'dst_port', 'ssrc', 'stream_id'].some((key) => field(stream, key).toLowerCase().includes(query))
    })
    .sort((left, right) => {
      if (filters.sort === 'highest_jitter') {
        return metric(right, 'jitter_ms') - metric(left, 'jitter_ms')
      }
      if (filters.sort === 'highest_interarrival_p95') {
        return metric(right, 'interarrival_p95_ms') - metric(left, 'interarrival_p95_ms')
      }
      if (filters.sort === 'most_packets') {
        return metric(right, 'packet_count') - metric(left, 'packet_count')
      }
      if (filters.sort === 'newest_first') {
        return dateMetric(right, 'sample_time') - dateMetric(left, 'sample_time')
      }
      return metric(right, 'loss_ratio') - metric(left, 'loss_ratio')
    })
}

export function MediaStreamFilters({
  filters,
  selectedCaptureId,
  totalCount,
  resultCount,
  onChange
}: {
  filters: MediaStreamFilterState
  selectedCaptureId?: string | null
  totalCount: number
  resultCount: number
  onChange: (filters: MediaStreamFilterState) => void
}) {
  const update = (patch: Partial<MediaStreamFilterState>) => onChange({ ...filters, ...patch })
  const selectedCaptureFilterActive = Boolean(selectedCaptureId) && filters.selectedCaptureOnly
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-300/80">Stream Filters</p>
          <p className="mt-1 text-sm text-slate-400">{resultCount.toLocaleString()} of {totalCount.toLocaleString()} streams</p>
        </div>
        <label className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <input className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-cyan-400" type="checkbox" checked={selectedCaptureFilterActive} disabled={!selectedCaptureId} onChange={(event) => update({ selectedCaptureOnly: event.target.checked })} />
          {selectedCaptureId ? 'Selected capture only' : 'Select a capture to filter streams'}
        </label>
      </div>
      <div className="mt-4 grid gap-3 lg:grid-cols-3 xl:grid-cols-5">
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Review status</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.reviewStatus} onChange={(event) => update({ reviewStatus: event.target.value as MediaStreamFilterState['reviewStatus'] })}>
            {reviewStatusOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Classification</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.classification} onChange={(event) => update({ classification: event.target.value as MediaStreamFilterState['classification'] })}>
            {classificationOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">QoE flags</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.qoeFlag} onChange={(event) => update({ qoeFlag: event.target.value as MediaStreamFilterState['qoeFlag'] })}>
            {qoeFlagOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Sort</span>
          <select className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100" value={filters.sort} onChange={(event) => update({ sort: event.target.value as MediaStreamFilterState['sort'] })}>
            {sortOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Search</span>
          <input className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600" value={filters.search} onChange={(event) => update({ search: event.target.value })} placeholder="IP, port, SSRC, stream id" />
        </label>
      </div>
    </div>
  )
}
