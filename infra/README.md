# Private Foundry infrastructure

This is the complete Bicep infrastructure for the approved demo. It provisions
**one environment at a time**. Use separate azd environments for `byo` and
`managed`; keep the mode, resource group, and address range unchanged on reruns.
There is no supported in-place BYO-to-managed conversion.

Default region: **South Central US (`southcentralus`)**. This is an intended
deployment region, not evidence of available model/VM capacity, quota, provider
registration, policy compliance, or API access in a particular subscription.

## Entry point and azd interface

`main.bicep` is subscription-scoped and creates `rg-${environmentName}`.
All resource names are deterministic from that group's resource ID. The template
does not contain a subscription ID, tenant ID, operator object ID, password,
access key, SAS, randomly generated workspace ID, or data-plane provision hook.

`main.parameters.json` contains ARM JSON, not Bicep parameter syntax. Required
azd substitutions have **no empty-value fallback**:

| Bicep parameter | Binding / default |
| --- | --- |
| `environmentName` | `${AZURE_ENV_NAME}`; nonempty, at most 40 characters |
| `location` | `${AZURE_LOCATION}`; Bicep default `southcentralus`, but azd must supply its nonempty environment value |
| `networkMode` | `${FOUNDRY_NETWORK_MODE}`; required `byo` or `managed` |
| `principalId` | `${AZURE_PRINCIPAL_ID}`; required operator **object** ID |
| `vmAdminPassword` | `${WINDOWS_ADMIN_PASSWORD}`; required secure parameter, 12–123 characters |
| `principalType` | `User`; also supports `Group` / `ServicePrincipal` |
| `vmAdminUsername` | `demoadmin` |
| `vmSize` | `Standard_D2s_v5` |
| `vmImageSku` / `vmImageVersion` | Windows Server `2022-datacenter-azure-edition` / `latest` |
| `privateAddressPrefix` | `10.42.0.0/16` for BYO, `10.43.0.0/16` for managed |
| `completionDeploymentName` / `completionModelName` | `gpt-5.2` / `gpt-5.2` |
| `completionModelVersion` / `completionModelSku` / `completionModelCapacity` | `2025-12-11` / `GlobalStandard` / `30` |
| `embeddingDeploymentName` / `embeddingModelName` | `text-embedding-3-large` / `text-embedding-3-large` |
| `embeddingModelVersion` / `embeddingModelSku` / `embeddingModelCapacity` | `1` / `Standard` / `10` |

Optional parameters are exposed by Bicep. They are not implicitly bound to
similarly named shell variables; customize the parameter file explicitly when
overriding them. Choose a nonoverlapping private IPv4 **/16** before creation.
The generated subnet offsets assume this size.
The model capacities leave room for CU's internal prompts and subsequent agent
inference. Capacity units are model/SKU-specific; they are not prepaid tokens.
Reduce them only after checking both quota and the request sizes needed by your
analyzer. Very small allocations can throttle even a small document.

Keep `WINDOWS_ADMIN_PASSWORD` only in the provisioning process environment.
Never use `azd env set` for the password, commit a parameter value, print it,
or export it in the Windows client configuration. No template output retrieves
or exposes secrets, including nested AVM outputs. No `listKeys` call is emitted.

### Outputs

The following 22 uppercase, nonsecret outputs are the parent CLI contract:

```text
AZURE_RESOURCE_GROUP
FOUNDRY_NETWORK_MODE
AZURE_AI_ACCOUNT_NAME
AZURE_AI_ACCOUNT_ID
AZURE_AI_PROJECT_NAME
AZURE_AI_PROJECT_ID
AZURE_AI_PROJECT_ENDPOINT
AZURE_AI_MODEL_DEPLOYMENT_NAME
CONTENT_UNDERSTANDING_ENDPOINT
CU_COMPLETION_DEPLOYMENT
CU_COMPLETION_MODEL_NAME
CU_EMBEDDING_DEPLOYMENT
CU_EMBEDDING_MODEL_NAME
DOCUMENT_STORAGE_ACCOUNT_NAME
DOCUMENT_STORAGE_ACCOUNT_ID
DOCUMENT_BLOB_ENDPOINT
DOCUMENT_CONTAINER_NAME
VM_NAME
VM_ID
VM_PRINCIPAL_ID
BASTION_NAME
PRIVATE_ADDRESS_PREFIX
```

