import type { StringRow } from '../api/types'
import { field, getMediaStreamSeverity, isTruthy } from './mediaQoeSeverity'

function countBy(streams: StringRow[], predicate: (stream: StringRow) => boolean): number {
  return streams.reduce((count, stream) => count + (predicate(stream) ? 1 : 0), 0)
}

export function MediaTriageSummary({ streams }: { streams: StringRow[] }) {
  const unreviewed = countBy(streams, (stream) => field(stream, 'review_status', 'unreviewed') === 'unreviewed')
  const accepted = countBy(streams, (stream) => field(stream, 'review_status') === 'accepted')
  const needsReview = countBy(streams, (stream) => field(stream, 'review_status') === 'needs_review')
  const excluded = countBy(streams, (stream) => field(stream, 'review_status') === 'excluded')
  const dscpMismatch = countBy(streams, (stream) => isTruthy(field(stream, 'dscp_mismatch')))
  const lossWarnings = countBy(streams, (stream) => getMediaStreamSeverity(stream).reasons.some((reason) => reason.startsWith('Loss')))
  const timingWarnings = countBy(streams, (stream) => getMediaStreamSeverity(stream).reasons.some((reason) => reason.startsWith('Jitter') || reason.startsWith('Timing')))
  const critical = countBy(streams, (stream) => getMediaStreamSeverity(stream).level === 'critical')

  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-8">
      <Metric label="Unreviewed streams" value={unreviewed} />
      <Metric label="Accepted streams" value={accepted} />
      <Metric label="Needs review" value={needsReview} />
      <Metric label="Excluded" value={excluded} />
      <Metric label="Critical" value={critical} />
      <Metric label="DSCP mismatch" value={dscpMismatch} />
      <Metric label="Loss warnings" value={lossWarnings} />
      <Metric label="Timing warnings" value={timingWarnings} />
    </div>
  )
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value.toLocaleString()}</p>
    </div>
  )
}
