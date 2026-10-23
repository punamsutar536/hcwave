// -----------------------------------------------------------------------------
// Single-purpose Azure AI service (Content Safety, Translator, Language).
// Custom sub-domain (needed for Entra ID + private endpoint), keyless,
// private only.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
@allowed([ 'ContentSafety', 'TextTranslation', 'TextAnalytics' ])
param kind string
param privateEndpointSubnetId string
param privateDnsZoneId string

@description('Principals granted "Cognitive Services User".')
param userPrincipalIds array = []

var cognitiveUserRole = 'a97b65f3-24c7-4388-baec-2e87135dc908'

resource account 'Microsoft.CognitiveServices/accounts@2024-10-01' = {
  name: name
  location: location
  tags: tags
  kind: kind
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    customSubDomainName: name
    publicNetworkAccess: 'Disabled'
    disableLocalAuth: true
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

resource users 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in userPrincipalIds: {
  scope: account
  name: guid(account.id, principalId, cognitiveUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', cognitiveUserRole)
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
    privateDnsZoneIds: [ privateDnsZoneId ]
  }
}

output id string = account.id
output name string = account.name
output endpoint string = 'https://${name}.cognitiveservices.azure.com/'
