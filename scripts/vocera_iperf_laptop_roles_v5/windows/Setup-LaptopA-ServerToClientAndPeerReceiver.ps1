<#
Laptop A role:
  1. Runs repeated client -> server tests against the server VM.
  2. Runs an iperf3 peer receiver on port 5203 so Laptop B can test client -> client.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$ServerIP,

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

    [int]$ServerPort = 5201,
    [int]$PeerListenPort = 5203,
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
    Role = "LaptopA-ClientToServer-And-PeerReceiver"
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
    Mode = "ClientToServer"
    ServerIP = $ServerIP
    ServerPort = $ServerPort
    PeerIP = ""
    PeerPort = $PeerListenPort
    StartPeerReceiver = $true
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

try {
    if (-not (Get-NetFirewallRule -DisplayName "Vocera iperf3 peer TCP $PeerListenPort" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Vocera iperf3 peer TCP $PeerListenPort" -Direction Inbound -Protocol TCP -LocalPort $PeerListenPort -Action Allow | Out-Null
    }
    if (-not (Get-NetFirewallRule -DisplayName "Vocera iperf3 peer UDP $PeerListenPort" -ErrorAction SilentlyContinue)) {
        New-NetFirewallRule -DisplayName "Vocera iperf3 peer UDP $PeerListenPort" -Direction Inbound -Protocol UDP -LocalPort $PeerListenPort -Action Allow | Out-Null
    }
} catch {
    Write-Warning "Could not create firewall rules automatically. Run PowerShell as Administrator or create inbound TCP/UDP $PeerListenPort rules manually."
}

Write-Host "Laptop A role configured."
Write-Host "Device: $DeviceName"
Write-Host "Config: $configPath"
Write-Host "ClientToServer target server: $ServerIP"
Write-Host "Peer receiver port: $PeerListenPort"
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
