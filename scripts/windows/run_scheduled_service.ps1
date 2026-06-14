[CmdletBinding()]
param(
    [string]$HostOverride = "",
    [int]$Port = 0,
    [switch]$AllowNonLocalHost,
    [string]$LogPath = ""
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path

if (-not $LogPath) {
    $LogPath = Join-Path $RepoRoot "logs\tts-service.log"
}

$LogDir = Split-Path -Parent $LogPath
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$RunService = Join-Path $ScriptDir "run_service.ps1"
$RunArgs = @()
if ($HostOverride) {
    $RunArgs += @("-HostOverride", $HostOverride)
}
if ($Port -gt 0) {
    $RunArgs += @("-Port", "$Port")
}
if ($AllowNonLocalHost) {
    $RunArgs += "-AllowNonLocalHost"
}

$StartTimestamp = Get-Date -Format o
Add-Content -Path $LogPath -Value "[$StartTimestamp] Starting TTS Platform local reader service."

$ExitCode = 0
try {
    & $RunService @RunArgs *>> $LogPath
    if ($null -ne $LASTEXITCODE) {
        $ExitCode = $LASTEXITCODE
    }
} catch {
    Add-Content -Path $LogPath -Value ($_ | Out-String)
    $ExitCode = 1
}

$EndTimestamp = Get-Date -Format o
Add-Content -Path $LogPath -Value "[$EndTimestamp] TTS Platform local reader service exited with code $ExitCode."
exit $ExitCode
