targetScope = 'resourceGroup'

param location string
param tags object
param virtualNetworkId string
param privateEndpointSubnetId string
param accountId string
param documentStorageId string
param agentStorageId string
param cosmosId string
param searchId string

var zoneNames = [
  'privatelink.services.ai.azure.com'
  'privatelink.openai.azure.com'
  'privatelink.cognitiveservices.azure.com'
  'privatelink.blob.${environment().suffixes.storage}'
  'privatelink.documents.azure.com'
  'privatelink.search.windows.net'
]

module dnsZones 'br/public:avm/res/network/private-dns-zone:0.8.1' = [
  for (zoneName, index) in zoneNames: {
    name: 'private-dns-${index}'
    params: {
      name: zoneName
      location: 'global'
      tags: tags
      enableTelemetry: false
      virtualNetworkLinks: [
        {
          name: 'customer-vnet'
          virtualNetworkResourceId: virtualNetworkId
          registrationEnabled: false
          resolutionPolicy: 'Default'
          tags: tags
        }
      ]
    }
  }
]

var targets = [
  {
    name: 'pe-foundry'
    resourceId: accountId
    groupId: 'account'
    dnsZoneIds: [
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[0])
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[1])
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[2])
    ]
  }
  {
    name: 'pe-documents'
    resourceId: documentStorageId
    groupId: 'blob'
    dnsZoneIds: [
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[3])
    ]
  }
  {
    name: 'pe-agent-storage'
    resourceId: agentStorageId
    groupId: 'blob'
    dnsZoneIds: [
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[3])
    ]
  }
  {
    name: 'pe-agent-cosmos'
    resourceId: cosmosId
    groupId: 'Sql'
    dnsZoneIds: [
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[4])
    ]
  }
  {
    name: 'pe-agent-search'
    resourceId: searchId
    groupId: 'searchService'
    dnsZoneIds: [
      resourceId('Microsoft.Network/privateDnsZones', zoneNames[5])
    ]
  }
]

@batchSize(1)
resource endpoints 'Microsoft.Network/privateEndpoints@2025-05-01' = [
  for target in targets: {
    name: target.name
    location: location
    tags: tags
    properties: {
      customNetworkInterfaceName: 'nic-${target.name}'
      subnet: {
        id: privateEndpointSubnetId
      }
      privateLinkServiceConnections: [
        {
          name: target.name
          properties: {
            privateLinkServiceId: target.resourceId
            groupIds: [
              target.groupId
            ]
          }
        }
      ]
    }
  }
]

resource zoneGroups 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2025-05-01' = [
  for (target, index) in targets: {
    parent: endpoints[index]
    name: 'default'
    properties: {
      privateDnsZoneConfigs: [
        for (zoneId, zoneIndex) in target.dnsZoneIds: {
          name: 'zone-${zoneIndex}'
          properties: {
            privateDnsZoneId: zoneId
          }
        }
      ]
    }
    // Target names/IDs above are deterministic (so the loop length is known
    // up front). This dependency waits for all real zones AND VNet links.
    dependsOn: [
      dnsZones
    ]
  }
]
