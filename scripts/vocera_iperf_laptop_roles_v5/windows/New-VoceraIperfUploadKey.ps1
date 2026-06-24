<#
Creates the SSH upload key used for SCP uploads to collectors01.

This script does not overwrite an existing key by default.

Why this script uses -N '""':
Windows PowerShell 5.1 can drop a true empty string when passing arguments to native EXEs.
ssh-keygen then sees "-N" without an argument and returns:
  option requires an argument -- N

Passing the literal token '""' causes Windows/OpenSSH argument parsing to treat it as an empty passphrase.
#>
param(
    [string]$KeyPath = "$env:USERPROFILE\.ssh\vocera_iperf_ed25519",
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$sshDir = Split-Path -Parent $KeyPath
New-Item -ItemType Directory -Force -Path $sshDir | Out-Null

if ((Test-Path $KeyPath) -and (Test-Path "$KeyPath.pub") -and -not $Force) {
    Write-Host "Key already exists: $KeyPath"
    Write-Host ""
    Write-Host "Public key:"
    Get-Content "$KeyPath.pub"
    exit 0
}

if ($Force) {
    Remove-Item $KeyPath -Force -ErrorAction SilentlyContinue
    Remove-Item "$KeyPath.pub" -Force -ErrorAction SilentlyContinue
}

$comment = "$env:COMPUTERNAME vocera iperf uploader"

Write-Host "Creating SSH key:"
Write-Host "  $KeyPath"
Write-Host ""

& ssh-keygen.exe -t ed25519 -f $KeyPath -C $comment -N '""'
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0) {
    throw "ssh-keygen failed with exit code $exitCode. Key was not created."
}

if (-not (Test-Path $KeyPath)) {
    throw "Private key was not created: $KeyPath"
}

if (-not (Test-Path "$KeyPath.pub")) {
    throw "Public key was not created: $KeyPath.pub"
}

Write-Host ""
Write-Host "Created key:"
Write-Host "  $KeyPath"
Write-Host "  $KeyPath.pub"
Write-Host ""
Write-Host "Add this public key to /home/appsadmin/.ssh/authorized_keys on collectors01:"
Write-Host ""
Get-Content "$KeyPath.pub"
