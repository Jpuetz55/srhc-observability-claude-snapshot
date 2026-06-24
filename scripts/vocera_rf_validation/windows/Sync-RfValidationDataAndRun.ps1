param(
    [string]$LocalRoot = "C:\rf-validation-data",
    [string]$CollectorHost = "10.0.128.107",
    [string]$CollectorUser = "appsadmin",
    [int]$SSHPort = 22,
    [string]$SSHKeyPath = "",
    [string]$RemoteRepo = "/home/appsadmin/grafana-mimir-observability",
    [string]$RemoteUploadRoot = "/var/lib/vocera-rf-validation/uploads",
    [string]$RunId = "",
    # PCAP QoE uses per-MAC folders under $LocalRoot. RF validation is a
    # single logical run and uses one shared $LocalRoot\badge-log\ folder.
    [string]$ControlBadgeMac = "00:09:ef:54:5f:46",
    [string]$TestBadgeMac = "",
    [switch]$SkipRfValidation,
    [switch]$UploadOnly
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

# Resolve OpenSSH tools, preferring Windows' built-in OpenSSH directory.
function Resolve-Tool {
    param([string]$Name)
    $candidate = Join-Path $env:WINDIR "System32\OpenSSH\$Name"
    if (Test-Path $candidate) { return $candidate }
    return $Name
}

# Invoke a native executable and fail on non-zero exit codes.
function Invoke-Native {
    param(
        [string]$FilePath,
        [string[]]$Arguments
    )
    Write-Host ("+ {0} {1}" -f $FilePath, ($Arguments -join " "))
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath failed with exit code $LASTEXITCODE"
    }
}

# Convert Windows path separators to remote POSIX separators.
function ConvertTo-PosixPath {
    param([string]$Value)
    return ($Value -replace "\\", "/")
}

# Quote a value for inclusion in the remote single-quoted shell command.
function ConvertTo-ShellSingleQuoted {
    param([string]$Value)
    return "'" + ($Value -replace "'", "'\''") + "'"
}

# Validate that the run id is safe for paths, archives, and shell arguments.
function Test-RunId {
    param([string]$Value)
    return $Value -match '^[A-Za-z0-9_.-]+$'
}

# Convert AA:BB:CC:DD:EE:FF -> aa-bb-cc-dd-ee-ff for filesystem-safe folder names.
function ConvertTo-MacFolder {
    param([string]$Mac)
    if ([string]::IsNullOrWhiteSpace($Mac)) { return "" }
    return ($Mac.ToLowerInvariant() -replace "[^0-9a-f]", "-")
}

function ConvertTo-MacToken {
    param([string]$Mac)
    if ([string]::IsNullOrWhiteSpace($Mac)) { return "" }
    return ($Mac.ToLowerInvariant() -replace "[^0-9a-f]", "")
}

# Return the newest file under a folder whose name matches one of the extensions.
function Get-NewestFile {
    param(
        [string]$Root,
        [string[]]$Extensions
    )
    if (-not (Test-Path $Root)) {
        throw "Required folder not found: $Root"
    }
    $files = @(Get-ChildItem -Path $Root -Recurse -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        foreach ($extension in $Extensions) {
            if ($name.EndsWith($extension.ToLowerInvariant())) { return $true }
        }
        return $false
    } | Sort-Object LastWriteTimeUtc -Descending)
    if (-not $files -or $files.Count -eq 0) {
        throw "No matching files found under $Root"
    }
    return $files[0]
}

function Get-NewestFileOrNull {
    param(
        [string]$Root,
        [string[]]$Extensions
    )
    if (-not (Test-Path $Root)) {
        return $null
    }
    $files = @(Get-ChildItem -Path $Root -Recurse -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        foreach ($extension in $Extensions) {
            if ($name.EndsWith($extension.ToLowerInvariant())) { return $true }
        }
        return $false
    } | Sort-Object LastWriteTimeUtc -Descending)
    if (-not $files -or $files.Count -eq 0) {
        return $null
    }
    return $files[0]
}

