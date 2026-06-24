import type { StringRow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { MediaParseRunList } from './MediaParseRunList'
import { StatusPill } from './StatusPill'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
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

export function MediaCaptureExecution({
  capture,
  parseRuns,
  loading,
  error,
  executing,
  onExecute
}: {
  capture: StringRow | null
  parseRuns: StringRow[]
  loading?: boolean
  error?: string | null
  executing?: boolean
  onExecute?: (capture: StringRow, reparse: boolean) => void
}) {
  const status = field(capture, 'capture_status', 'unknown')
  const canExecute = Boolean(capture && onExecute)
  const reparse = status === 'complete'

  return (
    <CollapsibleCard title="Capture Execution History" eyebrow="Parser execution" defaultOpen={false}>
      {!capture ? (
        <p className="rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">Select a capture to inspect parser execution history.</p>
      ) : (
        <div className="space-y-4">
          <div className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="break-all text-sm font-semibold text-slate-100">{field(capture, 'source_name', field(capture, 'capture_id'))}</h3>
                  <StatusPill status={status} />
                </div>
                <p className="mt-1 break-all text-xs text-slate-500">{field(capture, 'capture_id')}</p>
                <p className="mt-2 text-sm text-slate-400">
                  Started {formatTimestamp(field(capture, 'parse_started_at'))} / Finished {formatTimestamp(field(capture, 'parse_finished_at'))}
                </p>
                {field(capture, 'parse_error') && (
                  <details className="mt-3 rounded-lg border border-rose-400/30 bg-rose-400/10 p-3">
                    <summary className="cursor-pointer text-sm font-semibold text-rose-100">View Error</summary>
                    <pre className="mt-3 whitespace-pre-wrap break-words text-xs text-rose-100">{field(capture, 'parse_error')}</pre>
                  </details>
                )}
              </div>
              {canExecute && (
                <Button type="button" disabled={executing} onClick={() => onExecute?.(capture, reparse)}>
                  {executing ? 'Running...' : reparse ? 'Reparse' : 'Parse'}
                </Button>
              )}
            </div>
          </div>
          <MediaParseRunList parseRuns={parseRuns} loading={loading} error={error} />
        </div>
      )}
    </CollapsibleCard>
  )
}
