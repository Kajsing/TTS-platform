[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Both", "X64", "X86")]
    [string]$Architecture = "Both",
    [string]$TokenId = "TTS_PLATFORM_DUMMY_ALIAS",
    [string]$VoiceName = "TTS Platform Dummy Voice",
    [string]$SourceTokenId = "TTS_MS_EN-US_ZIRA_11.0"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

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

function Set-RegistryString {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    New-ItemProperty -LiteralPath $Path -Name $Name -Value $Value -PropertyType String -Force | Out-Null
}

function Install-TokenAlias {
    param([ValidateSet("X64", "X86")][string]$Arch)

    $root = Get-TokenRoot -Arch $Arch
    $sourcePath = Join-Path $root $SourceTokenId
    $targetPath = Join-Path $root $TokenId
    $targetAttributesPath = Join-Path $targetPath "Attributes"

    if (-not (Test-Path -LiteralPath $sourcePath)) {
        throw "Source SAPI token was not found for ${Arch}: $sourcePath"
    }

    $source = Get-ItemProperty -LiteralPath $sourcePath

    if ($PSCmdlet.ShouldProcess($targetPath, "Install SAPI dummy voice token")) {
        if (Test-Path -LiteralPath $targetPath) {
            Remove-Item -LiteralPath $targetPath -Recurse -Force
        }

        New-Item -Path $targetPath -Force | Out-Null
        New-Item -Path $targetAttributesPath -Force | Out-Null

        Set-RegistryString -Path $targetPath -Name "(default)" -Value $VoiceName
        Set-RegistryString -Path $targetPath -Name "409" -Value $VoiceName
        foreach ($name in @("CLSID", "LangDataPath", "VoicePath")) {
            $value = [string]$source.$name
            if (-not $value) {
                throw "Source SAPI token is missing ${name}: $sourcePath"
            }
            Set-RegistryString -Path $targetPath -Name $name -Value $value
        }

        Set-RegistryString -Path $targetAttributesPath -Name "Name" -Value $VoiceName
        Set-RegistryString -Path $targetAttributesPath -Name "Vendor" -Value "TTS Platform"
        Set-RegistryString -Path $targetAttributesPath -Name "Language" -Value "409"
        Set-RegistryString -Path $targetAttributesPath -Name "Gender" -Value "Female"
        Set-RegistryString -Path $targetAttributesPath -Name "Age" -Value "Adult"
        Set-RegistryString -Path $targetAttributesPath -Name "Version" -Value "0.1.0"
    }

    return [ordered]@{
        architecture = $Arch
        token_path = $targetPath
        source_token_path = $sourcePath
        voice_name = $VoiceName
    }
}

if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Installing machine-level SAPI voice tokens requires an elevated PowerShell prompt."
}

$results = foreach ($arch in Get-Architectures) {
    Install-TokenAlias -Arch $arch
}

[ordered]@{
    installed = $true
    token_id = $TokenId
    voice_name = $VoiceName
    architecture = $Architecture
    results = @($results)
    next_steps = @(
        "Run scripts\windows\check_sapi_voice.ps1 -RequireInstalled",
        "Open TextAloud and check for TTS Platform Dummy Voice",
        "Run scripts\windows\remove_sapi_voice.ps1 when done testing"
    )
} | ConvertTo-Json -Depth 5