function Get-NewestBadgeLogForMacs {
    param(
        [string]$Root,
        [string[]]$BadgeMacs
    )
    if (-not (Test-Path $Root)) {
        Write-Warning "Shared badge-log folder not found: $Root; RF validation will be skipped."
        return $null
    }
    $tokens = @()
    foreach ($mac in $BadgeMacs) {
        if ([string]::IsNullOrWhiteSpace($mac)) { continue }
        $macHex = ConvertTo-MacToken $mac
        if ([string]::IsNullOrWhiteSpace($macHex)) {
            throw "Badge MAC is empty or unparseable: '$mac'"
        }
        $tokens += [pscustomobject]@{ MacHex = $macHex; Mac = $mac }
    }
    if ($tokens.Count -eq 0) {
        Write-Warning "No badge MACs were provided for shared badge-log selection; RF validation will be skipped."
        return $null
    }

    $candidates = @()
    foreach ($file in @(Get-ChildItem -Path $Root -Recurse -File)) {
        $name = $file.Name.ToLowerInvariant()
        $isBadgeLog = (
            $name.EndsWith(".tar.gz") -or
            $name.EndsWith(".tgz") -or
            $name.EndsWith(".zip") -or
            $name.EndsWith(".sys") -or
            $name.EndsWith(".txt") -or
            $name.EndsWith(".log")
        )
        if (-not $isBadgeLog) { continue }
        foreach ($item in $tokens) {
            if ($name -like "*$($item.MacHex)*") {
                $candidates += [pscustomobject]@{
                    File = $file
                    BadgeMac = $item.Mac
                    LastWriteTimeUtc = $file.LastWriteTimeUtc
                }
                break
            }
        }
    }
    $candidates = @($candidates | Sort-Object LastWriteTimeUtc -Descending)
    if (-not $candidates -or $candidates.Count -eq 0) {
        Write-Warning "No badge log matching configured badge MACs under $Root; RF validation will be skipped."
        return $null
    }
    if ($candidates.Count -gt 1) {
        Write-Warning ("Multiple shared badge logs match configured MACs; using newest: {0}" -f $candidates[0].File.FullName)
    }
    return $candidates[0]
}

# Resolve one device's local layout. Missing/empty Pcaps folders are allowed so
# a partially staged run can still upload and process whatever inputs exist.
function Resolve-DeviceLayout {
    param(
        [string]$Role,
        [string]$BadgeMac,
        [string]$LocalRoot
    )
    $folderName = ConvertTo-MacFolder $BadgeMac
    if ([string]::IsNullOrWhiteSpace($folderName)) {
        throw "$Role badge MAC is empty or unparseable: '$BadgeMac'"
    }
    $deviceRoot = Join-Path $LocalRoot $folderName
    if (-not (Test-Path $deviceRoot)) {
        Write-Warning "$Role device folder not found: $deviceRoot (derived from MAC $BadgeMac); PCAP QoE will skip this device."
        return [pscustomobject]@{
            Role = $Role
            BadgeMac = $BadgeMac
            FolderName = $folderName
            DeviceRoot = $deviceRoot
            PcapDir = Join-Path $deviceRoot "Pcaps"
            PcapCount = 0
            Present = $false
        }
    }
    $pcapDir = Join-Path $deviceRoot "Pcaps"
    if (-not (Test-Path $pcapDir)) {
        Write-Warning "$Role Pcaps folder not found: $pcapDir; PCAP QoE will skip this device."
        return [pscustomobject]@{
            Role = $Role
            BadgeMac = $BadgeMac
            FolderName = $folderName
            DeviceRoot = $deviceRoot
            PcapDir = $pcapDir
            PcapCount = 0
            Present = $false
        }
    }
    $pcapCount = @(Get-ChildItem -Path $pcapDir -Recurse -File | Where-Object {
        $name = $_.Name.ToLowerInvariant()
        $name.EndsWith(".pcap") -or $name.EndsWith(".pcapng") -or $name.EndsWith(".cap")
    }).Count
    if ($pcapCount -eq 0) {
        Write-Warning "${Role}: no .pcap/.pcapng/.cap under $pcapDir."
    }
    return [pscustomobject]@{
        Role = $Role
        BadgeMac = $BadgeMac
        FolderName = $folderName
        DeviceRoot = $deviceRoot
        PcapDir = $pcapDir
        PcapCount = $pcapCount
        Present = $true
    }
}

if (-not (Test-Path $LocalRoot)) {
    throw "Local root not found: $LocalRoot"
}

# The Ekahau survey project and badge logs are shared for the single RF
# validation run. Missing/empty folders skip RF validation but still allow PCAP
# QoE processing.
$surveyDir = Join-Path $LocalRoot "survey"
$surveyFile = Get-NewestFileOrNull -Root $surveyDir -Extensions @(".esx", ".zip", ".json")
if ($null -eq $surveyFile) {
    Write-Warning "No survey .esx/.zip/.json found under $surveyDir; RF validation will be skipped."
}

$sharedBadgeDir = Join-Path $LocalRoot "badge-log"
$badgeMacsForRf = @($ControlBadgeMac)
if (-not [string]::IsNullOrWhiteSpace($TestBadgeMac)) {
    $badgeMacsForRf += $TestBadgeMac
}
$rfBadgeSelection = Get-NewestBadgeLogForMacs -Root $sharedBadgeDir -BadgeMacs $badgeMacsForRf
if ($null -ne $rfBadgeSelection) {
    $badgeFile = $rfBadgeSelection.File
    $rfBadgeMac = $rfBadgeSelection.BadgeMac
} else {
    $badgeFile = $null
    $rfBadgeMac = $ControlBadgeMac
}
$skipRfValidation = $SkipRfValidation -or ($null -eq $surveyFile) -or ($null -eq $badgeFile)

