import type { GrafanaPanelConfig } from '../api/types'

function missingPanelFields(config?: GrafanaPanelConfig | null): string[] {
  if (!config) {
    return ['dashboard UID', 'dashboard slug', 'panel ID']
  }
  const missing = []
  if (!config.dashboardUid) missing.push('dashboard UID')
  if (!config.slug) missing.push('dashboard slug')
  if (!config.panelId) missing.push('panel ID')
  return missing
}

export function GrafanaPanel({
  title,
  config,
  basePath,
  orgId,
  theme,
  from = 'now-6h',
  to = 'now',
  vars = {},
  variables = {}
}: {
  title: string
  config?: GrafanaPanelConfig | null
  basePath: string
  orgId: string
  theme: string
  from?: string
  to?: string
  vars?: Record<string, string | undefined>
  variables?: Record<string, string | undefined | null>
}) {
  const missing = [...(!basePath ? ['base path'] : []), ...missingPanelFields(config)]
  if (missing.length || !config) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-950/70 p-5 text-sm text-slate-400">
        <p className="font-semibold text-slate-200">{title}</p>
        <p className="mt-2">Grafana panel not configured.</p>
        <p className="mt-2 text-xs text-slate-500">Missing: {missing.join(', ')}</p>
      </div>
    )
  }

  const mergedVariables = { ...variables, ...vars }
  const params = new URLSearchParams({
    orgId,
    panelId: String(config.panelId),
    from,
    to,
    theme
  })
  const dashboardParams = new URLSearchParams({
    orgId,
    from,
    to,
    theme
  })
  for (const [key, value] of Object.entries(mergedVariables)) {
    if (value) params.set(`var-${key}`, value)
    if (value) dashboardParams.set(`var-${key}`, value)
  }
  const normalizedBasePath = basePath.replace(/\/$/, '')
  const src = `${normalizedBasePath}/d-solo/${encodeURIComponent(config.dashboardUid)}/${encodeURIComponent(config.slug)}?${params.toString()}`
  const dashboardUrl = `${normalizedBasePath}/d/${encodeURIComponent(config.dashboardUid)}/${encodeURIComponent(config.slug)}?${dashboardParams.toString()}`

  return (
    <div className="space-y-2">
      <iframe
        title={title}
        src={src}
        className="h-80 w-full rounded-2xl border border-slate-800 bg-slate-950"
        loading="lazy"
      />
      <div className="flex flex-wrap gap-3">
        <a className="inline-flex text-xs font-medium text-cyan-300 hover:text-cyan-200" href={dashboardUrl} target="_blank" rel="noreferrer">
          Open {title} dashboard
        </a>
        {mergedVariables.capture_id && (
          <a className="inline-flex text-xs font-medium text-cyan-300 hover:text-cyan-200" href={dashboardUrl} target="_blank" rel="noreferrer">
            Open selected capture context
          </a>
        )}
        {mergedVariables.stream_id && (
          <a className="inline-flex text-xs font-medium text-cyan-300 hover:text-cyan-200" href={dashboardUrl} target="_blank" rel="noreferrer">
            Open selected stream context
          </a>
        )}
        <a className="inline-flex text-xs font-medium text-cyan-300 hover:text-cyan-200" href={src} target="_blank" rel="noreferrer">
          Open panel URL
        </a>
      </div>
    </div>
  )
}
