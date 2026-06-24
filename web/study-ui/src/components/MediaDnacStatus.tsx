import type { MediaDnacStatusResponse } from '../api/types'
import { Button } from './Button'
import { StatusPill } from './StatusPill'

function yesNo(value: boolean | null | undefined): string {
  if (value === null || value === undefined) {
    return 'not checked'
  }
  return value ? 'yes' : 'no'
}

function statusLabel(value: boolean | null | undefined, okText: string, badText: string): string {
  if (value === null || value === undefined) {
    return 'not checked'
  }
  return value ? okText : badText
}

export function MediaDnacStatus({
  status,
  loading = false,
  error,
  onRefresh
}: {
  status?: MediaDnacStatusResponse | null
  loading?: boolean
  error?: string | null
  onRefresh?: () => void
}) {
  return (
    <section className="space-y-3">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-sm font-semibold text-slate-100">DNAC/iCAP readiness</p>
          <p className="mt-1 text-sm text-slate-500">Catalyst Center checks stay server-side; credentials and tokens are never returned to the browser.</p>
        </div>
        {onRefresh && (
          <Button type="button" variant="secondary" disabled={loading} onClick={onRefresh}>
            {loading ? 'Checking...' : 'Check API'}
          </Button>
        )}
      </div>

      {error && <p className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{error}</p>}
      {!error && loading && !status && <p className="rounded-lg border border-slate-800 bg-slate-950/70 p-3 text-sm text-slate-500">Checking DNAC/iCAP status...</p>}

      {status && (
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <StatusPill status={status.configured ? 'configured' : 'missing config'} />
            <StatusPill status={status.auth_ok ? 'auth ok' : status.auth_ok === false ? 'auth failed' : 'auth not checked'} />
            <StatusPill status={status.capture_files_api_ok ? 'capture files api ok' : status.capture_files_api_ok === false ? 'capture files api failed' : 'capture files api not checked'} />
            <StatusPill status={status.download_enabled ? 'download enabled' : 'download disabled'} />
            <StatusPill status={status.start_capture_available ? 'start available' : 'start unavailable'} />
          </div>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Metric label="DNAC base URL configured" value={yesNo(status.base_url_configured)} />
            <Metric label="DNAC username configured" value={yesNo(status.username_configured)} />
            <Metric label="DNAC password configured" value={yesNo(status.password_configured)} />
            <Metric label="TLS verify" value={yesNo(status.tls_verify)} />
            <Metric label="Raw dir" value={status.raw_dir || 'blank'} breakWords />
            <Metric label="Raw dir readable" value={yesNo(status.raw_dir_readable)} />
            <Metric label="Default client MAC" value={status.default_client_mac || 'blank'} />
            <Metric label="Default capture type" value={status.default_capture_type || 'FULL'} />
            <Metric label="Client detail" value={statusLabel(status.client_detail_ok, 'ok', 'failed')} />
            <Metric label="Capture files API" value={statusLabel(status.capture_files_api_ok, 'ok', 'failed')} />
            <Metric label="Returned files" value={status.capture_files_returned === null || status.capture_files_returned === undefined ? 'not checked' : status.capture_files_returned.toLocaleString()} />
            <Metric label="ICAP start-capture" value={status.start_capture_unavailable_reason || (status.start_capture_available ? 'available' : 'intentionally unavailable')} breakWords />
            <Metric label="Resolved AP/WLC" value={status.resolved ? Object.values(status.resolved).filter(Boolean).join(' / ') || 'blank' : 'not checked'} breakWords />
          </div>

          {status.missing_config.length > 0 && (
            <p className="rounded-lg border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">
              Missing Catalyst Center config: {status.missing_config.join(', ')}
            </p>
          )}
          {status.error_summary && (
            <details className="rounded-lg border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">
              <summary className="cursor-pointer font-semibold">View DNAC/iCAP error</summary>
              <pre className="mt-3 whitespace-pre-wrap break-words text-xs">{status.error_summary}</pre>
            </details>
          )}
        </div>
      )}
    </section>
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
