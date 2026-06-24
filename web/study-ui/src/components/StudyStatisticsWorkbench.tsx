import { useCallback, useEffect, useMemo, useState } from 'react'
import { listStudySamples } from '../api/client'
import type { SampleMetricStats, SampleStatistics, Study, StudySample } from '../api/types'
import { Button } from './Button'
import { Card } from './Card'

const emptyMetric: SampleMetricStats = {
  count: 0,
  mean: null,
  stddev: null,
  variance: null,
  min: null,
  max: null,
  range: null,
  p05: null,
  p25: null,
  p50: null,
  p75: null,
  p95: null,
  iqr: null,
  sem: null,
  ci95_low: null,
  ci95_high: null,
  outlier_count: 0
}

const emptyStatistics: SampleStatistics = { cal_delta: emptyMetric }

function fmt(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return '—'
  }
  return value.toFixed(digits)
}

function fmtRaw(value: string | number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || value === '') {
    return '—'
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed.toFixed(digits) : String(value)
}

function field(sample: StudySample, key: keyof StudySample, fallback = '—'): string {
  const value = sample[key]
  if (value === null || value === undefined || value === '') {
    return fallback
  }
  return String(value)
}

export function StudyStatisticsWorkbench({
  study,
  onError
}: {
  study: Study | null
  onError: (message: string | null) => void
  onToast: (message: string) => void
}) {
  const studyId = study?.study_id ?? null
  const [samples, setSamples] = useState<StudySample[]>([])
  const [statistics, setStatistics] = useState<SampleStatistics>(emptyStatistics)
  const [zThreshold, setZThreshold] = useState(2)
  const [loading, setLoading] = useState(false)
  const [error, setLocalError] = useState<string | null>(null)

  const load = useCallback(
    async (threshold: number) => {
      if (!studyId) {
        setSamples([])
        setStatistics(emptyStatistics)
        setLocalError(null)
        return
      }
      setLoading(true)
      try {
        const response = await listStudySamples(studyId, threshold)
        setSamples(response.samples ?? [])
        setStatistics(response.statistics ?? emptyStatistics)
        setLocalError(response.ok ? null : response.detail ?? response.error ?? 'Run statistics unavailable.')
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Failed to load completed run statistics.'
        setLocalError(message)
        onError(message)
      } finally {
        setLoading(false)
      }
    },
    [studyId, onError]
  )

  useEffect(() => {
    // Intentional: reload completed-match statistics when the study changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load(zThreshold)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [studyId])

  function changeThreshold(value: number) {
    if (!Number.isFinite(value) || value <= 0) {
      return
    }
    setZThreshold(value)
    void load(value)
  }

  const totalOutliers = useMemo(() => samples.filter((sample) => sample.is_outlier).length, [samples])

  if (!study) {
    return (
      <Card title="Completed run statistics" eyebrow="RF validation matches">
        <p className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
          Select or create a study, execute a run, then complete candidate rows to populate the Cal Delta statistics table.
        </p>
      </Card>
    )
  }

  return (
    <Card
      title="Completed run statistics"
      eyebrow="Cal Delta from parsed run matches"
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-xs font-medium text-slate-400">
            Outlier z &gt;
            <input
              type="number"
              step="0.5"
              min="0.5"
              className="w-16 rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-sm text-slate-100 outline-none ring-cyan-400/30 focus:ring-2"
              value={zThreshold}
              disabled={loading}
              onChange={(event) => changeThreshold(Number(event.target.value))}
            />
          </label>
          <Button variant="secondary" type="button" disabled={loading} onClick={() => void load(zThreshold)}>
            Refresh
          </Button>
        </div>
      }
    >
      <p className="text-sm text-slate-400">
        These statistics are calculated from the <span className="font-semibold text-slate-200">Cal Delta</span> field on completed
        RF-validation match rows in <span className="font-semibold text-slate-200">{study.study_name ?? study.study_id}</span>. A run is
        created from one Vocera badge log archive and one Ekahau <code className="text-cyan-200">.esx</code> survey. After the parser finds
        candidate matches and the rows are completed, the calibrated delta values feed this summary.
      </p>

      {error && <div className="mt-4 rounded-xl border border-amber-400/30 bg-amber-400/10 p-3 text-sm text-amber-100">{error}</div>}

      <StatisticsSummary statistics={statistics} sampleCount={samples.length} outliers={totalOutliers} zThreshold={zThreshold} />
      <SamplesTable samples={samples} loading={loading} />
    </Card>
  )
}

function StatisticsSummary({
  statistics,
  sampleCount,
  outliers,
  zThreshold
}: {
  statistics: SampleStatistics
  sampleCount: number
  outliers: number
  zThreshold: number
}) {
  const rows: Array<[string, (metric: SampleMetricStats) => string]> = [
    ['Count', (metric) => String(metric.count)],
    ['Mean', (metric) => fmt(metric.mean)],
    ['Std. dev.', (metric) => fmt(metric.stddev)],
    ['Variance', (metric) => fmt(metric.variance)],
    ['Std. error (SEM)', (metric) => fmt(metric.sem)],
    ['95% CI of mean', (metric) => (metric.ci95_low === null || metric.ci95_high === null ? '—' : `${fmt(metric.ci95_low)} – ${fmt(metric.ci95_high)}`)],
    ['Min', (metric) => fmt(metric.min)],
    ['p05', (metric) => fmt(metric.p05)],
    ['p25', (metric) => fmt(metric.p25)],
    ['Median (p50)', (metric) => fmt(metric.p50)],
    ['p75', (metric) => fmt(metric.p75)],
    ['p95', (metric) => fmt(metric.p95)],
    ['Max', (metric) => fmt(metric.max)],
    ['Range', (metric) => fmt(metric.range)],
    ['IQR', (metric) => fmt(metric.iqr)],
    ['Outliers', (metric) => String(metric.outlier_count ?? 0)]
  ]

  return (
    <div className="mt-5 overflow-hidden rounded-2xl border border-slate-800">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 bg-slate-950/70 px-4 py-3">
        <p className="text-sm font-semibold text-slate-100">Central-limit summary</p>
        <p className="text-xs text-slate-500">
          {sampleCount} completed match{sampleCount === 1 ? '' : 'es'} with Cal Delta · {outliers} outlier{outliers === 1 ? '' : 's'} · z &gt; {zThreshold}
        </p>
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-950/40 text-left text-xs uppercase tracking-[0.16em] text-slate-500">
            <th className="px-4 py-2 font-medium">Statistic</th>
            <th className="px-4 py-2 font-medium">Cal Delta (dB)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, accessor]) => (
            <tr key={label} className="border-t border-slate-800/60">
              <td className="px-4 py-2 text-slate-400">{label}</td>
              <td className="px-4 py-2 font-mono text-slate-100">{accessor(statistics.cal_delta)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function SamplesTable({ samples, loading }: { samples: StudySample[]; loading: boolean }) {
  if (loading) {
    return <p className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">Loading completed matches…</p>
  }

  if (!samples.length) {
    return (
      <p className="mt-6 rounded-2xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-500">
        No completed match rows with Cal Delta yet. Create/execute a run from a badge log archive and Ekahau .esx survey, then complete candidate rows in Manual survey entry.
      </p>
    )
  }

  return (
    <div className="mt-6 overflow-x-auto rounded-2xl border border-slate-800">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-slate-950/60 text-left text-xs uppercase tracking-[0.16em] text-slate-500">
            <th className="px-3 py-2 font-medium">#</th>
            <th className="px-3 py-2 font-medium">Run</th>
            <th className="px-3 py-2 font-medium">AP / BSSID</th>
            <th className="px-3 py-2 font-medium">Ch</th>
            <th className="px-3 py-2 font-medium">Badge RSSI</th>
            <th className="px-3 py-2 font-medium">Ekahau RSSI</th>
            <th className="px-3 py-2 font-medium">Ekahau SNR</th>
            <th className="px-3 py-2 font-medium">Cal Delta</th>
            <th className="px-3 py-2 font-medium">z(Delta)</th>
          </tr>
        </thead>
        <tbody>
          {samples.map((sample, index) => (
            <tr key={sample.sample_id} className={`border-t border-slate-800/60 ${sample.is_outlier ? 'bg-rose-500/10' : ''}`}>
              <td className="px-3 py-2 text-slate-500">{index + 1}</td>
              <td className="px-3 py-2 text-slate-200">{field(sample, 'run_name')}</td>
              <td className="px-3 py-2 text-slate-200">
                <div>{field(sample, 'ap_name')}</div>
                <div className="font-mono text-xs text-slate-500">{field(sample, 'bssid')}</div>
              </td>
              <td className="px-3 py-2 font-mono text-slate-400">{field(sample, 'channel')}</td>
              <td className="px-3 py-2 font-mono text-slate-100">{fmtRaw(sample.badge_rssi_dbm)}</td>
              <td className="px-3 py-2 font-mono text-slate-100">{fmtRaw(sample.ekahau_rssi_dbm)}</td>
              <td className="px-3 py-2 font-mono text-slate-100">{fmtRaw(sample.ekahau_snr_db)}</td>
              <td className={`px-3 py-2 font-mono ${sample.cal_delta_is_outlier ? 'font-semibold text-rose-300' : 'text-slate-100'}`}>
                {fmtRaw(sample.calibrated_delta_db)}
              </td>
              <td className="px-3 py-2 font-mono text-slate-400">{fmt(sample.cal_delta_z_score)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
