#Requires -Version 5.1
#Requires -RunAsAdministrator
[CmdletBinding(SupportsShouldProcess = $true)]
param([string]$ToolsRoot = 'C:\Tools\PrivateCuDemo')
. (Join-Path $PSScriptRoot 'Common.ps1')
if (-not $PSCmdlet.ShouldProcess($ToolsRoot, 'Install Azure CLI, azd, uv, and Python 3.13')) {
    return
}
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ToolsRoot = [System.IO.Path]::GetFullPath($ToolsRoot)
$downloads = Join-Path $ToolsRoot 'downloads'
[System.IO.Directory]::CreateDirectory($downloads) | Out-Null

function Get-VerifiedDownload {
    param([string]$Url, [string]$Path, [string]$Sha256)
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $Path -TimeoutSec 300
    if ($Sha256 -and (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ne $Sha256) {
        throw "SHA-256 mismatch for $Path. The installer was not executed."
    }
}

function Install-MicrosoftMsi {
    param([string]$Path)
    $signature = Get-AuthenticodeSignature -LiteralPath $Path
    if ($signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation(?:,|$)') {
        throw "The Microsoft installer signature is not valid: $Path"
    }
    $process = Start-Process -FilePath 'msiexec.exe' -ArgumentList @(
        '/i', "`"$Path`"", '/quiet', '/norestart'
    ) -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Installer failed with exit code $($process.ExitCode): $Path"
    }
    if ($process.ExitCode -eq 3010) {
        Write-Warning 'The installer requests a restart. Restart the VM when convenient.'
    }
}

$azMsi = Join-Path $downloads 'azure-cli-x64.msi'
Get-VerifiedDownload -Url 'https://aka.ms/installazurecliwindowsx64' -Path $azMsi
Install-MicrosoftMsi -Path $azMsi

$azdMsi = Join-Path $downloads 'azd-1.33.0-windows-amd64.msi'
Get-VerifiedDownload -Url 'https://github.com/Azure/azure-dev/releases/download/azure-dev-cli_1.33.0/azd-windows-amd64.msi' `
    -Path $azdMsi -Sha256 'fff4981975ff067942189249fb0ede00e79c5730d2d9ada8b08b129bc4242845'
Install-MicrosoftMsi -Path $azdMsi

$uvArchive = Join-Path $downloads 'uv-0.12.12-windows-x64.zip'
Get-VerifiedDownload -Url 'https://github.com/astral-sh/uv/releases/download/0.12.12/uv-x86_64-pc-windows-msvc.zip' `
    -Path $uvArchive -Sha256 '3d54912924c36e862c14f427d04f2ed70a99e8001d1c30caa101f6d5711626d5'
$uvDirectory = Join-Path $ToolsRoot 'uv-0.12.12'
Expand-Archive -LiteralPath $uvArchive -DestinationPath $uvDirectory -Force
$uvExecutables = @(Get-ChildItem -LiteralPath $uvDirectory -Filter 'uv.exe' -File -Recurse)
if ($uvExecutables.Count -ne 1) {
    throw 'Expected exactly one uv.exe in the verified uv archive.'
}
$uvPath = $uvExecutables[0].Directory.FullName
$machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
if ($uvPath -notin ($machinePath -split ';')) {
    [Environment]::SetEnvironmentVariable('Path', "$machinePath;$uvPath", 'Machine')
}
$env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' +
    [Environment]::GetEnvironmentVariable('Path', 'User')
$env:UV_NATIVE_TLS = 'true'
Invoke-DemoCommand -Command $uvExecutables[0].FullName -Arguments @('python', 'install', '3.13')
Invoke-DemoCommand -Command 'az' -Arguments @('version', '--output', 'json')
Invoke-DemoCommand -Command 'azd' -Arguments @('version')
Invoke-DemoCommand -Command $uvExecutables[0].FullName -Arguments @('--version')
Write-Host 'Tools installed. Open a new terminal, then follow the VM steps in README.md.'
Write-Host "Installers are retained under $downloads for inspection."
