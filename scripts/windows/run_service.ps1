[CmdletBinding()]
param(
    [string]$HostOverride = "",
    [int]$Port = 0,
    [switch]$AllowNonLocalHost,
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$ServiceSrc = Join-Path $RepoRoot "apps\tts_service\src"
$CoreSrc = Join-Path $RepoRoot "packages\tts_core\src"
$ConfigPath = Join-Path $RepoRoot "config\config.toml"

$PythonPathParts = @($ServiceSrc, $CoreSrc)
if ($env:PYTHONPATH) {
    $PythonPathParts += $env:PYTHONPATH
}
$env:PYTHONPATH = ($PythonPathParts -join [System.IO.Path]::PathSeparator)

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$PythonExe = ""
$PythonPrefixArgs = @()
if ($env:TTS_PLATFORM_PYTHON) {
    $PythonExe = $env:TTS_PLATFORM_PYTHON
} elseif (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    $PythonExe = "py"
    $PythonPrefixArgs = @("-3")
} else {
    $PythonExe = "python"
}

$ModuleArgs = @("-m", "tts_service.cli")

if ($SetupOnly -or -not (Test-Path $ConfigPath)) {
    & $PythonExe @PythonPrefixArgs @ModuleArgs "setup-local" "--repo-root" $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}

if ($SetupOnly) {
    exit 0
}

$ServeArgs = $ModuleArgs + @("serve", "--repo-root", $RepoRoot)
if ($HostOverride) {
    $ServeArgs += @("--host", $HostOverride)
}
if ($Port -gt 0) {
    $ServeArgs += @("--port", "$Port")
}
if ($AllowNonLocalHost) {
    $ServeArgs += "--allow-non-local-host"
}

& $PythonExe @PythonPrefixArgs @ServeArgs
exit $LASTEXITCODE
