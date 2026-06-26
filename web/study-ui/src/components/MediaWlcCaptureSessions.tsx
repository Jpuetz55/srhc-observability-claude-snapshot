import { useEffect, useMemo, useState } from 'react'
import {
  createMediaQoeWlcSessionEvent,
  createStudyMediaQoeWlcSession,
  getMediaQoeWlcDefaults,
  getMediaQoeWlcSession,
  listStudyMediaQoeWlcSessions,
  setMediaQoeWlcAttemptActiveGroup,
  setMediaQoeWlcAttemptOutcome,
  startMediaQoeWlcAttempt,
  updateMediaQoeWlcSession
} from '../api/client'
import type {
  MediaWlcDefaultsResponse,
  MediaWlcSessionCreateRequest,
  MediaWlcSessionDetailResponse,
  StringRow
} from '../api/types'
import { Card } from './Card'

type GroupCandidate = {
  group: string
  vlan: number
  mgid: number | null
  row: string
}

type CreateForm = {
  capture_purpose: 'short_validation' | 'incident_reproduction' | 'extended_monitored'
  notes: string
  advanced: boolean
  override_reason: string
  wlc_interface: string
  ring_file_count: string
  ring_file_size_mb: string
  vocera_vlan: string
}

const EMPTY_CREATE_FORM: CreateForm = {
  capture_purpose: 'short_validation',
  notes: '',
  advanced: false,
  override_reason: '',
  wlc_interface: '',
  ring_file_count: '',
  ring_file_size_mb: '',
  vocera_vlan: ''
}

const INGEST_STATE_LABELS: Record<string, string> = {
  waiting_for_export: 'Waiting for WLC export',
  upload_detected: 'Upload detected',
  waiting_for_stability: 'Waiting for stable upload',
  validating: 'Validating artifact',
  validated: 'Validated',
  promoted: 'Finalized as evidence',
  registered: 'Registered',
  imported: 'Imported',
  parsing: 'Parsing',
  parsed: 'Parsed',
  failed: 'Failed',
  retry_pending: 'Retry pending',
  quarantined: 'Quarantined'
}

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function detailField(row: Record<string, unknown> | null | undefined, key: string, fallback = ''): string {
  const value = row?.[key]
  if (value === null || value === undefined || value === '') {
    return fallback
  }
  return String(value)
}

function nowIso(): string {
  return new Date().toISOString()
}

function inputClass(): string {
  return 'w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400'
}

function numericValue(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function ingestStateLabel(state: string): string {
  return INGEST_STATE_LABELS[state] ?? (state || 'Unknown')
}

function shortSha(sha: string): string {
  return sha ? `${sha.slice(0, 12)}…` : '—'
}

function formatBytes(value: string): string {
  const n = Number(value)
  if (!Number.isFinite(n) || n <= 0) {
    return '—'
  }
  if (n < 1024) {
    return `${n} B`
  }
  if (n < 1024 * 1024) {
    return `${(n / 1024).toFixed(1)} KB`
  }
  if (n < 1024 * 1024 * 1024) {
    return `${(n / (1024 * 1024)).toFixed(1)} MB`
  }
  return `${(n / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function shellQuote(value: string): string {
  return `'${value.replaceAll("'", "'\"'\"'")}'`
}

function voceraGroupInPool(value: string): boolean {
  const match = value.match(/^230\.230\.(\d{1,3})\.(\d{1,3})$/)
  if (!match) {
    return false
  }
  const third = Number(match[1])
  const fourth = Number(match[2])
  return Number.isInteger(third) && Number.isInteger(fourth) && third >= 0 && third <= 15 && fourth >= 1 && fourth <= 254
}

function parseGroupCandidates(text: string): GroupCandidate[] {
  const candidates: GroupCandidate[] = []
  const seen = new Set<string>()
  for (const line of text.split(/\r?\n/)) {
    const match = line.match(/^\s*(?:(\d+)\s+)?(230\.230\.\d{1,3}\.\d{1,3})\s+(\d{1,4})\s*$/)
    if (!match || !voceraGroupInPool(match[2])) {
      continue
    }
    const vlan = Number(match[3])
    if (!Number.isInteger(vlan) || vlan < 1 || vlan > 4094) {
      continue
    }
    const mgid = match[1] ? Number(match[1]) : null
    const key = `${match[2]}|${vlan}|${mgid ?? ''}`
    if (!seen.has(key)) {
      candidates.push({ group: match[2], vlan, mgid, row: line.trim() })
      seen.add(key)
    }
  }
  return candidates
}

function commandWithGroup(text: string, attempt: StringRow | null): string {
  if (!attempt) {
    return text
  }
  const group = field(attempt, 'resolved_group_ip') || field(attempt, 'dynamic_multicast_ip')
  const vlan = field(attempt, 'resolved_group_vlan') || field(attempt, 'vocera_vlan')
  const mgid = field(attempt, 'resolved_mgid') || field(attempt, 'mgid')
  return text
    .replaceAll('<VOCERA_GROUP>', group || '<VOCERA_GROUP>')
    .replaceAll('<RESOLVED_GROUP_IP>', group || '<RESOLVED_GROUP_IP>')
    .replaceAll('<RESOLVED_GROUP_VLAN>', vlan || '<RESOLVED_GROUP_VLAN>')
    .replaceAll('<RESOLVED_MGID>', mgid || '<RESOLVED_MGID>')
}

