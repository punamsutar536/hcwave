// -----------------------------------------------------------------------------
// Private DNS zones for every private endpoint, linked to the VNet so pods,
// Logic Apps and Functions resolve PaaS names to private IPs.
// -----------------------------------------------------------------------------
param namePrefix string
param vnetId string
param tags object = {}

@description('Name of the PostgreSQL private zone (must end with .postgres.database.azure.com).')
param postgresZoneName string = '${namePrefix}.private.postgres.database.azure.com'

var zones = {
  keyVault: 'privatelink.vaultcore.azure.net'
  acr: 'privatelink.azurecr.io'
  blob: 'privatelink.blob.${environment().suffixes.storage}'
  queue: 'privatelink.queue.${environment().suffixes.storage}'
  table: 'privatelink.table.${environment().suffixes.storage}'
  file: 'privatelink.file.${environment().suffixes.storage}'
  serviceBus: 'privatelink.servicebus.windows.net'
  cognitive: 'privatelink.cognitiveservices.azure.com'
  openai: 'privatelink.openai.azure.com'
  aiServices: 'privatelink.services.ai.azure.com'
  search: 'privatelink.search.windows.net'
  sites: 'privatelink.azurewebsites.net'
  postgres: postgresZoneName
}

resource privateZones 'Microsoft.Network/privateDnsZones@2024-06-01' = [for zone in items(zones): {
  name: zone.value
  location: 'global'
  tags: tags
}]

resource links 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = [for (zone, i) in items(zones): {
  parent: privateZones[i]
  name: '${namePrefix}-link'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnetId }
    registrationEnabled: false
  }
}]

output zoneIds object = {
  keyVault: resourceId('Microsoft.Network/privateDnsZones', zones.keyVault)
  acr: resourceId('Microsoft.Network/privateDnsZones', zones.acr)
  blob: resourceId('Microsoft.Network/privateDnsZones', zones.blob)
  queue: resourceId('Microsoft.Network/privateDnsZones', zones.queue)
  table: resourceId('Microsoft.Network/privateDnsZones', zones.table)
  file: resourceId('Microsoft.Network/privateDnsZones', zones.file)
  serviceBus: resourceId('Microsoft.Network/privateDnsZones', zones.serviceBus)
  cognitive: resourceId('Microsoft.Network/privateDnsZones', zones.cognitive)
  openai: resourceId('Microsoft.Network/privateDnsZones', zones.openai)
  aiServices: resourceId('Microsoft.Network/privateDnsZones', zones.aiServices)
  search: resourceId('Microsoft.Network/privateDnsZones', zones.search)
  sites: resourceId('Microsoft.Network/privateDnsZones', zones.sites)
  postgres: resourceId('Microsoft.Network/privateDnsZones', zones.postgres)
}
