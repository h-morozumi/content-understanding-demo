#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{1,31}$')]
    [string]$EnvironmentName,
    [Parameter(Mandatory = $true)]
    [ValidateSet('byo', 'managed')]
    [string]$NetworkMode,
    [Parameter(Mandatory = $true)]
    [guid]$SubscriptionId,
    [ValidateSet('australiaeast', 'eastus', 'eastus2', 'japaneast', 'southcentralus',
        'swedencentral', 'uksouth', 'westus', 'westus3')]
    [string]$Location = 'southcentralus'
)
. (Join-Path $PSScriptRoot 'Common.ps1')
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if (Test-Path -LiteralPath (Join-Path $root ".azure\$EnvironmentName")) {
        throw 'This environment already exists. Do not change its Foundry network mode.'
    }
    Invoke-DemoCommand -Command 'azd' -Arguments @(
        'env', 'new', $EnvironmentName, '--subscription', $SubscriptionId.ToString(),
        '--location', $Location, '--no-prompt'
    )
    Invoke-DemoCommand -Command 'azd' -Arguments @(
        'env', 'set', 'AZURE_SUBSCRIPTION_ID', $SubscriptionId.ToString(), '-e', $EnvironmentName
    )
    Invoke-DemoCommand -Command 'azd' -Arguments @(
        'env', 'set', 'AZURE_LOCATION', $Location, '-e', $EnvironmentName
    )
    Invoke-DemoCommand -Command 'azd' -Arguments @(
        'env', 'set', 'FOUNDRY_NETWORK_MODE', $NetworkMode, '-e', $EnvironmentName
    )
    Write-Host "Prepared local environment $EnvironmentName ($NetworkMode, $Location)."
    Write-Host 'No Azure resources were provisioned. Review quotas and policies before provisioning.'
}
finally {
    Pop-Location
}
