[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Create", "Status", "Remove")]
    [string]$Action,

    [Parameter(Mandatory = $true)]
    [string]$ProfileId,

    [string]$LocalAddress,
    [int]$LocalPort,
    [ValidateSet("lan", "wireguard")]
    [string]$Mode,
    [string]$RemoteAddress,
    [string]$InterfaceAlias,
    [ValidateSet("Private", "Public", "Domain")]
    [string]$NetworkProfile,
    [string]$Program
)

$ErrorActionPreference = "Stop"
$ruleName = "TTSPlatform.Reader.Remote.$ProfileId"
$displayName = "TTS Platform Reader secure remote access"
$ruleGroup = "TTS Platform Reader"

function Test-PrivateAddress([System.Net.IPAddress]$Address) {
    $bytes = $Address.GetAddressBytes()
    if ($Address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
        return ($bytes[0] -eq 10) -or
            ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
            ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
    }
    return $Address.IsIPv6UniqueLocal
}

function Test-PrivateNetwork([string]$Value) {
    $parts = @($Value -split "/", 2)
    if ($parts.Count -gt 2 -or [string]::IsNullOrWhiteSpace($parts[0])) {
        return $false
    }
    $address = $null
    if (-not [System.Net.IPAddress]::TryParse($parts[0], [ref]$address) -or
        -not (Test-PrivateAddress $address) -or
        [System.Net.IPAddress]::IsLoopback($address)) {
        return $false
    }
    $maximumPrefix = if ($address.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork) {
        32
    } else {
        128
    }
    $prefix = $maximumPrefix
    if ($parts.Count -eq 2) {
        if (-not [int]::TryParse($parts[1], [ref]$prefix) -or
            $prefix -lt 1 -or $prefix -gt $maximumPrefix) {
            return $false
        }
    }
    $minimumPrefix = if ($maximumPrefix -eq 128) { 64 } else { 24 }
    return $prefix -ge $minimumPrefix
}

function Assert-CommonInputs {
    $parsedProfileId = [guid]::Empty
    if (-not [guid]::TryParse($ProfileId, [ref]$parsedProfileId)) {
        throw "The Reader remote profile id must be a UUID."
    }
    $parsedAddress = $null
    if ([string]::IsNullOrWhiteSpace($LocalAddress) -or
        -not [System.Net.IPAddress]::TryParse($LocalAddress, [ref]$parsedAddress) -or
        -not (Test-PrivateAddress $parsedAddress) -or
        [System.Net.IPAddress]::IsLoopback($parsedAddress)) {
        throw "The local address must be an explicit private non-loopback IP address."
    }
    if ($LocalPort -lt 1024 -or $LocalPort -gt 65535) {
        throw "The local port must be between 1024 and 65535."
    }
    if ([string]::IsNullOrWhiteSpace($Program) -or
        -not [System.IO.Path]::IsPathRooted($Program) -or
        -not (Test-Path -LiteralPath $Program -PathType Leaf)) {
        throw "The gateway program must be an existing absolute file."
    }

    $localInterface = @(Get-NetIPAddress -IPAddress $LocalAddress -ErrorAction SilentlyContinue)
    if ($localInterface.Count -ne 1) {
        throw "The selected local address is not uniquely assigned on this computer."
    }
    if ($Mode -eq "lan") {
        if ($RemoteAddress -ne "LocalSubnet" -or $NetworkProfile -ne "Private" -or
            -not [string]::IsNullOrWhiteSpace($InterfaceAlias)) {
            throw "The LAN rule must use LocalSubnet, the Private profile, and no tunnel alias."
        }
        $connection = @(Get-NetConnectionProfile -InterfaceIndex $localInterface[0].InterfaceIndex -ErrorAction SilentlyContinue)
        if ($connection.Count -ne 1 -or $connection[0].NetworkCategory.ToString() -ne "Private") {
            throw "The selected LAN interface is not currently a Private Windows network."
        }
        return
    }
    if ($Mode -ne "wireguard" -or [string]::IsNullOrWhiteSpace($InterfaceAlias) -or
        $RemoteAddress -eq "Any" -or $RemoteAddress -match "^0\.0\.0\.0/0$|^::/0$") {
        throw "The WireGuard rule requires an exact interface alias and private peer IP or subnet."
    }
    if ($localInterface[0].InterfaceAlias -ne $InterfaceAlias) {
        throw "The selected local address does not belong to the selected WireGuard interface."
    }
    if (-not (Test-PrivateNetwork $RemoteAddress)) {
        throw "The WireGuard peer must be a private IP address or subnet."
    }
    $connection = @(Get-NetConnectionProfile -InterfaceAlias $InterfaceAlias -ErrorAction SilentlyContinue)
    if ($connection.Count -ne 1) {
        throw "The selected WireGuard interface has no unique Windows network profile."
    }
    $actualProfile = $connection[0].NetworkCategory.ToString()
    $expectedProfile = if ($NetworkProfile -eq "Domain") { "DomainAuthenticated" } else { $NetworkProfile }
    if ($actualProfile -ne $expectedProfile) {
        throw "The selected WireGuard network profile changed."
    }
}

