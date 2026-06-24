<#
Compatibility wrapper for the Laptop A client-to-server role.

The original script name included ServerToClient, but the intended Laptop A
role is now client -> server while also hosting the peer receiver for Laptop B.
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

$legacyScript = Join-Path $PSScriptRoot "Setup-LaptopA-ServerToClientAndPeerReceiver.ps1"
if (-not (Test-Path $legacyScript)) {
    throw "Required setup script not found: $legacyScript"
}

& $legacyScript @PSBoundParameters
