targetScope = 'resourceGroup'

param location string
param tags object
param documentStorageName string
param agentStorageName string
param cosmosName string
param searchName string

// AVM storage 0.33.0 was evaluated. It unconditionally evaluates listKeys for
// secure outputs, even when shared-key authorization is disabled. Native
// Storage avoids unused key retrieval/outputs altogether in this keyless demo.
resource documents 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: documentStorageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowCrossTenantReplication: false
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
      virtualNetworkRules: []
      resourceAccessRules: []
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

resource documentBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: documents
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource documentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' = {
  parent: documentBlobService
  name: 'documents'
  properties: {
    publicAccess: 'None'
  }
}

resource agentStorage 'Microsoft.Storage/storageAccounts@2025-01-01' = {
  name: agentStorageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    allowCrossTenantReplication: false
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
      virtualNetworkRules: []
      resourceAccessRules: []
    }
    encryption: {
      keySource: 'Microsoft.Storage'
      requireInfrastructureEncryption: true
      services: {
        blob: {
          enabled: true
          keyType: 'Account'
        }
      }
    }
  }
}

// Do not precreate or invent the platform's workspace-ID-based containers.
resource agentBlobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' = {
  parent: agentStorage
  name: 'default'
  properties: {
    deleteRetentionPolicy: {
      enabled: true
      days: 7
    }
    containerDeleteRetentionPolicy: {
      enabled: true
      days: 7
    }
  }
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
    enableAutomaticFailover: false
    enableMultipleWriteLocations: false
    enableFreeTier: false
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAclBypass: 'None'
    networkAclBypassResourceIds: []
    isVirtualNetworkFilterEnabled: true
    ipRules: []
    virtualNetworkRules: []
  }
}

resource search 'Microsoft.Search/searchServices@2025-05-01' = {
  name: searchName
  location: location
  tags: tags
  sku: {
    name: 'basic'
  }
  properties: {
    // RBAC-only auth; do not combine disableLocalAuth with aadOrApiKey.
    disableLocalAuth: true
    publicNetworkAccess: 'disabled'
    partitionCount: 1
    replicaCount: 1
    hostingMode: 'Default'
    semanticSearch: 'disabled'
    networkRuleSet: {
      bypass: 'None'
      ipRules: []
    }
  }
}

output documentStorageName string = documents.name
output documentStorageId string = documents.id
output documentBlobEndpoint string = documents.properties.primaryEndpoints.blob
output documentContainerName string = documentContainer.name
output agentStorageName string = agentStorage.name
output agentStorageId string = agentStorage.id
output agentBlobEndpoint string = agentStorage.properties.primaryEndpoints.blob
output cosmosName string = cosmos.name
output cosmosId string = cosmos.id
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output searchName string = search.name
output searchId string = search.id
output searchEndpoint string = 'https://${search.name}.search.windows.net'
