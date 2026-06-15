[CmdletBinding()]
param(
    [ValidateSet("X64", "X86")]
    [string]$Architecture = "X86",
    [string]$TokenId = "TTS_PLATFORM_NATIVE_DUMMY",
    [string]$VoiceName = "TTS Platform Native Dummy Voice",
    [string]$ClassId = "{7F241B98-6F49-4A18-9A40-98764D039A1B}",
    [switch]$RequireInstalled
)

$ErrorActionPreference = "Stop"

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

$tokenPath = Join-Path (Get-TokenRoot) $TokenId
$attributesPath = Join-Path $tokenPath "Attributes"
$classPath = Join-Path (Get-ClassesRoot) $ClassId
$inprocPath = Join-Path $classPath "InprocServer32"

$tokenExists = Test-Path -LiteralPath $tokenPath
$classExists = Test-Path -LiteralPath $classPath
$inprocExists = Test-Path -LiteralPath $inprocPath
$registeredDll = $null
$registeredName = $null
if ($inprocExists) {
    $registeredDll = (Get-ItemProperty -LiteralPath $inprocPath -Name "(default)" -ErrorAction SilentlyContinue)."(default)"
}
if (Test-Path -LiteralPath $attributesPath) {
    $registeredName = (Get-ItemProperty -LiteralPath $attributesPath -Name "Name" -ErrorAction SilentlyContinue).Name
}
$dllExists = $registeredDll -and (Test-Path -LiteralPath $registeredDll)

$ok = $tokenExists -and $classExists -and $inprocExists -and $dllExists
$summary = [ordered]@{
    token_id = $TokenId
    voice_name = $VoiceName
    architecture = $Architecture
    token_path = $tokenPath
    token_exists = $tokenExists
    token_name = $registeredName
    class_id = $ClassId
    class_path = $classPath
    class_exists = $classExists
    inproc_path = $inprocPath
    inproc_exists = $inprocExists
    registered_dll = $registeredDll
    registered_dll_exists = [bool]$dllExists
    ok = [bool]$ok
}

if ($RequireInstalled -and -not $ok) {
    $summary["message"] = "Native SAPI voice is not fully registered."
    $summary | ConvertTo-Json -Depth 5
    exit 1
}

$summary["message"] = "Native SAPI voice check completed."
$summary | ConvertTo-Json -Depth 5