async function copyText(text: string): Promise<void> {
  if (!text) {
    return
  }
  await navigator.clipboard?.writeText(text)
}

function profileRows(defaults: MediaWlcDefaultsResponse | null, form?: CreateForm): [string, string][] {
  const d = defaults?.defaults
  return [
    ['WLC', d?.wlc_name ?? '—'],
    ['SSH target', d?.wlc_ssh_host ? `${d.wlc_ssh_host}:${d.wlc_ssh_port ?? 22}` : '—'],
    ['Interface', form?.advanced && form.wlc_interface ? form.wlc_interface : d?.wlc_interface ?? '—'],
    ['Collector', d?.collector_host ?? '—'],
    ['SCP account', d?.collector_scp_username ?? '—'],
    ['SCP port', String(d?.collector_scp_port ?? 22)],
    ['Vocera VLAN', form?.advanced && form.vocera_vlan ? form.vocera_vlan : String(d?.vocera_vlan ?? 684)],
    ['Multicast pool', d?.vocera_multicast_pool ?? '—'],
    ['Expected DSCP', String(d?.expected_dscp ?? 46)],
    [
      'Capture buffer',
      `${form?.advanced && form.ring_file_count ? form.ring_file_count : d?.ring_file_count ?? 5} files x ${form?.advanced && form.ring_file_size_mb ? form.ring_file_size_mb : d?.ring_file_size_mb ?? 100} MB`
    ]
  ]
}

function hasCompleteCaptureProfile(defaults: MediaWlcDefaultsResponse | null): boolean {
  const profile = defaults?.defaults
  if (!profile) {
    return false
  }
  return Boolean(
    profile.wlc_name?.trim() &&
    profile.wlc_ssh_host?.trim() &&
    Number(profile.wlc_ssh_port ?? 22) > 0 &&
    profile.wlc_interface?.trim() &&
    profile.collector_host?.trim() &&
    profile.collector_scp_username?.trim() &&
    Number(profile.collector_scp_port) > 0 &&
    Number(profile.vocera_vlan) > 0 &&
    profile.vocera_multicast_pool?.trim() &&
    Number.isFinite(Number(profile.expected_dscp)) &&
    Number(profile.ring_file_count) > 0 &&
    Number(profile.ring_file_size_mb) > 0
  )
}

function commandSheet(commandSheets: Record<string, string>, name: string, attempt: StringRow | null): string {
  return commandWithGroup(commandSheets[name] ?? '', attempt)
}

function statusPill(label: string, tone: 'cyan' | 'emerald' | 'amber' | 'slate' | 'rose' = 'slate') {
  const tones = {
    cyan: 'border-cyan-500/40 bg-cyan-950/30 text-cyan-100',
    emerald: 'border-emerald-500/40 bg-emerald-950/30 text-emerald-100',
    amber: 'border-amber-500/40 bg-amber-950/30 text-amber-100',
    slate: 'border-slate-700 bg-slate-950/50 text-slate-200',
    rose: 'border-rose-500/40 bg-rose-950/30 text-rose-100'
  }
  return <span className={`inline-flex rounded-full border px-2 py-1 text-xs ${tones[tone]}`}>{label}</span>
}

function CommandSheetPanel({ title, text, onCopied }: { title: string; text: string; onCopied: (message: string) => void }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/50 p-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm font-semibold text-slate-100">{title}</p>
        <button
          className="rounded-md border border-cyan-500/60 px-3 py-1 text-xs text-cyan-100 disabled:opacity-50"
          disabled={!text}
          onClick={() => {
            void copyText(text).then(() => onCopied(`Copied ${title}.`))
          }}
        >
          Copy
        </button>
      </div>
      <pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap rounded border border-slate-800 bg-slate-950 p-3 text-xs text-slate-300">{text || 'Command sheet unavailable for this session.'}</pre>
    </div>
  )
}

