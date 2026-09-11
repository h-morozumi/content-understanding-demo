#Requires -Version 5.1
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z][a-z0-9-]{1,31}$')]
    [string]$EnvironmentName,
    [string]$OutputPath,
    [switch]$Force
)
. (Join-Path $PSScriptRoot 'Common.ps1')
$root = Split-Path $PSScriptRoot -Parent
Push-Location $root
try {
    if ([string]::IsNullOrWhiteSpace($OutputPath)) {
        $OutputPath = Join-Path $root ".azure\$EnvironmentName\client.json"
    }
    $output = [System.IO.Path]::GetFullPath($OutputPath)
    if ((Test-Path -LiteralPath $output) -and -not $Force) {
        throw 'The output already exists. Select a new path or explicitly use -Force.'
    }
    $values = Read-DemoEnvironment -EnvironmentName $EnvironmentName
    $required = @(
        'AZURE_AI_PROJECT_ENDPOINT', 'CONTENT_UNDERSTANDING_ENDPOINT',
        'DOCUMENT_BLOB_ENDPOINT', 'DOCUMENT_CONTAINER_NAME',
        'AZURE_AI_MODEL_DEPLOYMENT_NAME', 'CU_COMPLETION_DEPLOYMENT',
        'CU_EMBEDDING_DEPLOYMENT', 'CU_COMPLETION_MODEL_NAME', 'CU_EMBEDDING_MODEL_NAME',
        'FOUNDRY_NETWORK_MODE', 'AZURE_AI_ACCOUNT_ID', 'AZURE_AI_PROJECT_ID',
        'DOCUMENT_STORAGE_ACCOUNT_ID'
    )
    $optional = @(
        'HOSTED_AGENT_NAME', 'CU_ANALYZER_ID', 'MAX_DOCUMENT_BYTES', 'ANALYSIS_TIMEOUT_SECONDS'
    )
    $config = [ordered]@{}
    foreach ($key in $required) {
        $config[$key] = Get-RequiredEnvironmentValue -Values $values -Name $key
    }
    foreach ($key in $optional) {
        $property = $values.PSObject.Properties[$key]
        if ($null -ne $property) {
            $config[$key] = [string]$property.Value
        }
    }
    [System.IO.Directory]::CreateDirectory((Split-Path $output -Parent)) | Out-Null
    [System.IO.File]::WriteAllText(
        $output, ($config | ConvertTo-Json -Depth 5), (New-Object System.Text.UTF8Encoding($false))
    )
    Write-Host "Exported non-secret client configuration to $output"
}
finally {
    Pop-Location
}
