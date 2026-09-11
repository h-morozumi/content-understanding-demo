targetScope = 'resourceGroup'

import { roleIds } from './role-definitions.bicep'

param projectPrincipalId string
@description('Persisted Foundry project internalId from the RP, never a newly generated GUID.')
@minLength(32)
@maxLength(36)
param projectInternalId string
param agentStorageName string
param cosmosName string

var compactId = replace(toLower(projectInternalId), '-', '')
var workspaceId = '${substring(compactId, 0, 8)}-${substring(compactId, 8, 4)}-${substring(compactId, 12, 4)}-${substring(compactId, 16, 4)}-${substring(compactId, 20, 12)}'

resource storage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: agentStorageName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' existing = {
  name: cosmosName
}

// Official standard-agent ABAC pattern: the added blob-tag privileges apply
// only to this workspace's generated *-azureml-agent containers. The base Blob
// Data Contributor role already authorizes container provisioning in this
// dedicated backing account. This role never applies to business documents.
var ownerCondition = '((!(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/read\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/filter/action\'}) AND !(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/tags/write\'})) OR (@Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringStartsWithIgnoreCase \'${workspaceId}\' AND @Resource[Microsoft.Storage/storageAccounts/blobServices/containers:name] StringLikeIgnoreCase \'*-azureml-agent\'))'

resource storageOwner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, projectPrincipalId, roleIds.storageBlobDataOwner, workspaceId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataOwner)
    principalId: projectPrincipalId
    principalType: 'ServicePrincipal'
    conditionVersion: '2.0'
    condition: ownerCondition
  }
}

// Cosmos data-plane role IDs are local to the Cosmos account, NOT Azure RBAC.
// The account is dedicated to one project's generated backing containers.
resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2025-04-15' = {
  parent: cosmos
  name: guid(cosmos.id, projectPrincipalId, workspaceId, '00000000-0000-0000-0000-000000000002')
  properties: {
    principalId: projectPrincipalId
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    scope: cosmos.id
  }
  dependsOn: [
    storageOwner
  ]
}
