[CmdletBinding()]
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [ValidateSet("Both", "Win32", "x64")]
    [string]$Platform = "Both",
    [string]$MsBuildPath = "",
    [switch]$RequireBuildTools
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = (Resolve-Path (Join-Path $ScriptDir "..\..")).Path
$ProjectPath = Join-Path $RepoRoot "apps\sapi_bridge\TtsPlatformSapiBridge.vcxproj"
$BuildToolsPackageId = "Microsoft.VisualStudio.2022.BuildTools"
$BuildToolsComponents = @(
    "Microsoft.VisualStudio.Workload.VCTools",
    "Microsoft.VisualStudio.Component.Windows10SDK.19041"
)

function Get-BuildToolsInstallCommand {
    $componentArgs = ($BuildToolsComponents | ForEach-Object { "--add $_" }) -join " "
    return "winget install --id $BuildToolsPackageId --exact --source winget --override `"--wait --passive $componentArgs --includeRecommended`""
}

function Find-MSBuildUnderVisualStudio {
    $roots = @(
        (Join-Path $env:ProgramFiles "Microsoft Visual Studio"),
        (Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio")
    )
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) {
            continue
        }
        $candidate = Get-ChildItem -Path $root -Recurse -Filter MSBuild.exe -ErrorAction SilentlyContinue |
            Where-Object { $_.FullName -like "*\MSBuild\Current\Bin\MSBuild.exe" } |
            Select-Object -First 1
        if ($candidate) {
            return $candidate.FullName
        }
    }
    return ""
}

function Resolve-MSBuild {
    if ($MsBuildPath) {
        if (-not (Test-Path -LiteralPath $MsBuildPath)) {
            throw "MSBuild path does not exist: $MsBuildPath"
        }
        return (Resolve-Path -LiteralPath $MsBuildPath).Path
    }

    $fromPath = Get-Command msbuild.exe -ErrorAction SilentlyContinue
    if ($fromPath) {
        return $fromPath.Source
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path -LiteralPath $vswhere) {
        $installPath = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -property installationPath
        if ($installPath) {
            $candidate = Join-Path $installPath "MSBuild\Current\Bin\MSBuild.exe"
            if (Test-Path -LiteralPath $candidate) {
                return $candidate
            }
        }
    }

    return Find-MSBuildUnderVisualStudio
}

function Get-Platforms {
    if ($Platform -eq "Both") {
        return @("Win32", "x64")
    }
    return @($Platform)
}

function Build-Platform {
    param(
        [string]$ResolvedMsBuild,
        [ValidateSet("Win32", "x64")][string]$BuildPlatform
    )

    $arguments = @(
        $ProjectPath,
        "/m",
        "/restore",
        "/p:Configuration=$Configuration",
        "/p:Platform=$BuildPlatform"
    )
    & $ResolvedMsBuild @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "MSBuild failed for $BuildPlatform $Configuration with exit code $LASTEXITCODE."
    }

    $dllPath = Join-Path $RepoRoot "apps\sapi_bridge\build\$BuildPlatform\$Configuration\TtsPlatformSapiBridge.dll"
    return [ordered]@{
        platform = $BuildPlatform
        configuration = $Configuration
        dll_path = $dllPath
        dll_exists = Test-Path -LiteralPath $dllPath
    }
}

$resolvedMsBuild = Resolve-MSBuild
if (-not $resolvedMsBuild) {
    $message = "MSBuild was not found. Install Visual Studio Build Tools with Desktop development with C++ and the Windows SDK, then run from a Developer PowerShell."
    if ($RequireBuildTools) {
        throw $message
    }
    [ordered]@{
        ok = $false
        built = $false
        message = $message
        project = $ProjectPath
        install_guidance = [ordered]@{
            winget_available = [bool](Get-Command winget.exe -ErrorAction SilentlyContinue)
            visual_studio_build_tools_package = $BuildToolsPackageId
            required_components = $BuildToolsComponents
            winget_command = Get-BuildToolsInstallCommand
        }
        next_steps = @(
            "Install Visual Studio Build Tools with Desktop development with C++",
            "Include the Windows 10 or 11 SDK",
            "Open a Visual Studio Developer PowerShell",
            "Run scripts\windows\build_sapi_bridge.ps1"
        )
    } | ConvertTo-Json -Depth 5
    exit 0
}

$results = foreach ($buildPlatform in Get-Platforms) {
    Build-Platform -ResolvedMsBuild $resolvedMsBuild -BuildPlatform $buildPlatform
}

[ordered]@{
    ok = $true
    built = $true
    msbuild = $resolvedMsBuild
    project = $ProjectPath
    configuration = $Configuration
    platform = $Platform
    results = @($results)
    next_steps = @(
        "Run scripts\windows\install_sapi_native_voice.ps1 -Architecture <X86-or-X64> -DllPath <built-dll>",
        "Run scripts\windows\check_sapi_native_voice.ps1 -RequireInstalled",
        "Open TextAloud and test TTS Platform Native Dummy Voice"
    )
} | ConvertTo-Json -Depth 5
