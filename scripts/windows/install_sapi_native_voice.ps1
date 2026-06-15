[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet("X64", "X86")]
    [string]$Architecture = "X86",
    [string]$DllPath = "",
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

function Set-RegistryString {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )

    New-ItemProperty -LiteralPath $Path -Name $Name -Value $Value -PropertyType String -Force | Out-Null
}

if (-not $WhatIfPreference -and -not (Test-IsAdministrator)) {
    throw "Installing machine-level native SAPI voice tokens requires an elevated PowerShell prompt."
}

if (-not $DllPath) {
    throw "DllPath is required. Build the bridge first with scripts\windows\build_sapi_bridge.ps1."
}
$ResolvedDllPath = (Resolve-Path -LiteralPath $DllPath).Path

$tokenPath = Join-Path (Get-TokenRoot) $TokenId
$attributesPath = Join-Path $tokenPath "Attributes"
$classPath = Join-Path (Get-ClassesRoot) $ClassId
$inprocPath = Join-Path $classPath "InprocServer32"

if ($PSCmdlet.ShouldProcess($ResolvedDllPath, "Register native SAPI COM class and voice token")) {
    New-Item -Path $classPath -Force | Out-Null
    New-Item -Path $inprocPath -Force | Out-Null
    Set-RegistryString -Path $classPath -Name "(default)" -Value "TTS Platform SAPI Engine"
    Set-RegistryString -Path $inprocPath -Name "(default)" -Value $ResolvedDllPath
    Set-RegistryString -Path $inprocPath -Name "ThreadingModel" -Value "Both"

    if (Test-Path -LiteralPath $tokenPath) {
        Remove-Item -LiteralPath $tokenPath -Recurse -Force
    }
    New-Item -Path $tokenPath -Force | Out-Null
    New-Item -Path $attributesPath -Force | Out-Null

    Set-RegistryString -Path $tokenPath -Name "(default)" -Value $VoiceName
    Set-RegistryString -Path $tokenPath -Name "409" -Value $VoiceName
    Set-RegistryString -Path $tokenPath -Name "CLSID" -Value $ClassId

    Set-RegistryString -Path $attributesPath -Name "Name" -Value $VoiceName
    Set-RegistryString -Path $attributesPath -Name "Vendor" -Value "TTS Platform"
    Set-RegistryString -Path $attributesPath -Name "Language" -Value "409"
    Set-RegistryString -Path $attributesPath -Name "Gender" -Value "Female"
    Set-RegistryString -Path $attributesPath -Name "Age" -Value "Adult"
    Set-RegistryString -Path $attributesPath -Name "Version" -Value "0.1.0"
}

[ordered]@{
    installed = $true
    architecture = $Architecture
    token_id = $TokenId
    voice_name = $VoiceName
    class_id = $ClassId
    dll_path = $ResolvedDllPath
    token_path = $tokenPath
    class_path = $classPath
    next_steps = @(
        "Run scripts\windows\check_sapi_native_voice.ps1 -Architecture $Architecture -RequireInstalled",
        "Open TextAloud and test TTS Platform Native Dummy Voice",
        "Run scripts\windows\remove_sapi_native_voice.ps1 -Architecture $Architecture when done testing"
    )
} | ConvertTo-Json -Depth 5

