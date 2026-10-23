// -----------------------------------------------------------------------------
// Private endpoint + private DNS zone group for one PaaS sub-resource.
// Keeps the database, storage and AI services off the public internet.
// -----------------------------------------------------------------------------
@description('Private endpoint name.')
param name string

@description('Azure region.')
param location string

@description('Tags applied to the endpoint.')
param tags object = {}

@description('Subnet that hosts private endpoints.')
param subnetId string

@description('Resource ID of the target PaaS resource.')
param privateLinkResourceId string

@description('Sub-resource (group ID), e.g. blob, vault, namespace, account.')
param groupId string

@description('Private DNS zone IDs to register the endpoint in.')
param privateDnsZoneIds array

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    subnet: { id: subnetId }
    privateLinkServiceConnections: [
      {
        name: name
        properties: {
          privateLinkServiceId: privateLinkResourceId
          groupIds: [ groupId ]
        }
      }
    ]
  }
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [for (zoneId, i) in privateDnsZoneIds: {
      name: 'zone-${i}'
      properties: { privateDnsZoneId: zoneId }
    }]
  }
}

output id string = endpoint.id
