targetScope = 'resourceGroup'

import { agentFqdns, vmSetupFqdns, certificateFqdns, windowsKmsAddresses } from './egress-allowlist.bicep'

param name string
param location string
param tags object
param firewallSubnetId string
param managementSubnetId string
param windowsPrefix string
param agentPrefix string

var workloadPrefixes = [
  windowsPrefix
  agentPrefix
]

resource dataPublicIp 'Microsoft.Network/publicIPAddresses@2025-05-01' = {
  name: 'pip-${name}-data'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

// Basic requires a separate management NIC, subnet, and public IP. There is
// deliberately no workload route table on either Firewall infrastructure subnet.
resource managementPublicIp 'Microsoft.Network/publicIPAddresses@2025-05-01' = {
  name: 'pip-${name}-management'
  location: location
  tags: tags
  sku: {
    name: 'Standard'
    tier: 'Regional'
  }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource policy 'Microsoft.Network/firewallPolicies@2025-05-01' = {
  name: 'afwp-${name}'
  location: location
  tags: tags
  properties: {
    sku: {
      tier: 'Basic'
    }
    threatIntelMode: 'Alert'
    // Basic has no DNS proxy, custom DNS, network-FQDN rules, or TLS inspection.
    // The VNet uses Azure-provided DNS and application rules use HTTPS SNI.
  }
}

resource egressRules 'Microsoft.Network/firewallPolicies/ruleCollectionGroups@2025-05-01' = {
  parent: policy
  name: 'required-egress'
  properties: {
    priority: 100
    ruleCollections: [
      {
        name: 'azure-platform'
        priority: 100
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        action: {
          type: 'Allow'
        }
        rules: [
          {
            name: 'entra-identity'
            ruleType: 'NetworkRule'
            ipProtocols: [
              'TCP'
            ]
            sourceAddresses: workloadPrefixes
            destinationAddresses: [
              'AzureActiveDirectory'
            ]
            destinationPorts: [
              '443'
            ]
          }
          {
            name: 'operator-arm-control-plane'
            ruleType: 'NetworkRule'
            ipProtocols: [
              'TCP'
            ]
            sourceAddresses: [
              windowsPrefix
            ]
            destinationAddresses: [
              'AzureResourceManager'
            ]
            destinationPorts: [
              '443'
            ]
          }
          {
            name: 'windows-activation'
            ruleType: 'NetworkRule'
            ipProtocols: [
              'TCP'
            ]
            sourceAddresses: [
              windowsPrefix
            ]
            destinationAddresses: windowsKmsAddresses
            destinationPorts: [
              '1688'
            ]
          }
        ]
      }
      {
        name: 'runtime-and-source-build'
        priority: 200
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        action: {
          type: 'Allow'
        }
        rules: [
          {
            name: 'approved-runtime-and-package-hosts'
            ruleType: 'ApplicationRule'
            sourceAddresses: workloadPrefixes
            protocols: [
              {
                protocolType: 'Https'
                port: 443
              }
            ]
            targetFqdns: agentFqdns
          }
        ]
      }
      {
        name: 'windows-setup'
        priority: 300
        ruleCollectionType: 'FirewallPolicyFilterRuleCollection'
        action: {
          type: 'Allow'
        }
        rules: [
          {
            name: 'approved-installers-and-repository'
            ruleType: 'ApplicationRule'
            sourceAddresses: [
              windowsPrefix
            ]
            protocols: [
              {
                protocolType: 'Https'
                port: 443
              }
            ]
            targetFqdns: vmSetupFqdns
          }
          {
            name: 'authenticode-and-tls-revocation'
            ruleType: 'ApplicationRule'
            sourceAddresses: [
              windowsPrefix
            ]
            protocols: [
              {
                protocolType: 'Http'
                port: 80
              }
              {
                protocolType: 'Https'
                port: 443
              }
            ]
            targetFqdns: certificateFqdns
          }
          {
            name: 'windows-security-updates'
            ruleType: 'ApplicationRule'
            sourceAddresses: [
              windowsPrefix
            ]
            protocols: [
              {
                protocolType: 'Http'
                port: 80
              }
              {
                protocolType: 'Https'
                port: 443
              }
            ]
            fqdnTags: [
              'WindowsUpdate'
            ]
          }
        ]
      }
    ]
  }
}

resource firewall 'Microsoft.Network/azureFirewalls@2025-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'AZFW_VNet'
      tier: 'Basic'
    }
    firewallPolicy: {
      id: policy.id
    }
    ipConfigurations: [
      {
        name: 'data'
        properties: {
          subnet: {
            id: firewallSubnetId
          }
          publicIPAddress: {
            id: dataPublicIp.id
          }
        }
      }
    ]
    managementIpConfiguration: {
      name: 'management'
      properties: {
        subnet: {
          id: managementSubnetId
        }
        publicIPAddress: {
          id: managementPublicIp.id
        }
      }
    }
  }
  dependsOn: [
    egressRules
  ]
}

output privateIpAddress string = firewall.properties.ipConfigurations[0].properties.privateIPAddress
