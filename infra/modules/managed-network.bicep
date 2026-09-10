targetScope = 'resourceGroup'

import { roleIds } from './role-definitions.bicep'
import { agentFqdns } from './egress-allowlist.bicep'

param accountName string
param accountPrincipalId string
param documentStorageName string
param agentStorageName string
param cosmosName string
param searchName string

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource documents 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: documentStorageName
}

resource agentStorage 'Microsoft.Storage/storageAccounts@2025-01-01' existing = {
  name: agentStorageName
}

resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2025-04-15' existing = {
  name: cosmosName
}

resource search 'Microsoft.Search/searchServices@2025-05-01' existing = {
  name: searchName
}

// Approve managed outbound PEs on precisely five target resources, not the RG
// or subscription. The Foundry ACCOUNT identity owns these approvals.
var approverRoleId = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.networkConnectionApprover)

resource approveSelf 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, accountPrincipalId, approverRoleId)
  properties: {
    principalId: accountPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: approverRoleId
  }
}

resource approveDocuments 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: documents
  name: guid(documents.id, accountPrincipalId, approverRoleId)
  properties: {
    principalId: accountPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: approverRoleId
  }
}

resource approveAgentStorage 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: agentStorage
  name: guid(agentStorage.id, accountPrincipalId, approverRoleId)
  properties: {
    principalId: accountPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: approverRoleId
  }
}

resource approveCosmos 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: cosmos
  name: guid(cosmos.id, accountPrincipalId, approverRoleId)
  properties: {
    principalId: accountPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: approverRoleId
  }
}

resource approveSearch 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: search
  name: guid(search.id, accountPrincipalId, approverRoleId)
  properties: {
    principalId: accountPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: approverRoleId
  }
}

resource managedNetwork 'Microsoft.CognitiveServices/accounts/managedNetworks@2026-05-01' = {
  parent: account
  name: 'default'
  properties: {
    managedNetwork: {
      isolationMode: 'AllowOnlyApprovedOutbound'
      managedNetworkKind: 'V2'
      firewallSku: 'Basic'
      // The official managed-network Bicep sample sets this provisioning flag.
      // It is still absent from the published 2026-05-01 Swagger. Preserve the
      // wire property with this ONE local schema exception, not a no-types
      // resource or an unrelated generic ARM deployment.
      #disable-next-line BCP037
      provisionNetworkNow: true
    }
  }
  dependsOn: [
    approveSelf
    approveDocuments
    approveAgentStorage
    approveCosmos
    approveSearch
  ]
}

var privateTargets = [
  // Critical: inbound customer PE != outbound managed PE. Hosted model proxy
  // and CU calls need this self endpoint because the Foundry account is private.
  {
    name: 'pe-foundry-self'
    resourceId: account.id
    groupId: 'account'
  }
  {
    name: 'pe-business-documents'
    resourceId: documents.id
    groupId: 'blob'
  }
  {
    name: 'pe-agent-storage'
    resourceId: agentStorage.id
    groupId: 'blob'
  }
  {
    name: 'pe-agent-cosmos'
    resourceId: cosmos.id
    groupId: 'Sql'
  }
  {
    name: 'pe-agent-search'
    resourceId: search.id
    groupId: 'searchService'
  }
]

// The managed-network RP rejects concurrent outbound-rule operations. Batch
// each collection at one and explicitly order collections, as in sample 18.
@batchSize(1)
resource privateEndpointRules 'Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2026-05-01' = [
  for target in privateTargets: {
    parent: managedNetwork
    name: target.name
    properties: {
      type: 'PrivateEndpoint'
      category: 'UserDefined'
      destination: {
        serviceResourceId: target.resourceId
        subresourceTarget: target.groupId
      }
    }
  }
]

resource entraRule 'Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2026-05-01' = {
  parent: managedNetwork
  name: 'entra-identity'
  properties: {
    type: 'ServiceTag'
    category: 'UserDefined'
    destination: {
      serviceTag: 'AzureActiveDirectory'
      protocol: 'TCP'
      portRanges: '443'
      action: 'Allow'
    }
  }
  dependsOn: [
    privateEndpointRules
  ]
}

@batchSize(1)
resource fqdnRules 'Microsoft.CognitiveServices/accounts/managedNetworks/outboundRules@2026-05-01' = [
  for fqdn in agentFqdns: {
    parent: managedNetwork
    // Stable names even if the list is reordered. FQDN rules are billable:
    // they cause the managed Basic Firewall to be provisioned.
    name: 'fqdn-${uniqueString(fqdn)}'
    properties: {
      type: 'FQDN'
      category: 'UserDefined'
      destination: fqdn
    }
    dependsOn: [
      entraRule
    ]
  }
]