# Build the device list. Test device is optional - omit -TestBadgeMac to fall
# back to single-device mode (legacy behavior).
$devices = @()
$devices += Resolve-DeviceLayout -Role "control" -BadgeMac $ControlBadgeMac -LocalRoot $LocalRoot
if (-not [string]::IsNullOrWhiteSpace($TestBadgeMac)) {
    if ($TestBadgeMac -eq $ControlBadgeMac) {
        throw "ControlBadgeMac and TestBadgeMac must differ (both are $TestBadgeMac)"
    }
    $devices += Resolve-DeviceLayout -Role "test" -BadgeMac $TestBadgeMac -LocalRoot $LocalRoot
}

if ([string]::IsNullOrWhiteSpace($RunId)) {
    $RunId = "srhc_vocera_ekahau_{0}" -f (Get-Date -Format "yyyy_MM_dd_HHmmss")
}
if (-not (Test-RunId $RunId)) {
    throw "RunId may only contain letters, numbers, underscore, dot, and dash: $RunId"
}
if (-not $RemoteUploadRoot.StartsWith("/") -or $RemoteUploadRoot -eq "/") {
    throw "RemoteUploadRoot must be an absolute non-root POSIX path: $RemoteUploadRoot"
}

$scp = Resolve-Tool "scp.exe"
$ssh = Resolve-Tool "ssh.exe"
$remoteUploadDir = "$RemoteUploadRoot/$RunId"
$remoteZip = "/tmp/vocera-rf-validation-$RunId.zip"

