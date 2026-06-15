[CmdletBinding()]
param(
    [ValidateSet("Both", "X64", "X86")]
    [string]$Architecture = "Both",
    [string]$TokenId = "TTS_PLATFORM_DUMMY_ALIAS",
    [string]$VoiceName = "TTS Platform Dummy Voice",
    [switch]$RequireInstalled
)

$ErrorActionPreference = "Stop"

function Get-TokenRoot {
    param([ValidateSet("X64", "X86")][string]$Arch)

    if ($Arch -eq "X86") {
        return "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens"
    }
    return "HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens"
}

function Get-Architectures {
    if ($Architecture -eq "Both") {
        return @("X64", "X86")
    }
    return @($Architecture)
}

function Get-RegistryStatus {
    param([ValidateSet("X64", "X86")][string]$Arch)

    $path = Join-Path (Get-TokenRoot -Arch $Arch) $TokenId
    $attributesPath = Join-Path $path "Attributes"
    $exists = Test-Path -LiteralPath $path
    $name = $null
    if (Test-Path -LiteralPath $attributesPath) {
        $name = (Get-ItemProperty -LiteralPath $attributesPath -Name "Name" -ErrorAction SilentlyContinue).Name
    }
    return [ordered]@{
        architecture = $Arch
        token_path = $path
        exists = $exists
        name = $name
    }
}

function Get-CurrentComVoiceDescriptions {
    try {
        $voice = New-Object -ComObject SAPI.SpVoice
        return @($voice.GetVoices() | ForEach-Object { $_.GetDescription() })
    } catch {
        return @()
    }
}

function Get-Wow64ComVoiceDescriptions {
    $wowPowerShell = Join-Path $env:WINDIR "SysWOW64\WindowsPowerShell\v1.0\powershell.exe"
    if (-not (Test-Path -LiteralPath $wowPowerShell)) {
        return $null
    }

    $script = @'
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$voice = New-Object -ComObject SAPI.SpVoice
@($voice.GetVoices() | ForEach-Object { $_.GetDescription() }) | ConvertTo-Json -Depth 3
'@
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($script))
    try {
        $output = & $wowPowerShell -NoProfile -NonInteractive -EncodedCommand $encoded 2>$null
        if (-not $output) {
            return @()
        }
        $parsed = $output | ConvertFrom-Json
        if ($parsed -is [array]) {
            return @($parsed)
        }
        return @($parsed)
    } catch {
        return @()
    }
}

$registry = foreach ($arch in Get-Architectures) {
    Get-RegistryStatus -Arch $arch
}

$currentDescriptions = Get-CurrentComVoiceDescriptions
$wow64Descriptions = Get-Wow64ComVoiceDescriptions

$summary = [ordered]@{
    token_id = $TokenId
    voice_name = $VoiceName
    architecture = $Architecture
    registry = @($registry)
    current_process = [ordered]@{
        pointer_size = [IntPtr]::Size
        found = $currentDescriptions -contains $VoiceName
        voices = @($currentDescriptions)
    }
    wow64_process = if ($null -eq $wow64Descriptions) {
        [ordered]@{
            available = $false
            found = $false
            voices = @()
        }
    } else {
        [ordered]@{
            available = $true
            found = @($wow64Descriptions) -contains $VoiceName
            voices = @($wow64Descriptions)
        }
    }
}

$missingRegistry = @($summary.registry | Where-Object { -not $_.exists })
$foundInAnyComView = $summary.current_process.found -or $summary.wow64_process.found

if ($RequireInstalled -and ($missingRegistry.Count -gt 0 -or -not $foundInAnyComView)) {
    $summary["ok"] = $false
    $summary["message"] = "SAPI dummy voice is not fully installed or not visible through COM enumeration."
    $summary | ConvertTo-Json -Depth 6
    exit 1
}

$summary["ok"] = $true
$summary["message"] = "SAPI dummy voice check completed."
$summary | ConvertTo-Json -Depth 6