The project endpoint is
`https://<account>.services.ai.azure.com/api/projects/<project>`.
CU uses **that same account's**
`https://<account>.cognitiveservices.azure.com` endpoint. CU API version
`2025-11-01` and model-alias defaults are configured by the Python application
from the VM, not by workstation-side infrastructure hooks.
The two `*_MODEL_NAME` outputs carry the actual model identifiers independently
of deployment aliases, so the parent setup can validate analyzer `supportedModels`
even when deployment names have been customized.

## Network and data boundaries

Each environment has one customer VNet:

| Subnet | BYO example | Purpose |
| --- | --- | --- |
| `windows` | `10.42.0.0/24` | Private Windows Server 2022 VM |
| `private-endpoints` | `10.42.1.0/24` | Five customer private endpoints |
| `agents` | `10.42.2.0/24` | Dedicated `Microsoft.App/environments` delegation |
| `AzureBastionSubnet` | `10.42.3.0/26` | Bastion Standard |
| `AzureFirewallSubnet` | `10.42.3.64/26` | Firewall Basic data NIC |
| `AzureFirewallManagementSubnet` | `10.42.3.128/26` | Firewall Basic management NIC |

The managed variant reserves, but does not inject into, the customer `agents`
subnet. Its hosted compute runs in the separate Microsoft-managed network.
There is no customer-created Container Apps environment, tool host, ACR, APIM,
classic Machine Learning hub, or extra Key Vault.

The customer has **three public IPs**: Bastion, Firewall data, and Firewall
management. The VM has none. Its only allowed inbound connection is TCP/3389
from the Bastion subnet. Bastion uses its documented management flows and
Standard native-client/file-copy support; it is not forced through the workload
UDR. Firewall infrastructure subnets likewise do not receive that UDR.
The VM's implicitly created OS disk is explicitly environment-tagged as well.
Resources that support tags receive `azd-env-name`; service-owned managed
network internals and child resource types without tags remain provider-managed.

The two workload subnets have default outbound access disabled and a `0.0.0.0/0`
route to the **actual allocated Firewall private IP**. Routing is not based on a
guessed `.4` address. The VNet/Firewall are created before the route table and
workload subnets, so there is no temporary unrestricted workload configuration
or second conflicting definition of those subnets on a rerun.

Basic Firewall supports application FQDN filtering, service tags, and FQDN tags,
but **not DNS proxy, custom DNS, network-rule FQDNs, or TLS inspection**. Clients
therefore use Azure-provided DNS. Six Private DNS zones are linked to the VNet:

- `privatelink.services.ai.azure.com`
- `privatelink.openai.azure.com`
- `privatelink.cognitiveservices.azure.com`
- `privatelink.blob.core.windows.net`
- `privatelink.documents.azure.com`
- `privatelink.search.windows.net`

Public access is disabled **at initial creation** on Foundry, both Storage
accounts, Cosmos DB, and Search. There is no trusted-service bypass or shared-key
fallback. The only business container is private `documents`; Agent backing
Storage is a different account.

### Approved outbound traffic

`modules/egress-allowlist.bicep` is the reviewable FQDN inventory. It includes the
documented MCR, AKS infrastructure, and managed identity dependencies, plus the
approved Python feed and its Azure Artifacts distribution hosts.
The user-approved, credential-free Simple index is
`https://packagefeedproxy.microsoft.io/pypi/simple/`. Its hostname is already in
the shared allowlist: customer Firewall permits HTTPS/TCP 443 from both the VM
and BYO agent subnets, and the managed network creates a corresponding FQDN
outbound rule for source-code remote builds. The parent exports the index URL
into `requirements.txt` by exporting locked requirements and explicitly adding
the approved index directive; no credentials or
broader public-package-host exception is needed for this addition.

