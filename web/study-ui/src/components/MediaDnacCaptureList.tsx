import type { MediaDnacCapture } from '../api/types'
import { Button } from './Button'
import { getCaptureConcernBadges, getCaptureTrustedRtpBadge, getCaptureUsefulnessSummary } from './mediaQoeSeverity'
import { StatusPill } from './StatusPill'

function formatBytes(value: number | null | undefined): string {
  const numeric = Number(value)
  if (!Number.isFinite(numeric) || numeric <= 0) {
    return 'unknown'
  }
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let scaled = numeric
  let index = 0
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024
    index += 1
  }
  return `${scaled.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function formatTimestamp(value: string | null | undefined): string {
  if (!value) {
    return 'blank'
  }
  const date = new Date(value)
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

function valueText(value: string | number | null | undefined, fallback = '0'): string {
  if (value === undefined || value === null || value === '') {
    return fallback
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString() : String(value)
}

export function MediaDnacCaptureList({
  captures,
  loading = false,
  error,
  rawDir,
  busyCaptureKey,
  executingCaptureId,
  onDownloadRegister,
  onParseRegistered,
  onOpenRegistered
}: {
  captures: MediaDnacCapture[]
  loading?: boolean
  error?: string | null
  rawDir?: string
  busyCaptureKey?: string | null
  executingCaptureId?: string | null
  onDownloadRegister?: (capture: MediaDnacCapture, parseAfterRegister: boolean) => void
  onParseRegistered?: (capture: MediaDnacCapture, reparse: boolean) => void
  onOpenRegistered?: (capture: MediaDnacCapture) => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-100">Completed ICAP captures</p>
          <p className="mt-1 text-sm text-slate-500">{rawDir || 'Raw directory not loaded'}</p>
        </div>
        <p className="text-sm text-slate-500">
          {loading ? 'Loading captures...' : `${captures.length.toLocaleString()} capture${captures.length === 1 ? '' : 's'}`}
        </p>
      </div>

      {error && <p className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}
      {!error && !loading && captures.length === 0 && (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">
          No completed ICAP captures loaded for this search.
        </p>
      )}

      {captures.length > 0 && (
        <div className="space-y-3">
          {captures.map((capture) => {
            const captureKey = capture.dnac_capture_id || capture.file_name
            const registeredCaptureId = capture.registered_capture_id || ''
            const downloaded = Boolean(capture.already_downloaded)
            const registeredHere = Boolean(capture.already_registered)
            const registeredElsewhere = Boolean(capture.registered_in_other_study)
            const parsed = Boolean(capture.already_parsed || capture.capture_status === 'complete')
            const usefulnessSummary = registeredHere ? getCaptureUsefulnessSummary(capture) : null
            const trustedRtpBadge = getCaptureTrustedRtpBadge(capture)
            const concernBadges = getCaptureConcernBadges(capture)
            const parseQueuedOrRunning = capture.capture_status === 'queued' || capture.capture_status === 'running'
            const downloadBusy = busyCaptureKey === captureKey
            const parseBusy = Boolean(registeredCaptureId && executingCaptureId === registeredCaptureId)
            const anyCaptureActionBusy = Boolean(busyCaptureKey || executingCaptureId)
            const downloadDisabled = loading || anyCaptureActionBusy || registeredHere || registeredElsewhere
            const parseDisabled = loading || anyCaptureActionBusy || !registeredCaptureId || parseQueuedOrRunning
            return (
              <article key={`${capture.dnac_capture_id || capture.file_name}-${capture.local_path || ''}`} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="break-all text-sm font-semibold text-slate-100">{capture.file_name}</span>
                      <StatusPill status={capture.capture_type || 'ICAP'} />
                      <StatusPill status={downloaded ? 'downloaded' : 'remote only'} />
                      <StatusPill status={registeredHere ? capture.capture_status || 'registered' : registeredElsewhere ? 'other study' : 'not registered'} />
                      {usefulnessSummary && <StatusPill status={usefulnessSummary.label} />}
                      {parsed && <StatusPill status="parsed" />}
                      {trustedRtpBadge && <StatusPill status={trustedRtpBadge.label} />}
                      {registeredHere && concernBadges.map((badge) => <StatusPill key={badge.status} status={badge.label} />)}
                    </div>
                    <p className="mt-2 break-all text-xs text-slate-500">{capture.local_path || 'No local path resolved'}</p>
                    {(onDownloadRegister || onParseRegistered || onOpenRegistered) && (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {!registeredHere && !registeredElsewhere && onDownloadRegister && (
                          <>
                            <Button type="button" variant="secondary" disabled={downloadDisabled} onClick={() => onDownloadRegister(capture, false)}>
                              {downloadBusy ? 'Downloading...' : 'Download + Register'}
                            </Button>
                            <Button type="button" disabled={downloadDisabled} onClick={() => onDownloadRegister(capture, true)}>
                              {downloadBusy ? 'Downloading...' : 'Download + Register + Parse'}
                            </Button>
                          </>
                        )}
                        {registeredHere && parsed && onOpenRegistered && (
                          <Button type="button" variant="secondary" disabled={loading || parseBusy || !registeredCaptureId} onClick={() => onOpenRegistered(capture)}>
                            Open Registered Capture
                          </Button>
                        )}
                        {registeredHere && onParseRegistered && (
                          <Button type="button" disabled={parseDisabled} onClick={() => onParseRegistered(capture, parsed)}>
                            {parseBusy || capture.capture_status === 'running' ? 'Running...' : parsed ? 'Reparse' : 'Parse Registered Capture'}
                          </Button>
                        )}
                        {registeredElsewhere && <p className="self-center text-xs text-amber-200">Registered in another study.</p>}
                      </div>
                    )}
                  </div>
                  <div className="grid gap-2 sm:grid-cols-2 xl:min-w-[520px]">
                    <Metric label="DNAC capture ID" value={capture.dnac_capture_id || 'blank'} breakWords />
                    <Metric label="Size" value={formatBytes(capture.file_size)} />
                    <Metric label="Created" value={formatTimestamp(capture.created_at)} />
                    <Metric label="Updated" value={formatTimestamp(capture.updated_at)} />
                    <Metric label="Client MAC" value={capture.client_mac || 'blank'} />
                    <Metric label="AP MAC" value={capture.ap_mac || 'blank'} />
                    <Metric label="Streams" value={valueText(capture.stream_count)} />
                    <Metric label="RTP QoE" value={valueText(capture.rtp_qoe_stream_count)} />
                  </div>
                </div>
              </article>
            )
          })}
        </div>
      )}
    </section>
  )
}

function Metric({ label, value, breakWords = false }: { label: string; value: string; breakWords?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-sm font-semibold text-slate-200 ${breakWords ? 'break-all' : 'truncate'}`}>{value}</p>
    </div>
  )
}
