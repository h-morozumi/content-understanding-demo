#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$scratch = Join-Path ([System.IO.Path]::GetTempPath()) ("private-cu-tests-" + [guid]::NewGuid())
[System.IO.Directory]::CreateDirectory($scratch) | Out-Null
$global:DemoTestCommands = New-Object System.Collections.Generic.List[object]
$global:DemoTestFailure = $false
$global:DemoTestValues = @{
    AZURE_SUBSCRIPTION_ID = '11111111-1111-4111-8111-111111111111'
    AZURE_AI_PROJECT_ENDPOINT = 'https://example.services.ai.azure.com/api/projects/demo'
    CONTENT_UNDERSTANDING_ENDPOINT = 'https://example.cognitiveservices.azure.com'
    DOCUMENT_BLOB_ENDPOINT = 'https://example.blob.core.windows.net'
    DOCUMENT_CONTAINER_NAME = 'documents'
    AZURE_AI_MODEL_DEPLOYMENT_NAME = 'gpt-5.2'
    CU_COMPLETION_DEPLOYMENT = 'gpt-5.2'
    CU_EMBEDDING_DEPLOYMENT = 'embedding'
    CU_COMPLETION_MODEL_NAME = 'gpt-5.2'
    CU_EMBEDDING_MODEL_NAME = 'text-embedding-3-large'
    FOUNDRY_NETWORK_MODE = 'byo'
    AZURE_AI_ACCOUNT_ID = '/subscriptions/example/account'
    AZURE_AI_PROJECT_ID = '/subscriptions/example/project'
    DOCUMENT_STORAGE_ACCOUNT_ID = '/subscriptions/example/storage'
    WINDOWS_ADMIN_PASSWORD = 'must-not-be-exported'
    AZURE_CLIENT_SECRET = 'must-not-be-exported'
}

# These functions shadow the native commands; no Azure CLI/azd process is started.
function global:azd {
    $global:DemoTestCommands.Add(@($args))
    $global:LASTEXITCODE = 0
    if ($global:DemoTestFailure) {
        $global:LASTEXITCODE = 9
        return
    }
    if ($args.Count -ge 2 -and $args[0] -eq 'env' -and $args[1] -eq 'get-values') {
        return ($global:DemoTestValues | ConvertTo-Json)
    }
}
function global:az {
    $global:DemoTestCommands.Add(@($args))
    $global:LASTEXITCODE = 0
    return '2099-01-01'
}
function Assert-Demo {
    param([bool]$Condition, [string]$Message)
    if (-not $Condition) {
        throw $Message
    }
}

$output = Join-Path $scratch 'client.json'
$previousPassword = [Environment]::GetEnvironmentVariable('WINDOWS_ADMIN_PASSWORD', 'Process')
try {
    & (Join-Path $root 'scripts\Export-ClientConfig.ps1') -EnvironmentName demo-test -OutputPath $output
    $config = Get-Content -LiteralPath $output -Raw | ConvertFrom-Json
    Assert-Demo ($config.DOCUMENT_CONTAINER_NAME -eq 'documents') 'Required output was lost.'
    Assert-Demo ($null -eq $config.PSObject.Properties['WINDOWS_ADMIN_PASSWORD']) 'Password was exported.'
    Assert-Demo ($null -eq $config.PSObject.Properties['AZURE_CLIENT_SECRET']) 'Client secret was exported.'

    $failed = $false
    try {
        & (Join-Path $root 'scripts\Export-ClientConfig.ps1') -EnvironmentName demo-test -OutputPath $output
    }
    catch [System.Management.Automation.RuntimeException] {
        $failed = $_.Exception.Message -match 'already exists'
    }
    Assert-Demo $failed 'Existing client configuration was overwritten without -Force.'

    & (Join-Path $root 'scripts\New-DemoEnvironment.ps1') -EnvironmentName demo-unit-byo `
        -NetworkMode byo -SubscriptionId '11111111-1111-4111-8111-111111111111'
    $commands = $global:DemoTestCommands | ConvertTo-Json -Depth 5
    Assert-Demo ($commands.Contains('southcentralus')) 'The chosen default region was not applied.'
    Assert-Demo ($commands.Contains('FOUNDRY_NETWORK_MODE')) 'The network mode was not applied.'

    $env:WINDOWS_ADMIN_PASSWORD = 'previous-test-value'
    $password = ConvertTo-SecureString 'UnitTestOnly-123!' -AsPlainText -Force
    & (Join-Path $root 'scripts\Provision-Demo.ps1') -EnvironmentName demo-test `
        -QuotaReviewed -VmAdminPassword $password
    Assert-Demo ($env:WINDOWS_ADMIN_PASSWORD -eq 'previous-test-value') 'Password environment was not restored.'
    $commands = $global:DemoTestCommands | ConvertTo-Json -Depth 5
    Assert-Demo (-not $commands.Contains('UnitTestOnly-123!')) 'Password was passed on a command line.'
    Assert-Demo (-not $commands.Contains('WINDOWS_ADMIN_PASSWORD')) 'Password was saved with azd env set.'

    $global:DemoTestFailure = $true
    $failed = $false
    try {
        & (Join-Path $root 'scripts\Provision-Demo.ps1') -EnvironmentName demo-test `
            -QuotaReviewed -VmAdminPassword $password
    }
    catch [System.Management.Automation.RuntimeException] {
        $failed = $_.Exception.Message -match 'exit code 9'
    }
    Assert-Demo $failed 'Native-command failure was swallowed.'
    Assert-Demo ($env:WINDOWS_ADMIN_PASSWORD -eq 'previous-test-value') 'Failure leaked password environment.'
    Write-Host 'PowerShell environment, secret export, and failure-handling tests passed.'
}
finally {
    [Environment]::SetEnvironmentVariable('WINDOWS_ADMIN_PASSWORD', $previousPassword, 'Process')
    Remove-Item -LiteralPath 'Function:\azd', 'Function:\az'
    if (Test-Path -LiteralPath $output) {
        Remove-Item -LiteralPath $output
    }
    [System.IO.Directory]::Delete($scratch)
    Remove-Variable -Name DemoTestCommands, DemoTestFailure, DemoTestValues -Scope Global
}
