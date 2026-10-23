// -----------------------------------------------------------------------------
// Azure AI Search for hospital FAQs and policies: hybrid (keyword + vector)
// search with the semantic ranker. Keys disabled; private endpoint only.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param privateDnsZoneId string
param logAnalyticsWorkspaceId string

@allowed([ 'basic', 'standard', 'standard2' ])
param sku string = 'standard'
param replicaCount int = 1

@description('Principals that create indexes and read/write documents (workload identity).')
param contributorPrincipalIds array = []

var indexDataContributor = '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
var serviceContributor = '7ca78c08-252a-4471-8644-bb5ff32d4ba0'

resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: replicaCount
    partitionCount: 1
    hostingMode: 'default'
    publicNetworkAccess: 'disabled'
    disableLocalAuth: true
    semanticSearch: 'standard'
  }
}

resource indexContributors 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in contributorPrincipalIds: {
  scope: search
  name: guid(search.id, principalId, indexDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', indexDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource serviceContributors 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in contributorPrincipalIds: {
  scope: search
  name: guid(search.id, principalId, serviceContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', serviceContributor)
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
    privateLinkResourceId: search.id
    groupId: 'searchService'
    privateDnsZoneIds: [ privateDnsZoneId ]
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: search
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = search.id
output name string = search.name
output endpoint string = 'https://${name}.search.windows.net'
