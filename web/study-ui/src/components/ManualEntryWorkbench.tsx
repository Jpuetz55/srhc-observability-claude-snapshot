import type { FormEvent } from 'react'
import type { StringRow } from '../api/types'
import { Button } from './Button'
import { CollapsibleCard } from './CollapsibleCard'

export type ManualEntryDraft = {
  ekahau_rssi_dbm: string
  ekahau_snr_db: string
  notes: string
}

export type ManualEntryForm = {
  candidate_match_id: string
  match_id: string
  survey_point_id: string
  bssid: string
  survey_time: string
  ekahau_rssi_dbm: string
  ekahau_snr_db: string
  notes: string
}

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function formatDecimal(value: string, digits = 1, suffix = ''): string {
  if (!value) {
    return ''
  }
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) {
    return value
  }
  return `${parsed.toFixed(digits)}${suffix}`
}

function truthy(value: string): boolean {
  return ['1', 'true', 't', 'yes', 'y'].includes(value.trim().toLowerCase())
}

function formatCentralTimestamp(value: string): string {
  if (!value) {
    return ''
  }

  const normalized = (value.includes('T') ? value : value.replace(' ', 'T'))
    .replace(/([+-]\d{2})$/, '$1:00')
    .replace(/([+-]\d{2})(\d{2})$/, '$1:$2')
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) {
    return value
  }

  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/Chicago',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hourCycle: 'h23',
    timeZoneName: 'short'
  }).formatToParts(date)

  const pick = (type: string) => parts.find((part) => part.type === type)?.value ?? ''
  const millisecond = normalized.match(/\.(\d{1,6})/)?.[1]?.slice(0, 3).padEnd(3, '0')
  const suffix = millisecond ? `.${millisecond}` : ''

  return `${pick('year')}-${pick('month')}-${pick('day')} ${pick('hour')}:${pick('minute')}:${pick('second')}${suffix} ${pick('timeZoneName')}`
}

// Candidate matching is timestamp-only: a badge reading is a candidate for an
// Ekahau survey point when their timestamps fall within the match window. The
// quality states below grade only that time alignment so the reviewer can see
// whether a candidate is trustworthy before completing it.
type QualityState = 'clean' | 'ambiguous' | 'near_edge'

type CandidateQuality = {
  states: QualityState[]
  deltaSeconds: number | null
}

type CalDeltaSeverity = {
  label: 'Normal' | 'Review' | 'High concern' | 'Pending'
  tone: string
  title: string
}

const QUALITY_META: Record<QualityState, { label: string; tone: string; title: string }> = {
  clean: {
    label: 'Clean',
    tone: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
    title: 'One badge reading aligns to this survey point and the timestamp delta is comfortably inside the match window.'
  },
  ambiguous: {
    label: 'Ambiguous',
    tone: 'border-amber-400/40 bg-amber-400/10 text-amber-100',
    title: 'This badge reading is within the match window of more than one Ekahau survey point, so the timestamp alignment is not one-to-one.'
  },
  near_edge: {
    label: 'Near edge',
    tone: 'border-orange-400/40 bg-orange-400/10 text-orange-100',
    title: 'The timestamp delta is more than 80% of the match window — a small clock drift could drop this match.'
  }
}

