import { Button } from './Button'

export type MediaDnacCaptureSearchState = {
  client_mac: string
  ap_mac: string
  capture_type: string
  lookback_minutes: string
  limit: string
}

export function MediaDnacCaptureSearch({
  value,
  loading = false,
  disabled = false,
  onChange,
  onCheckStatus,
  onListCaptures
}: {
  value: MediaDnacCaptureSearchState
  loading?: boolean
  disabled?: boolean
  onChange: (value: MediaDnacCaptureSearchState) => void
  onCheckStatus: () => void
  onListCaptures: () => void
}) {
  const update = (key: keyof MediaDnacCaptureSearchState, nextValue: string) => {
    onChange({ ...value, [key]: nextValue })
  }

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-950/70 p-4">
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-[1.2fr_1.2fr_0.8fr_0.8fr_0.7fr]">
        <label className="text-sm font-medium text-slate-300">
          Client MAC
          <input
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={value.client_mac}
            disabled={disabled || loading}
            onChange={(event) => update('client_mac', event.target.value)}
            placeholder="00:09:ef:54:5f:46"
          />
        </label>
        <label className="text-sm font-medium text-slate-300">
          AP MAC
          <input
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={value.ap_mac}
            disabled={disabled || loading}
            onChange={(event) => update('ap_mac', event.target.value)}
            placeholder="optional"
          />
        </label>
        <label className="text-sm font-medium text-slate-300">
          Capture type
          <select
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={value.capture_type || 'FULL'}
            disabled={disabled || loading}
            onChange={(event) => update('capture_type', event.target.value)}
          >
            <option value="FULL">FULL</option>
            <option value="OTA">OTA</option>
            <option value="ONBOARDING">ONBOARDING</option>
          </select>
        </label>
        <label className="text-sm font-medium text-slate-300">
          Lookback minutes
          <input
            type="number"
            min="0"
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={value.lookback_minutes}
            disabled={disabled || loading}
            onChange={(event) => update('lookback_minutes', event.target.value)}
          />
        </label>
        <label className="text-sm font-medium text-slate-300">
          Limit
          <input
            type="number"
            min="1"
            max="100"
            className="mt-2 w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-slate-100 outline-none ring-cyan-400/30 focus:ring-4"
            value={value.limit}
            disabled={disabled || loading}
            onChange={(event) => update('limit', event.target.value)}
          />
        </label>
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        <Button type="button" variant="secondary" disabled={disabled || loading} onClick={onCheckStatus}>
          Check API
        </Button>
        <Button type="button" disabled={disabled || loading || !value.client_mac.trim()} onClick={onListCaptures}>
          List Captures
        </Button>
      </div>
    </section>
  )
}
