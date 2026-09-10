targetScope = 'resourceGroup'

param name string
param location string
param tags object
param accountName string
param agentStorageName string
param agentStorageId string
param agentBlobEndpoint string
param cosmosName string
param cosmosId string
param cosmosEndpoint string
param searchName string
param searchId string
param searchEndpoint string

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' = {
  parent: account
  name: name
  location: location
  tags: tags
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Private document analysis'
    description: 'Hosted Python downloads private Blob content and calls CU analyzeBinary from the selected Foundry network.'
  }
}

// Serialize connection writes as in the standard-agent sample. The business
// document account is intentionally NOT an Agent backing-storage connection.
resource cosmosConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: cosmosName
  properties: {
    category: 'CosmosDB'
    target: cosmosEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: cosmosId
      location: location
    }
  }
}

resource storageConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: agentStorageName
  properties: {
    category: 'AzureStorageAccount'
    target: agentBlobEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: agentStorageId
      location: location
    }
  }
  dependsOn: [
    cosmosConnection
  ]
}

resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2026-05-01' = {
  parent: project
  name: searchName
  properties: {
    category: 'CognitiveSearch'
    target: searchEndpoint
    authType: 'AAD'
    metadata: {
      ApiType: 'Azure'
      ResourceId: searchId
      location: location
    }
  }
  dependsOn: [
    storageConnection
  ]
}

// This read-only preview response is the one used by the official 15/18 samples
// to obtain the RP-generated workspace ID. It is NOT guid(project.id) or random.
resource workspaceMetadata 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' existing = {
  parent: account
  name: project.name
}

output name string = project.name
output resourceId string = project.id
output principalId string = project.identity.principalId
// Swagger omits internalId although the RP returns it; keep the schema exception
// local to this read, matching modules-network-secured/ai-project-identity.bicep.
#disable-next-line BCP053
output internalId string = workspaceMetadata.properties.internalId
output storageConnectionName string = storageConnection.name
output cosmosConnectionName string = cosmosConnection.name
output searchConnectionName string = searchConnection.name