The VM additionally gets the pinned tool/repository download hosts,
Windows Update, installer certificate validation, and Azure ARM/Entra access.
Bootstrap HTTPS access includes `aka.ms`, the exact Microsoft-owned
`azcliprod.blob.core.windows.net` installer account, `github.com`,
`api.github.com`, `raw.githubusercontent.com`, `codeload.github.com`,
`release-assets.githubusercontent.com`, and `objects.githubusercontent.com`.
These bootstrap hosts are VM-only, not added to hosted-agent egress. The
separate VM-only certificate rule also allows HTTP/HTTPS to `www.microsoft.com`
for Microsoft's published PKI certificate/CRL paths; Windows signature checks
must not be bypassed when the chain needs these downloads.
Windows activation permits only the three documented Azure Global KMS IPs on
TCP/1688. DNS, IMDS, and Azure VM Agent WireServer traffic are explicitly accounted
for in NSGs. Private service traffic stays on Private Link.

HTTP(S) `Internet` NSG entries allow the transport through the UDR; they do not
override Firewall's destination allowlist. There is no Firewall rule allowing
all internet, `*.blob.core.windows.net`, or public document telemetry. Public
package/release hosts are nevertheless a trust boundary: FQDN filtering is not
per-repository or per-artifact filtering. Use the parent scripts' signature/hash
checks and locked Python requirements.

The managed variant uses `AllowOnlyApprovedOutbound`, managed Firewall **Basic**,
and five outbound private endpoints: **self Foundry**, business Blob, Agent Blob,
Cosmos NoSQL, and Search. Customer inbound private endpoints alone would not
provide these outbound paths. The account identity has Network Connection
Approver only on these five target resources. Rule operations are serialized.
Managed FQDN rules support ports 80/443 as a service limitation, unlike the
customer Firewall's HTTPS-only package rule.

## Identities and provisioning order

These are different principals; permissions on one do not authorize the others:

| Principal | Scope and purpose |
| --- | --- |
| Foundry account identity | Approve the five managed private endpoints, managed variant only |
| Foundry project identity | Foundry User on its parent account for the model proxy; standard backing-service roles |
| Windows VM identity | CU Reader on the account; Foundry Agent Consumer on the project; Blob Contributor on `documents` only |
| Operator `principalId` | Project Manager on the project; CU Contributor for defaults/setup; Blob Contributor on `documents`; Reader on VM/NIC/Bastion |
| Platform-created hosted agent identity | Created during source deployment; the parent's deployment command grants Blob Reader on `documents` and CU Reader on the account |

The operator also receives **conditional** RBAC Administrator on the CU account
and document container: only CU Reader / Blob Reader respectively, and only to
service principals. This closes the source-deployment permission gap without
subscription/RG-wide Owner or unconditional RBAC Administrator. Foundry Project
Manager's built-in delegation alone only permits Foundry User assignments.
Foundry Agent Consumer grants only endpoint interaction. The VM cannot create
or modify agents and has no role-assignment administration. SDK invocation binds
directly to the named agent endpoint without a management-read call.

Deployment order follows the current official standard-agent samples:

1. Network/Firewall/UDR, private dependent services, and account network injection.
2. Customer PEs/DNS; managed approvals/network/outbound rules when selected.
3. Model deployments, project identity, and three AAD backing connections.
4. Project model-proxy role; backing Blob Contributor, Cosmos Operator, Search
   Service Contributor, and Search Index Data Contributor.
5. Project capability host binds the backing connections. **Do not create a
   second account capability host**: account network injection creates it.
6. Read the persisted project workspace ID; grant the official workspace-scoped
   Blob Data Owner ABAC role and Cosmos SQL data contributor on the dedicated
   Agent Cosmos account.

No workspace/container IDs are invented, and role-assignment names are stable.
The platform creates its own backing database/containers. Existing account
network settings are not patched between modes.

## AVM selection and API exceptions

The published `avm/ptn/ai-ml/ai-foundry:0.7.0` pattern was inspected. It does not
expose the required managed-network configuration and includes optional resources
outside this demo. The following **published versions**, verified from Microsoft
Container Registry tag metadata, are pinned instead:

| AVM resource module | Version |
| --- | --- |
| `avm/res/network/virtual-network` | `0.10.2` |
| `avm/res/compute/virtual-machine` | `0.22.3` |
| `avm/res/network/bastion-host` | `0.8.2` |
| `avm/res/network/private-dns-zone` | `0.8.1` |

AVM Storage `0.33.0` was inspected but intentionally not used: it unconditionally
evaluates `listKeys` for secure outputs. Native Storage permits a completely
keyless generated template. Native Foundry, Firewall, Cosmos, Search, PEs, and
RBAC keep the creation-time security and evolving API settings explicit.
AVM deployment telemetry is disabled.

