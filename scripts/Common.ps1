#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Invoke-DemoCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [string[]]$Arguments = @()
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

function Read-DemoEnvironment {
    param([Parameter(Mandatory = $true)][string]$EnvironmentName)
    $raw = Invoke-DemoCommand -Command 'azd' -Arguments @(
        'env', 'get-values', '--environment', $EnvironmentName, '--output', 'json'
    )
    return (($raw -join "`n") | ConvertFrom-Json)
}

function Get-RequiredEnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]$Values,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $property = $Values.PSObject.Properties[$Name]
    if ($null -eq $property -or [string]::IsNullOrWhiteSpace([string]$property.Value)) {
        throw "Missing $Name in the selected azd environment."
    }
    return [string]$property.Value
}
