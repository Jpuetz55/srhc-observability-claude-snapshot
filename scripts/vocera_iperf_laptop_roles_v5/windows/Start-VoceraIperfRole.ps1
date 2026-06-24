<#
Starts the configured laptop role.
- Laptop A: starts peer receiver and test loop.
- Laptop B: starts test loop.
#>
param(
    [string]$ConfigPath = "C:\VoceraIperf\config\role.json"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath. Run a Setup-Laptop*.ps1 script first."
}

$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$device = $config.DeviceName
$stateDir = Join-Path $config.LocalBasePath "$device\state"
$logDir = Join-Path $config.LocalBasePath "$device\logs"
New-Item -ItemType Directory -Force -Path $stateDir,$logDir | Out-Null

$loopPidFile = Join-Path $stateDir "vocera_role_loop.pid"
$loopStopFile = Join-Path $stateDir "vocera_role_loop.stop"
$peerPidFile = Join-Path $stateDir "vocera_peer_server.pid"

Remove-Item $loopStopFile -Force -ErrorAction SilentlyContinue

if ($config.StartPeerReceiver -eq $true) {
    $existingPeerPid = $null
    if (Test-Path $peerPidFile) {
        $txt = Get-Content $peerPidFile -Raw -ErrorAction SilentlyContinue
        $parsed = 0
        if ([int]::TryParse(($txt -as [string]).Trim(), [ref]$parsed)) { $existingPeerPid = $parsed }
    }

    if ($existingPeerPid -and (Get-Process -Id $existingPeerPid -ErrorAction SilentlyContinue)) {
        Write-Host "Peer receiver already running. PID=$existingPeerPid"
    } else {
        $peerLogBase = Join-Path $logDir ("vocera_peer_server-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
        $peerStdout = $peerLogBase -replace "\.log$", "-stdout.log"
        $peerStderr = $peerLogBase -replace "\.log$", "-stderr.log"

        $peerArgs = @("-s", "-p", "$($config.PeerPort)")
        $proc = Start-Process -FilePath $config.IperfPath `
            -ArgumentList $peerArgs `
            -WindowStyle Minimized `
            -RedirectStandardOutput $peerStdout `
            -RedirectStandardError $peerStderr `
            -PassThru

        $proc.Id | Set-Content -Path $peerPidFile -Encoding ASCII
        Write-Host "Started peer receiver on port $($config.PeerPort). PID=$($proc.Id)"
    }
}

$existingLoopPid = $null
if (Test-Path $loopPidFile) {
    $txt = Get-Content $loopPidFile -Raw -ErrorAction SilentlyContinue
    $parsed = 0
    if ([int]::TryParse(($txt -as [string]).Trim(), [ref]$parsed)) { $existingLoopPid = $parsed }
}

if ($existingLoopPid -and (Get-Process -Id $existingLoopPid -ErrorAction SilentlyContinue)) {
    throw "Role loop already running. PID=$existingLoopPid"
}

$runner = Join-Path $config.InstallRoot "windows\Run-VoceraIperfRoleLoop.ps1"
if (-not (Test-Path $runner)) { throw "Runner not found: $runner" }

$startLogBase = Join-Path $logDir ("vocera_role_loop-start-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
$startStdout = $startLogBase -replace "\.log$", "-stdout.log"
$startStderr = $startLogBase -replace "\.log$", "-stderr.log"

$proc = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $runner, "-ConfigPath", $ConfigPath) `
    -WindowStyle Minimized `
    -RedirectStandardOutput $startStdout `
    -RedirectStandardError $startStderr `
    -PassThru

$proc.Id | Set-Content -Path $loopPidFile -Encoding ASCII

Write-Host "Started Vocera iperf role loop."
Write-Host "Role: $($config.Role)"
Write-Host "Mode: $($config.Mode)"
Write-Host "PID: $($proc.Id)"
Write-Host "Status:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Get-VoceraIperfRoleStatus.ps1"'
Write-Host "Stop:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Stop-VoceraIperfRole.ps1"'