Most Foundry resources use the typed stable `2026-05-01` API. In particular,
the current project capability-host payload only contains backing connections;
older sample `capabilityHostKind` / public-hosting flags are account-host fields,
not valid properties of the current project-host schema.

There are exactly two local schema exceptions, not a blanket no-types setting:

- `foundry-project.bicep` reads the RP's persisted `internalId` with the
  `2025-04-01-preview` API used by the official samples. The public Swagger omits
  this read-only field. `BCP053` is suppressed on this output only.
- `managed-network.bicep` preserves the official sample's
  `provisionNetworkNow: true` wire property. The current Swagger still omits it.
  `BCP037` is suppressed on this property only. Confirm actual managed-network
  and outbound-rule provisioning state before deploying/running hosted code.

## Offline verification

Using an installed Azure CLI/Bicep (no login required):

```powershell
$compiled = Join-Path $env:TEMP 'private-foundry-main.json'
az bicep build --file .\infra\main.bicep --no-restore --outfile $compiled
# Only if the compiler reports missing pinned modules:
# az bicep restore --file .\infra\main.bicep
# Then repeat the build.
python .\infra\tests\test_infrastructure.py --template $compiled -v
```

The build type-checks **both** conditional network branches. The standard-library
tests inspect the real compiled templates, parameter/output contract, separate
mode/CIDR choices, routing, NSGs, Firewall features, private endpoints/DNS,
keyless resources, scoped RBAC, serial operations, and capability-host ordering.
They do not execute ARM expressions or pretend to be a deployment.

Offline verification completed on 2026-09-10 with installed Bicep **0.46.1**:

| Check | Result |
| --- | --- |
| `az bicep build --file infra\main.bicep --no-restore --outfile <temp artifact>` | Passed; both conditional branches checked |
| Independent compilation of all 17 files in `infra\modules\` | Passed |
| `python infra\tests\test_infrastructure.py --template <temp artifact>` | **30 tests passed**, including CU model-name outputs, corporate-feed coverage, and VM-only bootstrap/PKI rules |
| ARM azd parameter JSON parsing / output contract | Passed |
| `git diff --check --no-index` on owned files | Passed |
| Generated key/secret outputs, `listKeys`, `listAccountSas`, `utcNow`, `newGuid` | None |

No Bicep errors or unsuppressed template warnings remained. Azure CLI emitted
only its informational notice that a newer Bicep release exists; no upgrade
was performed. The four AVM references were restored only after the first
`--no-restore` build reported that those pinned artifacts were missing.
Compiled JSON artifacts were kept outside the repository in a unique temporary
directory; no actual password was needed for compilation.

Actual Azure checks were explicitly deferred. Before real provisioning, verify
resource providers, quotas, policies, regional model/SKU capacity, VM image/Trusted
Launch support, deployment/role-assignment permissions, and expected costs.
Allow sufficient time for network/capability-host provisioning and RBAC
propagation; these can take tens of minutes. After provisioning, verify private
DNS/routes, deny-by-default egress, managed PE approval/state, and the real
hosted agent's identity/network using the parent application's diagnostics.
A successful compile does **not** prove any of those live behaviors.

## Primary references

- [Foundry networking options](https://learn.microsoft.com/azure/foundry/agents/concepts/networking-options)
- [Private standard-agent sample (15)](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep/15-private-network-standard-agent-setup)
- [Managed network sample (18)](https://github.com/microsoft-foundry/foundry-samples/tree/main/infrastructure/infrastructure-setup-bicep/18-managed-virtual-network)
- [Managed network documentation](https://learn.microsoft.com/azure/foundry/how-to/managed-virtual-network)
- [Source-code hosted-agent deployment](https://learn.microsoft.com/azure/foundry/agents/how-to/deploy-hosted-agent-code)
- [Hosted agent permissions](https://learn.microsoft.com/azure/foundry/agents/concepts/hosted-agent-permissions)
- [CU security and least-privilege roles](https://learn.microsoft.com/azure/ai-services/content-understanding/concepts/secure-communications)
- [Current model names/versions](https://learn.microsoft.com/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure)
- [Microsoft PKI certificate and revocation endpoints](https://www.microsoft.com/pkiops/docs/repository.htm)
