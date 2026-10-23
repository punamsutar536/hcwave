// -----------------------------------------------------------------------------
// Microsoft Foundry (Azure AI Services) with Azure OpenAI model deployments:
// a small model for intent/tagging, a larger one for replies, and an
// embedding model for RAG. Keyless (Entra ID only), private endpoint only.
// Deploy in an Indian region (South/Central India) where the models are
// available; "Standard" (regional) deployments keep processing in-region.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param zoneIds object
param logAnalyticsWorkspaceId string

@description('Model deployments: name, model, version, sku (Standard = regional), capacity (K TPM).')
param deployments array = [
  { name: 'gpt-5-mini', model: 'gpt-5-mini', version: '2025-08-07', sku: 'Standard', capacity: 50 }
  { name: 'gpt-5', model: 'gpt-5', version: '2025-08-07', sku: 'Standard', capacity: 20 }
  { name: 'text-embedding-3-large', model: 'text-embedding-3-large', version: '1', sku: 'Standard', capacity: 50 }
]

@description('Principals granted "Cognitive Services OpenAI User" (workload identity, APIM).')
param userPrincipalIds array = []

@description('Create a Foundry project (for tracing and evaluations in the portal).')
param createProject bool = true

var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' = {
  name: name
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    allowProjectManagement: true
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

@batchSize(1) // model deployments on one account must be sequential
resource modelDeployments 'Microsoft.CognitiveServices/accounts/deployments@2025-04-01-preview' = [for d in deployments: {
  parent: account
  name: d.name
  sku: { name: d.sku, capacity: d.capacity }
  properties: {
    model: { format: 'OpenAI', name: d.model, version: d.version }
    versionUpgradeOption: 'OnceCurrentVersionExpired'
    raiPolicyName: 'Microsoft.DefaultV2'
  }
}]

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-04-01-preview' = if (createProject) {
  parent: account
  name: '${name}-project'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'hcwave'
    description: 'Hospital AI Wave 1 – tracing and evaluations'
  }
}

resource users 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in userPrincipalIds: {
  scope: account
  name: guid(account.id, principalId, openAiUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

module endpoint 'private-endpoint.bicep' = {
  name: '${name}-pe'
  params: {
    name: '${name}-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: account.id
    groupId: 'account'
    privateDnsZoneIds: [ zoneIds.cognitive, zoneIds.openai, zoneIds.aiServices ]
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: account
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'audit', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = account.id
output name string = account.name
output endpoint string = 'https://${name}.openai.azure.com/'
output servicesEndpoint string = 'https://${name}.services.ai.azure.com/'
output principalId string = account.identity.principalId
