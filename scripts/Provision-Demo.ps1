#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{1,31}$')]
    [string]$EnvironmentName,
    [switch]$QuotaReviewed,
    [securestring]$VmAdminPassword
)
. (Join-Path $PSScriptRoot 'Common.ps1')
if (-not $QuotaReviewed) {
    throw 'Review service availability, quota, policies, costs, and RBAC in README.md; then use -QuotaReviewed.'
}
$root = Split-Path $PSScriptRoot -Parent
$previousPassword = [Environment]::GetEnvironmentVariable('WINDOWS_ADMIN_PASSWORD', 'Process')
Push-Location $root
try {
    $values = Read-DemoEnvironment -EnvironmentName $EnvironmentName
    $subscription = Get-RequiredEnvironmentValue -Values $values -Name 'AZURE_SUBSCRIPTION_ID'
    $mode = Get-RequiredEnvironmentValue -Values $values -Name 'FOUNDRY_NETWORK_MODE'
    if ($mode -notin @('byo', 'managed')) {
        throw 'Invalid network mode. Prepare a new byo or managed azd environment.'
    }
    # Check the operator's selected subscription without printing an access token.
    Invoke-DemoCommand -Command 'az' -Arguments @(
        'account', 'get-access-token', '--subscription', $subscription,
        '--resource', 'https://management.azure.com/', '--query', 'expiresOn', '-o', 'tsv'
    ) | Out-Null
    if ($null -eq $VmAdminPassword) {
        $VmAdminPassword = Read-Host 'Windows VM administrator password (not saved to azd)' -AsSecureString
    }
    if ($VmAdminPassword.Length -lt 12) {
        throw 'Use a strong VM password with at least 12 characters.'
    }
    $env:WINDOWS_ADMIN_PASSWORD = (
        New-Object System.Net.NetworkCredential('', $VmAdminPassword)
    ).Password
    Invoke-DemoCommand -Command 'azd' -Arguments @(
        'provision', '--environment', $EnvironmentName, '--no-prompt'
    )
}
finally {
    [Environment]::SetEnvironmentVariable('WINDOWS_ADMIN_PASSWORD', $previousPassword, 'Process')
    Pop-Location
}
