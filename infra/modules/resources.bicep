targetScope = 'resourceGroup'

param location string
param tags object
@allowed([
  'byo'
  'managed'
])
param networkMode string
param principalId string
param principalType string
param vmAdminUsername string
@secure()
param vmAdminPassword string
param vmSize string
param vmImageSku string
param vmImageVersion string
param privateAddressPrefix string
param completionDeploymentName string
param completionModelName string
param completionModelVersion string
param completionModelSku string
param completionModelCapacity int
param embeddingDeploymentName string
param embeddingModelName string
param embeddingModelVersion string
param embeddingModelSku string
param embeddingModelCapacity int

// Stable for a resource group's entire lifetime. No time/random names and no
// mode-based renaming that could silently orphan an existing Foundry account.
var suffix = uniqueString(resourceGroup().id)
var names = {
  network: 'vnet-${suffix}'
  firewall: 'afw-${suffix}'
  bastion: 'bas-${suffix}'
  vm: 'vm-${take(suffix, 11)}'
  account: 'aif-${suffix}'
  project: 'document-analysis'
  documents: 'stdoc${suffix}'
  agentStorage: 'stagent${suffix}'
  cosmos: 'cosmos-${suffix}'
  search: 'srch-${suffix}'
}

module network './network.bicep' = {
  name: 'customer-network'
  params: {
    name: names.network
    location: location
    tags: tags
    firewallName: names.firewall
    bastionName: names.bastion
    privateAddressPrefix: privateAddressPrefix
    principalId: principalId
    principalType: principalType
  }
}

module services './private-services.bicep' = {
  name: 'private-services'
  params: {
    location: location
    tags: tags
    documentStorageName: names.documents
    agentStorageName: names.agentStorage
    cosmosName: names.cosmos
    searchName: names.search
  }
}

module account './foundry-account.bicep' = {
  name: 'foundry-account'
  params: {
    name: names.account
    location: location
    tags: tags
    networkMode: networkMode
    agentSubnetId: network.outputs.agentSubnetId
  }
}

// Both variants need customer-visible private ingress for the Windows VM.
module privateLinks './private-links.bicep' = {
  name: 'private-links-and-dns'
  params: {
    location: location
    tags: tags
    virtualNetworkId: network.outputs.virtualNetworkId
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    accountId: account.outputs.resourceId
    documentStorageId: services.outputs.documentStorageId
    agentStorageId: services.outputs.agentStorageId
    cosmosId: services.outputs.cosmosId
    searchId: services.outputs.searchId
  }
}

module managedNetwork './managed-network.bicep' = if (networkMode == 'managed') {
  name: 'foundry-managed-network'
  params: {
    accountName: account.outputs.name
    accountPrincipalId: account.outputs.principalId
    documentStorageName: services.outputs.documentStorageName
    agentStorageName: services.outputs.agentStorageName
    cosmosName: services.outputs.cosmosName
    searchName: services.outputs.searchName
  }
  // Do not race managed outbound PE approval against customer ingress PE writes.
  dependsOn: [
    privateLinks
  ]
}

module models './model-deployments.bicep' = {
  name: 'model-deployments'
  params: {
    accountName: account.outputs.name
    completionDeploymentName: completionDeploymentName
    completionModelName: completionModelName
    completionModelVersion: completionModelVersion
    completionModelSku: completionModelSku
    completionModelCapacity: completionModelCapacity
    embeddingDeploymentName: embeddingDeploymentName
    embeddingModelName: embeddingModelName
    embeddingModelVersion: embeddingModelVersion
    embeddingModelSku: embeddingModelSku
    embeddingModelCapacity: embeddingModelCapacity
  }
}

module project './foundry-project.bicep' = {
  name: 'foundry-project-and-connections'
  params: {
    name: names.project
    location: location
    tags: tags
    accountName: account.outputs.name
    agentStorageName: services.outputs.agentStorageName
    agentStorageId: services.outputs.agentStorageId
    agentBlobEndpoint: services.outputs.agentBlobEndpoint
    cosmosName: services.outputs.cosmosName
    cosmosId: services.outputs.cosmosId
    cosmosEndpoint: services.outputs.cosmosEndpoint
    searchName: services.outputs.searchName
    searchId: services.outputs.searchId
    searchEndpoint: services.outputs.searchEndpoint
  }
  dependsOn: [
    privateLinks
    managedNetwork
    models
  ]
}

module agentProvisioningRoles './agent-provisioning-roles.bicep' = {
  name: 'agent-backing-provisioning-roles'
  params: {
    accountName: account.outputs.name
    projectPrincipalId: project.outputs.principalId
    agentStorageName: services.outputs.agentStorageName
    cosmosName: services.outputs.cosmosName
    searchName: services.outputs.searchName
  }
}

// Network injection creates the account's @aml_aiagentservice capability host.
// Declaring a second account host causes HTTP 409. Only bind the project's host.
module capabilityHost './project-capability-host.bicep' = {
  name: 'project-capability-host'
  params: {
    accountName: account.outputs.name
    projectName: project.outputs.name
    storageConnectionName: project.outputs.storageConnectionName
    cosmosConnectionName: project.outputs.cosmosConnectionName
    searchConnectionName: project.outputs.searchConnectionName
  }
  dependsOn: [
    agentProvisioningRoles
  ]
}

// Capability host creation materializes the backing database/containers.
// The official standard-agent sequence assigns these data roles afterwards.
module agentDataRoles './agent-data-roles.bicep' = {
  name: 'agent-backing-data-roles'
  params: {
    projectPrincipalId: project.outputs.principalId
    projectInternalId: project.outputs.internalId
    agentStorageName: services.outputs.agentStorageName
    cosmosName: services.outputs.cosmosName
  }
  dependsOn: [
    capabilityHost
  ]
}

module windows './windows-vm.bicep' = {
  name: 'windows-client'
  params: {
    name: names.vm
    location: location
    tags: tags
    subnetId: network.outputs.windowsSubnetId
    adminUsername: vmAdminUsername
    adminPassword: vmAdminPassword
    vmSize: vmSize
    imageSku: vmImageSku
    imageVersion: vmImageVersion
    principalId: principalId
    principalType: principalType
  }
}

module clientRoles './client-roles.bicep' = {
  name: 'operator-and-vm-roles'
  params: {
    accountName: account.outputs.name
    projectName: project.outputs.name
    vmPrincipalId: windows.outputs.principalId
    operatorPrincipalId: principalId
    operatorPrincipalType: principalType
    documentStorageName: services.outputs.documentStorageName
    documentContainerName: services.outputs.documentContainerName
  }
}

output accountName string = account.outputs.name
output accountId string = account.outputs.resourceId
output projectName string = project.outputs.name
output projectId string = project.outputs.resourceId
output projectEndpoint string = 'https://${account.outputs.name}.services.ai.azure.com/api/projects/${project.outputs.name}'
output contentUnderstandingEndpoint string = 'https://${account.outputs.name}.cognitiveservices.azure.com'
output documentStorageName string = services.outputs.documentStorageName
output documentStorageId string = services.outputs.documentStorageId
output documentBlobEndpoint string = services.outputs.documentBlobEndpoint
output documentContainerName string = services.outputs.documentContainerName
output vmName string = windows.outputs.name
output vmId string = windows.outputs.resourceId
output vmPrincipalId string = windows.outputs.principalId
output bastionName string = network.outputs.bastionName
