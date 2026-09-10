targetScope = 'resourceGroup'

param name string
param location string
param tags object
param subnetId string
param adminUsername string
@secure()
param adminPassword string
param vmSize string
param imageSku string
param imageVersion string
param principalId string
param principalType string

module virtualMachine 'br/public:avm/res/compute/virtual-machine:0.22.3' = {
  name: 'private-windows-vm'
  params: {
    name: name
    computerName: name
    location: location
    tags: tags
    enableTelemetry: false
    vmSize: vmSize
    osType: 'Windows'
    availabilityZone: -1
    adminUsername: adminUsername
    adminPassword: adminPassword
    imageReference: {
      publisher: 'MicrosoftWindowsServer'
      offer: 'WindowsServer'
      sku: imageSku
      version: imageVersion
    }
    securityType: 'TrustedLaunch'
    secureBootEnabled: true
    vTpmEnabled: true
    managedIdentities: {
      systemAssigned: true
    }
    osDisk: {
      name: 'osdisk-${name}'
      createOption: 'FromImage'
      caching: 'ReadWrite'
      diskSizeGB: 128
      deleteOption: 'Delete'
      managedDisk: {
        storageAccountType: 'StandardSSD_LRS'
      }
    }
    nicConfigurations: [
      {
        name: 'nic-${name}'
        deleteOption: 'Delete'
        enableIPForwarding: false
        enableAcceleratedNetworking: false
        tags: tags
        ipConfigurations: [
          {
            name: 'private-ip'
            subnetResourceId: subnetId
            privateIPAllocationMethod: 'Dynamic'
            privateIPAddressVersion: 'IPv4'
            // No pipConfiguration: the VM never gets a public IP.
          }
        ]
        roleAssignments: [
          {
            principalId: principalId
            principalType: principalType
            roleDefinitionIdOrName: 'Reader'
          }
        ]
      }
    ]
    roleAssignments: [
      {
        principalId: principalId
        principalType: principalType
        roleDefinitionIdOrName: 'Reader'
      }
    ]
    provisionVMAgent: true
    enableAutomaticUpdates: true
    patchMode: 'AutomaticByOS'
    bootDiagnostics: false
    // Windows Server has Defender built in; no extra extension download path,
    // public telemetry agent, or workstation-side data-plane provision hook.
    extensionAntiMalwareConfig: {
      enabled: false
    }
  }
}

// The VM API creates its OS disk implicitly and does not inherit VM tags onto
// that separately billable resource. Tag it explicitly without updating disk
// storage/security properties or replacing the image-created disk.
resource osDisk 'Microsoft.Compute/disks@2025-01-02' existing = {
  name: 'osdisk-${name}'
}

resource osDiskTags 'Microsoft.Resources/tags@2021-04-01' = {
  scope: osDisk
  name: 'default'
  properties: {
    tags: union(osDisk.tags ?? {}, tags)
  }
  dependsOn: [
    virtualMachine
  ]
}

output name string = virtualMachine.outputs.name
output resourceId string = virtualMachine.outputs.resourceId
output principalId string = virtualMachine.outputs.systemAssignedMIPrincipalId!
