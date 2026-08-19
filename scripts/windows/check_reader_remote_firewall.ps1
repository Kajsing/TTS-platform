[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LocalAddress,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1024, 65535)]
    [int]$LocalPort,

    [Parameter(Mandatory = $true)]
    [string]$RemoteAddress,

    [Parameter(Mandatory = $true)]
    [string]$InterfaceAlias,

    [Parameter(Mandatory = $true)]
    [ValidateSet("Private", "Public", "Domain")]
    [string]$NetworkProfile,

    [Parameter(Mandatory = $true)]
    [string]$Program
)

$ErrorActionPreference = "Stop"
$helperPath = Join-Path $PSScriptRoot "reader_remote_firewall.ps1"
$profileId = [guid]::NewGuid().ToString("D")
$ruleName = "TTSPlatform.Reader.Remote.$profileId"
$createAttempted = $false
$primaryFailure = $null
$firstCreate = $null
$secondCreate = $null
$statusCheck = $null
$removeResult = $null

function Assert-Elevated {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]::new($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run this acceptance check from an elevated PowerShell window."
    }
}

function Invoke-FirewallHelper([string]$RequestedAction) {
    $arguments = @(
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        $helperPath,
        "-Action",
        $RequestedAction,
        "-ProfileId",
        $profileId
    )
    if ($RequestedAction -ne "Remove") {
        $arguments += @(
            "-LocalAddress",
            $LocalAddress,
            "-LocalPort",
            $LocalPort.ToString(),
            "-Mode",
            "wireguard",
            "-RemoteAddress",
            $RemoteAddress,
            "-InterfaceAlias",
            $InterfaceAlias,
            "-NetworkProfile",
            $NetworkProfile,
            "-Program",
            $Program
        )
    }
    $lines = @(& powershell.exe @arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $output = ($lines | Out-String).Trim()
    if ($exitCode -ne 0) {
        throw "Firewall helper $RequestedAction failed: $output"
    }
    try {
        return $output | ConvertFrom-Json
    } catch {
        throw "Firewall helper $RequestedAction returned invalid status output."
    }
}

Assert-Elevated
if (-not (Test-Path -LiteralPath $helperPath -PathType Leaf)) {
    throw "The Reader firewall helper is missing."
}
if ($null -ne (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue)) {
    throw "The temporary acceptance rule name unexpectedly already exists."
}

try {
    $createAttempted = $true
    $firstCreate = Invoke-FirewallHelper "Create"
    if (-not $firstCreate.exists -or -not $firstCreate.matches) {
        throw "The first firewall create did not produce the exact requested rule."
    }

    $secondCreate = Invoke-FirewallHelper "Create"
    if (-not $secondCreate.exists -or -not $secondCreate.matches) {
        throw "The idempotent second create changed or rejected the exact rule."
    }

    $statusCheck = Invoke-FirewallHelper "Status"
    if (-not $statusCheck.exists -or -not $statusCheck.matches) {
        throw "The independent firewall status check did not match the exact rule."
    }
} catch {
    $primaryFailure = $_
} finally {
    if ($createAttempted) {
        try {
            $removeResult = Invoke-FirewallHelper "Remove"
        } catch {
            if ($null -eq $primaryFailure) {
                $primaryFailure = $_
            }
        }
    }
}

$remainingRule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
if ($null -ne $remainingRule) {
    throw "Firewall acceptance did not clean up $ruleName. Remove that exact rule before continuing."
}
if ($null -ne $primaryFailure) {
    throw "Firewall acceptance failed and its temporary rule was removed: $($primaryFailure.Exception.Message)"
}
if ($null -eq $removeResult -or -not $removeResult.removed) {
    throw "Firewall acceptance could not prove that its temporary rule was removed."
}

[pscustomobject]@{
    status = "ok"
    mode = "wireguard"
    profile_id = $profileId
    rule_name = $ruleName
    first_create_matched = [bool]$firstCreate.matches
    second_create_matched = [bool]$secondCreate.matches
    status_matched = [bool]$statusCheck.matches
    removed = [bool]$removeResult.removed
    rule_remaining = $false
    firewall_changed = $false
} | ConvertTo-Json -Compress
