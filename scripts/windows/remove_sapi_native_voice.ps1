[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("X64", "X86")]
    [string]$Architecture = "X86",
    [string]$TokenId = "TTS_PLATFORM_NATIVE_DUMMY",
    [string]$VoiceName = "TTS Platform Native Dummy Voice",
    [string]$ClassId = "{7F241B98-6F49-4A18-9A40-98764D039A1B}"
)

$ErrorActionPreference = "Stop"

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-TokenRoot {
    if ($Architecture -eq "X86") {
        return "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Speech\Voices\Tokens"
    }
    return "HKLM:\SOFTWARE\Microsoft\Speech\Voices\Tokens"
}

function Get-ClassesRoot {
    if ($Architecture -eq "X86") {
        return "HKLM:\SOFTWARE\WOW6432Node\Classes\CLSID"
    }
    return "HKLM:\SOFTWARE\Classes\CLSID"
}

if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Removing machine-level native SAPI voice tokens requires an elevated PowerShell prompt."
}

$tokenPath = Join-Path (Get-TokenRoot) $TokenId
$classPath = Join-Path (Get-ClassesRoot) $ClassId

$removedToken = Test-Path -LiteralPath $tokenPath
$removedClass = Test-Path -LiteralPath $classPath

if ($removedToken -and $PSCmdlet.ShouldProcess($tokenPath, "Remove native SAPI voice token")) {
    Remove-Item -LiteralPath $tokenPath -Recurse -Force
}
if ($removedClass -and $PSCmdlet.ShouldProcess($classPath, "Remove native SAPI COM class")) {
    Remove-Item -LiteralPath $classPath -Recurse -Force
}

[ordered]@{
    removed = $true
    architecture = $Architecture
    token_id = $TokenId
    voice_name = $VoiceName
    class_id = $ClassId
    token_removed = $removedToken
    class_removed = $removedClass
    next_steps = @(
        "Run scripts\windows\check_sapi_native_voice.ps1 -Architecture $Architecture to confirm removal"
    )
} | ConvertTo-Json -Depth 5
