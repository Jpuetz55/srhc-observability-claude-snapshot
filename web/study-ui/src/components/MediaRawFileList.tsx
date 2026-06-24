import { useMemo, useState } from 'react'
import type { MediaRawFile } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { getCaptureConcernBadges, getCaptureTrustedRtpBadge, getCaptureUsefulnessSummary } from './mediaQoeSeverity'
import { StatusPill } from './StatusPill'

function valueText(value: string | number | undefined, fallback = '0'): string {
  if (value === undefined || value === null || value === '') {
    return fallback
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toLocaleString() : String(value)
}

function formatBytes(value: string | number | undefined): string {
  const bytes = Number(value)
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return '0 B'
  }
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let scaled = bytes
  let index = 0
  while (scaled >= 1024 && index < units.length - 1) {
    scaled /= 1024
    index += 1
  }
  return `${scaled.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

function formatTimestamp(value: string | undefined): string {
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

export function MediaRawFileList({
  rawDir,
  files,
  loading,
  busy,
  error,
  executingCaptureId,
  onScan,
  onRegister,
  onRegisterSelected,
  onParse
}: {
  rawDir?: string
  files: MediaRawFile[]
  loading?: boolean
  busy?: boolean
  error?: string | null
  executingCaptureId?: string | null
  onScan: () => void
  onRegister: (file: MediaRawFile) => void
  onRegisterSelected: (files: MediaRawFile[]) => void
  onParse: (captureId: string, reparse: boolean) => void
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const selectedFiles = useMemo(
    () => files.filter((file) => selected.has(file.source_path) && !file.registered),
    [files, selected]
  )

  const toggle = (sourcePath: string) => {
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(sourcePath)) {
        next.delete(sourcePath)
      } else {
        next.add(sourcePath)
      }
      return next
    })
  }

  const registerSelected = () => {
    onRegisterSelected(selectedFiles)
    setSelected(new Set())
  }

  return (
    <CollapsibleCard
      title="Raw Capture Files"
      eyebrow={loading ? 'Scanning raw directory' : rawDir || 'Server raw directory'}
      defaultOpen={false}
      actions={
        <Button type="button" variant="secondary" disabled={loading || busy} onClick={(event) => { event.stopPropagation(); onScan() }}>
          {loading ? 'Scanning...' : 'Scan Raw Directory'}
        </Button>
      }
    >
      <div className="space-y-4">
        {error && <div className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</div>}
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" variant="secondary" disabled={!selectedFiles.length || loading || busy} onClick={registerSelected}>
            Register Selected
          </Button>
          <p className="text-sm text-slate-500">
            {files.length ? `${files.length.toLocaleString()} eligible file${files.length === 1 ? '' : 's'}` : 'No scan results loaded'}
          </p>
        </div>

        {!files.length ? (
          <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">
            Click Scan Raw Directory to list existing capture files on the server.
          </p>
        ) : (
          <div className="space-y-3">
            {files.map((file) => {
              const captureId = file.capture_id
              const parseBusy = executingCaptureId === captureId
              const usefulnessSummary = file.registered ? getCaptureUsefulnessSummary(file) : null
              const trustedRtpBadge = getCaptureTrustedRtpBadge(file)
              const concernBadges = getCaptureConcernBadges(file)
              return (
                <article key={file.source_path} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
                    <label className="flex min-w-0 gap-3">
                      <input
                        type="checkbox"
                        className="mt-1 h-4 w-4 rounded border-slate-700 bg-slate-900 text-cyan-400"
                        checked={selected.has(file.source_path)}
                        disabled={Boolean(file.registered) || loading || busy}
                        onChange={() => toggle(file.source_path)}
                      />
                      <span className="min-w-0">
                        <span className="flex flex-wrap items-center gap-2">
                          <span className="break-all text-sm font-semibold text-slate-100">{file.source_name}</span>
                          <StatusPill status={file.registered ? file.capture_status || 'registered' : 'unregistered'} />
                          {usefulnessSummary && <StatusPill status={usefulnessSummary.label} />}
                          {trustedRtpBadge && <StatusPill status={trustedRtpBadge.label} />}
                          {file.registered && concernBadges.map((badge) => <StatusPill key={badge.status} status={badge.label} />)}
                        </span>
                        <span className="mt-1 block break-all text-xs text-slate-500">{file.source_path}</span>
                        <span className="mt-2 block text-sm text-slate-400">
                          {formatBytes(file.source_size_bytes)} / Modified {formatTimestamp(file.source_mtime)}
                        </span>
                      </span>
                    </label>
                    <div className="flex flex-wrap gap-2">
                      {!file.registered && (
                        <Button type="button" variant="secondary" disabled={loading || busy} onClick={() => onRegister(file)}>
                          Register
                        </Button>
                      )}
                      {file.registered && captureId && (
                        <Button type="button" disabled={loading || busy || parseBusy} onClick={() => onParse(captureId, file.capture_status === 'complete')}>
                          {parseBusy ? 'Running...' : file.capture_status === 'complete' ? 'Reparse' : 'Parse'}
                        </Button>
                      )}
                    </div>
                  </div>
                  {file.registered && (
                    <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                      <Metric label="Capture ID" value={captureId || 'blank'} />
                      <Metric label="Streams" value={valueText(file.stream_count)} />
                      <Metric label="RTP QoE" value={valueText(file.rtp_qoe_stream_count)} />
                      <Metric label="Status" value={file.capture_status || 'registered'} />
                    </div>
                  )}
                </article>
              )
            })}
          </div>
        )}
      </div>
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
