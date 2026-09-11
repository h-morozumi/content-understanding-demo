targetScope = 'resourceGroup'

param name string
param location string
param tags object
param firewallName string
param bastionName string
param privateAddressPrefix string
param principalId string
param principalType string

var windowsPrefix = cidrSubnet(privateAddressPrefix, 24, 0)
var privateEndpointPrefix = cidrSubnet(privateAddressPrefix, 24, 1)
var agentPrefix = cidrSubnet(privateAddressPrefix, 24, 2)
var bastionPrefix = cidrSubnet(privateAddressPrefix, 26, 12)
var firewallPrefix = cidrSubnet(privateAddressPrefix, 26, 13)
var firewallManagementPrefix = cidrSubnet(privateAddressPrefix, 26, 14)

module security './network-security-groups.bicep' = {
  name: 'subnet-security'
  params: {
    name: 'nsg-${name}'
    location: location
    tags: tags
    windowsPrefix: windowsPrefix
    agentPrefix: agentPrefix
    privateEndpointPrefix: privateEndpointPrefix
    bastionPrefix: bastionPrefix
  }
}

// AVM writes the VNet and its child subnets separately. Workload subnets below
// have ONE authoritative definition and are created only AFTER Firewall/UDR.
// This avoids a guessed Firewall private IP, a dependency cycle, or temporarily
// removing/reapplying a workload's route table during subsequent deployments.
module virtualNetwork 'br/public:avm/res/network/virtual-network:0.10.2' = {
  name: 'virtual-network'
  params: {
    name: name
    location: location
    tags: tags
    enableTelemetry: false
    addressPrefixes: [
      privateAddressPrefix
    ]
    // Azure-provided DNS resolves our linked Private DNS zones. Basic Firewall
    // has neither DNS proxy nor custom DNS support; never use it as a resolver.
    subnets: [
      {
        name: 'private-endpoints'
        addressPrefix: privateEndpointPrefix
        privateEndpointNetworkPolicies: 'Disabled'
        defaultOutboundAccess: false
      }
      {
        name: 'AzureBastionSubnet'
        addressPrefix: bastionPrefix
        networkSecurityGroupResourceId: security.outputs.bastionNsgId
      }
      {
        name: 'AzureFirewallSubnet'
        addressPrefix: firewallPrefix
      }
      {
        name: 'AzureFirewallManagementSubnet'
        addressPrefix: firewallManagementPrefix
      }
    ]
  }
}

module firewall './firewall.bicep' = {
  name: 'egress-firewall'
  params: {
    name: firewallName
    location: location
    tags: tags
    firewallSubnetId: virtualNetwork.outputs.subnetResourceIds[2]
    managementSubnetId: virtualNetwork.outputs.subnetResourceIds[3]
    windowsPrefix: windowsPrefix
    agentPrefix: agentPrefix
  }
}

resource workloadRoutes 'Microsoft.Network/routeTables@2025-05-01' = {
  name: 'rt-${name}-egress'
  location: location
  tags: tags
  properties: {
    disableBgpRoutePropagation: true
    routes: [
      {
        name: 'AllInternetViaFirewall'
        properties: {
          addressPrefix: '0.0.0.0/0'
          nextHopType: 'VirtualAppliance'
          nextHopIpAddress: firewall.outputs.privateIpAddress
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2025-05-01' existing = {
  // A child resource's parent name must be known at deployment start. The
  // route-table -> firewall -> AVM dependency ensures this VNet already exists.
  name: name
}

resource windowsSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-05-01' = {
  parent: vnet
  name: 'windows'
  properties: {
    addressPrefix: windowsPrefix
    defaultOutboundAccess: false
    networkSecurityGroup: {
      id: security.outputs.windowsNsgId
    }
    routeTable: {
      id: workloadRoutes.id
    }
  }
}

// Also reserve this dedicated /24 in the managed variant to keep the customer
// topology comparable. Only the BYO Foundry account is injected into it.
resource agentSubnet 'Microsoft.Network/virtualNetworks/subnets@2025-05-01' = {
  parent: vnet
  name: 'agents'
  properties: {
    addressPrefix: agentPrefix
    defaultOutboundAccess: false
    delegations: [
      {
        name: 'foundry-agent-environment'
        properties: {
          serviceName: 'Microsoft.App/environments'
        }
      }
    ]
    networkSecurityGroup: {
      id: security.outputs.agentNsgId
    }
    routeTable: {
      id: workloadRoutes.id
    }
  }
  // Serialize subnet changes: Microsoft.Network can reject concurrent PUTs.
  dependsOn: [
    windowsSubnet
  ]
}

module bastion 'br/public:avm/res/network/bastion-host:0.8.2' = {
  name: 'bastion'
  params: {
    name: bastionName
    location: location
    tags: tags
    enableTelemetry: false
    virtualNetworkResourceId: virtualNetwork.outputs.resourceId
    skuName: 'Standard'
    scaleUnits: 2
    enableFileCopy: true
    enableShareableLink: false
    enableIpConnect: false
    enableSessionRecording: false
    publicIPAddressObject: {
      name: 'pip-${bastionName}'
      skuName: 'Standard'
      publicIPAllocationMethod: 'Static'
      publicIPAddressVersion: 'IPv4'
      // Do not assume zone availability; region/SKU checks are deferred.
      availabilityZones: []
      tags: tags
    }
    roleAssignments: [
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: 'Reader'
      }
    ]
  }
  dependsOn: [
    agentSubnet
  ]
}

output virtualNetworkId string = virtualNetwork.outputs.resourceId
output windowsSubnetId string = windowsSubnet.id
output agentSubnetId string = agentSubnet.id
output privateEndpointSubnetId string = virtualNetwork.outputs.subnetResourceIds[0]
output bastionName string = bastion.outputs.name
