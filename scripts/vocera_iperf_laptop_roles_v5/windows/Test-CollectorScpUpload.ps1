<#
Tests SSH and SCP upload to collectors01.
#>
param(
    [string]$CollectorHost = "collectors01",
    [string]$CollectorUser = "appsadmin",
    [int]$SSHPort = 22,
    [string]$SSHKeyPath = "$env:USERPROFILE\.ssh\vocera_iperf_ed25519",
    [string]$RemoteBasePath = "/var/lib/vocera-iperf-qoe/incoming",
    [string]$DeviceName = $env:COMPUTERNAME
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $SSHKeyPath)) {
    throw "SSHKeyPath not found: $SSHKeyPath"
}

$sshPath = Join-Path $env:WINDIR "System32\OpenSSH\ssh.exe"
$scpPath = Join-Path $env:WINDIR "System32\OpenSSH\scp.exe"
if (-not (Test-Path $sshPath)) { $sshPath = "ssh.exe" }
if (-not (Test-Path $scpPath)) { $scpPath = "scp.exe" }

$remoteDir = "$RemoteBasePath/$DeviceName/test"
$tempFile = Join-Path $env:TEMP "vocera-iperf-scp-test.txt"

"scp test from $DeviceName at $(Get-Date -Format o)" | Set-Content -Path $tempFile -Encoding UTF8

$sshArgs = @("-i", $SSHKeyPath, "-o", "BatchMode=yes")
if ($SSHPort -ne 22) { $sshArgs += @("-p", "$SSHPort") }
$sshArgs += @("$CollectorUser@$CollectorHost", "hostname && whoami && mkdir -p $remoteDir")

& $sshPath @sshArgs
if ($LASTEXITCODE -ne 0) {
    throw "SSH test failed."
}

$scpArgs = @("-i", $SSHKeyPath, "-o", "BatchMode=yes")
if ($SSHPort -ne 22) { $scpArgs += @("-P", "$SSHPort") }

$target = "{0}@{1}:{2}/" -f $CollectorUser, $CollectorHost, $remoteDir
$scpArgs += @($tempFile, $target)

& $scpPath @scpArgs
if ($LASTEXITCODE -ne 0) {
    throw "SCP upload failed."
}

Write-Host "SCP upload succeeded."
Write-Host "Remote target: $target"
