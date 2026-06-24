import { useEffect, useState } from 'react'
import type { MediaQoeStreamReviewPayload, MediaStreamClassification, MediaStreamReviewStatus, StringRow } from '../api/types'
import { Button } from './Button'

const CLASSIFICATIONS: Array<{ value: MediaStreamClassification; label: string }> = [
  { value: 'vocera_rtp', label: 'Vocera RTP' },
  { value: 'server_to_badge', label: 'Server to badge' },
  { value: 'badge_to_server', label: 'Badge to server' },
  { value: 'badge_to_badge', label: 'Badge to badge' },
  { value: 'non_rtp_udp', label: 'Non-RTP UDP' },
  { value: 'unknown_udp', label: 'Unknown UDP' },
  { value: 'control', label: 'Control' },
  { value: 'noise', label: 'Noise' },
  { value: 'exclude', label: 'Exclude' }
]

const REVIEW_STATUSES: Array<{ value: MediaStreamReviewStatus; label: string }> = [
  { value: 'unreviewed', label: 'Unreviewed' },
  { value: 'accepted', label: 'Accepted' },
  { value: 'excluded', label: 'Excluded' },
  { value: 'needs_review', label: 'Needs review' }
]

function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

function boolState(value: string | undefined): 'true' | 'false' | 'unset' {
  if (value === 'true' || value === 't' || value === '1') {
    return 'true'
  }
  if (value === 'false' || value === 'f' || value === '0') {
    return 'false'
  }
  return 'unset'
}

function acceptedValue(value: 'true' | 'false' | 'unset'): boolean | null {
  if (value === 'true') {
    return true
  }
  if (value === 'false') {
    return false
  }
  return null
}

export function MediaStreamReview({
  stream,
  disabled = false,
  onSave
}: {
  stream: StringRow
  disabled?: boolean
  onSave: (payload: MediaQoeStreamReviewPayload) => Promise<void>
}) {
  const [accepted, setAccepted] = useState<'true' | 'false' | 'unset'>(boolState(field(stream, 'accepted')))
  const [reviewStatus, setReviewStatus] = useState<MediaStreamReviewStatus>((field(stream, 'review_status', 'unreviewed') as MediaStreamReviewStatus) || 'unreviewed')
  const [classification, setClassification] = useState<MediaStreamClassification | ''>((field(stream, 'stream_classification') as MediaStreamClassification | '') || '')
  const [notes, setNotes] = useState(field(stream, 'review_notes'))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setAccepted(boolState(field(stream, 'accepted')))
    setReviewStatus((field(stream, 'review_status', 'unreviewed') as MediaStreamReviewStatus) || 'unreviewed')
    setClassification((field(stream, 'stream_classification') as MediaStreamClassification | '') || '')
    setNotes(field(stream, 'review_notes'))
    setError(null)
  }, [stream])

  const save = async () => {
    try {
      setSaving(true)
      setError(null)
      await onSave({
        accepted: acceptedValue(accepted),
        review_status: reviewStatus,
        stream_classification: classification || null,
        review_notes: notes.trim() ? notes.trim() : null
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save review')
    } finally {
      setSaving(false)
    }
  }

  const quickSave = async (payload: MediaQoeStreamReviewPayload) => {
    try {
      setSaving(true)
      setError(null)
      await onSave(payload)
      if ('accepted' in payload) {
        setAccepted(payload.accepted === true ? 'true' : payload.accepted === false ? 'false' : 'unset')
      }
      if (payload.review_status) {
        setReviewStatus(payload.review_status)
      }
      if ('stream_classification' in payload) {
        setClassification((payload.stream_classification ?? '') as MediaStreamClassification | '')
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to save review')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="flex flex-wrap gap-2">
        <Button type="button" variant={reviewStatus === 'accepted' && classification === 'vocera_rtp' ? 'primary' : 'secondary'} disabled={disabled || saving} onClick={() => quickSave({ accepted: true, review_status: 'accepted', stream_classification: 'vocera_rtp' })}>
          Accept as Vocera RTP
        </Button>
        <Button type="button" variant={classification === 'server_to_badge' ? 'primary' : 'secondary'} disabled={disabled || saving} onClick={() => quickSave({ accepted: true, review_status: 'accepted', stream_classification: 'server_to_badge' })}>
          Mark server -&gt; badge
        </Button>
        <Button type="button" variant={classification === 'badge_to_server' ? 'primary' : 'secondary'} disabled={disabled || saving} onClick={() => quickSave({ accepted: true, review_status: 'accepted', stream_classification: 'badge_to_server' })}>
          Mark badge -&gt; server
        </Button>
        <Button type="button" variant={reviewStatus === 'needs_review' ? 'primary' : 'secondary'} disabled={disabled || saving} onClick={() => quickSave({ accepted: null, review_status: 'needs_review', stream_classification: classification || null })}>
          Needs review
        </Button>
        <Button type="button" variant={reviewStatus === 'excluded' && classification === 'noise' ? 'danger' : 'secondary'} disabled={disabled || saving} onClick={() => quickSave({ accepted: false, review_status: 'excluded', stream_classification: 'noise' })}>
          Exclude as noise
        </Button>
      </div>

      <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(180px,0.7fr)_minmax(180px,0.7fr)_minmax(0,1.6fr)_auto] lg:items-end">
        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Review status</span>
          <select
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={reviewStatus}
            disabled={disabled || saving}
            onChange={(event) => setReviewStatus(event.target.value as MediaStreamReviewStatus)}
          >
            {REVIEW_STATUSES.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Classification</span>
          <select
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100"
            value={classification}
            disabled={disabled || saving}
            onChange={(event) => setClassification(event.target.value as MediaStreamClassification | '')}
          >
            <option value="">Unclassified</option>
            {CLASSIFICATIONS.map((item) => (
              <option key={item.value} value={item.value}>
                {item.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="text-xs font-semibold text-slate-400">Notes</span>
          <input
            className="mt-1 w-full rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 placeholder:text-slate-600"
            value={notes}
            disabled={disabled || saving}
            onChange={(event) => setNotes(event.target.value)}
            placeholder="Review notes"
          />
        </label>

        <Button type="button" disabled={disabled || saving} onClick={save}>
          {saving ? 'Saving...' : 'Save Review'}
        </Button>
      </div>
      {error && <p className="mt-3 rounded-lg border border-rose-400/30 bg-rose-400/10 p-2 text-sm text-rose-100">{error}</p>}
    </div>
  )
}
