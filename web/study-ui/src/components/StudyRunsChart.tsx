import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { StringRow } from '../api/types'

function toNumber(value: string | undefined): number {
  const parsed = Number(value ?? '0')
  return Number.isFinite(parsed) ? parsed : 0
}

function labelDate(value: string | undefined): string {
  if (!value) return 'unknown'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value.slice(0, 16)
  return parsed.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

export function StudyRunsChart({ runs }: { runs: StringRow[] }) {
  const data = [...runs]
    .reverse()
    .slice(-20)
    .map((run) => ({
      name: labelDate(run.created_at),
      candidates: toNumber(run.candidate_match_count),
      completed: toNumber(run.completed_match_count),
      manual: toNumber(run.manual_observation_count)
    }))

  if (!data.length) {
    return <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-6 text-sm text-slate-400">No run data yet.</div>
  }

  return (
    <div className="h-72 rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ left: 0, right: 14, top: 10, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148, 163, 184, 0.16)" />
          <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fill: '#94a3b8', fontSize: 12 }} tickLine={false} axisLine={false} allowDecimals={false} />
          <Tooltip contentStyle={{ background: '#020617', border: '1px solid #334155', borderRadius: 12, color: '#e2e8f0' }} />
          <Line type="monotone" dataKey="candidates" stroke="currentColor" className="text-cyan-300" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="completed" stroke="currentColor" className="text-emerald-300" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="manual" stroke="currentColor" className="text-violet-300" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