function parseNumber(value: string | undefined): number | null {
  if (value === undefined || value === '') {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatSignedDelta(value: number | null): string {
  if (value === null) {
    return 'unknown'
  }
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(3)} s`
}

function formatWindow(windowSeconds: number): string {
  if (!Number.isFinite(windowSeconds) || windowSeconds <= 0) {
    return '±1 s'
  }
  const text = Number.isInteger(windowSeconds) ? String(windowSeconds) : windowSeconds.toFixed(2)
  return `±${text} s`
}

function getCalDeltaSeverity(value: string | undefined): CalDeltaSeverity {
  const parsed = parseNumber(value)
  if (parsed === null) {
    return {
      label: 'Pending',
      tone: 'border-slate-600 bg-slate-800 text-slate-300',
      title: 'Cal Delta severity is available after a completed match has a numeric Cal Delta.'
    }
  }

  const absolute = Math.abs(parsed)
  if (absolute > 10) {
    return {
      label: 'High concern',
      tone: 'border-rose-400/40 bg-rose-400/10 text-rose-100',
      title: '|Cal Delta| is greater than 10 dB.'
    }
  }
  if (absolute > 5) {
    return {
      label: 'Review',
      tone: 'border-amber-400/40 bg-amber-400/10 text-amber-100',
      title: '|Cal Delta| is greater than 5 dB.'
    }
  }
  return {
    label: 'Normal',
    tone: 'border-emerald-400/30 bg-emerald-400/10 text-emerald-100',
    title: '|Cal Delta| is 5 dB or less.'
  }
}

// Grade pending candidates. Ambiguity needs the whole set: the same badge
// reading (bssid + badge_time) matched to more than one survey point means the
// time alignment is not one-to-one.
function classifyCandidates(pending: StringRow[], windowSeconds: number): Map<string, CandidateQuality> {
  const surveyPointsByReading = new Map<string, Set<string>>()
  for (const row of pending) {
    const bssid = field(row, 'bssid').trim().toLowerCase()
    const badgeTime = field(row, 'badge_time').trim()
    const surveyPointId = field(row, 'survey_point_id').trim()
    if (!bssid || !badgeTime || !surveyPointId) {
      continue
    }
    const key = `${bssid}|${badgeTime}`
    const points = surveyPointsByReading.get(key) ?? new Set<string>()
    points.add(surveyPointId)
    surveyPointsByReading.set(key, points)
  }

  const nearEdgeThreshold = windowSeconds > 0 ? windowSeconds * 0.8 : null
  const result = new Map<string, CandidateQuality>()
  for (const row of pending) {
    const candidateId = field(row, 'candidate_match_id').trim()
    if (!candidateId) {
      continue
    }
    const delta = parseNumber(row.time_delta_seconds)
    const absDelta = delta === null ? null : Math.abs(delta)
    const key = `${field(row, 'bssid').trim().toLowerCase()}|${field(row, 'badge_time').trim()}`
    const sharedPoints = surveyPointsByReading.get(key)
    const states: QualityState[] = []
    if (sharedPoints && sharedPoints.size > 1) {
      states.push('ambiguous')
    }
    if (absDelta !== null && nearEdgeThreshold !== null && absDelta > nearEdgeThreshold) {
      states.push('near_edge')
    }
    if (states.length === 0) {
      states.push('clean')
    }
    result.set(candidateId, { states, deltaSeconds: delta })
  }
  return result
}

function QualityChip({ state }: { state: QualityState }) {
  const meta = QUALITY_META[state]
  return (
    <span title={meta.title} className={`rounded-full border px-2 py-0.5 text-xs font-semibold ${meta.tone}`}>
      {meta.label}
    </span>
  )
}

export function ManualEntryWorkbench({
  pending,
  completed,
  drafts,
  selectedCandidateId,
  form,
  busy,
  windowSeconds,
  onDraftChange,
  onSaveDraft,
  onSaveDraftAndNext,
  onSelectRow,
  onFormChange,
  onSubmitForm,
  onClearForm,
  onResetMatch
}: {
  pending: StringRow[]
  completed: StringRow[]
  drafts: Record<string, ManualEntryDraft>
  selectedCandidateId: string
  form: ManualEntryForm
  busy: boolean
  windowSeconds: number
  onDraftChange: (candidateMatchId: string, key: keyof ManualEntryDraft, value: string) => void
  onSaveDraft: (row: StringRow) => void
  onSaveDraftAndNext: (row: StringRow) => void
  onSelectRow: (row: StringRow) => void
  onFormChange: (key: keyof ManualEntryForm, value: string) => void
  onSubmitForm: (event: FormEvent) => void
  onClearForm: () => void
  onResetMatch: (matchId: string) => void
}) {
  const candidateQuality = classifyCandidates(pending, windowSeconds)
  return (
    <CollapsibleCard title="Complete candidate matches" eyebrow="Timestamp-aligned review queue" defaultOpen={true}>
      <div className="space-y-6">
        <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
          <p className="text-sm text-slate-300">
            Each pending row is a <span className="font-semibold text-slate-100">candidate generated by timestamp proximity only</span>: a
            badge reading whose timestamp is within <span className="font-mono text-cyan-100">{formatWindow(windowSeconds)}</span> of this
            Ekahau survey point. Complete a row by entering the Ekahau RSSI/SNR for the BSSID that Ekahau actually measured — each BSSID needs
            its own value.
          </p>
          <p className="mt-2 text-xs text-slate-500">
            BSSID, AP name, channel, RSSI and SNR are review context, not match criteria. Rows are sorted selected AP first, then badge score and badge RSSI.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="uppercase tracking-[0.14em] text-slate-500">Quality:</span>
            <QualityChip state="clean" />
            <QualityChip state="ambiguous" />
            <QualityChip state="near_edge" />
            <span className="text-slate-500">(hover a chip for its definition)</span>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span className="uppercase tracking-[0.14em] text-slate-500">Cal Delta severity:</span>
            <span className="rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-0.5 font-semibold text-emerald-100">
              Normal &lt;= 5 dB
            </span>
            <span className="rounded-full border border-amber-400/40 bg-amber-400/10 px-2 py-0.5 font-semibold text-amber-100">
              Review &gt; 5 dB
            </span>
            <span className="rounded-full border border-rose-400/40 bg-rose-400/10 px-2 py-0.5 font-semibold text-rose-100">
              High concern &gt; 10 dB
            </span>
          </div>

          {pending.length ? (
            <div className="mt-4 space-y-3">
              {pending.map((row) => {
                const candidateMatchId = field(row, 'candidate_match_id')
                const draft = drafts[candidateMatchId] ?? { ekahau_rssi_dbm: '', ekahau_snr_db: '', notes: '' }
                const isSelectedCandidate = truthy(field(row, 'badge_selected'))
                const quality = candidateQuality.get(candidateMatchId) ?? { states: ['clean'], deltaSeconds: parseNumber(row.time_delta_seconds) }
                return (
                  <CandidateCard
                    key={candidateMatchId}
                    row={row}
                    selected={selectedCandidateId === candidateMatchId}
                    selectedCandidate={isSelectedCandidate}
                    draft={draft}
                    busy={busy}
                    quality={quality}
                    windowSeconds={windowSeconds}
                    onDraftChange={(key, value) => onDraftChange(candidateMatchId, key, value)}
                    onSave={() => onSaveDraft(row)}
                    onSaveAndNext={() => onSaveDraftAndNext(row)}
                    onNotes={() => onSelectRow(row)}
                  />
                )
              })}
            </div>
          ) : (
            <div className="mt-4 rounded-xl border border-slate-800 bg-slate-950/70 p-4 text-sm text-slate-400">
              <p className="font-semibold text-slate-200">No candidate matches found.</p>
              <p className="mt-2">
                Candidates are generated by timestamp proximity only: a badge reading whose timestamp is within{' '}
                <span className="font-mono text-cyan-100">{formatWindow(windowSeconds)}</span> of an Ekahau survey point.
              </p>
              <ul className="mt-2 list-disc space-y-1 pl-5">
                <li>Verify the badge archive and Ekahau survey cover the same collection time.</li>
                <li>Check the badge vs Ekahau clock offset and the timezone used for parsing.</li>
                <li>Confirm the run executed without parser errors (see the run result summary below).</li>
                <li>If collection timing was loose, widen the match window in the validation config and re-run.</li>
              </ul>
            </div>
          )}
        </section>

        <ManualEntryEditForm form={form} busy={busy} onChange={onFormChange} onSubmit={onSubmitForm} onClear={onClearForm} />

        <section className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4">
          <div>
            <p className="text-sm font-semibold text-slate-100">Completed manual entries</p>
            <p className="mt-1 text-sm text-slate-500">Entries that have been saved and materialized into badge matches.</p>
          </div>

          {completed.length ? (
            <div className="mt-4 space-y-3">
              {completed.map((row) => (
                <CompletedEntryCard key={field(row, 'match_id')} row={row} busy={busy} onEdit={() => onSelectRow(row)} onReset={() => onResetMatch(field(row, 'match_id'))} />
              ))}
            </div>
          ) : (
            <p className="mt-4 text-sm text-slate-500">No completed manual entries are available for this run yet. Complete a candidate above to produce a Cal Delta value.</p>
          )}
        </section>
      </div>
    </CollapsibleCard>
  )
}

function CandidateCard({
  row,
  selected,
  selectedCandidate,
  draft,
  busy,
  quality,
  windowSeconds,
  onDraftChange,
  onSave,
  onSaveAndNext,
  onNotes
}: {
  row: StringRow
  selected: boolean
  selectedCandidate: boolean
  draft: ManualEntryDraft
  busy: boolean
  quality: CandidateQuality
  windowSeconds: number
  onDraftChange: (key: keyof ManualEntryDraft, value: string) => void
  onSave: () => void
  onSaveAndNext: () => void
  onNotes: () => void
}) {
  return (
    <article className={`rounded-xl border p-4 ${selected ? 'border-cyan-400/40 bg-cyan-400/10' : selectedCandidate ? 'border-emerald-400/30 bg-emerald-400/5' : 'border-slate-800 bg-slate-900/60'}`}>
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <MeasurementIdentity row={row} selectedCandidate={selectedCandidate} />
        <SignalGrid row={row} />
        <div className="grid gap-2 sm:grid-cols-[110px_110px_auto_auto_auto] xl:min-w-[560px]">
          <label className="text-xs font-medium text-slate-400">
            Ekahau RSSI
            <input
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 outline-none ring-cyan-400/30 focus:ring-2"
              value={draft.ekahau_rssi_dbm}
              disabled={busy}
              onChange={(event) => onDraftChange('ekahau_rssi_dbm', event.target.value)}
              placeholder="-65"
            />
          </label>
          <label className="text-xs font-medium text-slate-400">
            Ekahau SNR
            <input
              className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm text-slate-100 outline-none ring-cyan-400/30 focus:ring-2"
              value={draft.ekahau_snr_db}
              disabled={busy}
              onChange={(event) => onDraftChange('ekahau_snr_db', event.target.value)}
              placeholder="35"
            />
          </label>
          <Button className="self-end" disabled={busy || !draft.ekahau_rssi_dbm.trim()} onClick={onSave}>
            Save
          </Button>
          <Button className="self-end" variant="secondary" disabled={busy || !draft.ekahau_rssi_dbm.trim()} onClick={onSaveAndNext}>
            Save &amp; Next
          </Button>
          <Button className="self-end" variant="secondary" disabled={busy} onClick={onNotes}>
            Notes
          </Button>
        </div>
      </div>
      <MatchExplanation quality={quality} windowSeconds={windowSeconds} />
      <CandidateDetails row={row} />
    </article>
  )
}

function MatchExplanation({ quality, windowSeconds }: { quality: CandidateQuality; windowSeconds: number }) {
  return (
    <div className="mt-3 rounded-lg border border-cyan-400/20 bg-cyan-400/5 px-3 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-cyan-400/30 bg-cyan-400/10 px-2 py-0.5 text-xs font-semibold text-cyan-100">
          Timestamp-only match
        </span>
        {quality.states.map((state) => (
          <QualityChip key={state} state={state} />
        ))}
      </div>
      <p className="mt-2 text-xs text-slate-300">
        <span className="text-emerald-300">✓</span> Matched by timestamp proximity only — badge reading within{' '}
        <span className="font-mono text-cyan-100">{formatWindow(windowSeconds)}</span> of this Ekahau survey point. Actual delta{' '}
        <span className="font-mono text-cyan-100">{formatSignedDelta(quality.deltaSeconds)}</span>.
      </p>
    </div>
  )
}

function CompletedEntryCard({ row, busy, onEdit, onReset }: { row: StringRow; busy: boolean; onEdit: () => void; onReset: () => void }) {
  return (
    <article className="rounded-xl border border-slate-800 bg-slate-900/60 p-4">
      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
        <div className="min-w-0 space-y-3">
          <MeasurementIdentity row={row} selectedCandidate={truthy(field(row, 'badge_selected'))} />
          <CalDeltaSeverityBadge value={field(row, 'calibrated_delta_db')} />
        </div>
        <div className="grid gap-2 sm:grid-cols-2 xl:min-w-[360px]">
          <Metric label="Ekahau RSSI" value={formatDecimal(field(row, 'ekahau_rssi_dbm'), 1, ' dBm')} />
          <Metric label="Ekahau SNR" value={formatDecimal(field(row, 'ekahau_snr_db'), 1, ' dB')} />
          <Metric label="Expected" value={formatDecimal(field(row, 'expected_badge_rssi_dbm'), 1, ' dBm')} />
          <Metric label="Cal Delta" value={formatDecimal(field(row, 'calibrated_delta_db'), 1, ' dB')} />
          <Metric label="Time delta" value={formatSignedDelta(parseNumber(field(row, 'time_delta_seconds')))} />
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button variant="secondary" disabled={busy} onClick={onEdit}>
            Edit
          </Button>
          <Button variant="danger" disabled={busy} onClick={onReset}>
            Reset
          </Button>
        </div>
      </div>
      <CandidateDetails row={row} />
    </article>
  )
}

function CalDeltaSeverityBadge({ value }: { value: string }) {
  const severity = getCalDeltaSeverity(value)
  return (
    <span title={severity.title} className={`inline-flex rounded-full border px-2 py-1 text-xs font-semibold ${severity.tone}`}>
      Cal Delta severity: {severity.label}
    </span>
  )
}

function MeasurementIdentity({ row, selectedCandidate }: { row: StringRow; selectedCandidate: boolean }) {
  const band = field(row, 'band')
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className={selectedCandidate ? 'rounded-full border border-emerald-400/30 bg-emerald-400/10 px-2 py-1 text-xs font-semibold text-emerald-100' : 'rounded-full border border-slate-700 bg-slate-950 px-2 py-1 text-xs font-semibold text-slate-300'}>
          {selectedCandidate ? 'Selected AP' : 'Candidate'}
        </span>
        <span className="text-sm text-slate-300">{formatCentralTimestamp(field(row, 'survey_time'))}</span>
      </div>
      <p className="mt-2 font-semibold text-slate-100">{field(row, 'ap_name', 'Unnamed AP')}</p>
      <p className="mt-1 break-all font-mono text-xs text-slate-500">{field(row, 'bssid')}</p>
      <p className="mt-2 text-xs text-slate-500">
        Channel {field(row, 'channel', 'unknown')}{band ? ` · ${band}` : ''}
      </p>
    </div>
  )
}

function SignalGrid({ row }: { row: StringRow }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3 xl:min-w-[360px]">
      <Metric label="Badge RSSI" value={formatDecimal(field(row, 'badge_rssi_dbm'), 1, ' dBm')} />
      <Metric label="Badge SNR" value={formatDecimal(field(row, 'badge_snr_db'), 1, ' dB')} />
      <Metric label="Score" value={formatDecimal(field(row, 'badge_score'), 1)} />
    </div>
  )
}

function ManualEntryEditForm({
  form,
  busy,
  onChange,
  onSubmit,
  onClear
}: {
  form: ManualEntryForm
  busy: boolean
  onChange: (key: keyof ManualEntryForm, value: string) => void
  onSubmit: (event: FormEvent) => void
  onClear: () => void
}) {
  return (
    <form className="rounded-2xl border border-slate-800 bg-slate-950/70 p-4" onSubmit={onSubmit}>
      <div className="grid gap-4 md:grid-cols-2">
        <label className="block text-sm font-medium text-slate-300">
          Ekahau RSSI (dBm)
          <input
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={form.ekahau_rssi_dbm}
            disabled={!form.candidate_match_id || busy}
            onChange={(event) => onChange('ekahau_rssi_dbm', event.target.value)}
            placeholder="-65"
          />
        </label>
        <label className="block text-sm font-medium text-slate-300">
          Ekahau SNR (dB)
          <input
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={form.ekahau_snr_db}
            disabled={!form.candidate_match_id || busy}
            onChange={(event) => onChange('ekahau_snr_db', event.target.value)}
            placeholder="35"
          />
        </label>
      </div>

      <label className="mt-4 block text-sm font-medium text-slate-300">
        Notes
        <textarea
          className="mt-2 min-h-24 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
          value={form.notes}
          disabled={!form.candidate_match_id || busy}
          onChange={(event) => onChange('notes', event.target.value)}
        />
      </label>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button disabled={!form.candidate_match_id || busy}>Save Manual Entry</Button>
        <Button variant="secondary" type="button" disabled={busy} onClick={onClear}>
          Clear Selection
        </Button>
      </div>
      <p className="mt-3 text-sm text-slate-500">Select a pending row or edit an existing completed entry to keep it in sync with the correct Ekahau observation.</p>
    </form>
  )
}

function CandidateDetails({ row }: { row: StringRow }) {
  return (
    <details className="mt-3 rounded-lg border border-slate-800 bg-slate-950/70 p-3">
      <summary className="cursor-pointer text-sm font-medium text-slate-300">Measurement details</summary>
      <div className="mt-3 grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
        <Value label="Candidate ID" value={field(row, 'candidate_match_id')} />
        <Value label="Survey point" value={field(row, 'survey_point_id')} />
        <Value label="Status" value={field(row, 'manual_entry_status', 'pending')} />
        <Value label="Correlator quality" value={field(row, 'match_quality')} />
        <Value label="SNR source" value={field(row, 'badge_snr_source')} />
      </div>
    </details>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/80 px-3 py-2">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 truncate text-sm font-semibold text-slate-200">{value || 'blank'}</p>
    </div>
  )
}

function Value({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <p className="text-xs uppercase tracking-[0.14em] text-slate-500">{label}</p>
      <p className="mt-1 break-all text-slate-300">{value || 'blank'}</p>
    </div>
  )
}
