<#
Runs the configured laptop role indefinitely until stopped.
Normally started by Start-VoceraIperfRole.ps1.
#>
param(
    [string]$ConfigPath = "C:\VoceraIperf\config\role.json"
)

$ErrorActionPreference = "Continue"

if (-not (Test-Path $ConfigPath)) {
    throw "Config not found: $ConfigPath. Run a Setup-Laptop*.ps1 script first."
}

$config = Get-Content $ConfigPath -Raw | ConvertFrom-Json

$device = $config.DeviceName
$localBase = $config.LocalBasePath
$stateDir = Join-Path $localBase "$device\state"
$logDir = Join-Path $localBase "$device\logs"
New-Item -ItemType Directory -Force -Path $stateDir,$logDir | Out-Null

$pidFile = Join-Path $stateDir "vocera_role_loop.pid"
$stopFile = Join-Path $stateDir "vocera_role_loop.stop"
$heartbeatFile = Join-Path $stateDir "vocera_role_loop.heartbeat"
$logFile = Join-Path $logDir ("vocera_role_loop-{0}.log" -f (Get-Date -Format "yyyyMMdd-HHmmss"))

# Write one timestamped role-loop log line to console and file.
function Write-RoleLog {
    param([string]$Level, [string]$Message)
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    $line | Tee-Object -FilePath $logFile -Append
}

# Return true when the stop-request file is present.
function Stop-Requested {
    return Test-Path $stopFile
}

# Sleep in one-second increments so stop requests are honored quickly.
function Sleep-WithStopCheck {
    param([int]$Seconds)
    for ($i = 0; $i -lt $Seconds; $i++) {
        if (Stop-Requested) { return $true }
        Start-Sleep -Seconds 1
        if (($i % 10) -eq 0) {
            Get-Date -Format "yyyy-MM-dd HH:mm:ss" | Set-Content -Path $heartbeatFile -Encoding ASCII
        }
    }
    return $false
}

try {
    $PID | Set-Content -Path $pidFile -Encoding ASCII
    Remove-Item $stopFile -Force -ErrorAction SilentlyContinue

    $oneShot = Join-Path $config.InstallRoot "windows\Run-VoceraIperfOneShotAndScp.ps1"
    if (-not (Test-Path $oneShot)) { throw "One-shot script not found: $oneShot" }

    Write-RoleLog "INFO" "Started role loop. PID=$PID Role=$($config.Role) Mode=$($config.Mode) Device=$device"

    while ($true) {
        Get-Date -Format "yyyy-MM-dd HH:mm:ss" | Set-Content -Path $heartbeatFile -Encoding ASCII

        if (Stop-Requested) {
            Write-RoleLog "INFO" "Stop requested before run."
            break
        }

        $args = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-File", $oneShot,
            "-Mode", $config.Mode,
            "-IperfPath", $config.IperfPath,
            "-ServerPort", "$($config.ServerPort)",
            "-PeerPort", "$($config.PeerPort)",
            "-CollectorHost", $config.CollectorHost,
            "-CollectorUser", $config.CollectorUser,
            "-SSHKeyPath", $config.SSHKeyPath,
            "-RemoteBasePath", $config.RemoteBasePath,
            "-LocalBasePath", $config.LocalBasePath,
            "-DeviceName", $config.DeviceName,
            "-Role", $config.Role,
            "-Site", $config.Site,
            "-SSID", $config.SSID,
            "-DurationSeconds", "$($config.DurationSeconds)",
            "-Bitrate", $config.Bitrate,
            "-PayloadBytes", "$($config.PayloadBytes)",
            "-Tos", $config.Tos
        )

        if ($null -ne $config.LatencyProbeCount) {
            $args += @("-LatencyProbeCount", "$($config.LatencyProbeCount)")
        }
        if ($null -ne $config.LatencyProbeTimeoutMilliseconds) {
            $args += @("-LatencyProbeTimeoutMilliseconds", "$($config.LatencyProbeTimeoutMilliseconds)")
        }

        if ($config.ServerIP) { $args += @("-ServerIP", $config.ServerIP) }
        if ($config.PeerIP) { $args += @("-PeerIP", $config.PeerIP) }

        try {
            Write-RoleLog "INFO" "Starting test run: Mode=$($config.Mode)"
            & powershell.exe @args 2>&1 | Tee-Object -FilePath $logFile -Append
            if ($LASTEXITCODE -eq 0) {
                Write-RoleLog "INFO" "Test/upload run completed."
            } else {
                Write-RoleLog "ERROR" "Test/upload run returned exit code $LASTEXITCODE. Loop continues."
            }
        } catch {
            Write-RoleLog "ERROR" "Test/upload exception: $($_.Exception.Message). Loop continues."
        }

        if (Stop-Requested) {
            Write-RoleLog "INFO" "Stop requested after run."
            break
        }

        $sleepSeconds = [Math]::Max(1, [int]$config.IntervalMinutes * 60)
        Write-RoleLog "INFO" "Sleeping $sleepSeconds seconds."
        if (Sleep-WithStopCheck -Seconds $sleepSeconds) {
            Write-RoleLog "INFO" "Stop requested during sleep."
            break
        }
    }
} finally {
    Write-RoleLog "INFO" "Role loop exiting."
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
    Remove-Item $stopFile -Force -ErrorAction SilentlyContinue
}
