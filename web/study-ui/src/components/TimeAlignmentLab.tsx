import type { ReactNode } from 'react'
import type { RfTimeAlignmentResponse, ToleranceSweepWindow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'

// Hand-rolled SVG (no chart dependency). Charts use a fixed viewBox and scale to
// width via className="w-full". Everything is derived live from the run's stored
// badge events and survey points — nothing here mutates the run.

function fmtSeconds(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—'
  }
  return `${value.toFixed(digits)} s`
}

function fmtSignedSeconds(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—'
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(digits)} s`
}

function scale(value: number, domainMin: number, domainMax: number, rangeMin: number, rangeMax: number): number {
  if (domainMax === domainMin) {
    return (rangeMin + rangeMax) / 2
  }
  const ratio = (value - domainMin) / (domainMax - domainMin)
  return rangeMin + ratio * (rangeMax - rangeMin)
}

function downsample(values: number[], max: number): number[] {
  if (values.length <= max) {
    return values
  }
  const step = values.length / max
  const out: number[] = []
  for (let i = 0; i < max; i += 1) {
    out.push(values[Math.floor(i * step)])
  }
  return out
}

type HistogramBin = { x0: number; x1: number; count: number }

function histogram(values: number[], domainMin: number, domainMax: number, binCount: number): HistogramBin[] {
  const bins: HistogramBin[] = Array.from({ length: binCount }, (_, i) => ({
    x0: domainMin + ((domainMax - domainMin) * i) / binCount,
    x1: domainMin + ((domainMax - domainMin) * (i + 1)) / binCount,
    count: 0
  }))
  if (domainMax === domainMin) {
    bins[0].count = values.length
    return bins
  }
  for (const value of values) {
    let index = Math.floor(((value - domainMin) / (domainMax - domainMin)) * binCount)
    if (index < 0) index = 0
    if (index >= binCount) index = binCount - 1
    bins[index].count += 1
  }
  return bins
}

export function TimeAlignmentLab({
  data,
  loading,
  error,
  busy,
  onApplyWindow,
  onReload
}: {
  data: RfTimeAlignmentResponse | null
  loading: boolean
  error: string | null
  busy: boolean
  onApplyWindow: (windowSeconds: number) => void
  onReload: () => void
}) {
  const sweep = data?.sweep
  const hasPoints = Boolean(sweep && sweep.survey_point_count_with_same_date_badge > 0)

  return (
    <CollapsibleCard title="Time Alignment Lab" eyebrow="Non-destructive tolerance preview" defaultOpen={false}>
      <div className="space-y-5">
        <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <p className="max-w-3xl text-sm text-slate-400">
            Candidate matching is timestamp-only. This previews how many survey points would match — and how clean those matches are — at
            different tolerances, computed straight from this run&apos;s stored badge events and Ekahau survey points. Nothing changes until you
            apply a window and re-run.
          </p>
          <Button variant="secondary" disabled={loading || busy} onClick={onReload}>
            {loading ? 'Loading…' : 'Refresh preview'}
          </Button>
        </div>

        {error && <div className="rounded-2xl border border-amber-400/30 bg-amber-400/10 p-4 text-sm text-amber-100">{error}</div>}

        {!error && loading && <p className="text-sm text-slate-500">Computing tolerance sweep…</p>}

        {!error && !loading && !hasPoints && (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
            <p className="font-semibold text-slate-200">No overlapping badge/Ekahau timestamps to preview.</p>
            <p className="mt-2">
              The Lab needs survey points whose nearest badge reading shares the same local date. Execute the run, and confirm the badge
              archive and Ekahau survey cover the same collection time.
            </p>
          </div>
        )}

        {!error && !loading && hasPoints && sweep && data && (
          <>
            <SweepSummary sweep={sweep} />
            <SensitivityTable
              windows={sweep.windows}
              currentWindow={data.current_window_seconds}
              busy={busy}
              onApplyWindow={onApplyWindow}
            />
            <div className="grid gap-5 xl:grid-cols-2">
              <ChartCard title="Tolerance sensitivity" hint="Matched survey points and ambiguous matches as the window widens. Look for the knee — where widening adds mostly ambiguity.">
                <SensitivityCurve windows={sweep.windows} currentWindow={data.current_window_seconds} />
              </ChartCard>
              <ChartCard title="Timestamp delta histogram" hint="Distribution of badge − survey timestamp deltas (nearest reading per point). A shifted center suggests a consistent collection offset.">
                <DeltaHistogram deltas={sweep.signed_deltas} currentWindow={data.current_window_seconds} />
              </ChartCard>
              <ChartCard title="Dual timeline" hint="Badge events (top) and Ekahau survey points (bottom) across the run's time range." wide>
                <DualTimeline timeline={data.timeline} />
              </ChartCard>
              <ChartCard title="Timestamp delta vs Cal Delta" hint="Completed matches only. If Cal Delta worsens as the timestamp gap grows, collection timing is polluting the result.">
                <CalDeltaScatter points={data.cal_delta_points} />
              </ChartCard>
            </div>
          </>
        )}
      </div>
    </CollapsibleCard>
  )
}

function SweepSummary({ sweep }: { sweep: NonNullable<RfTimeAlignmentResponse['sweep']> }) {
  const tiles: { label: string; value: string; hint: string }[] = [
    { label: 'Survey points (same-date)', value: String(sweep.survey_point_count_with_same_date_badge), hint: 'Points with a same-local-date badge reading.' },
    { label: 'Closest gap', value: fmtSeconds(sweep.abs_delta_min_seconds, 3), hint: 'Smallest nearest badge↔survey gap.' },
    { label: 'Median gap', value: fmtSeconds(sweep.abs_delta_median_seconds, 3), hint: 'Median nearest gap (|delta|).' },
    { label: 'p90 gap', value: fmtSeconds(sweep.abs_delta_p90_seconds, 3), hint: '90th percentile nearest gap.' },
    { label: 'Offset estimate', value: fmtSignedSeconds(sweep.signed_delta_median_seconds, 3), hint: 'Median signed delta (badge − survey). A consistent non-zero value suggests a clock/collection offset.' }
  ]
  return (
    <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-5">
      {tiles.map((tile) => (
        <div key={tile.label} title={tile.hint} className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
          <p className="text-xs uppercase tracking-wider text-slate-400">{tile.label}</p>
          <p className="mt-2 text-lg font-semibold text-slate-100">{tile.value}</p>
        </div>
      ))}
    </div>
  )
}

function SensitivityTable({
  windows,
  currentWindow,
  busy,
  onApplyWindow
}: {
  windows: ToleranceSweepWindow[]
  currentWindow: number
  busy: boolean
  onApplyWindow: (windowSeconds: number) => void
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-900/70 text-left text-xs uppercase tracking-wider text-slate-400">
          <tr>
            <th className="px-4 py-2">Window</th>
            <th className="px-4 py-2">Matched points</th>
            <th className="px-4 py-2">Near edge</th>
            <th className="px-4 py-2">Ambiguous</th>
            <th className="px-4 py-2 text-right">Action</th>
          </tr>
        </thead>
        <tbody>
          {windows.map((row) => {
            const isCurrent = row.window_seconds === currentWindow
            return (
              <tr key={row.window_seconds} className={isCurrent ? 'bg-cyan-400/5' : ''}>
                <td className="px-4 py-2 font-mono text-slate-100">
                  ±{row.window_seconds} s{isCurrent && <span className="ml-2 rounded-full border border-cyan-400/40 bg-cyan-400/10 px-2 py-0.5 text-xs text-cyan-100">current</span>}
                </td>
                <td className="px-4 py-2 text-slate-200">{row.matched_points}</td>
                <td className="px-4 py-2 text-orange-200">{row.near_edge_points}</td>
                <td className="px-4 py-2 text-amber-200">{row.ambiguous_points}</td>
                <td className="px-4 py-2 text-right">
                  <Button
                    variant={isCurrent ? 'secondary' : 'primary'}
                    disabled={busy || isCurrent}
                    onClick={() => onApplyWindow(row.window_seconds)}
                  >
                    {isCurrent ? 'Applied' : `Apply ±${row.window_seconds}s & re-run`}
                  </Button>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function ChartCard({ title, hint, wide, children }: { title: string; hint: string; wide?: boolean; children: ReactNode }) {
  return (
    <div className={`rounded-2xl border border-slate-800 bg-slate-950/70 p-4 ${wide ? 'xl:col-span-2' : ''}`}>
      <p className="text-sm font-semibold text-cyan-100">{title}</p>
      <p className="mt-1 text-xs text-slate-500">{hint}</p>
      <div className="mt-3">{children}</div>
    </div>
  )
}

function SensitivityCurve({ windows, currentWindow }: { windows: ToleranceSweepWindow[]; currentWindow: number }) {
  if (windows.length === 0) {
    return <p className="text-sm text-slate-500">No data.</p>
  }
  const W = 320
  const H = 130
  const padX = 30
  const padY = 16
  const maxCount = Math.max(1, ...windows.map((row) => row.matched_points))
  const xs = windows.map((_, i) => scale(i, 0, Math.max(1, windows.length - 1), padX, W - padX))
  const yFor = (count: number) => scale(count, 0, maxCount, H - padY, padY)

  const line = (key: 'matched_points' | 'ambiguous_points') =>
    windows.map((row, i) => `${xs[i].toFixed(1)},${yFor(row[key]).toFixed(1)}`).join(' ')

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Tolerance sensitivity curve">
        <line x1={padX} y1={H - padY} x2={W - padX} y2={H - padY} stroke="#334155" strokeWidth={1} />
        <line x1={padX} y1={padY} x2={padX} y2={H - padY} stroke="#334155" strokeWidth={1} />
        <polyline points={line('matched_points')} fill="none" stroke="#34d399" strokeWidth={2} />
        <polyline points={line('ambiguous_points')} fill="none" stroke="#fbbf24" strokeWidth={2} strokeDasharray="4 3" />
        {windows.map((row, i) => (
          <g key={row.window_seconds}>
            <circle cx={xs[i]} cy={yFor(row.matched_points)} r={row.window_seconds === currentWindow ? 4 : 2.5} fill="#34d399" />
            <text x={xs[i]} y={H - 4} textAnchor="middle" fontSize={8} fill="#94a3b8">±{row.window_seconds}</text>
          </g>
        ))}
        <text x={padX - 4} y={padY} textAnchor="end" fontSize={8} fill="#94a3b8">{maxCount}</text>
        <text x={padX - 4} y={H - padY} textAnchor="end" fontSize={8} fill="#94a3b8">0</text>
      </svg>
      <div className="mt-1 flex gap-4 text-xs text-slate-400">
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 bg-emerald-400" /> matched</span>
        <span className="flex items-center gap-1"><span className="inline-block h-2 w-3 bg-amber-400" /> ambiguous</span>
      </div>
    </div>
  )
}

function DeltaHistogram({ deltas, currentWindow }: { deltas: number[]; currentWindow: number }) {
  if (deltas.length === 0) {
    return <p className="text-sm text-slate-500">No deltas to plot.</p>
  }
  const W = 320
  const H = 130
  const padX = 24
  const padY = 14
  const rawMin = Math.min(...deltas)
  const rawMax = Math.max(...deltas)
  const domainMin = Math.min(rawMin, -currentWindow)
  const domainMax = Math.max(rawMax, currentWindow)
  const bins = histogram(deltas, domainMin, domainMax, 25)
  const maxCount = Math.max(1, ...bins.map((bin) => bin.count))
  const xFor = (value: number) => scale(value, domainMin, domainMax, padX, W - padX)
  const barWidth = Math.max(1, (W - 2 * padX) / bins.length - 1)

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Timestamp delta histogram">
        <line x1={padX} y1={H - padY} x2={W - padX} y2={H - padY} stroke="#334155" strokeWidth={1} />
        {bins.map((bin, i) => {
          const x = xFor(bin.x0)
          const h = scale(bin.count, 0, maxCount, 0, H - 2 * padY)
          return <rect key={i} x={x} y={H - padY - h} width={barWidth} height={h} fill="#22d3ee" opacity={0.8} />
        })}
        {/* zero line and ±window guides */}
        <line x1={xFor(0)} y1={padY} x2={xFor(0)} y2={H - padY} stroke="#64748b" strokeWidth={1} strokeDasharray="2 2" />
        <line x1={xFor(-currentWindow)} y1={padY} x2={xFor(-currentWindow)} y2={H - padY} stroke="#f87171" strokeWidth={1} />
        <line x1={xFor(currentWindow)} y1={padY} x2={xFor(currentWindow)} y2={H - padY} stroke="#f87171" strokeWidth={1} />
        <text x={xFor(-currentWindow)} y={padY - 3} textAnchor="middle" fontSize={8} fill="#fca5a5">−{currentWindow}s</text>
        <text x={xFor(currentWindow)} y={padY - 3} textAnchor="middle" fontSize={8} fill="#fca5a5">+{currentWindow}s</text>
        <text x={padX} y={H - 3} textAnchor="start" fontSize={8} fill="#94a3b8">{fmtSignedSeconds(domainMin, 1)}</text>
        <text x={W - padX} y={H - 3} textAnchor="end" fontSize={8} fill="#94a3b8">{fmtSignedSeconds(domainMax, 1)}</text>
      </svg>
      <p className="mt-1 text-xs text-slate-400">Red lines mark the current ±{currentWindow}s window; dashed line is zero delta.</p>
    </div>
  )
}

function DualTimeline({ timeline }: { timeline: RfTimeAlignmentResponse['timeline'] }) {
  const badge = timeline.badge_event_epochs
  const survey = timeline.survey_point_epochs
  if (badge.length === 0 && survey.length === 0) {
    return <p className="text-sm text-slate-500">No timeline data.</p>
  }
  const all = [...badge, ...survey]
  const t0 = timeline.window_start_epoch ?? Math.min(...all)
  const t1 = timeline.window_end_epoch ?? Math.max(...all)
  const W = 660
  const H = 90
  const padX = 12
  const badgeY = 26
  const surveyY = 64
  const xFor = (t: number) => scale(t, t0, t1, padX, W - padX)
  const badgePlot = downsample(badge, 900)
  const surveyPlot = downsample(survey, 900)

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Dual timeline of badge events and survey points">
        <text x={padX} y={badgeY - 10} fontSize={9} fill="#67e8f9">Badge events ({badge.length}{timeline.badge_truncated ? '+' : ''} of {timeline.badge_event_count} in overlap window)</text>
        {badgePlot.map((t, i) => (
          <line key={`b${i}`} x1={xFor(t)} y1={badgeY} x2={xFor(t)} y2={badgeY + 16} stroke="#22d3ee" strokeWidth={1} opacity={0.6} />
        ))}
        <text x={padX} y={surveyY - 10} fontSize={9} fill="#fcd34d">Ekahau survey points ({survey.length}{timeline.survey_truncated ? '+' : ''} of {timeline.survey_point_count} in overlap window)</text>
        {surveyPlot.map((t, i) => (
          <line key={`s${i}`} x1={xFor(t)} y1={surveyY} x2={xFor(t)} y2={surveyY + 16} stroke="#fbbf24" strokeWidth={1} opacity={0.7} />
        ))}
      </svg>
      <p className="mt-1 text-xs text-slate-500">
        Trimmed to the badge/survey overlap window{timeline.badge_truncated || timeline.survey_truncated ? ', and downsampled for display' : ''}.
      </p>
    </div>
  )
}

function CalDeltaScatter({ points }: { points: RfTimeAlignmentResponse['cal_delta_points'] }) {
  if (points.length === 0) {
    return <p className="text-sm text-slate-500">No completed matches yet — complete candidates to populate this.</p>
  }
  const W = 320
  const H = 150
  const padX = 32
  const padY = 16
  const xMax = Math.max(...points.map((p) => p.abs_time_delta_seconds), 0.001)
  const yMin = Math.min(...points.map((p) => p.calibrated_delta_db))
  const yMax = Math.max(...points.map((p) => p.calibrated_delta_db))
  const yLo = Math.min(yMin, 0)
  const yHi = Math.max(yMax, 0)
  const xFor = (v: number) => scale(v, 0, xMax, padX, W - padX)
  const yFor = (v: number) => scale(v, yLo, yHi, H - padY, padY)

  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Timestamp delta versus Cal Delta scatter">
        <line x1={padX} y1={H - padY} x2={W - padX} y2={H - padY} stroke="#334155" strokeWidth={1} />
        <line x1={padX} y1={padY} x2={padX} y2={H - padY} stroke="#334155" strokeWidth={1} />
        {yLo < 0 && yHi > 0 && <line x1={padX} y1={yFor(0)} x2={W - padX} y2={yFor(0)} stroke="#475569" strokeWidth={1} strokeDasharray="2 2" />}
        {points.map((p, i) => (
          <circle key={i} cx={xFor(p.abs_time_delta_seconds)} cy={yFor(p.calibrated_delta_db)} r={2.5} fill="#a78bfa" opacity={0.75} />
        ))}
        <text x={padX} y={H - 3} textAnchor="start" fontSize={8} fill="#94a3b8">0 s</text>
        <text x={W - padX} y={H - 3} textAnchor="end" fontSize={8} fill="#94a3b8">{fmtSeconds(xMax, 1)}</text>
        <text x={padX - 4} y={yFor(yHi)} textAnchor="end" fontSize={8} fill="#94a3b8">{yHi.toFixed(1)}</text>
        <text x={padX - 4} y={yFor(yLo)} textAnchor="end" fontSize={8} fill="#94a3b8">{yLo.toFixed(1)}</text>
      </svg>
      <p className="mt-1 text-xs text-slate-400">x: |timestamp delta| (s) · y: Cal Delta (dB)</p>
    </div>
  )
}
