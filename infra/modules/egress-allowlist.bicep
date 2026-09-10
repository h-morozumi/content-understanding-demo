// Shared allowlist: customer Firewall and Foundry's managed Firewall must agree
// on the source-build/runtime dependencies. No "*" destination, public customer
// Blob wildcard, customer ACR, Docker Hub, or document telemetry destination.
//
// Sources:
// https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code
// https://learn.microsoft.com/azure/container-apps/use-azure-firewall
// Package feed/redirects are the repository's approved uv/requirements sources.
@export()
var agentFqdns = [
  'mcr.microsoft.com'
  '*.data.mcr.microsoft.com'
  'packages.aks.azure.com'
  'acs-mirror.azureedge.net'
  '*.identity.azure.net'
  'login.microsoft.com'
  '*.login.microsoft.com'
  // These are documented public-Azure platform FQDNs, not URLs of resources
  // that this deployment creates in an arbitrary sovereign cloud.
  #disable-next-line no-hardcoded-env-urls
  'login.microsoftonline.com'
  #disable-next-line no-hardcoded-env-urls
  '*.login.microsoftonline.com'
  'packagefeedproxy.microsoft.io'
  'ms-feed-25.pkgs.visualstudio.com'
  'pkgs.dev.azure.com'
  '*.vsblob.vsassets.io'
]

// These are ONLY available to the Windows subnet, not to hosted Python code.
// GitHub release hosts serve the pinned azd/uv and uv-managed Python artifacts.
// The single public Blob hostname below is Microsoft's Azure CLI installer,
// not a wildcard exception for application storage.
@export()
var vmSetupFqdns = [
  'aka.ms'
  // Microsoft-owned installer account; substituting our cloud/storage suffix
  // would incorrectly describe a different, nonexistent download destination.
  #disable-next-line no-hardcoded-env-urls
  'azcliprod.blob.core.windows.net'
  'github.com'
  'api.github.com'
  'raw.githubusercontent.com'
  'codeload.github.com'
  'objects.githubusercontent.com'
  'release-assets.githubusercontent.com'
  'login.live.com'
  #disable-next-line no-hardcoded-env-urls
  'device.login.microsoftonline.com'
  'microsoft.com'
  'www.microsoft.com'
]

// Authenticode / TLS revocation checks for the Microsoft-signed installers.
@export()
var certificateFqdns = [
  // Microsoft PKI publishes HTTP certificate/CRL endpoints needed by Windows
  // chain validation; the installer HTTPS-only rule is insufficient for these.
  // https://www.microsoft.com/pkiops/docs/repository.htm
  'www.microsoft.com'
  'crl.microsoft.com'
  'mscrl.microsoft.com'
  'oneocsp.microsoft.com'
  'ocsp.msocsp.com'
  'ctldl.windowsupdate.com'
  'crl3.digicert.com'
  'crl4.digicert.com'
  'ocsp.digicert.com'
  'cacerts.digicert.com'
]

// Basic does not support network-rule FQDNs or DNS proxy. Windows KMS uses
// TCP/1688 and these documented Azure Global addresses, through Firewall SNAT.
// https://learn.microsoft.com/troubleshoot/azure/virtual-machines/windows/custom-routes-enable-kms-activation
@export()
var windowsKmsAddresses = [
  '20.118.99.224'
  '40.83.235.53'
  '23.102.135.246'
]
