<#
Copies all Windows scripts to C:\VoceraIperf\windows and optionally copies the full iperf3 folder to C:\Tools\iperf3.
#>
param(
    [string]$InstallRoot = "C:\VoceraIperf",
    [string]$IperfSourceDir = ""
)

$ErrorActionPreference = "Stop"

$sourceWindows = Split-Path -Parent $MyInvocation.MyCommand.Path
$destWindows = Join-Path $InstallRoot "windows"

New-Item -ItemType Directory -Force -Path $destWindows | Out-Null
Copy-Item -Path (Join-Path $sourceWindows "*.ps1") -Destination $destWindows -Force

if ($IperfSourceDir) {
    if (-not (Test-Path $IperfSourceDir)) {
        throw "IperfSourceDir not found: $IperfSourceDir"
    }

    New-Item -ItemType Directory -Force -Path "C:\Tools\iperf3" | Out-Null
    Copy-Item -Path (Join-Path $IperfSourceDir "*") -Destination "C:\Tools\iperf3" -Recurse -Force
    Get-ChildItem "C:\Tools\iperf3" -Recurse | Unblock-File
}

Write-Host "Installed scripts to: $destWindows"
Write-Host ""
Write-Host "Scripts installed:"
Get-ChildItem $destWindows -Filter "*.ps1" | Select-Object Name
Write-Host ""
Write-Host "Verify iperf3:"
Write-Host '  & "C:\Tools\iperf3\iperf3.exe" --version'
