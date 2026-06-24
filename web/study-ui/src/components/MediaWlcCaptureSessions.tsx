import { useEffect, useMemo, useState } from 'react'
import {
  createMediaQoeWlcSessionEvent,
  createStudyMediaQoeWlcSession,
  getMediaQoeWlcDefaults,
  listMediaQoeWlcSessionAttempts,
  listStudyMediaQoeWlcSessions,
  setMediaQoeWlcAttemptActiveGroup,
  updateMediaQoeWlcSession
} from '../api/client'
import type { MediaWlcDefaultsResponse, MediaWlcSessionCreateRequest, StringRow } from '../api/types'
import { CollapsibleCard } from './CollapsibleCard'

function field(row: StringRow | null | undefined, key: string, fallback = ''): string {
  return row?.[key] ?? fallback
}

function nowIso(): string {
  return new Date().toISOString()
}

function textInputClass(): string {
  return 'w-full rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400'
}

function numericValue(value: string, fallback: number): number {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

type GroupCandidate = {
  group: string
  vlan: number
  mgid: number | null
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
      candidates.push({ group: match[2], vlan, mgid })
      seen.add(key)
    }
  }
  return candidates
}

function validVlan(value: string): boolean {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 4094
}

type FormState = {
  session_id: string
  capture_name: string
  wlc_name: string
  wlc_interface: string
  collector_host: string
  collector_scp_username: string
  collector_scp_port: string
  ring_file_count: string
  ring_file_size_mb: string
  expected_dscp: string
  vocera_vlan: string
  vocera_multicast_pool: string
  sender_mac: string
  sender_ip: string
  receiver_mac: string
  receiver_ip: string
  continuous_export_enabled: boolean
}

function formFromDefaults(defaults: MediaWlcDefaultsResponse | null): FormState {
  const d = defaults?.defaults
  return {
    session_id: '',
    capture_name: d?.capture_name ?? '',
    wlc_name: d?.wlc_name ?? '',
    wlc_interface: d?.wlc_interface ?? '',
    collector_host: d?.collector_host ?? '',
    collector_scp_username: d?.collector_scp_username ?? '',
    collector_scp_port: String(d?.collector_scp_port ?? 22),
    ring_file_count: String(d?.ring_file_count ?? 5),
    ring_file_size_mb: String(d?.ring_file_size_mb ?? 100),
    expected_dscp: String(d?.expected_dscp ?? 46),
    vocera_vlan: String(d?.vocera_vlan ?? 684),
    vocera_multicast_pool: d?.vocera_multicast_pool ?? '',
    sender_mac: d?.sender?.mac ?? '',
    sender_ip: d?.sender?.ip ?? '',
    receiver_mac: d?.receiver?.mac ?? '',
    receiver_ip: d?.receiver?.ip ?? '',
    continuous_export_enabled: Boolean(d?.continuous_export_enabled)
  }
}

