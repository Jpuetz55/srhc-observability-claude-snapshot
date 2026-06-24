import type { StringRow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { getCaptureConcernBadges, getCaptureTrustedRtpBadge, getCaptureUsefulnessSummary } from './mediaQoeSeverity'
import { StatusPill } from './StatusPill'

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function boolLabel(value: string | undefined): string {
  if (value === 'true' || value === 't' || value === '1') {
    return 'yes'
  }
  if (value === 'false' || value === 'f' || value === '0') {
    return 'no'
  }
  return value || 'unknown'
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

export function MediaCaptureList({
  captures,
  title,
  eyebrow,
  emptyMessage,
  selectedCaptureId,
  onSelectCapture,
  onExecuteCapture,
  executingCaptureId,
  defaultOpen = true
}: {
  captures: StringRow[]
  title: string
  eyebrow: string
  emptyMessage: string
  selectedCaptureId?: string | null
  onSelectCapture?: (captureId: string | null) => void
  onExecuteCapture?: (capture: StringRow, reparse: boolean) => void
  executingCaptureId?: string | null
  defaultOpen?: boolean
}) {
  const visibleCaptures = captures.slice(0, 100)

  return (
    <CollapsibleCard title={title} eyebrow={eyebrow} defaultOpen={defaultOpen}>
      {!captures.length ? (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">{emptyMessage}</p>
      ) : (
        <div className="space-y-3">
          {visibleCaptures.map((capture) => {
            const captureId = field(capture, 'capture_id')
            const selected = selectedCaptureId === captureId
            const status = field(capture, 'capture_status', 'unknown')
            const usefulnessSummary = getCaptureUsefulnessSummary(capture)
            const trustedRtpBadge = getCaptureTrustedRtpBadge(capture)
            const concernBadges = getCaptureConcernBadges(capture)
            const reparse = status === 'complete'
            const executing = executingCaptureId === captureId
            const execute = () => {
              onExecuteCapture?.(capture, reparse)
            }
            return (
              <article key={captureId} className={`rounded-xl border p-4 ${selected ? 'border-cyan-400/50 bg-cyan-400/10' : 'border-slate-800 bg-slate-950/70'}`}>
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="text-sm font-semibold text-slate-100">{field(capture, 'source_name', captureId || 'Unnamed capture')}</h3>
                      <StatusPill status={usefulnessSummary.label} />
                      <StatusPill status={status} />
                      {trustedRtpBadge && <StatusPill status={trustedRtpBadge.label} />}
                      {concernBadges.map((badge) => <StatusPill key={badge.status} status={badge.label} />)}
                    </div>
                    <p className="mt-1 text-xs text-slate-500">{captureId}</p>
                    <p className="mt-2 text-sm text-slate-400">
                      Captured {formatTimestamp(field(capture, 'capture_time'))} / Parsed {formatTimestamp(field(capture, 'parsed_at'))}
                    </p>
                    {field(capture, 'parse_error') && (
                      <details className="mt-2 rounded-lg border border-rose-400/30 bg-rose-400/10 p-2 text-sm text-rose-100">
                        <summary className="cursor-pointer font-semibold">View Error</summary>
                        <pre className="mt-2 whitespace-pre-wrap break-words text-xs">{field(capture, 'parse_error')}</pre>
                      </details>
                    )}
                  </div>

                  {(onSelectCapture || onExecuteCapture) && (
                    <div className="flex flex-wrap gap-2">
                      {onExecuteCapture && (
                        <Button type="button" disabled={executing || status === 'running' || status === 'queued'} onClick={execute}>
                          {executing || status === 'running' ? 'Running...' : reparse ? 'Reparse' : 'Parse'}
                        </Button>
                      )}
                      {onSelectCapture && (
                      <Button type="button" variant={selected ? 'primary' : 'secondary'} onClick={() => onSelectCapture(selected ? null : captureId)}>
                        {selected ? 'Showing streams' : 'View streams'}
                      </Button>
                      )}
                    </div>
                  )}
                </div>

                <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-6">
                  <Metric label="Parse success" value={boolLabel(field(capture, 'parse_success'))} />
                  <Metric label="Packets read" value={numberLabel(field(capture, 'packets_read'))} />
                  <Metric label="UDP packets" value={numberLabel(field(capture, 'udp_packets_seen'))} />
                  <Metric label="Streams" value={numberLabel(field(capture, 'stream_count'))} />
                  <Metric label="RTP QoE" value={numberLabel(field(capture, 'rtp_qoe_stream_count'))} />
                  <Metric label="DSCP mismatch" value={numberLabel(field(capture, 'dscp_mismatch_stream_count'))} />
                </div>
                <div className="mt-3 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                  <Metric label="Parse started" value={formatTimestamp(field(capture, 'parse_started_at'))} />
                  <Metric label="Parse finished" value={formatTimestamp(field(capture, 'parse_finished_at'))} />
                  <Metric label="Duration seconds" value={field(capture, 'parse_duration_seconds', 'blank')} />
                </div>

                <details className="mt-4 rounded-lg border border-slate-800 bg-slate-900/70 p-3">
                  <summary className="cursor-pointer text-sm font-semibold text-slate-300">Source details</summary>
                  <div className="mt-3 grid gap-3 text-sm md:grid-cols-2">
                    <Detail label="Source path" value={field(capture, 'source_path', 'blank')} />
                    <Detail label="Source identity hash" value={field(capture, 'source_sha256', 'blank')} />
                    <Detail label="Source size" value={numberLabel(field(capture, 'source_size_bytes'))} />
                    <Detail label="Capture point" value={field(capture, 'capture_point', 'blank')} />
                    <Detail label="Site" value={field(capture, 'site', 'blank')} />
                  </div>
                </details>
              </article>
            )
          })}
          {captures.length > visibleCaptures.length && <p className="text-sm text-slate-500">Showing the first {visibleCaptures.length} of {captures.length} captures.</p>}
        </div>
      )}
    </CollapsibleCard>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
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
