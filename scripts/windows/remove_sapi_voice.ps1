[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("Both", "X64", "X86")]
    [string]$Architecture = "Both",
    [string]$TokenId = "TTS_PLATFORM_DUMMY_ALIAS"
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

if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Removing machine-level SAPI voice tokens requires an elevated PowerShell prompt."
}

$results = foreach ($arch in Get-Architectures) {
    $path = Join-Path (Get-TokenRoot -Arch $arch) $TokenId
    $existed = Test-Path -LiteralPath $path
    if ($existed -and $PSCmdlet.ShouldProcess($path, "Remove SAPI dummy voice token")) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
    [ordered]@{
        architecture = $arch
        token_path = $path
        removed = $existed
    }
}

[ordered]@{
    removed = $true
    token_id = $TokenId
    architecture = $Architecture
    results = @($results)
    next_steps = @(
        "Run scripts\windows\check_sapi_voice.ps1 to confirm the token is gone"
    )
} | ConvertTo-Json -Depth 5

