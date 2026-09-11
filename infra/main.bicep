targetScope = 'subscription'

@description('The azd environment name. Use different environments for byo and managed; do not change a deployed account between modes.')
@minLength(1)
@maxLength(40)
param environmentName string

@description('Azure region for this environment. Availability, policy, and quota must be checked before provisioning.')
@minLength(1)
param location string = 'southcentralus'

@description('Creation-time Foundry network isolation. Each mode requires its own azd environment and resources.')
@allowed([
  'byo'
  'managed'
])
param networkMode string

@description('Object ID of the operator who configures CU defaults and deploys the hosted agent from the VM. Not an application/client ID.')
@minLength(36)
@maxLength(36)
param principalId string

@description('Directory object type for the operator principal.')
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param principalType string = 'User'

@secure()
@description('Windows administrator password. Supply WINDOWS_ADMIN_PASSWORD in the provisioning process environment, never in azd env files or source control.')
@minLength(12)
@maxLength(123)
param vmAdminPassword string

@description('Local Windows administrator name. Azure/Windows reserved usernames are not permitted.')
@minLength(1)
@maxLength(20)
param vmAdminUsername string = 'demoadmin'

@description('VM SKU. The default has two vCPUs; capacity and Trusted Launch compatibility remain subject to live verification.')
param vmSize string = 'Standard_D2s_v5'

@description('Windows Server 2022 Gen2 image SKU, compatible with Trusted Launch.')
param vmImageSku string = '2022-datacenter-azure-edition'

@description('Windows image version. Pin an available image version here if required by your image policy.')
param vmImageVersion string = 'latest'

@description('Nonoverlapping private IPv4 /16 for this environment. Choose before provisioning; do not change a live network.')
param privateAddressPrefix string = networkMode == 'byo' ? '10.42.0.0/16' : '10.43.0.0/16'

@description('Deployment used by the hosted agent and the CU completion aliases.')
@minLength(1)
param completionDeploymentName string = 'gpt-5.2'

@description('CU-supported completion model. Confirm supportedModels on the chosen analyzer before use.')
@minLength(1)
param completionModelName string = 'gpt-5.2'

@description('Published GPT-5.2 model version; this is not an assertion of regional SKU availability or quota.')
@minLength(1)
param completionModelVersion string = '2025-12-11'

@description('Model deployment SKU. GlobalStandard can process outside the resource region; choose an available SKU appropriate to your data-residency requirements.')
@minLength(1)
param completionModelSku string = 'GlobalStandard'

@description('Completion deployment capacity units. Small demo default, subject to model-specific minimums and quota.')
@minValue(1)
param completionModelCapacity int = 30

@description('Deployment used by the CU embedding aliases.')
@minLength(1)
param embeddingDeploymentName string = 'text-embedding-3-large'

@description('CU-supported embedding model.')
@minLength(1)
param embeddingModelName string = 'text-embedding-3-large'

@description('Published embedding model version.')
@minLength(1)
param embeddingModelVersion string = '1'

@description('Embedding deployment SKU; verify availability and quota before provisioning.')
@minLength(1)
param embeddingModelSku string = 'Standard'

@description('Embedding deployment capacity units, subject to model-specific minimums and quota.')
@minValue(1)
param embeddingModelCapacity int = 10

var tags = {
  'azd-env-name': environmentName
  'foundry-network-mode': networkMode
}

resource resourceGroup 'Microsoft.Resources/resourceGroups@2025-04-01' = {
  name: 'rg-${environmentName}'
  location: location
  tags: tags
}

module resources './modules/resources.bicep' = {
  name: 'private-foundry-resources'
  scope: resourceGroup
  params: {
    location: location
    tags: tags
    networkMode: networkMode
    principalId: principalId
    principalType: principalType
    vmAdminUsername: vmAdminUsername
    vmAdminPassword: vmAdminPassword
    vmSize: vmSize
    vmImageSku: vmImageSku
    vmImageVersion: vmImageVersion
    privateAddressPrefix: privateAddressPrefix
    completionDeploymentName: completionDeploymentName
    completionModelName: completionModelName
    completionModelVersion: completionModelVersion
    completionModelSku: completionModelSku
    completionModelCapacity: completionModelCapacity
    embeddingDeploymentName: embeddingDeploymentName
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingModelSku: embeddingModelSku
    embeddingModelCapacity: embeddingModelCapacity
  }
}

// These nonsecret outputs are the azd / Windows CLI interface.
output AZURE_RESOURCE_GROUP string = resourceGroup.name
output FOUNDRY_NETWORK_MODE string = networkMode
output AZURE_AI_ACCOUNT_NAME string = resources.outputs.accountName
output AZURE_AI_ACCOUNT_ID string = resources.outputs.accountId
output AZURE_AI_PROJECT_NAME string = resources.outputs.projectName
output AZURE_AI_PROJECT_ID string = resources.outputs.projectId
output AZURE_AI_PROJECT_ENDPOINT string = resources.outputs.projectEndpoint
output AZURE_AI_MODEL_DEPLOYMENT_NAME string = completionDeploymentName
output CONTENT_UNDERSTANDING_ENDPOINT string = resources.outputs.contentUnderstandingEndpoint
output CU_COMPLETION_DEPLOYMENT string = completionDeploymentName
output CU_COMPLETION_MODEL_NAME string = completionModelName
output CU_EMBEDDING_DEPLOYMENT string = embeddingDeploymentName
output CU_EMBEDDING_MODEL_NAME string = embeddingModelName
output DOCUMENT_STORAGE_ACCOUNT_NAME string = resources.outputs.documentStorageName
output DOCUMENT_STORAGE_ACCOUNT_ID string = resources.outputs.documentStorageId
output DOCUMENT_BLOB_ENDPOINT string = resources.outputs.documentBlobEndpoint
output DOCUMENT_CONTAINER_NAME string = resources.outputs.documentContainerName
output VM_NAME string = resources.outputs.vmName
output VM_ID string = resources.outputs.vmId
output VM_PRINCIPAL_ID string = resources.outputs.vmPrincipalId
output BASTION_NAME string = resources.outputs.bastionName
output PRIVATE_ADDRESS_PREFIX string = privateAddressPrefix