export function MediaWlcCaptureSessions({ studyId }: { studyId: string | null }) {
  const [defaults, setDefaults] = useState<MediaWlcDefaultsResponse | null>(null)
  const [form, setForm] = useState<FormState>(() => formFromDefaults(null))
  const [sessions, setSessions] = useState<StringRow[]>([])
  const [attempts, setAttempts] = useState<StringRow[]>([])
  const [currentAttemptId, setCurrentAttemptId] = useState<string | null>(null)
  const [commandSheets, setCommandSheets] = useState<Record<string, string>>({})
  const [groupSummaryText, setGroupSummaryText] = useState('')
  const [groupCandidates, setGroupCandidates] = useState<GroupCandidate[]>([])
  const [activeGroup, setActiveGroup] = useState('')
  const [activeGroupVlan, setActiveGroupVlan] = useState('')
  const [activeGroupMgid, setActiveGroupMgid] = useState('')
  const [overrideReason, setOverrideReason] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)

  const latestRunningSession = useMemo(
    () => sessions.find((session) => field(session, 'session_state') === 'running') ?? sessions[0],
    [sessions]
  )

  const displayedCommandSheets = useMemo(() => {
    if (!activeGroup) {
      return commandSheets
    }
    return Object.fromEntries(
      Object.entries(commandSheets).map(([name, text]) => [
        name,
        text
          .replaceAll('<VOCERA_GROUP>', activeGroup)
          .replaceAll('<RESOLVED_GROUP_IP>', activeGroup)
          .replaceAll('<RESOLVED_GROUP_VLAN>', activeGroupVlan || '<RESOLVED_GROUP_VLAN>')
          .replaceAll('<RESOLVED_MGID>', activeGroupMgid || '<RESOLVED_MGID>')
      ])
    )
  }, [activeGroup, activeGroupMgid, activeGroupVlan, commandSheets])

  const refresh = async () => {
    if (!studyId) {
      setSessions([])
      setAttempts([])
      setCurrentAttemptId(null)
      return
    }
    setLoading(true)
    setError(null)
    try {
      const [defaultsResponse, sessionsResponse] = await Promise.all([
        getMediaQoeWlcDefaults(),
        listStudyMediaQoeWlcSessions(studyId)
      ])
      setDefaults(defaultsResponse)
      const sessionRows = sessionsResponse.sessions ?? []
      setSessions(sessionRows)
      setForm((current) => (current.wlc_name ? current : formFromDefaults(defaultsResponse)))
      const targetSessionId = field(
        sessionRows.find((session) => field(session, 'session_state') === 'running') ?? sessionRows[0],
        'session_id'
      )
      if (targetSessionId) {
        const attemptResponse = await listMediaQoeWlcSessionAttempts(targetSessionId)
        const attemptRows = attemptResponse.attempts ?? []
        setAttempts(attemptRows)
        // Bind active-group resolution to the open attempt, falling back to the
        // most recent attempt so a refresh or operator handoff stays consistent.
        setCurrentAttemptId(attemptResponse.open_attempt_id ?? field(attemptRows[0], 'attempt_id') ?? null)
      } else {
        setAttempts([])
        setCurrentAttemptId(null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load WLC capture sessions')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void refresh()
  }, [studyId])

  const updateForm = (key: keyof FormState, value: string | boolean) => {
    setForm((current) => ({ ...current, [key]: value }))
  }

  const setActiveGroupFromSummary = () => {
    const candidates = parseGroupCandidates(groupSummaryText)
    setGroupCandidates(candidates)
    if (!candidates.length) {
      setError('No candidate 230.230.0.0/20 Vocera group rows were found in the pasted summary.')
      return
    }
    setError(null)
    setMessage(`Found ${candidates.length} active group candidate${candidates.length === 1 ? '' : 's'}. Select the row that matches the broadcast.`)
  }

  const selectActiveGroupCandidate = async (candidate: GroupCandidate) => {
    const configuredVlan = numericValue(form.vocera_vlan, 684)
    const mismatch = candidate.vlan !== configuredVlan
    if (mismatch && !overrideReason.trim()) {
      setError('Enter an override reason before selecting a group on a VLAN different from the configured default.')
      return
    }
    // A dynamic Vocera group is assigned per broadcast, so the selection binds to
    // a specific attempt, not the capture session.
    if (!currentAttemptId) {
      setError('Mark a broadcast (Broadcast Started or an outcome) first so the active group attaches to that attempt.')
      return
    }
    setActiveGroup(candidate.group)
    setActiveGroupVlan(String(candidate.vlan))
    setActiveGroupMgid(candidate.mgid === null ? '' : String(candidate.mgid))
    setBusy(true)
    setError(null)
    try {
      await setMediaQoeWlcAttemptActiveGroup(currentAttemptId, {
        group_ip: candidate.group,
        group_vlan: candidate.vlan,
        mgid: candidate.mgid ?? undefined,
        selection_source: mismatch ? 'operator_override' : 'observed_confirmation',
        vlan_override_reason: mismatch ? overrideReason.trim() : undefined,
        group_summary_raw: groupSummaryText.trim() || undefined,
        selected_at: nowIso()
      })
      await refresh()
      setMessage(
        `Selected active group ${candidate.group} on VLAN ${candidate.vlan}` +
          `${candidate.mgid === null ? '' : `, MGID ${candidate.mgid}`} for attempt ${currentAttemptId}.`
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to store active group selection')
    } finally {
      setBusy(false)
    }
  }

  const createSession = async () => {
    if (!studyId) {
      setError('Select a multicast investigation study before creating a WLC session.')
      return
    }
    if (!validVlan(form.vocera_vlan)) {
      setError('Configured Vocera multicast VLAN is required and must be an integer from 1 to 4094.')
      return
    }
    const payload: MediaWlcSessionCreateRequest = {
      session_id: form.session_id.trim() || undefined,
      capture_name: form.capture_name.trim() || undefined,
      wlc_name: form.wlc_name.trim() || undefined,
      wlc_interface: form.wlc_interface.trim() || undefined,
      collector_host: form.collector_host.trim() || undefined,
      collector_scp_username: form.collector_scp_username.trim() || undefined,
      collector_scp_port: numericValue(form.collector_scp_port, 22),
      ring_file_count: numericValue(form.ring_file_count, 5),
      ring_file_size_mb: numericValue(form.ring_file_size_mb, 100),
      expected_dscp: numericValue(form.expected_dscp, 46),
      vocera_vlan: numericValue(form.vocera_vlan, 684),
      vocera_multicast_pool: form.vocera_multicast_pool.trim() || undefined,
      sender_mac: form.sender_mac.trim() || undefined,
      sender_ip: form.sender_ip.trim() || undefined,
      receiver_mac: form.receiver_mac.trim() || undefined,
      receiver_ip: form.receiver_ip.trim() || undefined,
      continuous_export_enabled: form.continuous_export_enabled
    }
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const response = await createStudyMediaQoeWlcSession(studyId, payload)
      setCommandSheets(response.command_sheets ?? {})
      setMessage(response.message ?? 'Created WLC capture session.')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to create WLC capture session')
    } finally {
      setBusy(false)
    }
  }

  const patchSession = async (session: StringRow, state: 'running' | 'stopped' | 'exported' | 'aborted') => {
    const sessionId = field(session, 'session_id')
    if (!sessionId) {
      return
    }
    setBusy(true)
    setError(null)
    try {
      await updateMediaQoeWlcSession(sessionId, {
        session_state: state,
        capture_started_at: state === 'running' ? nowIso() : undefined,
        capture_stopped_at: state === 'stopped' || state === 'exported' || state === 'aborted' ? nowIso() : undefined
      })
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to update WLC session')
    } finally {
      setBusy(false)
    }
  }

  const markEvent = async (session: StringRow | undefined, eventKind: 'broadcast_started' | 'heard' | 'missed' | 'partial' | 'choppy' | 'alert_only' | 'session_end') => {
    const sessionId = field(session, 'session_id')
    if (!sessionId) {
      setError('Create or select a Vocera multicast capture session before marking an event.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const response = await createMediaQoeWlcSessionEvent(sessionId, {
        event_kind: eventKind,
        event_time: nowIso(),
        browser_event_time: nowIso()
      })
      if (response.attempt_id) {
        setCurrentAttemptId(response.attempt_id)
      }
      setMessage(response.attempt_id ? `Marked ${eventKind}: ${response.attempt_id}` : `Marked ${eventKind}.`)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to mark WLC session event')
    } finally {
      setBusy(false)
    }
  }

  return (
    <CollapsibleCard title="Vocera Multicast Capture Sessions" eyebrow="Manual WLC EPC workflow" defaultOpen={true}>
      <div className="space-y-5">
        <div className="grid gap-3 md:grid-cols-4">
          <label className="space-y-1 text-sm text-slate-300">
            <span>Session ID</span>
            <input className={textInputClass()} value={form.session_id} onChange={(event) => updateForm('session_id', event.target.value)} placeholder="auto" />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Capture Name</span>
            <input className={textInputClass()} value={form.capture_name} onChange={(event) => updateForm('capture_name', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>WLC</span>
            <input className={textInputClass()} value={form.wlc_name} onChange={(event) => updateForm('wlc_name', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Interface</span>
            <input className={textInputClass()} value={form.wlc_interface} onChange={(event) => updateForm('wlc_interface', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Collector Host</span>
            <input className={textInputClass()} value={form.collector_host} onChange={(event) => updateForm('collector_host', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>SCP Username</span>
            <input className={textInputClass()} value={form.collector_scp_username} onChange={(event) => updateForm('collector_scp_username', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Ring Files</span>
            <input className={textInputClass()} value={form.ring_file_count} onChange={(event) => updateForm('ring_file_count', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>File MB</span>
            <input className={textInputClass()} value={form.ring_file_size_mb} onChange={(event) => updateForm('ring_file_size_mb', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Vocera Pool</span>
            <input className={textInputClass()} value={form.vocera_multicast_pool} onChange={(event) => updateForm('vocera_multicast_pool', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300 md:col-span-2">
            <span>Configured Vocera multicast VLAN</span>
            <input className={textInputClass()} value={form.vocera_vlan} onChange={(event) => updateForm('vocera_vlan', event.target.value)} />
            <span className="block text-xs text-slate-500">
              Used to generate WLC multicast-group, IGMP, MGID, and source queries. Badge client VLAN observations do not automatically change this value.
            </span>
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Sender MAC</span>
            <input className={textInputClass()} value={form.sender_mac} onChange={(event) => updateForm('sender_mac', event.target.value)} />
          </label>
          <label className="space-y-1 text-sm text-slate-300">
            <span>Receiver MAC</span>
            <input className={textInputClass()} value={form.receiver_mac} onChange={(event) => updateForm('receiver_mac', event.target.value)} />
          </label>
          <label className="flex items-center gap-2 pt-7 text-sm text-slate-300">
            <input type="checkbox" checked={form.continuous_export_enabled} onChange={(event) => updateForm('continuous_export_enabled', event.target.checked)} />
            Continuous export
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <button className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-slate-950 disabled:opacity-50" disabled={!studyId || busy} onClick={() => { void createSession() }}>
            Create Session
          </button>
          <button className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={!studyId || loading} onClick={() => { void refresh() }}>
            Refresh
          </button>
          {latestRunningSession && (
            <>
              <button className="rounded-lg border border-emerald-500/60 px-3 py-2 text-sm text-emerald-100 disabled:opacity-50" disabled={busy} onClick={() => { void patchSession(latestRunningSession, 'running') }}>
                Mark Running
              </button>
              <button className="rounded-lg border border-amber-500/60 px-3 py-2 text-sm text-amber-100 disabled:opacity-50" disabled={busy} onClick={() => { void patchSession(latestRunningSession, 'stopped') }}>
                Mark Stopped
              </button>
            </>
          )}
        </div>

        <div className="flex flex-wrap gap-2">
          {(['broadcast_started', 'heard', 'missed', 'partial', 'choppy', 'alert_only', 'session_end'] as const).map((eventKind) => (
            <button key={eventKind} className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy || !latestRunningSession} onClick={() => { void markEvent(latestRunningSession, eventKind) }}>
              {eventKind.replaceAll('_', ' ')}
            </button>
          ))}
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">
          {defaults?.password_policy.message ?? 'Manual mode does not collect WLC or SCP secrets.'}
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3 text-sm text-slate-300">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-500">Observed VLAN context</p>
          <div className="mt-2 grid gap-2 md:grid-cols-5">
            <span>Sender client VLAN: unknown until imported</span>
            <span>Sender multicast VLAN: unknown until imported</span>
            <span>Receiver client VLAN: unknown until imported</span>
            <span>Receiver multicast VLAN: unknown until imported</span>
            <span>Active group VLAN: {activeGroupVlan || 'unknown until selected'}</span>
          </div>
        </div>

        <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-3">
          <div className="grid gap-3 lg:grid-cols-[1fr_auto] lg:items-end">
            <label className="space-y-1 text-sm text-slate-300">
              <span>Group summary paste</span>
              <textarea
                className="min-h-24 w-full rounded-lg border border-slate-700 bg-slate-950/70 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400"
                value={groupSummaryText}
                onChange={(event) => setGroupSummaryText(event.target.value)}
                placeholder="Paste show wireless multicast group summary output"
              />
            </label>
            <button className="rounded-lg border border-slate-700 px-3 py-2 text-sm text-slate-200 disabled:opacity-50" disabled={busy || !groupSummaryText.trim()} onClick={setActiveGroupFromSummary}>
              Find Active Group Candidates
            </button>
          </div>
          {groupCandidates.length > 0 && (
            <div className="mt-3 overflow-auto rounded-lg border border-slate-800">
              <table className="min-w-full divide-y divide-slate-800 text-sm">
                <thead className="bg-slate-950/60 text-left text-xs uppercase tracking-wide text-slate-400">
                  <tr>
                    <th className="px-3 py-2">Dynamic group</th>
                    <th className="px-3 py-2">Observed VLAN</th>
                    <th className="px-3 py-2">Candidate MGID</th>
                    <th className="px-3 py-2">Select</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {groupCandidates.map((candidate) => {
                    const configuredVlan = numericValue(form.vocera_vlan, 684)
                    const mismatch = candidate.vlan !== configuredVlan
                    return (
                      <tr key={`${candidate.group}-${candidate.vlan}-${candidate.mgid ?? 'none'}`} className="text-slate-200">
                        <td className="px-3 py-2 font-mono text-xs">{candidate.group}</td>
                        <td className="px-3 py-2">{candidate.vlan}{mismatch ? ' (differs from configured)' : ''}</td>
                        <td className="px-3 py-2">{candidate.mgid ?? 'unknown'}</td>
                        <td className="px-3 py-2">
                          <button className="rounded-lg border border-cyan-500/60 px-3 py-1 text-xs text-cyan-100 disabled:opacity-50" disabled={busy} onClick={() => { void selectActiveGroupCandidate(candidate) }}>
                            Use
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
          <label className="mt-3 block space-y-1 text-sm text-slate-300">
            <span>Override active-group VLAN reason</span>
            <input
              className={textInputClass()}
              value={overrideReason}
              onChange={(event) => setOverrideReason(event.target.value)}
              placeholder="Required only when selected group VLAN differs from configured VLAN"
            />
          </label>
          <p className="mt-2 text-xs text-slate-500">
            Configured VLAN: {form.vocera_vlan || 'not set'}; active group: {activeGroup || 'not set'}; active group VLAN: {activeGroupVlan || 'unresolved'}.
            Command previews replace only visible placeholders and do not hide the original transcript evidence requirement.
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Group selection binds to attempt: {currentAttemptId ?? 'none yet — mark a broadcast first'}
            {attempts.length > 0 ? ` (${attempts.length} attempt${attempts.length === 1 ? '' : 's'} this session).` : '.'}
          </p>
        </div>

        {error && <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-3 text-sm text-rose-100">{error}</div>}
        {message && <div className="rounded-lg border border-emerald-900 bg-emerald-950/30 p-3 text-sm text-emerald-100">{message}</div>}

        {Object.keys(displayedCommandSheets).length > 0 && (
          <div className="space-y-2">
            {Object.entries(displayedCommandSheets).map(([name, text]) => (
              <details key={name} className="rounded-lg border border-slate-800 bg-slate-950/50 p-3">
                <summary className="cursor-pointer text-sm font-semibold text-slate-200">{name}</summary>
                <pre className="mt-3 max-h-80 overflow-auto whitespace-pre-wrap text-xs text-slate-300">{text}</pre>
              </details>
            ))}
          </div>
        )}

        <div className="overflow-auto rounded-lg border border-slate-800">
          <table className="min-w-full divide-y divide-slate-800 text-sm">
            <thead className="bg-slate-950/60 text-left text-xs uppercase tracking-wide text-slate-400">
              <tr>
                <th className="px-3 py-2">Session</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Capture</th>
                <th className="px-3 py-2">Interface</th>
                <th className="px-3 py-2">Ring</th>
                <th className="px-3 py-2">Configured VLAN</th>
                <th className="px-3 py-2">Resolved VLAN</th>
                <th className="px-3 py-2">Attempts</th>
                <th className="px-3 py-2">Events</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {sessions.map((session) => (
                <tr key={field(session, 'session_id')} className="text-slate-200">
                  <td className="px-3 py-2 font-mono text-xs">{field(session, 'session_id')}</td>
                  <td className="px-3 py-2">{field(session, 'session_state')}</td>
                  <td className="px-3 py-2">{field(session, 'capture_name')}</td>
                  <td className="px-3 py-2">{field(session, 'wlc_interface')}</td>
                  <td className="px-3 py-2">{field(session, 'ring_total_size_mb')} MB</td>
                  <td className="px-3 py-2">{field(session, 'configured_vocera_vlan', '684')}</td>
                  <td className="px-3 py-2">{field(session, 'resolved_group_vlan', 'unresolved')}</td>
                  <td className="px-3 py-2">{field(session, 'attempt_count', '0')}</td>
                  <td className="px-3 py-2">{field(session, 'event_count', '0')}</td>
                </tr>
              ))}
              {sessions.length === 0 && (
                <tr>
                  <td className="px-3 py-6 text-center text-slate-500" colSpan={9}>
                    No WLC capture sessions found for this study.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </CollapsibleCard>
  )
}
