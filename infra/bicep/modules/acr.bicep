// -----------------------------------------------------------------------------
// Azure Container Registry (Premium for private endpoints). Admin user is
// disabled; AKS pulls with its kubelet identity (AcrPull).
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param privateDnsZoneId string

@description('Enabled lets hosted CI agents push images; use Disabled with self-hosted agents in the VNet.')
param publicNetworkAccess string = 'Enabled'

@description('Principals granted AcrPull (AKS kubelet identity).')
param pullPrincipalIds array = []

var acrPullRole = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: 'Premium' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: publicNetworkAccess
    networkRuleBypassOptions: 'AzureServices'
    zoneRedundancy: 'Disabled'
    policies: {
      retentionPolicy: { days: 30, status: 'enabled' }
      trustPolicy: { type: 'Notary', status: 'disabled' }
    }
  }
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in pullPrincipalIds: {
  scope: registry
  name: guid(registry.id, principalId, acrPullRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRole)
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
    privateLinkResourceId: registry.id
    groupId: 'registry'
    privateDnsZoneIds: [ privateDnsZoneId ]
  }
}

output id string = registry.id
output name string = registry.name
output loginServer string = registry.properties.loginServer
