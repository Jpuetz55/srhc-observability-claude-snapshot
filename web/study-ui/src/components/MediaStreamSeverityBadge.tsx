import type { StringRow } from '../api/types'
import { getMediaStreamSeverity } from './mediaQoeSeverity'

const severityStyles = {
  critical: 'border-rose-400/50 bg-rose-400/10 text-rose-100',
  warning: 'border-amber-400/50 bg-amber-400/10 text-amber-100',
  good: 'border-emerald-400/50 bg-emerald-400/10 text-emerald-100',
  info: 'border-sky-400/50 bg-sky-400/10 text-sky-100',
  muted: 'border-slate-600 bg-slate-800/60 text-slate-400'
}

export function MediaStreamSeverityBadge({ stream }: { stream: StringRow }) {
  const severity = getMediaStreamSeverity(stream)
  return (
    <span
      className={`inline-flex max-w-full items-center rounded-full border px-2.5 py-1 text-xs font-semibold ${severityStyles[severity.level]}`}
      title={severity.reasons.join(', ')}
    >
      {severity.label}
    </span>
  )
}
