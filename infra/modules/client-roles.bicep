targetScope = 'resourceGroup'

import { roleIds } from './role-definitions.bicep'

param accountName string
param projectName string
param vmPrincipalId string
param operatorPrincipalId string
@allowed([
  'User'
  'Group'
  'ServicePrincipal'
])
param operatorPrincipalType string
param documentStorageName string
param documentContainerName string

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2026-05-01' existing = {
  parent: account
  name: projectName
}

resource documentStorage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: documentStorageName
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2025-01-01' existing = {
  parent: documentStorage
  name: 'default'
}

resource documentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2025-01-01' existing = {
  parent: blobService
  name: documentContainerName
}

resource vmCuReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, vmPrincipalId, roleIds.contentUnderstandingReader)
  properties: {
    principalId: vmPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.contentUnderstandingReader)
  }
}

resource vmAgentConsumer 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, vmPrincipalId, roleIds.foundryAgentConsumer)
  properties: {
    principalId: vmPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.foundryAgentConsumer)
  }
}

resource vmDocuments 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: documentContainer
  name: guid(documentContainer.id, vmPrincipalId, roleIds.storageBlobDataContributor)
  properties: {
    principalId: vmPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
  }
}

resource operatorProjectManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: project
  name: guid(project.id, operatorPrincipalId, roleIds.foundryProjectManager)
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.foundryProjectManager)
  }
}

resource operatorCuSetup 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, operatorPrincipalId, roleIds.contentUnderstandingContributor)
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.contentUnderstandingContributor)
  }
}

resource operatorDocuments 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: documentContainer
  name: guid(documentContainer.id, operatorPrincipalId, roleIds.storageBlobDataContributor)
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
  }
}

// Foundry Project Manager's built-in delegation is ONLY for Foundry User.
// Source deployment also grants the newly created agent identity Blob Reader
// and CU Reader. Permit exactly those grants on exactly those resources, to
// ServicePrincipals only, without giving the operator broad Owner/RBAC admin.
// The platform-created agent ID is not known until the code deployment runs.
var cuDelegationCondition = '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roleIds.contentUnderstandingReader}} AND @Request[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase \'ServicePrincipal\')) AND ((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/delete\'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roleIds.contentUnderstandingReader}} AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase \'ServicePrincipal\'))'
var blobDelegationCondition = '((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/write\'})) OR (@Request[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roleIds.storageBlobDataReader}} AND @Request[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase \'ServicePrincipal\')) AND ((!(ActionMatches{\'Microsoft.Authorization/roleAssignments/delete\'})) OR (@Resource[Microsoft.Authorization/roleAssignments:RoleDefinitionId] ForAnyOfAnyValues:GuidEquals {${roleIds.storageBlobDataReader}} AND @Resource[Microsoft.Authorization/roleAssignments:PrincipalType] StringEqualsIgnoreCase \'ServicePrincipal\'))'

resource operatorDelegateCuReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, operatorPrincipalId, roleIds.roleBasedAccessControlAdministrator, 'delegate-cu-reader')
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.roleBasedAccessControlAdministrator)
    conditionVersion: '2.0'
    condition: cuDelegationCondition
  }
}

resource operatorDelegateBlobReader 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: documentContainer
  name: guid(documentContainer.id, operatorPrincipalId, roleIds.roleBasedAccessControlAdministrator, 'delegate-blob-reader')
  properties: {
    principalId: operatorPrincipalId
    principalType: operatorPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.roleBasedAccessControlAdministrator)
    conditionVersion: '2.0'
    condition: blobDelegationCondition
  }
}