$localRootFull = (Resolve-Path $LocalRoot).Path.TrimEnd("\")
if ($null -ne $surveyFile) {
    $surveyRelative = $surveyFile.FullName.Substring($localRootFull.Length).TrimStart("\")
    $remoteSurveyInput = "$remoteUploadDir/$(ConvertTo-PosixPath $surveyRelative)"
} else {
    $remoteSurveyInput = ""
}
if ($null -ne $badgeFile) {
    $badgeRelative = $badgeFile.FullName.Substring($localRootFull.Length).TrimStart("\")
    $remoteBadgeInput = "$remoteUploadDir/$(ConvertTo-PosixPath $badgeRelative)"
} else {
    $remoteBadgeInput = ""
}

$tempZip = Join-Path $env:TEMP "vocera-rf-validation-$RunId.zip"
if (Test-Path $tempZip) {
    Remove-Item -Path $tempZip -Force
}

Write-Host "Run id: $RunId"
if ($null -ne $surveyFile) {
    Write-Host "Selected survey: $($surveyFile.FullName)"
} else {
    Write-Host "Selected survey: <none>"
}
if ($null -ne $badgeFile) {
    Write-Host "Selected RF badge log: $($badgeFile.FullName) (MAC $rfBadgeMac)"
} else {
    Write-Host "Selected RF badge log: <none>"
}
foreach ($device in $devices) {
    Write-Host ("Device [{0}] MAC {1} folder {2}: pcaps {3}" -f $device.Role, $device.BadgeMac, $device.DeviceRoot, $device.PcapCount)
}
Write-Host "Creating upload bundle: $tempZip"
Compress-Archive -Path (Join-Path $LocalRoot "*") -DestinationPath $tempZip -Force

$commonSshArgs = @()
if ($SSHPort -ne 22) { $commonSshArgs += @("-p", "$SSHPort") }
if (-not [string]::IsNullOrWhiteSpace($SSHKeyPath)) { $commonSshArgs += @("-i", $SSHKeyPath) }

$scpArgs = @()
if ($SSHPort -ne 22) { $scpArgs += @("-P", "$SSHPort") }
if (-not [string]::IsNullOrWhiteSpace($SSHKeyPath)) { $scpArgs += @("-i", $SSHKeyPath) }
$scpArgs += @($tempZip, "$CollectorUser@$CollectorHost`:$remoteZip")
Invoke-Native -FilePath $scp -Arguments $scpArgs

$extractCommand = @(
    "set -euo pipefail",
    "rm -rf $(ConvertTo-ShellSingleQuoted $remoteUploadDir)",
    "mkdir -p $(ConvertTo-ShellSingleQuoted $remoteUploadDir)",
    "python3 -m zipfile -e $(ConvertTo-ShellSingleQuoted $remoteZip) $(ConvertTo-ShellSingleQuoted $remoteUploadDir)",
    "rm -f $(ConvertTo-ShellSingleQuoted $remoteZip)"
) -join "; "

$sshExtractArgs = @()
$sshExtractArgs += $commonSshArgs
$sshExtractArgs += @("$CollectorUser@$CollectorHost", $extractCommand)
Invoke-Native -FilePath $ssh -Arguments $sshExtractArgs

if ($UploadOnly) {
    Write-Host "Upload complete. Remote upload directory: $remoteUploadDir"
    exit 0
}

# Build the env-var list for the server side. PCAP QoE receives the whole
# upload root and recursively discovers both per-MAC Pcaps folders. RF
# validation receives one badge log and one survey when both are available.
$remoteRunEnv = [System.Collections.Generic.List[string]]::new()
$remoteRunEnv.Add("VOCERA_SURVEY_OUTPUT_OWNER=$(ConvertTo-ShellSingleQuoted $CollectorUser)")
$remoteRunEnv.Add("VOCERA_SURVEY_RUN_ID=$(ConvertTo-ShellSingleQuoted $RunId)")
$remoteRunEnv.Add("VOCERA_SURVEY_UPLOAD_DIR=$(ConvertTo-ShellSingleQuoted $remoteUploadDir)")
$remoteRunEnv.Add("VOCERA_SURVEY_MEDIA_RAW_DIR=$(ConvertTo-ShellSingleQuoted $remoteUploadDir)")
$remoteRunEnv.Add("VOCERA_SURVEY_BADGE_MAC=$(ConvertTo-ShellSingleQuoted $rfBadgeMac)")
if ($skipRfValidation) {
    $remoteRunEnv.Add("VOCERA_SURVEY_SKIP_RF=1")
} else {
    $remoteRunEnv.Add('VOCERA_SURVEY_EKAHAU_PROJECT="$survey_input"')
    $remoteRunEnv.Add('VOCERA_SURVEY_BADGE_INPUT="$badge_input"')
}

$prelude = [System.Collections.Generic.List[string]]::new()
$prelude.Add("set -euo pipefail")
$prelude.Add("cd $(ConvertTo-ShellSingleQuoted $RemoteRepo)")
$prelude.Add("upload_dir=$(ConvertTo-ShellSingleQuoted $remoteUploadDir)")
if (-not $skipRfValidation) {
    $surveyNamePattern = ConvertTo-ShellSingleQuoted ("*" + $surveyFile.Name)
    $badgeNamePattern = ConvertTo-ShellSingleQuoted ("*" + $badgeFile.Name)
    $resolveSurveyCommand = 'if [ ! -e "$survey_input" ]; then survey_input="$(find "$upload_dir" -type f -name ' + $surveyNamePattern + ' -print -quit)"; fi'
    $resolveBadgeCommand = 'if [ ! -e "$badge_input" ]; then badge_input="$(find "$upload_dir" -type f -name ' + $badgeNamePattern + ' -print -quit)"; fi'
    $prelude.Add("survey_input=$(ConvertTo-ShellSingleQuoted $remoteSurveyInput)")
    $prelude.Add("badge_input=$(ConvertTo-ShellSingleQuoted $remoteBadgeInput)")
    $prelude.Add($resolveSurveyCommand)
    $prelude.Add($resolveBadgeCommand)
    $prelude.Add('if [ -z "$survey_input" ] || [ ! -e "$survey_input" ]; then echo "ERROR: uploaded survey file not found under $upload_dir"; find "$upload_dir" -maxdepth 5 -type f | sort; exit 1; fi')
    $prelude.Add('if [ -z "$badge_input" ] || [ ! -e "$badge_input" ]; then echo "ERROR: uploaded badge log not found under $upload_dir"; find "$upload_dir" -maxdepth 5 -type f | sort; exit 1; fi')
    $prelude.Add('echo "Remote survey: $survey_input"')
    $prelude.Add('echo "Remote RF badge: $badge_input"')
} else {
    $prelude.Add('echo "Remote RF validation: skipped because survey or control badge log is missing"')
}
$prelude.Add('echo "Remote media root: $upload_dir"')

$sudoRunCommand = "sudo env $($remoteRunEnv -join " ") bash ./scripts/run_vocera_survey_refresh.sh"
$prelude.Add($sudoRunCommand)
$remoteRunCommand = ($prelude -join "; ")

$sshRunArgs = @("-t")
$sshRunArgs += $commonSshArgs
$sshRunArgs += @("$CollectorUser@$CollectorHost", $remoteRunCommand)
Invoke-Native -FilePath $ssh -Arguments $sshRunArgs

Write-Host ""
Write-Host "Refresh complete."
Write-Host "Run id: $RunId"
Write-Host "Rollback command on server:"
Write-Host "  cd $RemoteRepo"
Write-Host "  sudo bash ./scripts/rollback_vocera_survey_refresh.sh --run-id $RunId"
