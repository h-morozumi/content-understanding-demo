targetScope = 'resourceGroup'

import { roleIds } from './role-definitions.bicep'

param accountName string
param projectPrincipalId string
param agentStorageName string
param cosmosName string
param searchName string

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: agentStorageName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' existing = {
  name: cosmosName
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

// The PROJECT identity, not the operator or account identity, authenticates
// the model proxy to this Foundry account.
resource modelProxy 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, projectPrincipalId, roleIds.foundryUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.foundryUser)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Capability-host provisioning must be able to create its containers first.
// Account scope is restricted to the dedicated agent store, NEVER documents.
resource storageContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, projectPrincipalId, roleIds.storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource cosmosOperator 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cosmos
  name: guid(cosmos.id, projectPrincipalId, roleIds.cosmosOperator)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.cosmosOperator)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource searchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in [
    roleIds.searchServiceContributor
    roleIds.searchIndexDataContributor
  ]: {
    scope: search
    name: guid(search.id, projectPrincipalId, roleId)
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
      principalId: projectPrincipalId
      principalType: 'ServicePrincipal'
    }
  }
]
