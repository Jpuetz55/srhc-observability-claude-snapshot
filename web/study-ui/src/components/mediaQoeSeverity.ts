import type { StringRow } from '../api/types'

export const MEDIA_QOE_THRESHOLDS = {
  lossWarning: 0.01,
  lossCritical: 0.05,
  jitterWarningMs: 10,
  jitterCriticalMs: 20,
  interarrivalWarningMs: 25,
  interarrivalCriticalMs: 40
}

export type MediaStreamSeverityLevel = 'muted' | 'critical' | 'warning' | 'info' | 'good'

export type MediaStreamSeverity = {
  level: MediaStreamSeverityLevel
  label: string
  reasons: string[]
}

export type MediaStreamDscpContext = {
  label: 'Trusted RTP DSCP mismatch' | 'Non-RTP DSCP mismatch'
  status: 'trusted_rtp_dscp_mismatch' | 'non_rtp_dscp_mismatch'
  tone: 'warning' | 'info'
}

export type MediaCaptureTrustedRtpBadge = {
  label: 'Trusted RTP found' | 'No trusted RTP detected'
  status: 'trusted_rtp_found' | 'no_trusted_rtp_detected'
}

export type MediaCaptureConcernBadge = {
  label: 'Loss detected' | 'High loss' | 'Jitter review' | 'High jitter' | 'Interarrival review' | 'High interarrival' | 'Trusted RTP DSCP mismatch found' | 'Only non-RTP DSCP mismatch found' | 'DSCP mismatch present'
  status: 'loss_detected' | 'high_loss' | 'jitter_review' | 'high_jitter' | 'interarrival_review' | 'high_interarrival' | 'trusted_rtp_dscp_mismatch_found' | 'only_non_rtp_dscp_mismatch_found' | 'dscp_mismatch_present'
}

export type CaptureUsefulnessStatus = 'not_parsed' | 'parse_failed' | 'no_usable_rtp' | 'useful_rtp' | 'needs_review'

export type CaptureUsefulnessSummary = {
  status: CaptureUsefulnessStatus
  label: 'Not parsed' | 'Parse failed' | 'No usable RTP' | 'Useful RTP capture' | 'Needs review'
  tone: 'muted' | 'danger' | 'warning' | 'success' | 'info'
  description: string
}

export type MediaCaptureUsefulnessRow = {
  capture_status?: string | null
  parse_success?: string | number | boolean | null
  parse_exit_code?: string | number | null
  parsed_at?: string | null
  rtp_qoe_stream_count?: string | number | null
  dscp_mismatch_stream_count?: string | number | null
  trusted_rtp_dscp_mismatch_stream_count?: string | number | null
  non_rtp_dscp_mismatch_stream_count?: string | number | null
  lossy_stream_count?: string | number | null
  loss_p95_ratio?: string | number | null
  jitter_p95_ms?: string | number | null
  interarrival_p95_ms?: string | number | null
}

export function field(row: StringRow, key: string, fallback = ''): string {
  return row[key] ?? fallback
}

