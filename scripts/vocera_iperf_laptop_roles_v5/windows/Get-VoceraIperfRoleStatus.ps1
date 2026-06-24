<#
Shows status for the configured laptop role.
#>
param(
    [string]$ConfigPath = "C:\VoceraIperf\config\role.json"
)

if (-not (Test-Path $ConfigPath)) {
    Write-Host "Config not found: $ConfigPath"
    exit 1
}

$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$device = $config.DeviceName
$stateDir = Join-Path $config.LocalBasePath "$device\state"
$logDir = Join-Path $config.LocalBasePath "$device\logs"
$rawDir = Join-Path $config.LocalBasePath "$device\raw"

$loopPidFile = Join-Path $stateDir "vocera_role_loop.pid"
$loopStopFile = Join-Path $stateDir "vocera_role_loop.stop"
$loopHeartbeat = Join-Path $stateDir "vocera_role_loop.heartbeat"
$peerPidFile = Join-Path $stateDir "vocera_peer_server.pid"

# Return process status from a PID file, or null when the file is absent/invalid.
function Get-PidStatus {
    param([string]$Path)
    if (-not (Test-Path $Path)) { return $null }
    $txt = Get-Content $Path -Raw -ErrorAction SilentlyContinue
    $pidValue = 0
    if (-not [int]::TryParse(($txt -as [string]).Trim(), [ref]$pidValue)) { return $null }
    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    return [PSCustomObject]@{
        PID = $pidValue
        Running = [bool]$proc
        ProcessName = if ($proc) { $proc.ProcessName } else { $null }
    }
}

$loop = Get-PidStatus -Path $loopPidFile
$peer = Get-PidStatus -Path $peerPidFile

$heartbeat = ""
if (Test-Path $loopHeartbeat) {
    $heartbeat = (Get-Content $loopHeartbeat -Raw -ErrorAction SilentlyContinue).Trim()
}

[PSCustomObject]@{
    Role = $config.Role
    Mode = $config.Mode
    Device = $device
    SSID = $config.SSID
    LoopRunning = if ($loop) { $loop.Running } else { $false }
    LoopPID = if ($loop) { $loop.PID } else { $null }
    PeerReceiverEnabled = $config.StartPeerReceiver
    PeerReceiverRunning = if ($peer) { $peer.Running } else { $false }
    PeerReceiverPID = if ($peer) { $peer.PID } else { $null }
    StopRequested = Test-Path $loopStopFile
    Heartbeat = $heartbeat
    RawDir = $rawDir
    LogDir = $logDir
} | Format-List

if (Test-Path $rawDir) {
    Write-Host ""
    Write-Host "Latest raw files:"
    Get-ChildItem $rawDir -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 FullName,LastWriteTime,Length |
        Format-Table -AutoSize
}

if (Test-Path $logDir) {
    Write-Host ""
    Write-Host "Latest logs:"
    Get-ChildItem $logDir -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 10 FullName,LastWriteTime,Length |
        Format-Table -AutoSize
}
