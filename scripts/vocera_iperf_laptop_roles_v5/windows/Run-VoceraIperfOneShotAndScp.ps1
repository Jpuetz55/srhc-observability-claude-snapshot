<#
Runs one iperf test and uploads the wrapped JSON result to collectors01.

Modes:
  ClientToServer : iperf3 UDP test from this laptop -> server VM.
  ServerToClient : iperf3 reverse UDP test from server VM -> this laptop.
  ClientToPeer   : iperf3 UDP test from this laptop -> peer laptop.
#>
param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("ClientToServer","ServerToClient","ClientToPeer")]
    [string]$Mode,

    [string]$IperfPath = "C:\Tools\iperf3\iperf3.exe",
    [string]$ServerIP = "",
    [int]$ServerPort = 5201,
    [string]$PeerIP = "",
    [int]$PeerPort = 5203,

    [string]$CollectorHost = "collectors01",
    [string]$CollectorUser = "appsadmin",
    [int]$SSHPort = 22,
    [string]$SSHKeyPath = "$env:USERPROFILE\.ssh\vocera_iperf_ed25519",
    [string]$RemoteBasePath = "/var/lib/vocera-iperf-qoe/incoming",

    [string]$LocalBasePath = "C:\iperf-vocera-tests",
    [string]$DeviceName = $env:COMPUTERNAME,
    [string]$Role = "",

    [string]$Site = "srhc",
    [string]$SSID = "srhcvoice2",
    [int]$DurationSeconds = 60,
    [string]$Bitrate = "64K",
    [int]$PayloadBytes = 160,
    [string]$Tos = "0xb8",
    [int]$LatencyProbeCount = 5,
    [int]$LatencyProbeTimeoutMilliseconds = 1000
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $IperfPath)) { throw "IperfPath not found: $IperfPath" }
if (-not (Test-Path $SSHKeyPath)) { throw "SSHKeyPath not found: $SSHKeyPath" }

$rawDir = Join-Path $LocalBasePath "$DeviceName\raw"
$logDir = Join-Path $LocalBasePath "$DeviceName\logs"
New-Item -ItemType Directory -Force -Path $rawDir,$logDir | Out-Null

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$direction = switch ($Mode) {
    "ClientToServer" { "client_to_server" }
    "ServerToClient" { "server_to_client" }
    "ClientToPeer" { "client_to_client" }
}
$tmpJson = Join-Path $rawDir "$direction-$timestamp.iperf.json"
$errFile = Join-Path $rawDir "$direction-$timestamp-error.txt"
$outFile = Join-Path $rawDir "$direction-$timestamp.json"

switch ($Mode) {
    "ClientToServer" {
        if (-not $ServerIP) { throw "ServerIP is required for ClientToServer mode." }
        $target = $ServerIP
        $port = $ServerPort
        $iperfArgs = @("-c", $ServerIP, "-p", "$ServerPort", "-u", "-b", $Bitrate, "-l", "$PayloadBytes", "-t", "$DurationSeconds", "-i", "1", "--tos", $Tos, "-J")
    }
    "ServerToClient" {
        if (-not $ServerIP) { throw "ServerIP is required for ServerToClient mode." }
        $target = $ServerIP
        $port = $ServerPort
        $iperfArgs = @("-c", $ServerIP, "-p", "$ServerPort", "-u", "-b", $Bitrate, "-l", "$PayloadBytes", "-t", "$DurationSeconds", "-i", "1", "--tos", $Tos, "-R", "-J")
    }
    "ClientToPeer" {
        if (-not $PeerIP) { throw "PeerIP is required for ClientToPeer mode." }
        $target = $PeerIP
        $port = $PeerPort
        $iperfArgs = @("-c", $PeerIP, "-p", "$PeerPort", "-u", "-b", $Bitrate, "-l", "$PayloadBytes", "-t", "$DurationSeconds", "-i", "1", "--tos", $Tos, "-J")
    }
}

# Collect raw latency samples with ICMP first, falling back to TCP connect timing.
function Invoke-RawLatencyProbe {
    param(
        [Parameter(Mandatory=$true)]
        [string]$Target,
        [int]$Port = 0,
        [int]$Count = 5,
        [int]$TimeoutMilliseconds = 1000
    )

    $samples = @()
    $errors = @()

    if ($Count -le 0) {
        return [ordered]@{
            raw_latency_ms = $null
            latency_probe_min_ms = $null
            latency_probe_max_ms = $null
            latency_probe_count = 0
            latency_probe_received = 0
            latency_probe_source = "disabled"
            latency_probe_error = ""
        }
    }

    $ping = New-Object System.Net.NetworkInformation.Ping
    try {
        for ($i = 0; $i -lt $Count; $i++) {
            try {
                $reply = $ping.Send($Target, $TimeoutMilliseconds)
                if ($reply.Status -eq [System.Net.NetworkInformation.IPStatus]::Success) {
                    $samples += [double]$reply.RoundtripTime
                } else {
                    $errors += $reply.Status.ToString()
                }
            } catch {
                $errors += $_.Exception.Message
            }

            if ($i -lt ($Count - 1)) {
                Start-Sleep -Milliseconds 200
            }
        }
    } finally {
        $ping.Dispose()
    }

    $source = "icmp_ping"

    if (($samples.Count -eq 0) -and ($Port -gt 0)) {
        $errors += "icmp_no_replies"
        $source = "tcp_connect"
        $errors = @()

        for ($i = 0; $i -lt $Count; $i++) {
            $client = New-Object System.Net.Sockets.TcpClient
            $async = $null
            $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
            try {
                $async = $client.BeginConnect($Target, $Port, $null, $null)
                if (-not $async.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
                    $client.Close()
                    $errors += "tcp_connect_timeout"
                    continue
                }
                $client.EndConnect($async)
                $stopwatch.Stop()
                $samples += [double]$stopwatch.Elapsed.TotalMilliseconds
            } catch {
                $errors += $_.Exception.Message
            } finally {
                if ($null -ne $async) {
                    $async.AsyncWaitHandle.Close()
                }
                $client.Close()
            }

            if ($i -lt ($Count - 1)) {
                Start-Sleep -Milliseconds 200
            }
        }
    }

    $avg = $null
    $min = $null
    $max = $null
    if ($samples.Count -gt 0) {
        $measure = $samples | Measure-Object -Average -Minimum -Maximum
        $avg = [Math]::Round([double]$measure.Average, 3)
        $min = [Math]::Round([double]$measure.Minimum, 3)
        $max = [Math]::Round([double]$measure.Maximum, 3)
    }

    return [ordered]@{
        raw_latency_ms = $avg
        latency_probe_min_ms = $min
        latency_probe_max_ms = $max
        latency_probe_count = $Count
        latency_probe_received = $samples.Count
        latency_probe_source = $source
        latency_probe_error = (($errors | Select-Object -First 3) -join "; ")
    }
}