function CaptureProfileCard({ defaults, form }: { defaults: MediaWlcDefaultsResponse | null; form?: CreateForm }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Capture profile</p>
          <p className="mt-1 text-sm font-semibold text-slate-100">SRHC Vocera Multicast Default</p>
        </div>
        {statusPill('Manual WLC mode', 'cyan')}
      </div>
      <dl className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {profileRows(defaults, form).map(([label, value]) => (
          <div key={label}>
            <dt className="text-xs uppercase tracking-wide text-slate-500">{label}</dt>
            <dd className="mt-1 font-mono text-sm text-slate-200">{value}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-3 text-xs text-slate-500">{defaults?.password_policy.message ?? 'Manual mode does not collect WLC or SCP passwords.'}</p>
    </div>
  )
}

function SessionHistory({
  sessions,
  selectedSessionId,
  onSelect
}: {
  sessions: StringRow[]
  selectedSessionId: string | null
  onSelect: (sessionId: string) => void
}) {
  if (!sessions.length) {
    return (
      <div className="rounded-md border border-slate-800 bg-slate-950/40 p-6 text-center text-sm text-slate-400">
        No WLC capture sessions exist for this investigation.
      </div>
    )
  }
  return (
    <div className="grid gap-3 lg:grid-cols-2">
      {sessions.map((session) => {
        const sessionId = field(session, 'session_id')
        const selected = sessionId === selectedSessionId
        return (
          <button
            key={sessionId}
            className={`rounded-md border p-4 text-left transition ${selected ? 'border-cyan-500 bg-cyan-950/20' : 'border-slate-800 bg-slate-950/40 hover:border-slate-600'}`}
            onClick={() => onSelect(sessionId)}
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="font-mono text-sm font-semibold text-slate-100">{field(session, 'capture_name', sessionId)}</p>
                <p className="mt-1 text-xs text-slate-500">{sessionId}</p>
              </div>
              {statusPill(field(session, 'session_state', 'prepared'), selected ? 'cyan' : 'slate')}
            </div>
            <div className="mt-3 grid gap-2 text-xs text-slate-400 sm:grid-cols-2">
              <span>{field(session, 'sender_model', 'V5000')} {'->'} {field(session, 'receiver_model', 'C1000')}</span>
              <span>{field(session, 'wlc_interface', 'Port-channel1')}</span>
              <span>{field(session, 'attempt_count', '0')} attempts</span>
              <span>{field(session, 'event_count', '0')} timeline events</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}

function SessionCreateWizard({
  defaults,
  busy,
  onCreate,
  onCancel
}: {
  defaults: MediaWlcDefaultsResponse | null
  busy: boolean
  onCreate: (form: CreateForm) => Promise<void>
  onCancel: () => void
}) {
  const [form, setForm] = useState<CreateForm>(() => ({
    ...EMPTY_CREATE_FORM,
    wlc_interface: defaults?.defaults.wlc_interface ?? '',
    ring_file_count: String(defaults?.defaults.ring_file_count ?? 5),
    ring_file_size_mb: String(defaults?.defaults.ring_file_size_mb ?? 100),
    vocera_vlan: String(defaults?.defaults.vocera_vlan ?? 684)
  }))

  const update = (key: keyof CreateForm, value: string | boolean) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  return (
    <Card>
      <div className="space-y-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-cyan-300/80">New WLC capture session</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-50">Create prepared capture session</h2>
          </div>
          <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200" onClick={onCancel}>Cancel</button>
        </div>

        <div className="grid gap-3 md:grid-cols-3">
          {([
            ['short_validation', '90-second validation smoke'],
            ['incident_reproduction', 'Incident reproduction'],
            ['extended_monitored', 'Extended monitored capture']
          ] as const).map(([value, label], index) => (
            <label key={`${value}-${index}`} className={`rounded-md border p-3 ${form.capture_purpose === value ? 'border-cyan-500 bg-cyan-950/20' : 'border-slate-800 bg-slate-950/40'}`}>
              <input
                className="mr-2"
                type="radio"
                checked={form.capture_purpose === value}
                onChange={() => update('capture_purpose', value)}
              />
              <span className="text-sm text-slate-200">{label}</span>
            </label>
          ))}
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">Sender test device</p>
            <p className="mt-1 font-mono text-sm text-slate-200">{defaults?.defaults.sender?.model ?? 'V5000'} {defaults?.defaults.sender?.mac ?? '—'}</p>
          </div>
          <div className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
            <p className="text-xs uppercase tracking-wide text-slate-500">Receiver test device</p>
            <p className="mt-1 font-mono text-sm text-slate-200">{defaults?.defaults.receiver?.model ?? 'C1000'} {defaults?.defaults.receiver?.mac ?? '—'}</p>
          </div>
        </div>

        <label className="block space-y-1 text-sm text-slate-300">
          <span>Optional note</span>
          <input className={inputClass()} value={form.notes} onChange={(event) => update('notes', event.target.value)} />
        </label>

        <CaptureProfileCard defaults={defaults} form={form} />

        <details className="rounded-md border border-slate-800 bg-slate-950/40 p-3">
          <summary className="cursor-pointer text-sm font-semibold text-slate-200">
            <input className="mr-2" type="checkbox" checked={form.advanced} onChange={(event) => update('advanced', event.target.checked)} />
            Advanced overrides
          </summary>
          {form.advanced && (
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <label className="space-y-1 text-sm text-slate-300 md:col-span-4">
                <span>Override reason</span>
                <input className={inputClass()} value={form.override_reason} onChange={(event) => update('override_reason', event.target.value)} />
              </label>
              <label className="space-y-1 text-sm text-slate-300">
                <span>Interface</span>
                <input className={inputClass()} value={form.wlc_interface} onChange={(event) => update('wlc_interface', event.target.value)} />
              </label>
              <label className="space-y-1 text-sm text-slate-300">
                <span>Ring files</span>
                <input className={inputClass()} value={form.ring_file_count} onChange={(event) => update('ring_file_count', event.target.value)} />
              </label>
              <label className="space-y-1 text-sm text-slate-300">
                <span>File MB</span>
                <input className={inputClass()} value={form.ring_file_size_mb} onChange={(event) => update('ring_file_size_mb', event.target.value)} />
              </label>
              <label className="space-y-1 text-sm text-slate-300">
                <span>Configured VLAN</span>
                <input className={inputClass()} value={form.vocera_vlan} onChange={(event) => update('vocera_vlan', event.target.value)} />
              </label>
            </div>
          )}
        </details>

        <button
          className="rounded-md bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50"
          disabled={busy || (form.advanced && !form.override_reason.trim())}
          onClick={() => { void onCreate(form) }}
        >
          Create prepared capture session
        </button>
      </div>
    </Card>
  )
}

function ArtifactStatusPanel({ artifacts, onRefresh, busy }: { artifacts: StringRow[]; onRefresh: () => void; busy: boolean }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-950/40 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">EPC artifact</p>
          <p className="mt-1 text-sm text-slate-300">Collector status for the selected session only.</p>
        </div>
        <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy} onClick={onRefresh}>Refresh ingest status</button>
      </div>
      <div className="mt-4 overflow-auto rounded-md border border-slate-800">
        <table className="min-w-full divide-y divide-slate-800 text-sm">
          <thead className="bg-slate-950/60 text-left text-xs uppercase tracking-wide text-slate-400">
            <tr>
              <th className="px-3 py-2">File</th>
              <th className="px-3 py-2">Size</th>
              <th className="px-3 py-2">SHA-256</th>
              <th className="px-3 py-2">State</th>
              <th className="px-3 py-2">Parser</th>
              <th className="px-3 py-2">Visibility</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {artifacts.map((artifact) => (
              <tr key={field(artifact, 'artifact_id')} className="text-slate-200">
                <td className="px-3 py-2 font-mono text-xs">{field(artifact, 'source_name', '—')}</td>
                <td className="px-3 py-2">{formatBytes(field(artifact, 'size_bytes'))}</td>
                <td className="px-3 py-2 font-mono text-xs">{shortSha(field(artifact, 'sha256'))}</td>
                <td className="px-3 py-2">{ingestStateLabel(field(artifact, 'ingest_state'))}</td>
                <td className="px-3 py-2">{field(artifact, 'parser_status', '—')}</td>
                <td className="px-3 py-2">{field(artifact, 'visibility_class', 'pending')}</td>
              </tr>
            ))}
            {!artifacts.length && (
              <tr>
                <td className="px-3 py-6 text-center text-slate-500" colSpan={6}>Waiting for WLC export into this session package.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function GroupSelectionPanel({
  attempt,
  configuredVlan,
  busy,
  onSelect,
  onMessage
}: {
  attempt: StringRow | null
  configuredVlan: number
  busy: boolean
  onSelect: (candidate: GroupCandidate, overrideReason: string, raw: string) => Promise<void>
  onMessage: (message: string) => void
}) {
  const [text, setText] = useState('')
  const [candidates, setCandidates] = useState<GroupCandidate[]>([])
  const [overrideReason, setOverrideReason] = useState('')

  return (
    <div className="space-y-3">
      <label className="block space-y-1 text-sm text-slate-300">
        <span>Group summary output</span>
        <textarea
          className="min-h-24 w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder="Paste show wireless multicast group summary output"
        />
      </label>
      <button
        className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50"
        disabled={!text.trim()}
        onClick={() => {
          const parsed = parseGroupCandidates(text)
          setCandidates(parsed)
          onMessage(parsed.length ? `Found ${parsed.length} candidate group${parsed.length === 1 ? '' : 's'}.` : 'No 230.230.x.x candidate group rows found.')
        }}
      >
        Find candidate groups
      </button>
      {candidates.length > 0 && (
        <div className="overflow-auto rounded-md border border-slate-800">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-950/60 text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Dynamic group</th>
                <th className="px-3 py-2">VLAN</th>
                <th className="px-3 py-2">MGID</th>
                <th className="px-3 py-2">Select</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {candidates.map((candidate) => {
                const mismatch = candidate.vlan !== configuredVlan
                return (
                  <tr key={`${candidate.group}-${candidate.vlan}-${candidate.mgid ?? 'none'}`} className="text-slate-200">
                    <td className="px-3 py-2 font-mono text-xs">{candidate.group}</td>
                    <td className="px-3 py-2">{candidate.vlan}{mismatch ? ' differs from configured' : ''}</td>
                    <td className="px-3 py-2">{candidate.mgid ?? 'unknown'}</td>
                    <td className="px-3 py-2">
                      <button
                        className="rounded-md border border-cyan-500/60 px-3 py-1 text-xs text-cyan-100 disabled:opacity-50"
                        disabled={busy || !attempt || (mismatch && !overrideReason.trim())}
                        onClick={() => { void onSelect(candidate, overrideReason, text) }}
                      >
                        Select
                      </button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
      {candidates.some((candidate) => candidate.vlan !== configuredVlan) && (
        <label className="block space-y-1 text-sm text-slate-300">
          <span>Override active-group VLAN reason</span>
          <input className={inputClass()} value={overrideReason} onChange={(event) => setOverrideReason(event.target.value)} />
        </label>
      )}
      {!attempt && <p className="text-xs text-amber-200">Start a broadcast attempt before selecting a multicast group.</p>}
    </div>
  )
}

function OperatorConsole({
  detail,
  defaults,
  busy,
  consoleUser,
  setConsoleUser,
  onPatchState,
  onStartAttempt,
  onSetOutcome,
  onSelectGroup,
  onRefresh,
  onMessage
}: {
  detail: MediaWlcSessionDetailResponse
  defaults: MediaWlcDefaultsResponse | null
  busy: boolean
  consoleUser: string
  setConsoleUser: (value: string) => void
  onPatchState: (state: 'running' | 'stopped' | 'exported' | 'aborted') => Promise<void>
  onStartAttempt: () => Promise<void>
  onSetOutcome: (outcome: 'heard' | 'missed' | 'partial' | 'choppy' | 'alert_only') => Promise<void>
  onSelectGroup: (candidate: GroupCandidate, overrideReason: string, raw: string) => Promise<void>
  onRefresh: () => void
  onMessage: (message: string) => void
}) {
  const session = detail.session
  const attempts = detail.attempts ?? []
  const activeAttempt = attempts.find((attempt) => field(attempt, 'attempt_id') === detail.open_attempt_id)
    ?? attempts.find((attempt) => field(attempt, 'attempt_id') === detail.selected_attempt_id)
    ?? attempts[0]
    ?? null
  const configuredVlan = numericValue(field(session, 'configured_vocera_vlan'), defaults?.defaults.vocera_vlan ?? 684)
  const wlcSshHost = defaults?.defaults.wlc_ssh_host?.trim() ?? ''
  const wlcSshPort = defaults?.defaults.wlc_ssh_port ?? 22
  const commandSheets = detail.command_sheets ?? {}
  const consoleCommand = field(session, 'command_package_path') && wlcSshHost
    ? [
        'make vocera-media-qoe-wlc-session-console \\',
        `  SESSION_DIR=${shellQuote(field(session, 'command_package_path'))} \\`,
        `  WLC_SSH_HOST=${shellQuote(wlcSshHost)} \\`,
        `  WLC_SSH_PORT=${shellQuote(String(wlcSshPort))} \\`,
        `  WLC_SSH_USER=${consoleUser.trim() ? shellQuote(consoleUser.trim()) : '<your-wlc-user>'}`
      ].join('\n')
    : ''
  const startSheet = field(session, 'capture_mode') === 'long_reproduction' ? 'start-long.cli' : 'start-short-validation.cli'

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-emerald-300/80">Selected session</p>
            <h2 className="mt-1 font-mono text-xl font-semibold text-slate-50">{field(session, 'capture_name', field(session, 'session_id'))}</h2>
            <p className="mt-1 text-sm text-slate-400">{field(session, 'session_id')}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            {statusPill(field(session, 'session_state', 'prepared'), 'cyan')}
            {statusPill(field(session, 'capture_mode', 'short_validation'), 'slate')}
          </div>
        </div>
        <div className="mt-4 grid gap-3 md:grid-cols-4">
          <div><p className="text-xs uppercase text-slate-500">Sender</p><p className="font-mono text-sm text-slate-200">{field(session, 'sender_mac')}</p></div>
          <div><p className="text-xs uppercase text-slate-500">Receiver</p><p className="font-mono text-sm text-slate-200">{field(session, 'receiver_mac')}</p></div>
          <div><p className="text-xs uppercase text-slate-500">Interface</p><p className="font-mono text-sm text-slate-200">{field(session, 'wlc_interface')}</p></div>
          <div><p className="text-xs uppercase text-slate-500">Next action</p><p className="text-sm text-slate-200">{detailField(detail.next_operator_action, 'label', 'Review session')}</p></div>
        </div>
      </Card>

      <div className="grid gap-4">
        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Step 1</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Prepare WLC</h3>
          <div className="mt-3 grid gap-3 lg:grid-cols-[18rem_1fr]">
            <label className="space-y-1 text-sm text-slate-300">
              <span>WLC SSH user</span>
              <input className={inputClass()} value={consoleUser} onChange={(event) => setConsoleUser(event.target.value)} placeholder="operator username" />
            </label>
            <CommandSheetPanel title="Logged WLC console command" text={consoleCommand} onCopied={onMessage} />
          </div>
          <div className="mt-3">
            <CommandSheetPanel title="baseline.cli" text={commandSheet(commandSheets, 'baseline.cli', activeAttempt)} onCopied={onMessage} />
          </div>
          <button className="mt-3 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy} onClick={() => { void createMediaQoeWlcSessionEvent(field(session, 'session_id'), { event_kind: 'note', event_time: nowIso(), notes: 'Baseline WLC output recorded.' }).then(onRefresh) }}>
            I recorded baseline output
          </button>
        </Card>

        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Step 2</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Start capture</h3>
          <CommandSheetPanel title={startSheet} text={commandSheet(commandSheets, startSheet, activeAttempt)} onCopied={onMessage} />
          <button className="mt-3 rounded-md border border-emerald-500/60 px-3 py-2 text-sm text-emerald-100 disabled:opacity-50" disabled={busy} onClick={() => { void onPatchState('running') }}>
            I started the WLC capture
          </button>
        </Card>

        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Step 3</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Record broadcast outcome</h3>
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy} onClick={() => { void onStartAttempt() }}>
              Start broadcast attempt
            </button>
            {(['heard', 'missed', 'partial', 'choppy', 'alert_only'] as const).map((outcome) => (
              <button key={outcome} className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy} onClick={() => { void onSetOutcome(outcome) }}>
                {outcome === 'heard' ? 'Heard clearly' : outcome.replaceAll('_', ' ')}
              </button>
            ))}
          </div>
          <p className="mt-3 text-xs text-slate-500">Active attempt: <span className="font-mono text-slate-300">{field(activeAttempt, 'attempt_id', 'none')}</span></p>
        </Card>

        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Step 4</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Select active multicast group</h3>
          <div className="mt-3">
            <CommandSheetPanel title="active-event.cli" text={commandSheet(commandSheets, 'active-event.cli', activeAttempt)} onCopied={onMessage} />
          </div>
          <div className="mt-3">
            <GroupSelectionPanel attempt={activeAttempt} configuredVlan={configuredVlan} busy={busy} onSelect={onSelectGroup} onMessage={onMessage} />
          </div>
          {activeAttempt && (field(activeAttempt, 'resolved_group_ip') || field(activeAttempt, 'dynamic_multicast_ip')) && (
            <div className="mt-3 rounded-md border border-emerald-900 bg-emerald-950/20 p-3 text-sm text-emerald-100">
              Selected: <span className="font-mono">{field(activeAttempt, 'resolved_group_ip') || field(activeAttempt, 'dynamic_multicast_ip')}</span> VLAN {field(activeAttempt, 'resolved_group_vlan') || field(activeAttempt, 'vocera_vlan', '—')} MGID {field(activeAttempt, 'resolved_mgid', '—')}
            </div>
          )}
          <div className="mt-3">
            <CommandSheetPanel title="resolved-active-group.cli" text={commandSheet(commandSheets, 'resolved-active-group.cli', activeAttempt)} onCopied={onMessage} />
          </div>
        </Card>

        <Card>
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Step 5</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-50">Stop, export, and ingest</h3>
          <CommandSheetPanel title="stop-export.cli" text={commandSheet(commandSheets, 'stop-export.cli', activeAttempt)} onCopied={onMessage} />
          <div className="mt-3 flex flex-wrap gap-2">
            <button className="rounded-md border border-amber-500/60 px-3 py-2 text-sm text-amber-100 disabled:opacity-50" disabled={busy} onClick={() => { void onPatchState('stopped') }}>
              I stopped the WLC capture
            </button>
            <button className="rounded-md border border-emerald-500/60 px-3 py-2 text-sm text-emerald-100 disabled:opacity-50" disabled={busy} onClick={() => { void onPatchState('exported') }}>
              I confirmed SCP export succeeded
            </button>
            <button className="rounded-md border border-rose-500/60 px-3 py-2 text-sm text-rose-100 disabled:opacity-50" disabled={busy} onClick={() => { void onPatchState('aborted') }}>
              I aborted this capture
            </button>
          </div>
          <p className="mt-3 text-xs text-amber-200">Do not run cleanup until the WLC confirms that SCP export completed.</p>
          <div className="mt-3">
            <ArtifactStatusPanel artifacts={detail.artifacts ?? []} onRefresh={onRefresh} busy={busy} />
          </div>
          <div className="mt-3">
            <CommandSheetPanel title="cleanup.cli" text={commandSheet(commandSheets, 'cleanup.cli', activeAttempt)} onCopied={onMessage} />
          </div>
          <button className="mt-3 rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy} onClick={() => { void createMediaQoeWlcSessionEvent(field(session, 'session_id'), { event_kind: 'note', event_time: nowIso(), notes: 'WLC cleanup completed.' }).then(onRefresh) }}>
            I completed WLC cleanup
          </button>
        </Card>
      </div>
    </div>
  )
}

export function MediaWlcCaptureSessions({ studyId }: { studyId: string | null }) {
  const [defaults, setDefaults] = useState<MediaWlcDefaultsResponse | null>(null)
  const [sessions, setSessions] = useState<StringRow[]>([])
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(() => new URLSearchParams(window.location.search).get('session'))
  const [detail, setDetail] = useState<MediaWlcSessionDetailResponse | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [consoleUser, setConsoleUser] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [validMediaStudy, setValidMediaStudy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const selectedSession = useMemo(
    () => sessions.find((session) => field(session, 'session_id') === selectedSessionId) ?? null,
    [selectedSessionId, sessions]
  )
  const completeCaptureProfile = hasCompleteCaptureProfile(defaults)
  const canCreateSession = Boolean(studyId) && validMediaStudy && completeCaptureProfile && !loading && !busy

  const updateUrlSession = (sessionId: string | null) => {
    const url = new URL(window.location.href)
    if (sessionId) {
      url.searchParams.set('session', sessionId)
    } else {
      url.searchParams.delete('session')
    }
    window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  }

  const loadDetail = async (sessionId: string | null) => {
    if (!sessionId) {
      setDetail(null)
      return
    }
    const response = await getMediaQoeWlcSession(sessionId)
    setDetail(response)
  }

  const refresh = async (preferredSessionId = selectedSessionId) => {
    if (!studyId) {
      setSessions([])
      setSelectedSessionId(null)
      setDetail(null)
      setValidMediaStudy(false)
      return
    }
    setLoading(true)
    setError(null)
    try {
      try {
        const defaultsResponse = await getMediaQoeWlcDefaults()
        setDefaults(defaultsResponse)
      } catch (err) {
        setDefaults(null)
        setError(err instanceof Error ? err.message : 'Failed to load WLC capture profile defaults')
      }
      const sessionsResponse = await listStudyMediaQoeWlcSessions(studyId)
      setValidMediaStudy(true)
      const rows = sessionsResponse.sessions ?? []
      setSessions(rows)
      const validPreferred = preferredSessionId && rows.some((session) => field(session, 'session_id') === preferredSessionId)
      const nextSelected = validPreferred ? preferredSessionId : rows.length === 1 ? field(rows[0], 'session_id') : null
      setSelectedSessionId(nextSelected)
      updateUrlSession(nextSelected)
      await loadDetail(nextSelected)
    } catch (err) {
      setValidMediaStudy(false)
      setSessions([])
      setSelectedSessionId(null)
      setDetail(null)
      updateUrlSession(null)
      setError(err instanceof Error ? err.message : 'Selected study is not a Media QoE investigation.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [studyId])

  const selectSession = async (sessionId: string) => {
    setSelectedSessionId(sessionId)
    updateUrlSession(sessionId)
    setError(null)
    setMessage(null)
    try {
      setLoading(true)
      await loadDetail(sessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to open WLC capture session')
    } finally {
      setLoading(false)
    }
  }

  const createSession = async (form: CreateForm) => {
    if (!studyId) {
      setError('Select or create a multicast investigation before creating a WLC session.')
      return
    }
    const payload: MediaWlcSessionCreateRequest = {
      capture_mode: form.capture_purpose === 'short_validation' ? 'short_validation' : 'long_reproduction',
      notes: form.advanced
        ? `${form.notes.trim() ? `${form.notes.trim()}\n\n` : ''}Capture purpose: ${form.capture_purpose.replaceAll('_', ' ')}.\nAdvanced override reason: ${form.override_reason.trim()}`
        : `${form.notes.trim() ? `${form.notes.trim()}\n\n` : ''}Capture purpose: ${form.capture_purpose.replaceAll('_', ' ')}.`.trim()
    }
    if (form.advanced) {
      payload.wlc_interface = form.wlc_interface.trim() || undefined
      payload.ring_file_count = numericValue(form.ring_file_count, defaults?.defaults.ring_file_count ?? 5)
      payload.ring_file_size_mb = numericValue(form.ring_file_size_mb, defaults?.defaults.ring_file_size_mb ?? 100)
      payload.vocera_vlan = numericValue(form.vocera_vlan, defaults?.defaults.vocera_vlan ?? 684)
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const response = await createStudyMediaQoeWlcSession(studyId, payload)
      const sessionId = field(response.session, 'session_id')
      setShowCreate(false)
      setMessage(response.message ?? 'Created WLC capture session.')
      await refresh(sessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create WLC capture session')
    } finally {
      setBusy(false)
    }
  }

  const patchSelectedState = async (state: 'running' | 'stopped' | 'exported' | 'aborted') => {
    if (!selectedSessionId) {
      setError('Open a WLC session before recording capture state.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await updateMediaQoeWlcSession(selectedSessionId, {
        session_state: state,
        capture_started_at: state === 'running' ? nowIso() : undefined,
        capture_stopped_at: state === 'stopped' || state === 'exported' || state === 'aborted' ? nowIso() : undefined
      })
      setMessage(`Recorded session state: ${state}.`)
      await refresh(selectedSessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update WLC session')
    } finally {
      setBusy(false)
    }
  }

  const startAttempt = async () => {
    if (!selectedSessionId) {
      setError('Open a WLC session before starting an attempt.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const response = await startMediaQoeWlcAttempt(selectedSessionId, { started_at: nowIso(), browser_event_time: nowIso() })
      setMessage(`Started attempt ${field(response.attempt, 'attempt_id')}.`)
      await refresh(selectedSessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start broadcast attempt')
    } finally {
      setBusy(false)
    }
  }

  const setOutcome = async (outcome: 'heard' | 'missed' | 'partial' | 'choppy' | 'alert_only') => {
    if (!selectedSessionId) {
      setError('Open a WLC session before recording an outcome.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      let attemptId = detail?.open_attempt_id || ''
      if (!attemptId) {
        const started = await startMediaQoeWlcAttempt(selectedSessionId, { started_at: nowIso(), browser_event_time: nowIso() })
        attemptId = field(started.attempt, 'attempt_id')
      }
      await setMediaQoeWlcAttemptOutcome(attemptId, {
        audio_result: outcome,
        alert_received: outcome === 'alert_only' ? true : undefined,
        audio_received: outcome === 'heard' ? true : outcome === 'alert_only' || outcome === 'missed' ? false : undefined,
        ended_at: nowIso(),
        browser_event_time: nowIso()
      })
      setMessage(`Recorded outcome ${outcome.replaceAll('_', ' ')} for ${attemptId}.`)
      await refresh(selectedSessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to record broadcast outcome')
    } finally {
      setBusy(false)
    }
  }

  const selectGroup = async (candidate: GroupCandidate, overrideReason: string, raw: string) => {
    const attempt = detail?.attempts.find((row) => field(row, 'attempt_id') === detail.open_attempt_id)
      ?? detail?.attempts.find((row) => field(row, 'attempt_id') === detail.selected_attempt_id)
      ?? null
    if (!attempt) {
      setError('Start a broadcast attempt before selecting an active group.')
      return
    }
    const configuredVlan = numericValue(field(detail?.session, 'configured_vocera_vlan'), defaults?.defaults.vocera_vlan ?? 684)
    const mismatch = candidate.vlan !== configuredVlan
    if (mismatch && !overrideReason.trim()) {
      setError('Enter an override reason before selecting a group on a VLAN different from the configured default.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      await setMediaQoeWlcAttemptActiveGroup(field(attempt, 'attempt_id'), {
        group_ip: candidate.group,
        group_vlan: candidate.vlan,
        mgid: candidate.mgid ?? undefined,
        selection_source: mismatch ? 'operator_override' : 'observed_confirmation',
        vlan_override_reason: mismatch ? overrideReason.trim() : undefined,
        group_summary_raw: raw.trim() || undefined,
        selected_row: candidate.row,
        selected_at: nowIso()
      })
      setMessage(`Selected ${candidate.group} VLAN ${candidate.vlan}${candidate.mgid === null ? '' : ` MGID ${candidate.mgid}`}.`)
      await refresh(selectedSessionId)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to store active group selection')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      <Card>
        <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.22em] text-slate-500">Investigation sessions</p>
            <h2 className="mt-1 text-xl font-semibold text-slate-50">WLC capture sessions</h2>
            <p className="mt-1 text-sm text-slate-400">
              Open a session before recording WLC state, broadcast attempts, active groups, or artifact status.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <button className="rounded-md bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50" disabled={!canCreateSession} onClick={() => setShowCreate(true)}>
              New WLC capture session
            </button>
            <button className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={loading} onClick={() => { void refresh() }}>
              Refresh
            </button>
          </div>
        </div>
      </Card>

      {error && <div className="rounded-md border border-rose-900 bg-rose-950/30 p-3 text-sm text-rose-100">{error}</div>}
      {message && <div className="rounded-md border border-emerald-900 bg-emerald-950/30 p-3 text-sm text-emerald-100">{message}</div>}
      {studyId && !validMediaStudy && !loading && (
        <div className="rounded-md border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-100">
          <p className="font-semibold">Selected study is not a Media QoE investigation.</p>
          <p className="mt-1 text-amber-100/80">WLC capture sessions can only be created under a study owned by the Media QoE database.</p>
        </div>
      )}
      {!loading && !completeCaptureProfile && (
        <div className="rounded-md border border-amber-900 bg-amber-950/30 p-3 text-sm text-amber-100">
          <p className="font-semibold">Capture profile unavailable.</p>
          <p className="mt-1 text-amber-100/80">Cannot create a WLC capture session until profile defaults load successfully.</p>
        </div>
      )}

      {showCreate && (
        <SessionCreateWizard defaults={defaults} busy={busy} onCreate={createSession} onCancel={() => setShowCreate(false)} />
      )}

      <SessionHistory sessions={sessions} selectedSessionId={selectedSessionId} onSelect={(sessionId) => { void selectSession(sessionId) }} />

      {selectedSession && detail ? (
        <OperatorConsole
          detail={detail}
          defaults={defaults}
          busy={busy}
          consoleUser={consoleUser}
          setConsoleUser={setConsoleUser}
          onPatchState={patchSelectedState}
          onStartAttempt={startAttempt}
          onSetOutcome={setOutcome}
          onSelectGroup={selectGroup}
          onRefresh={() => { void refresh(selectedSessionId) }}
          onMessage={setMessage}
        />
      ) : sessions.length > 1 ? (
        <div className="rounded-md border border-slate-800 bg-slate-950/40 p-6 text-center text-sm text-slate-400">
          Select one session to operate or review. No WLC action buttons are enabled until a session is selected.
        </div>
      ) : null}
    </div>
  )
}
