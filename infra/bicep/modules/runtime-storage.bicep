// -----------------------------------------------------------------------------
// Runtime storage for Logic Apps Standard / Azure Functions (state, Durable
// task hub, content share). The content share still needs an account key, so
// this account is separate from patient data and reachable only through
// private endpoints from the integrated subnets.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param zoneIds object

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

module endpoints 'private-endpoint.bicep' = [for service in [ 'blob', 'queue', 'table', 'file' ]: {
  name: '${name}-${service}-pe'
  params: {
    name: '${name}-${service}-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: account.id
    groupId: service
    privateDnsZoneIds: [ zoneIds[service] ]
  }
}]

output id string = account.id
output name string = account.name
