targetScope = 'resourceGroup'

param accountName string
param projectName string
param storageConnectionName string
param cosmosConnectionName string
param searchConnectionName string

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' existing = {
  parent: account
  name: projectName
}

resource capabilityHost 'Microsoft.CognitiveServices/accounts/projects/capabilityHosts@2026-05-01' = {
  parent: project
  name: 'agents'
  properties: {
    // With the stable 2026 API, kind/public-hosting flags belong to the ACCOUNT
    // host, not ProjectCapabilityHostProperties. Account network injection
    // already creates the private Agents host; the project binds its stores.
    storageConnections: [
      storageConnectionName
    ]
    threadStorageConnections: [
      cosmosConnectionName
    ]
    vectorStoreConnections: [
      searchConnectionName
    ]
  }
}
