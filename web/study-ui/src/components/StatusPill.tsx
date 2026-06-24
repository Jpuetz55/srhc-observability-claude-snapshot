export function StatusPill({ status }: { status?: string }) {
  const text = status || 'unknown'
  const normalized = text.toLowerCase()
  const style = normalized === 'complete' || normalized === 'ok' || normalized === 'ready' || normalized === 'trusted rtp found' || normalized === 'useful rtp capture'
    ? 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200'
    : normalized === 'failed' || normalized === 'error' || normalized === 'parse failed' || normalized.startsWith('high ')
      ? 'border-rose-400/40 bg-rose-400/10 text-rose-200'
      : normalized === 'running' || normalized === 'queued'
        ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200'
        : 'border-amber-400/40 bg-amber-400/10 text-amber-200'
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${style}`}>
      {text}
    </span>
  )
}