Write-Host "Running $Mode / $direction against ${target}:${port}"
Write-Host "Measuring raw latency to ${target}:${port} with $LatencyProbeCount probes"
$latencyProbe = Invoke-RawLatencyProbe -Target $target -Port $port -Count $LatencyProbeCount -TimeoutMilliseconds $LatencyProbeTimeoutMilliseconds
if ($null -ne $latencyProbe.raw_latency_ms) {
    Write-Host "Raw latency avg: $($latencyProbe.raw_latency_ms) ms via $($latencyProbe.latency_probe_source) ($($latencyProbe.latency_probe_received)/$($latencyProbe.latency_probe_count) replies)"
} else {
    Write-Warning "Raw latency unavailable ($($latencyProbe.latency_probe_received)/$($latencyProbe.latency_probe_count) replies). $($latencyProbe.latency_probe_error)"
}
Write-Host "& `"$IperfPath`" $($iperfArgs -join ' ')"

$jsonText = & $IperfPath @iperfArgs 2> $errFile
$exitCode = $LASTEXITCODE
$jsonText | Set-Content -Path $tmpJson -Encoding UTF8

if ($exitCode -ne 0) {
    $err = ""
    if (Test-Path $errFile) { $err = Get-Content $errFile -Raw }
    throw "iperf3 failed with exit code $exitCode. Error file: $errFile $err"
}

$iperfObj = Get-Content $tmpJson -Raw | ConvertFrom-Json

$wrapped = [ordered]@{
    metadata = [ordered]@{
        schema = "vocera_iperf_qoe_v1"
        generated_at_local = (Get-Date).ToString("o")
        device = $DeviceName
        role = $Role
        site = $Site
        ssid = $SSID
        mode = $Mode
        direction = $direction
        target = $target
        target_port = $port
        duration_seconds = $DurationSeconds
        bitrate = $Bitrate
        payload_bytes = $PayloadBytes
        tos = $Tos
        raw_latency_ms = $latencyProbe.raw_latency_ms
        latency_probe_min_ms = $latencyProbe.latency_probe_min_ms
        latency_probe_max_ms = $latencyProbe.latency_probe_max_ms
        latency_probe_count = $latencyProbe.latency_probe_count
        latency_probe_received = $latencyProbe.latency_probe_received
        latency_probe_source = $latencyProbe.latency_probe_source
        latency_probe_error = $latencyProbe.latency_probe_error
        collector_host = $CollectorHost
    }
    iperf3 = $iperfObj
}

$wrapped | ConvertTo-Json -Depth 100 | Set-Content -Path $outFile -Encoding UTF8
Remove-Item $tmpJson -Force -ErrorAction SilentlyContinue

$sshPath = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$scpPath = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"
if (-not (Test-Path $sshPath)) { $sshPath = "ssh.exe" }
if (-not (Test-Path $scpPath)) { $scpPath = "scp.exe" }

$remoteDir = "$RemoteBasePath/$DeviceName/raw"

$sshArgs = @(
    "-n",
    "-T",
    "-i", $SSHKeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2"
)
if ($SSHPort -ne 22) { $sshArgs += @("-p", "$SSHPort") }
$sshArgs += @("$CollectorUser@$CollectorHost", "mkdir -p -- $remoteDir")

& $sshPath @sshArgs
if ($LASTEXITCODE -ne 0) { throw "ssh mkdir failed for $remoteDir" }

$scpArgs = @(
    "-B",
    "-i", $SSHKeyPath,
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=2"
)
if ($SSHPort -ne 22) { $scpArgs += @("-P", "$SSHPort") }
$scpTarget = "{0}@{1}:{2}/" -f $CollectorUser, $CollectorHost, $remoteDir
$scpArgs += @($outFile, $scpTarget)

& $scpPath @scpArgs
if ($LASTEXITCODE -ne 0) { throw "scp upload failed to $scpTarget" }

Write-Host "Uploaded: $outFile"
Write-Host "Remote: $scpTarget"
