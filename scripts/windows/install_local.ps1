[CmdletBinding()]
param(
    [string]$PythonExecutable = "",
    [switch]$SkipSetup,
    [switch]$NoBuildTooling,
    [switch]$InstallRealRuntime
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$VenvDir = Join-Path $RepoRoot ".venv"
$VenvPython = Join-Path $VenvDir "Scripts\python.exe"

function Resolve-BasePython {
    if ($PythonExecutable) {
        return @{
            Exe = $PythonExecutable
            PrefixArgs = @()
        }
    }
    if ($env:TTS_PLATFORM_PYTHON) {
        return @{
            Exe = $env:TTS_PLATFORM_PYTHON
            PrefixArgs = @()
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        return @{
            Exe = "py"
            PrefixArgs = @("-3")
        }
    }
    return @{
        Exe = "python"
        PrefixArgs = @()
    }
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [switch]$RedirectStdoutToError
    )

    $StdoutPath = [System.IO.Path]::GetTempFileName()
    $StderrPath = [System.IO.Path]::GetTempFileName()
    try {
        $Process = Start-Process `
            -FilePath $FilePath `
            -ArgumentList $Arguments `
            -Wait `
            -PassThru `
            -NoNewWindow `
            -RedirectStandardOutput $StdoutPath `
            -RedirectStandardError $StderrPath
        $ExitCode = $Process.ExitCode
        $StdoutText = Get-Content -Raw -Path $StdoutPath
        $StderrText = Get-Content -Raw -Path $StderrPath
        if ($RedirectStdoutToError) {
            if ($StdoutText) {
                [Console]::Error.WriteLine($StdoutText.TrimEnd())
            }
        } elseif ($StdoutText) {
            $StdoutText.TrimEnd()
        }
        if ($StderrText) {
            [Console]::Error.WriteLine($StderrText.TrimEnd())
        }
        if ($ExitCode -ne 0) {
            exit $ExitCode
        }
    } finally {
        Remove-Item -LiteralPath $StdoutPath, $StderrPath -ErrorAction SilentlyContinue
    }
}

$BasePython = Resolve-BasePython
$CreatedVenv = $false
if (-not (Test-Path $VenvPython)) {
    Invoke-CheckedCommand `
        -FilePath $BasePython.Exe `
        -Arguments ($BasePython.PrefixArgs + @("-m", "venv", "--system-site-packages", $VenvDir)) `
        -RedirectStdoutToError
    $CreatedVenv = $true
}

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment python was not created at $VenvPython"
}

if (-not $NoBuildTooling) {
    Invoke-CheckedCommand `
        -FilePath $VenvPython `
        -Arguments @("-m", "pip", "install", "--disable-pip-version-check", "setuptools>=69", "wheel") `
        -RedirectStdoutToError
}

Invoke-CheckedCommand `
    -FilePath $VenvPython `
    -Arguments @("-m", "pip", "install", "--no-build-isolation", "--no-deps", "-e", $RepoRoot) `
    -RedirectStdoutToError

if ($InstallRealRuntime) {
    Invoke-CheckedCommand `
        -FilePath $VenvPython `
        -Arguments @("-m", "pip", "install", "--no-build-isolation", "-e", "$RepoRoot[real]") `
        -RedirectStdoutToError
}

$SetupPayload = $null
if (-not $SkipSetup) {
    $SetupOutput = & $VenvPython -m tts_service.cli setup-local --repo-root $RepoRoot
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
    $SetupPayload = ($SetupOutput -join "`n") | ConvertFrom-Json
}

[ordered]@{
    repo_root = $RepoRoot
    venv_created = $CreatedVenv
    venv_python = $VenvPython
    build_tooling_installed = -not $NoBuildTooling
    editable_install = $true
    real_runtime_installed = [bool]$InstallRealRuntime
    setup = $SetupPayload
} | ConvertTo-Json -Depth 8
