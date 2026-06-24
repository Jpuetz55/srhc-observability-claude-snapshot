import type { StringRow } from '../api/types'
import { Card } from './Card'
import { RunStatusMessage } from './RunStatusMessage'

function formatDate(dateStr: string | undefined): string {
  if (!dateStr) return 'unknown'
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' })
  } catch {
    return dateStr
  }
}

function field(row: StringRow | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function formatSeconds(value: string | undefined, digits = 2): string {
  if (!value) return '—'
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return '—'
  return `${parsed.toFixed(digits)} s`
}

function formatWindowLabel(value: string | undefined): string {
  const parsed = Number(value)
  if (!value || !Number.isFinite(parsed) || parsed <= 0) return '±1 s'
  const text = Number.isInteger(parsed) ? String(parsed) : parsed.toFixed(2)
  return `±${text} s`
}

export function RunResultSummary({
  run,
  alignment
}: {
  run: StringRow
  alignment?: StringRow
}) {
  const runStatus = field(run, 'run_status', 'draft')
  const runError = field(run, 'run_execution_error')
  const badgeEventCount = parseInt(field(run, 'badge_event_count', '0'), 10)
  const surveyPointCount = parseInt(field(run, 'survey_point_count', '0'), 10)
  const candidateCount = parseInt(field(run, 'candidate_match_count', '0'), 10)
  const sameDateOverlapCount = parseInt(field(alignment, 'same_date_survey_point_count', '0'), 10)
  const matchedWithinWindowCount = parseInt(field(alignment, 'matched_survey_point_count', '0'), 10)
  const matchWindowLabel = formatWindowLabel(field(alignment, 'default_match_window_seconds') || field(run, 'default_match_window_seconds'))
  const hasNearestDeltas = Boolean(field(alignment, 'nearest_delta_min_seconds') || field(alignment, 'nearest_delta_p50_seconds'))

  // Determine if we should show the result summary
  if (runStatus === 'draft') {
    return null
  }

  return (
    <Card title="Run result summary" eyebrow="Execution diagnostics">
      <div className="space-y-4">
        {/* Status message */}
        <RunStatusMessage status={runStatus} error={runError} badgeEventCount={badgeEventCount} surveyPointCount={surveyPointCount} sameDateOverlapCount={sameDateOverlapCount} />

        {/* Parser summary */}
        {badgeEventCount > 0 || surveyPointCount > 0 || candidateCount > 0 ? (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
            <p className="text-sm font-semibold text-cyan-100 mb-3">Parser results</p>
            <div className="grid grid-cols-3 gap-3">
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Badge events</p>
                <p className="mt-2 text-2xl font-bold text-slate-100">{badgeEventCount}</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Survey points</p>
                <p className="mt-2 text-2xl font-bold text-slate-100">{surveyPointCount}</p>
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Candidate matches</p>
                <p className="mt-2 text-2xl font-bold text-slate-100">{candidateCount}</p>
              </div>
            </div>
          </div>
        ) : null}

        {/* Date alignment diagnostics */}
        {alignment ? (
          <div className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4 space-y-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="text-sm font-semibold text-cyan-100">Time alignment</p>
              <p className="text-xs text-slate-500">
                Match window <span className="font-mono text-slate-300">{matchWindowLabel}</span> · timestamp-proximity tolerance
              </p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-xs text-slate-400 uppercase tracking-wider">Badge time range</p>
                <p className="mt-2 text-sm text-slate-200 font-mono">
                  {field(alignment, 'badge_first_time') ? formatDate(field(alignment, 'badge_first_time')) : 'no data'}
                </p>
                {field(alignment, 'badge_last_time') && <p className="text-sm text-slate-300 font-mono">to {formatDate(field(alignment, 'badge_last_time'))}</p>}
              </div>
              <div>
                <p className="text-xs text-slate-400 uppercase tracking-wider">Ekahau time range</p>
                <p className="mt-2 text-sm text-slate-200 font-mono">
                  {field(alignment, 'ekahau_first_time') ? formatDate(field(alignment, 'ekahau_first_time')) : 'no data'}
                </p>
                {field(alignment, 'ekahau_last_time') && <p className="text-sm text-slate-300 font-mono">to {formatDate(field(alignment, 'ekahau_last_time'))}</p>}
              </div>
            </div>

            {/* Overlap status */}
            <div className="grid gap-3 md:grid-cols-2">
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Same-date overlap</p>
                <p className="mt-2 text-lg font-semibold text-slate-100">{field(alignment, 'same_date_survey_point_count', '0')} survey points</p>
                {sameDateOverlapCount === 0 && badgeEventCount > 0 && surveyPointCount > 0 && (
                  <p className="mt-2 text-sm text-amber-200">
                    No date overlap between badge ({field(alignment, 'badge_date_count', '0')} date{parseInt(field(alignment, 'badge_date_count', '0'), 10) === 1 ? '' : 's'}) and Ekahau ({field(alignment, 'ekahau_date_count', '0')} date{parseInt(field(alignment, 'ekahau_date_count', '0'), 10) === 1 ? '' : 's'}).
                  </p>
                )}
              </div>
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Within {matchWindowLabel}</p>
                <p className="mt-2 text-lg font-semibold text-slate-100">{matchedWithinWindowCount} survey points</p>
                {sameDateOverlapCount > 0 && matchedWithinWindowCount === 0 && (
                  <p className="mt-2 text-sm text-amber-200">
                    Same-date data exists, but no badge/Ekahau survey points are within the {matchWindowLabel} match window.
                  </p>
                )}
              </div>
            </div>

            {hasNearestDeltas && (
              <div className="rounded-xl border border-slate-700 bg-slate-900/50 p-3">
                <p className="text-xs text-slate-400 uppercase tracking-wider">Time alignment quality</p>
                <p className="mt-1 text-xs text-slate-500">Nearest badge-to-survey timestamp gap per Ekahau point (same local date). Smaller and tighter is better.</p>
                <div className="mt-2 grid grid-cols-3 gap-3">
                  <div>
                    <p className="text-xs text-slate-500">Closest</p>
                    <p className="mt-1 text-sm font-semibold text-slate-100">{formatSeconds(field(alignment, 'nearest_delta_min_seconds'), 3)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">Median</p>
                    <p className="mt-1 text-sm font-semibold text-slate-100">{formatSeconds(field(alignment, 'nearest_delta_p50_seconds'), 3)}</p>
                  </div>
                  <div>
                    <p className="text-xs text-slate-500">p90</p>
                    <p className="mt-1 text-sm font-semibold text-slate-100">{formatSeconds(field(alignment, 'nearest_delta_p90_seconds'), 3)}</p>
                  </div>
                </div>
              </div>
            )}

            {/* Next action guidance */}
            <div className="rounded-xl border border-cyan-400/30 bg-cyan-400/5 p-3">
              <p className="text-xs text-slate-400 uppercase tracking-wider">Next action</p>
              <p className="mt-2 text-sm text-cyan-100">
                {candidateCount === 0 && badgeEventCount === 0
                  ? 'Upload or select a badge log file containing scan events.'
                  : candidateCount === 0 && surveyPointCount === 0
                    ? 'Upload or select an Ekahau file containing survey points.'
                    : candidateCount === 0 && sameDateOverlapCount === 0
                      ? 'Update Ekahau file to include survey date(s) matching the badge data.'
                      : candidateCount === 0 && matchedWithinWindowCount === 0
                        ? `Use badge and Ekahau files with survey timestamps within the ${matchWindowLabel} match window.`
                      : candidateCount > 0
                        ? 'Review the timestamp-aligned candidates and save only the BSSID measured in Ekahau.'
                        : 'Review file dates and timestamp alignment.'}
              </p>
            </div>
          </div>
        ) : null}
      </div>
    </Card>
  )
}
