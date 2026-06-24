import { useEffect, useState } from 'react'
import { getGrafanaStatus } from '../api/client'
import type { GrafanaStatusResponse } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'
import { StatusPill } from './StatusPill'

function field(row: Record<string, string | undefined>, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

export function GrafanaDiagnostics() {
  const [status, setStatus] = useState<GrafanaStatusResponse | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)

  async function refresh() {
    setLoading(true)
    setError(null)
    try {
      setStatus(await getGrafanaStatus())
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    refresh()
  }, [])

  const grafana = status?.grafana
  const healthStatus = grafana ? field(grafana.upstream_health, 'status', 'unknown') : 'unknown'

  return (
    <CollapsibleCard title="Grafana Embed Diagnostics" eyebrow="Troubleshooting" defaultOpen={false}>
      <div className="space-y-4 text-sm">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={healthStatus} />
            <span className="text-slate-400">{grafana?.proxy_enabled ? 'Proxy enabled' : 'Proxy disabled'}</span>
          </div>
          <Button variant="secondary" disabled={loading} onClick={refresh}>
            {loading ? 'Refreshing...' : 'Refresh Diagnostics'}
          </Button>
        </div>

        {error && <p className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-3 text-rose-100">{error}</p>}

        {grafana && (
          <>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
              <Value label="Base path" value={grafana.base_path} />
              <Value label="Upstream" value={grafana.upstream ?? 'blank'} />
              <Value label="Org" value={grafana.org_id} />
              <Value label="Theme" value={grafana.theme} />
            </div>

            {field(grafana.upstream_health, 'detail') && (
              <p className="rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-amber-100">{field(grafana.upstream_health, 'detail')}</p>
            )}

            <div className="space-y-3">
              {Object.entries(grafana.panels).map(([key, panel]) => (
                <article key={key} className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <p className="font-semibold text-slate-100">{panel.name}</p>
                      <p className="mt-1 text-xs text-slate-500">{panel.config_key}</p>
                    </div>
                    <StatusPill status={panel.configured ? 'ok' : 'missing'} />
                  </div>
                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                    <Value label="UID" value={panel.dashboard_uid ?? 'blank'} />
                    <Value label="Slug" value={panel.dashboard_slug ?? 'blank'} />
                    <Value label="Panel" value={panel.panel_id ?? 'blank'} />
                  </div>
                  {panel.missing?.length ? <p className="mt-3 text-xs text-amber-200">Missing: {panel.missing.join(', ')}</p> : null}
                  {panel.invalid?.length ? <p className="mt-3 text-xs text-rose-200">Invalid: {panel.invalid.join(', ')}</p> : null}
                  {panel.url ? (
                    <a className="mt-3 inline-flex break-all text-xs font-medium text-cyan-300 hover:text-cyan-200" href={panel.url} target="_blank" rel="noreferrer">
                      {panel.url}
                    </a>
                  ) : null}
                </article>
              ))}
            </div>
          </>
        )}
      </div>
    </CollapsibleCard>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-1 break-all font-mono text-xs text-slate-300">{value || 'blank'}</p>
    </div>
  )
}
