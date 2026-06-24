import type { MediaQoeStreamReviewPayload, StringRow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { MediaStreamReview } from './MediaStreamReview'
import { MediaStreamSeverityBadge } from './MediaStreamSeverityBadge'
import { getMediaStreamDscpContext, streamKey } from './mediaQoeSeverity'
import { StatusPill } from './StatusPill'

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function decimal(value: string | undefined, digits = 2, suffix = ''): string {
  if (!value) {
    return 'blank'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${parsed.toFixed(digits)}${suffix}` : value
}

function integer(value: string | undefined): string {
  if (!value) {
    return '0'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString() : value
}

function percent(value: string | undefined): string {
  if (!value) {
    return 'blank'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? `${(parsed * 100).toFixed(2)}%` : value
}

function boolText(value: string | undefined): string {
  if (value === 'true' || value === 't' || value === '1') {
    return 'yes'
  }
  if (value === 'false' || value === 'f' || value === '0') {
    return 'no'
  }
  return value || 'unknown'
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
    second: '2-digit',
    timeZoneName: 'short'
  }).format(date)
}

export function MediaStreamList({
  streams,
  title,
  eyebrow,
  emptyMessage,
  reviewDisabled = false,
  onReviewSave,
  selectedStreamKey,
  onSelectStream,
  defaultOpen = true
}: {
  streams: StringRow[]
  title: string
  eyebrow: string
  emptyMessage: string
  reviewDisabled?: boolean
  onReviewSave?: (stream: StringRow, payload: MediaQoeStreamReviewPayload) => Promise<void>
  selectedStreamKey?: string | null
  onSelectStream?: (stream: StringRow | null) => void
  defaultOpen?: boolean
}) {
  const visibleStreams = streams.slice(0, 100)

  return (
    <CollapsibleCard title={title} eyebrow={eyebrow} defaultOpen={defaultOpen}>
      {!streams.length ? (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">{emptyMessage}</p>
      ) : (
        <div className="space-y-3">
          {visibleStreams.map((stream) => {
            const key = streamKey(stream)
            const selected = selectedStreamKey === key
            const dscpContext = getMediaStreamDscpContext(stream)
            return (
              <article key={key} className={`rounded-xl border p-4 ${selected ? 'border-cyan-400/50 bg-cyan-400/10' : 'border-slate-800 bg-slate-950/70'}`}>
                <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="break-all text-sm font-semibold text-slate-100">
                        {field(stream, 'src_ip')}:{field(stream, 'src_port')} -&gt; {field(stream, 'dst_ip')}:{field(stream, 'dst_port')}
                      </h3>
                      <MediaStreamSeverityBadge stream={stream} />
                      <StatusPill status={field(stream, 'review_status', 'unreviewed')} />
                    </div>
                    <p className="mt-1 text-xs text-slate-500">
                      {field(stream, 'source_name', field(stream, 'capture_id'))} / Stream {field(stream, 'stream_id')}
                    </p>
                    <p className="mt-2 text-sm text-slate-400">
                      {field(stream, 'measurement_mode', 'unknown mode')} / {field(stream, 'direction', 'unknown direction')} / {field(stream, 'device_role', 'unknown role')}
                    </p>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <div className="rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2 text-sm text-slate-300">
                      Accepted: <span className="font-semibold text-slate-100">{boolText(field(stream, 'accepted'))}</span>
                    </div>
                    {onSelectStream && (
                      <Button type="button" variant={selected ? 'primary' : 'secondary'} onClick={() => onSelectStream(selected ? null : stream)}>
                        {selected ? 'Selected stream' : 'Select stream'}
                      </Button>
                    )}
                  </div>
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                  <Metric label="Packets" value={integer(field(stream, 'packet_count'))} />
                  <Metric label="Payload" value={field(stream, 'payload_type', 'blank')} />
                  <Metric label="DSCP" value={field(stream, 'dscp', 'blank')} />
                  <Metric label="Loss" value={percent(field(stream, 'loss_ratio'))} />
                  <Metric label="Jitter" value={decimal(field(stream, 'jitter_ms'), 2, ' ms')} />
                  <Metric label="Interarrival P95" value={decimal(field(stream, 'interarrival_p95_ms'), 2, ' ms')} />
                </div>

                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
                  <Metric label="DSCP context" value={dscpContext ? dscpContext.label : 'No DSCP mismatch'} />
                  <Metric label="Lost packets" value={integer(field(stream, 'lost_packets'))} />
                  <Metric label="Duplicates" value={integer(field(stream, 'duplicate_packets'))} />
                  <Metric label="Out of order" value={integer(field(stream, 'out_of_order_packets'))} />
                  <Metric label="Classification" value={field(stream, 'stream_classification', 'unclassified')} />
                </div>

                <details className="mt-4 rounded-lg border border-slate-800 bg-slate-900/70 p-3">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-300">Stream details</summary>
                  <div className="mt-3 grid gap-3 text-sm md:grid-cols-2 xl:grid-cols-4">
                    <Detail label="SSRC" value={field(stream, 'ssrc', 'blank')} />
                    <Detail label="Sample time" value={formatTimestamp(field(stream, 'sample_time'))} />
                    <Detail label="First seen" value={formatTimestamp(field(stream, 'first_seen'))} />
                    <Detail label="Last seen" value={formatTimestamp(field(stream, 'last_seen'))} />
                    <Detail label="Server" value={field(stream, 'server', 'blank')} />
                    <Detail label="Device" value={field(stream, 'device_name', 'blank')} />
                    <Detail label="Peer device" value={field(stream, 'peer_device_name', 'blank')} />
                    <Detail label="Reviewed by" value={field(stream, 'reviewed_by', 'blank')} />
                  </div>
                </details>

                {onReviewSave && <MediaStreamReview stream={stream} disabled={reviewDisabled} onSave={(payload) => onReviewSave(stream, payload)} />}
              </article>
            )
          })}
          {streams.length > visibleStreams.length && <p className="text-sm text-slate-500">Showing the first {visibleStreams.length} of {streams.length} streams.</p>}
        </div>
      )}
    </CollapsibleCard>
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

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 break-all text-slate-300">{value}</p>
    </div>
  )
}
