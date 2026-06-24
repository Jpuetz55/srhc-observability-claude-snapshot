<#
Laptop B role:
  Runs repeated client -> client tests to Laptop A's wireless IP.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$PeerIP,

    [string]$SSID = "srhcvoice2",
    [int]$IntervalMinutes = 5,
    [int]$DurationSeconds = 60,

    [string]$InstallRoot = "C:\VoceraIperf",
    [string]$LocalBasePath = "C:\iperf-vocera-tests",
    [string]$IperfPath = "C:\Tools\iperf3\iperf3.exe",

    [string]$CollectorHost = "collectors01",
    [string]$CollectorUser = "appsadmin",
    [string]$SSHKeyPath = "$env:USERPROFILE\.ssh\vocera_iperf_ed25519",
    [string]$RemoteBasePath = "/var/lib/vocera-iperf-qoe/incoming",

    [int]$PeerPort = 5203,
    [string]$Bitrate = "64K",
    [int]$PayloadBytes = 160,
    [string]$Tos = "0xb8",
    [string]$Site = "srhc",
    [string]$DeviceName = $env:COMPUTERNAME,
    [int]$LatencyProbeCount = 5,
    [int]$LatencyProbeTimeoutMilliseconds = 1000
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $IperfPath)) { throw "IperfPath not found: $IperfPath" }
if (-not (Test-Path $SSHKeyPath)) { throw "SSHKeyPath not found: $SSHKeyPath" }

$configDir = Join-Path $InstallRoot "config"
$stateDir = Join-Path $LocalBasePath "$DeviceName\state"
$logDir = Join-Path $LocalBasePath "$DeviceName\logs"
$rawDir = Join-Path $LocalBasePath "$DeviceName\raw"

New-Item -ItemType Directory -Force -Path $configDir,$stateDir,$logDir,$rawDir | Out-Null

$config = [ordered]@{
    Role = "LaptopB-ClientToClient-Tester"
    DeviceName = $DeviceName
    Site = $Site
    SSID = $SSID
    InstallRoot = $InstallRoot
    LocalBasePath = $LocalBasePath
    IperfPath = $IperfPath
    CollectorHost = $CollectorHost
    CollectorUser = $CollectorUser
    SSHKeyPath = $SSHKeyPath
    RemoteBasePath = $RemoteBasePath
    Mode = "ClientToPeer"
    ServerIP = ""
    ServerPort = 5201
    PeerIP = $PeerIP
    PeerPort = $PeerPort
    StartPeerReceiver = $false
    IntervalMinutes = $IntervalMinutes
    DurationSeconds = $DurationSeconds
    Bitrate = $Bitrate
    PayloadBytes = $PayloadBytes
    Tos = $Tos
    LatencyProbeCount = $LatencyProbeCount
    LatencyProbeTimeoutMilliseconds = $LatencyProbeTimeoutMilliseconds
}

$configPath = Join-Path $configDir "role.json"
$config | ConvertTo-Json -Depth 10 | Set-Content -Path $configPath -Encoding UTF8

Write-Host "Laptop B role configured."
Write-Host "Device: $DeviceName"
Write-Host "Config: $configPath"
Write-Host "ClientToClient target: ${PeerIP}:${PeerPort}"
Write-Host "Raw latency probe: $LatencyProbeCount ICMP probes, timeout ${LatencyProbeTimeoutMilliseconds}ms"
Write-Host "SSID metadata: $SSID"
Write-Host ""
Write-Host "Start:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Start-VoceraIperfRole.ps1"'
Write-Host ""
Write-Host "Stop:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Stop-VoceraIperfRole.ps1"'
Write-Host ""
Write-Host "Status:"
Write-Host '  powershell -ExecutionPolicy Bypass -File "C:\VoceraIperf\windows\Get-VoceraIperfRoleStatus.ps1"'
