targetScope = 'resourceGroup'

param name string
param location string
param tags object
@allowed([
  'byo'
  'managed'
])
param networkMode string
param agentSubnetId string

// Account network injection is a CREATION-TIME decision, not a later patch.
// Keep the name and selected mode unchanged on reruns of the same environment.
// https://learn.microsoft.com/azure/foundry/how-to/managed-virtual-network
resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: {
    name: 'S0'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    allowProjectManagement: true
    customSubDomainName: name
    disableLocalAuth: true
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'None'
      ipRules: []
      virtualNetworkRules: []
    }
    networkInjections: [
      {
        scenario: 'agent'
        useMicrosoftManagedNetwork: networkMode == 'managed'
        subnetArmId: networkMode == 'byo' ? agentSubnetId : ''
      }
    ]
  }
}

output name string = account.name
output resourceId string = account.id
output principalId string = account.identity.principalId
