import type { MediaExecutionStatusResponse } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { StatusPill } from './StatusPill'

function byteLabel(value: number): string {
  if (!Number.isFinite(value)) {
    return 'unknown'
  }
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let size = value
  let unit = 0
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024
    unit += 1
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`
}

function yesNo(value: boolean): string {
  return value ? 'yes' : 'no'
}

export function MediaExecutionStatus({
  status,
  loading = false,
  error,
  onRefresh
}: {
  status?: MediaExecutionStatusResponse | null
  loading?: boolean
  error?: string | null
  onRefresh?: () => void
}) {
  return (
    <CollapsibleCard
      title="Media QoE Execution Guardrails"
      eyebrow="Operator Status"
      defaultOpen={false}
      actions={onRefresh && (
        <Button type="button" variant="secondary" disabled={loading} onClick={(event) => {
          event.stopPropagation()
          onRefresh()
        }}>
          {loading ? 'Refreshing...' : 'Refresh'}
        </Button>
      )}
    >
      {error && <p className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}
      {!error && loading && !status && <p className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-sm text-slate-500">Loading execution guardrails...</p>}
      {status && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <StatusPill status={status.execution_enabled ? 'execution enabled' : 'execution disabled'} />
            <StatusPill status={status.archive_enabled ? 'archive enabled' : 'archive disabled'} />
            <StatusPill status={status.raw_dir_readable ? 'raw dir readable' : 'raw dir blocked'} />
            <StatusPill status={status.parse_running ? 'parse running' : 'no active parse'} />
          </div>
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="Raw dir" value={status.raw_dir} breakWords />
            <Metric label="Allowed extensions" value={status.allowed_extensions.join(', ')} />
            <Metric label="Max scan files" value={status.max_scan_files.toLocaleString()} />
            <Metric label="Max parse size" value={byteLabel(status.max_parse_bytes)} />
            <Metric label="Parse timeout" value={`${status.parse_timeout_seconds.toLocaleString()} sec`} />
            <Metric label="Raw dir exists" value={yesNo(status.raw_dir_exists)} />
            <Metric label="Raw dir readable" value={yesNo(status.raw_dir_readable)} />
            <Metric label="Archive enabled" value={yesNo(status.archive_enabled)} />
            <Metric label="Parse running" value={yesNo(Boolean(status.parse_running))} />
            <Metric label="Active capture" value={String(status.active_parse?.capture_id || 'none')} breakWords />
            <Metric label="Active parse run" value={String(status.active_parse?.parse_run_id || 'none')} breakWords />
            <Metric label="Lock expires" value={String(status.active_parse?.expires_at || 'none')} />
          </div>
        </div>
      )}
    </CollapsibleCard>
  )
}

function Metric({ label, value, breakWords = false }: { label: string; value: string; breakWords?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg border border-slate-800 bg-slate-950/70 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-sm font-semibold text-slate-200 ${breakWords ? 'break-all' : 'truncate'}`}>{value}</p>
    </div>
  )
}