export function numberValue(value: string | number | null | undefined): number | null {
  if (value === undefined || value === null || value === '') {
    return null
  }
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

export function isTruthy(value: string | number | boolean | null | undefined): boolean {
  if (typeof value === 'boolean') {
    return value
  }
  if (typeof value === 'number') {
    return value === 1
  }
  return value === 'true' || value === 't' || value === '1' || value === 'yes'
}

export function isFalsey(value: string | number | boolean | null | undefined): boolean {
  if (typeof value === 'boolean') {
    return !value
  }
  if (typeof value === 'number') {
    return value === 0
  }
  return value === 'false' || value === 'f' || value === '0' || value === 'no'
}

export function streamKey(stream: StringRow): string {
  return `${field(stream, 'capture_id')}-${field(stream, 'stream_id')}`
}

export function getMediaStreamDscpContext(stream: StringRow): MediaStreamDscpContext | null {
  if (!isTruthy(field(stream, 'dscp_mismatch'))) {
    return null
  }

  const measurementMode = field(stream, 'measurement_mode').toLowerCase()
  if (measurementMode === 'rtp') {
    return {
      label: 'Trusted RTP DSCP mismatch',
      status: 'trusted_rtp_dscp_mismatch',
      tone: 'warning'
    }
  }

  return {
    label: 'Non-RTP DSCP mismatch',
    status: 'non_rtp_dscp_mismatch',
    tone: 'info'
  }
}

export function getCaptureConcernBadges(capture: MediaCaptureUsefulnessRow): MediaCaptureConcernBadge[] {
  if ((capture.capture_status || '').toLowerCase() !== 'complete' || !isTruthy(capture.parse_success)) {
    return []
  }

  const badges: MediaCaptureConcernBadge[] = []
  const lossP95Ratio = numberValue(capture.loss_p95_ratio) ?? 0
  const lossyStreamCount = numberValue(capture.lossy_stream_count) ?? 0
  const jitterP95Ms = numberValue(capture.jitter_p95_ms) ?? 0
  const interarrivalP95Ms = numberValue(capture.interarrival_p95_ms) ?? 0
  const trustedRtpDscpMismatchStreamCount = numberValue(capture.trusted_rtp_dscp_mismatch_stream_count) ?? 0
  const nonRtpDscpMismatchStreamCount = numberValue(capture.non_rtp_dscp_mismatch_stream_count) ?? 0
  const dscpMismatchStreamCount = numberValue(capture.dscp_mismatch_stream_count) ?? 0

  if (lossP95Ratio >= 0.03) {
    badges.push({ label: 'High loss', status: 'high_loss' })
  } else if (lossP95Ratio > 0 || lossyStreamCount > 0) {
    badges.push({ label: 'Loss detected', status: 'loss_detected' })
  }

  if (jitterP95Ms >= MEDIA_QOE_THRESHOLDS.jitterCriticalMs) {
    badges.push({ label: 'High jitter', status: 'high_jitter' })
  } else if (jitterP95Ms >= MEDIA_QOE_THRESHOLDS.jitterWarningMs) {
    badges.push({ label: 'Jitter review', status: 'jitter_review' })
  }

  if (interarrivalP95Ms >= 30) {
    badges.push({ label: 'High interarrival', status: 'high_interarrival' })
  } else if (interarrivalP95Ms >= MEDIA_QOE_THRESHOLDS.interarrivalWarningMs) {
    badges.push({ label: 'Interarrival review', status: 'interarrival_review' })
  }

  if (trustedRtpDscpMismatchStreamCount > 0) {
    badges.push({ label: 'Trusted RTP DSCP mismatch found', status: 'trusted_rtp_dscp_mismatch_found' })
  } else if (nonRtpDscpMismatchStreamCount > 0) {
    badges.push({ label: 'Only non-RTP DSCP mismatch found', status: 'only_non_rtp_dscp_mismatch_found' })
  } else if (dscpMismatchStreamCount > 0) {
    badges.push({ label: 'DSCP mismatch present', status: 'dscp_mismatch_present' })
  }

  return badges
}

export function getCaptureTrustedRtpBadge(capture: MediaCaptureUsefulnessRow): MediaCaptureTrustedRtpBadge | null {
  if ((capture.capture_status || '').toLowerCase() !== 'complete' || !isTruthy(capture.parse_success)) {
    return null
  }
  const trustedRtpCount = numberValue(capture.rtp_qoe_stream_count) ?? 0
  if (trustedRtpCount > 0) {
    return { label: 'Trusted RTP found', status: 'trusted_rtp_found' }
  }
  return { label: 'No trusted RTP detected', status: 'no_trusted_rtp_detected' }
}

export function getCaptureUsefulnessSummary(capture: MediaCaptureUsefulnessRow): CaptureUsefulnessSummary {
  const status = (capture.capture_status || '').toLowerCase()
  const parseExitCode = numberValue(capture.parse_exit_code)
  if (status === 'failed' || isFalsey(capture.parse_success) || (parseExitCode !== null && parseExitCode !== 0)) {
    return {
      status: 'parse_failed',
      label: 'Parse failed',
      tone: 'danger',
      description: 'Parser failed. Review parse logs or retry.'
    }
  }

  if (status !== 'complete' || !isTruthy(capture.parse_success)) {
    return {
      status: 'not_parsed',
      label: 'Not parsed',
      tone: 'muted',
      description: 'Registered but not parsed yet.'
    }
  }

  const trustedRtpCount = numberValue(capture.rtp_qoe_stream_count) ?? 0
  if (trustedRtpCount <= 0) {
    return {
      status: 'no_usable_rtp',
      label: 'No usable RTP',
      tone: 'warning',
      description: 'Parsed successfully, but no trusted RTP streams were detected.'
    }
  }

  if (getCaptureConcernBadges(capture).length) {
    return {
      status: 'needs_review',
      label: 'Needs review',
      tone: 'warning',
      description: 'Trusted RTP was found, but QoE or marking concerns were detected.'
    }
  }

  return {
    status: 'useful_rtp',
    label: 'Useful RTP capture',
    tone: 'success',
    description: 'Trusted RTP was found and no capture-level concerns were detected.'
  }
}

export function getMediaStreamSeverity(stream: StringRow): MediaStreamSeverity {
  const reviewStatus = field(stream, 'review_status', 'unreviewed').toLowerCase()
  const classification = field(stream, 'stream_classification').toLowerCase()
  if (reviewStatus === 'excluded' || ['exclude', 'noise', 'control'].includes(classification)) {
    return { level: 'muted', label: 'Muted', reasons: ['Excluded/noise/control'] }
  }

  const lossRatio = numberValue(field(stream, 'loss_ratio'))
  const jitterMs = numberValue(field(stream, 'jitter_ms'))
  const interarrivalP95Ms = numberValue(field(stream, 'interarrival_p95_ms'))
  const dscpContext = getMediaStreamDscpContext(stream)
  const criticalReasons: string[] = []
  const warningReasons: string[] = []

  if (lossRatio !== null && lossRatio >= MEDIA_QOE_THRESHOLDS.lossCritical) {
    criticalReasons.push('Loss critical')
  } else if (lossRatio !== null && lossRatio >= MEDIA_QOE_THRESHOLDS.lossWarning) {
    warningReasons.push('Loss warning')
  }

  if (jitterMs !== null && jitterMs >= MEDIA_QOE_THRESHOLDS.jitterCriticalMs) {
    criticalReasons.push('Jitter critical')
  } else if (jitterMs !== null && jitterMs >= MEDIA_QOE_THRESHOLDS.jitterWarningMs) {
    warningReasons.push('Jitter warning')
  }

  if (interarrivalP95Ms !== null && interarrivalP95Ms >= MEDIA_QOE_THRESHOLDS.interarrivalCriticalMs) {
    criticalReasons.push('Timing critical')
  } else if (interarrivalP95Ms !== null && interarrivalP95Ms >= MEDIA_QOE_THRESHOLDS.interarrivalWarningMs) {
    warningReasons.push('Timing warning')
  }

  if (dscpContext) {
    warningReasons.push(dscpContext.label)
  }

  if (criticalReasons.length) {
    return { level: 'critical', label: 'Critical', reasons: criticalReasons }
  }
  if (warningReasons.length) {
    return { level: 'warning', label: 'Warning', reasons: warningReasons }
  }

  const measurementMode = field(stream, 'measurement_mode').toLowerCase()
  const packetCount = numberValue(field(stream, 'packet_count')) ?? 0
  if (measurementMode === 'rtp' && packetCount >= 20) {
    return { level: 'good', label: 'Good RTP', reasons: ['RTP QoE stream'] }
  }
  if (measurementMode && measurementMode !== 'rtp') {
    return { level: 'info', label: 'Info', reasons: ['Non-RTP/unknown'] }
  }
  return { level: 'info', label: 'Info', reasons: ['Needs classification'] }
}
