targetScope = 'resourceGroup'

param accountName string
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

resource account 'Microsoft.CognitiveServices/accounts@2026-05-01' existing = {
  name: accountName
}

resource completion 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: completionDeploymentName
  sku: {
    name: completionModelSku
    capacity: completionModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: completionModelName
      version: completionModelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
}

resource embedding 'Microsoft.CognitiveServices/accounts/deployments@2026-05-01' = {
  parent: account
  name: embeddingDeploymentName
  sku: {
    name: embeddingModelSku
    capacity: embeddingModelCapacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: embeddingModelName
      version: embeddingModelVersion
    }
    versionUpgradeOption: 'NoAutoUpgrade'
  }
  dependsOn: [
    completion
  ]
}
