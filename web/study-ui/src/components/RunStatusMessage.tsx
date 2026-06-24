/**
 * Normalizes raw execution error messages into user-friendly status messages.
 * Maps common failure patterns to helpful diagnostics.
 */
export function RunStatusMessage({ status, error, badgeEventCount, surveyPointCount, sameDateOverlapCount }: { status?: string; error?: string; badgeEventCount?: number; surveyPointCount?: number; sameDateOverlapCount?: number }) {
  // Determine status color and icon
  const getStatusColor = (): { bg: string; border: string; text: string; icon: string } => {
    if (status === 'failed') {
      return { bg: 'bg-rose-400/10', border: 'border-rose-400/30', text: 'text-rose-100', icon: '✕' }
    }
    if (status === 'running') {
      return { bg: 'bg-amber-400/10', border: 'border-amber-400/30', text: 'text-amber-100', icon: '⋯' }
    }
    if (status === 'complete') {
      return { bg: 'bg-emerald-400/10', border: 'border-emerald-400/30', text: 'text-emerald-100', icon: '✓' }
    }
    return { bg: 'bg-slate-400/10', border: 'border-slate-400/30', text: 'text-slate-100', icon: '○' }
  }

  const normalizeError = (rawError: string): { title: string; details: string } => {
    if (!rawError) {
      return { title: 'No status available', details: '' }
    }

    const trimmed = rawError.trim().toLowerCase()

    // Parse badge event failures
    if (trimmed.includes('no badge scan events') || trimmed.includes('badge scan events') && trimmed.includes('0')) {
      return {
        title: 'Run failed: no badge scan events found',
        details: 'The selected badge archive is valid, but it does not contain roam/candidate scan blocks. Check that the file is from an active discovery session.'
      }
    }

    // Parse Ekahau failures
    if (trimmed.includes('no survey') || trimmed.includes('no ekahau') || trimmed.includes('ekahau') && trimmed.includes('not found')) {
      return {
        title: 'Run failed: no Ekahau survey data found',
        details: 'The selected Ekahau file does not contain survey point data, or the file could not be parsed. Verify the file is a valid Ekahau JSON or ESX export.'
      }
    }

    // Parse date overlap failures
    if (trimmed.includes('same-date overlap') || trimmed.includes('no same-date') || trimmed.includes('overlap') && trimmed.includes('0')) {
      return {
        title: 'Run complete: no matching rows',
        details: badgeEventCount !== undefined && surveyPointCount !== undefined && sameDateOverlapCount !== undefined
          ? `Badge has data from ${badgeEventCount} events, Ekahau has ${surveyPointCount} points, but they do not overlap on the same date. Verify the survey dates and badge capture dates align.`
          : 'Badge and Ekahau data exist but do not overlap on the same date. Verify both files contain data from matching dates.'
      }
    }

    // Parse file/path errors
    if (trimmed.includes('not available on disk') || trimmed.includes('file') && trimmed.includes('not found')) {
      return {
        title: 'Run failed: source file not available',
        details: 'The selected badge or Ekahau file could not be found on disk. The file may have been moved or deleted. Try uploading it again.'
      }
    }

    // Parse generic command failures
    if (trimmed.includes('command failed')) {
      const match = rawError.match(/exit code (\d+)/)
      const exitCode = match ? match[1] : 'unknown'
      return {
        title: `Run failed: command error (exit code ${exitCode})`,
        details: rawError.length > 100 ? rawError.substring(0, 100) + '...' : rawError
      }
    }

    // Fallback for unknown errors
    return {
      title: 'Run failed',
      details: rawError.length > 150 ? rawError.substring(0, 150) + '...' : rawError
    }
  }

  const statusColor = getStatusColor()
  const errorMessage = normalizeError(error || '')

  return (
    <div className={`rounded-2xl border ${statusColor.border} ${statusColor.bg} p-4`}>
      <div className="flex items-start gap-3">
        <div className={`text-xl ${statusColor.text} font-bold flex-shrink-0 w-6 h-6 flex items-center justify-center`}>{statusColor.icon}</div>
        <div className="flex-1">
          <p className={`font-semibold ${statusColor.text}`}>{errorMessage.title}</p>
          {errorMessage.details && <p className={`mt-2 text-sm ${statusColor.text.replace('100', '200')}`}>{errorMessage.details}</p>}
        </div>
      </div>
    </div>
  )
}
