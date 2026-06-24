<#
Stops the configured laptop role.
#>
param(
    [string]$ConfigPath = "C:\VoceraIperf\config\role.json",
    [int]$GraceSeconds = 10,
    [switch]$DoNotKillRemainingIperf3
)

$ErrorActionPreference = "Continue"

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath."
}

$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
$device = $config.DeviceName
$stateDir = Join-Path $config.LocalBasePath "$device\state"
New-Item -ItemType Directory -Force -Path $stateDir | Out-Null

$loopPidFile = Join-Path $stateDir "vocera_role_loop.pid"
$loopStopFile = Join-Path $stateDir "vocera_role_loop.stop"
$peerPidFile = Join-Path $stateDir "vocera_peer_server.pid"

"stop requested $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" | Set-Content -Path $loopStopFile -Encoding ASCII
Write-Host "Stop requested."

# Stop the process recorded in a PID file, waiting briefly before force kill.
function Stop-PidFromFile {
    param([string]$Path, [string]$Name)

    if (-not (Test-Path $Path)) {
        Write-Host "$Name PID file not found."
        return
    }

    $txt = Get-Content $Path -Raw -ErrorAction SilentlyContinue
    $pidValue = 0
    if (-not [int]::TryParse(($txt -as [string]).Trim(), [ref]$pidValue)) {
        Write-Warning "$Name PID file is invalid: $Path"
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
        return
    }

    $proc = Get-Process -Id $pidValue -ErrorAction SilentlyContinue
    if (-not $proc) {
        Write-Host "$Name PID $pidValue is not running."
        Remove-Item $Path -Force -ErrorAction SilentlyContinue
        return
    }

    Write-Host "Waiting up to $GraceSeconds seconds for $Name PID $pidValue..."
    $exited = $false
    for ($i = 0; $i -lt $GraceSeconds; $i++) {
        Start-Sleep -Seconds 1
        if (-not (Get-Process -Id $pidValue -ErrorAction SilentlyContinue)) {
            $exited = $true
            break
        }
    }

    if (-not $exited) {
        Write-Warning "Stopping $Name PID $pidValue."
        Stop-Process -Id $pidValue -Force -ErrorAction SilentlyContinue
    }

    Remove-Item $Path -Force -ErrorAction SilentlyContinue
}

Stop-PidFromFile -Path $loopPidFile -Name "role loop"

if ($config.StartPeerReceiver -eq $true) {
    Stop-PidFromFile -Path $peerPidFile -Name "peer receiver"
}

if (-not $DoNotKillRemainingIperf3) {
    $iperfProcesses = Get-Process -Name "iperf3" -ErrorAction SilentlyContinue
    if ($iperfProcesses) {
        Write-Warning "Stopping remaining iperf3.exe processes on this laptop."
        $iperfProcesses | Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item $loopStopFile -Force -ErrorAction SilentlyContinue
Write-Host "Stopped."