function Get-RuleStatus {
    $rule = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($null -eq $rule) {
        return [pscustomobject]@{
            exists = $false
            matches = $false
            rule_name = $ruleName
        }
    }
    $portFilter = $rule | Get-NetFirewallPortFilter
    $addressFilter = $rule | Get-NetFirewallAddressFilter
    $applicationFilter = $rule | Get-NetFirewallApplicationFilter
    $interfaceFilter = $rule | Get-NetFirewallInterfaceFilter
    $actualInterface = @($interfaceFilter.InterfaceAlias)
    $interfaceMatches = if ($Mode -eq "wireguard") {
        $actualInterface.Count -eq 1 -and $actualInterface[0] -eq $InterfaceAlias
    } else {
        $actualInterface.Count -eq 1 -and $actualInterface[0] -eq "Any"
    }
    $programMatches = [string]::Equals(
        [System.IO.Path]::GetFullPath($applicationFilter.Program),
        [System.IO.Path]::GetFullPath($Program),
        [System.StringComparison]::OrdinalIgnoreCase)
    $matches = $rule.Enabled.ToString() -eq "True" -and
        $rule.Direction.ToString() -eq "Inbound" -and
        $rule.Action.ToString() -eq "Allow" -and
        $rule.Profile.ToString() -eq $NetworkProfile -and
        $rule.EdgeTraversalPolicy.ToString() -eq "Block" -and
        $portFilter.Protocol.ToString() -eq "TCP" -and
        $portFilter.LocalPort.ToString() -eq $LocalPort.ToString() -and
        $addressFilter.LocalAddress.ToString() -eq $LocalAddress -and
        $addressFilter.RemoteAddress.ToString() -eq $RemoteAddress -and
        $programMatches -and $interfaceMatches
    return [pscustomobject]@{
        exists = $true
        matches = [bool]$matches
        rule_name = $ruleName
        enabled = $rule.Enabled.ToString()
        direction = $rule.Direction.ToString()
        action = $rule.Action.ToString()
        profile = $rule.Profile.ToString()
        protocol = $portFilter.Protocol.ToString()
        local_address = $addressFilter.LocalAddress.ToString()
        local_port = $portFilter.LocalPort.ToString()
        remote_address = $addressFilter.RemoteAddress.ToString()
        interface_alias = @($actualInterface)
        program = $applicationFilter.Program
        edge_traversal = $rule.EdgeTraversalPolicy.ToString()
    }
}

if ($Action -eq "Remove") {
    $parsedProfileId = [guid]::Empty
    if (-not [guid]::TryParse($ProfileId, [ref]$parsedProfileId)) {
        throw "The Reader remote profile id must be a UUID."
    }
    $existing = Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue
    if ($null -ne $existing) {
        Remove-NetFirewallRule -Name $ruleName
    }
    [pscustomobject]@{ removed = ($null -ne $existing); rule_name = $ruleName } |
        ConvertTo-Json -Compress
    exit 0
}

Assert-CommonInputs
if ($Action -eq "Create") {
    $status = Get-RuleStatus
    if ($status.exists -and -not $status.matches) {
        throw "A conflicting Reader firewall rule already exists and was not changed."
    }
    if (-not $status.exists) {
        $parameters = @{
            Name = $ruleName
            DisplayName = $displayName
            Group = $ruleGroup
            Enabled = "True"
            Direction = "Inbound"
            Action = "Allow"
            Protocol = "TCP"
            LocalAddress = $LocalAddress
            LocalPort = $LocalPort
            RemoteAddress = $RemoteAddress
            Profile = $NetworkProfile
            Program = $Program
            EdgeTraversalPolicy = "Block"
        }
        if ($Mode -eq "wireguard") {
            $parameters.InterfaceAlias = $InterfaceAlias
        }
        New-NetFirewallRule @parameters | Out-Null
    }
}

Get-RuleStatus | ConvertTo-Json -Compress
