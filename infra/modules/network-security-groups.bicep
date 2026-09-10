targetScope = 'resourceGroup'

import { windowsKmsAddresses } from './egress-allowlist.bicep'

param name string
param location string
param tags object
param windowsPrefix string
param agentPrefix string
param privateEndpointPrefix string
param bastionPrefix string

// HTTP(S) Internet entries below are transport gates, NOT internet allowlists:
// both subnets have an unbypassable default UDR to Azure Firewall. NSGs see the
// original destination, not the next-hop firewall. The firewall permits only
// the separately enumerated FQDNs/service tags. All other outbound ports deny.
resource windowsNsg 'Microsoft.Network/networkSecurityGroups@2025-05-01' = {
  name: '${name}-windows'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'RdpOnlyFromBastion'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: bastionPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: windowsPrefix
          destinationPortRange: '3389'
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'PrivateServiceHttps'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: privateEndpointPrefix
          destinationPortRange: '443'
        }
      }
      {
        name: 'AzureDns'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzurePlatformDNS'
          destinationPortRange: '53'
        }
      }
      {
        name: 'ManagedIdentityMetadata'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzurePlatformIMDS'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AzureVmAgentWireServer'
        properties: {
          priority: 130
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: '168.63.129.16'
          destinationPortRanges: [
            '80'
            '32526'
          ]
        }
      }
      {
        name: 'WindowsActivationViaFirewall'
        properties: {
          priority: 140
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefixes: windowsKmsAddresses
          destinationPortRange: '1688'
        }
      }
      {
        name: 'WebTransportViaFirewall'
        properties: {
          priority: 150
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: windowsPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRanges: [
            '80'
            '443'
          ]
        }
      }
      {
        name: 'DenyAllOtherOutbound'
        properties: {
          priority: 4096
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource agentNsg 'Microsoft.Network/networkSecurityGroups@2025-05-01' = {
  name: '${name}-agents'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AgentSubnetInternalIngress'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: agentPrefix
          destinationPortRange: '*'
        }
      }
      {
        name: 'PlatformLoadBalancerProbes'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: agentPrefix
          destinationPortRange: '30000-32767'
        }
      }
      {
        name: 'PrivateClientHttps'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefixes: [
            windowsPrefix
            privateEndpointPrefix
          ]
          sourcePortRange: '*'
          destinationAddressPrefix: agentPrefix
          destinationPortRanges: [
            '443'
            '31443'
          ]
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'AgentSubnetInternalEgress'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: agentPrefix
          destinationPortRange: '*'
        }
      }
      {
        name: 'PrivateServicesIncludingCosmosDirect'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: privateEndpointPrefix
          // Cosmos DB direct mode can use the full TCP range over Private Link.
          destinationPortRange: '*'
        }
      }
      {
        name: 'AzureDns'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzurePlatformDNS'
          destinationPortRange: '53'
        }
      }
      {
        name: 'AzurePlatformIdentity'
        properties: {
          priority: 130
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzurePlatformIMDS'
          destinationPortRange: '80'
        }
      }
      {
        name: 'WebTransportViaFirewall'
        properties: {
          priority: 140
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: agentPrefix
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRanges: [
            '80'
            '443'
          ]
        }
      }
      {
        name: 'DenyAllOtherOutbound'
        properties: {
          priority: 4096
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

// Bastion's management subnet must NOT receive the workload default UDR.
// Required platform flows: https://learn.microsoft.com/azure/bastion/bastion-nsg
resource bastionNsg 'Microsoft.Network/networkSecurityGroups@2025-05-01' = {
  name: '${name}-bastion'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'BastionHttpsIngress'
        properties: {
          priority: 100
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'GatewayManagerIngress'
        properties: {
          priority: 110
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'GatewayManager'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'AzureLoadBalancerIngress'
        properties: {
          priority: 120
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'AzureLoadBalancer'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '443'
        }
      }
      {
        name: 'BastionInternalIngress'
        properties: {
          priority: 130
          direction: 'Inbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges: [
            '8080'
            '5701'
          ]
        }
      }
      {
        name: 'DenyAllOtherInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
      {
        name: 'RdpToWindowsOnly'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: windowsPrefix
          destinationPortRange: '3389'
        }
      }
      {
        name: 'AzurePlatformEgress'
        properties: {
          priority: 110
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzureCloud'
          destinationPortRange: '443'
        }
      }
      {
        name: 'BastionInternalEgress'
        properties: {
          priority: 120
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'VirtualNetwork'
          destinationPortRanges: [
            '8080'
            '5701'
          ]
        }
      }
      {
        name: 'SessionAndCertificateValidation'
        properties: {
          priority: 130
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Internet'
          destinationPortRange: '80'
        }
      }
      {
        name: 'AzureDns'
        properties: {
          priority: 140
          direction: 'Outbound'
          access: 'Allow'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: 'AzurePlatformDNS'
          destinationPortRange: '53'
        }
      }
      {
        name: 'DenyAllOtherOutbound'
        properties: {
          priority: 4096
          direction: 'Outbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: '*'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

output windowsNsgId string = windowsNsg.id
output agentNsgId string = agentNsg.id
output bastionNsgId string = bastionNsg.id
