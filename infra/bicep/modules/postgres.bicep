// -----------------------------------------------------------------------------
// Azure Database for PostgreSQL – Flexible Server (patients, appointments,
// messages, reports, feedback). Private access only (delegated subnet),
// Microsoft Entra authentication (workload identity tokens, no passwords),
// TLS enforced, automated backups (optionally geo-redundant), optional
// zone-redundant HA. pgvector is allow-listed for the pgvector RAG option.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param delegatedSubnetId string
param privateDnsZoneId string
param logAnalyticsWorkspaceId string
param tenantId string = subscription().tenantId

param version string = '16'
param skuName string = 'Standard_D2ds_v5'
@allowed([ 'Burstable', 'GeneralPurpose', 'MemoryOptimized' ])
param skuTier string = 'GeneralPurpose'
param storageSizeGB int = 128
param backupRetentionDays int = 35
param geoRedundantBackup bool = false
param highAvailability bool = false

@description('Entra principal that administers the server (group recommended).')
param entraAdminObjectId string
param entraAdminName string
@allowed([ 'Group', 'User', 'ServicePrincipal' ])
param entraAdminType string = 'Group'

param databaseName string = 'hcwave'

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: skuName, tier: skuTier }
  properties: {
    version: version
    storage: { storageSizeGB: storageSizeGB, autoGrow: 'Enabled' }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: { mode: highAvailability ? 'ZoneRedundant' : 'Disabled' }
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Disabled'
      tenantId: tenantId
    }
  }
}

resource admin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: server
  name: entraAdminObjectId
  properties: {
    principalName: entraAdminName
    principalType: entraAdminType
    tenantId: tenantId
  }
}

resource extensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'azure.extensions'
  properties: { value: 'VECTOR,PG_TRGM,PGCRYPTO', source: 'user-override' }
  dependsOn: [ admin ]
}

resource secureTransport 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'require_secure_transport'
  properties: { value: 'ON', source: 'user-override' }
  dependsOn: [ extensions ]
}

resource logConnections 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'log_connections'
  properties: { value: 'ON', source: 'user-override' }
  dependsOn: [ secureTransport ]
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: server
  name: databaseName
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [ logConnections ]
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: server
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'audit', enabled: true }, { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = server.id
output name string = server.name
output fqdn string = server.properties.fullyQualifiedDomainName
output databaseName string = database.name
