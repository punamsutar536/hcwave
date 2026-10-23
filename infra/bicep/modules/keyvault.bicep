// -----------------------------------------------------------------------------
// Key Vault (RBAC mode, purge protection, private only). Holds the few
// secrets that cannot be replaced by managed identity (app HMAC key, Meta
// tokens if used, MSG91 key). AKS pods mount them via the Secrets Store CSI
// driver using workload identity.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param tenantId string = subscription().tenantId
param privateEndpointSubnetId string
param privateDnsZoneId string
param logAnalyticsWorkspaceId string

@description('Principals granted "Key Vault Secrets User" (read secrets).')
param secretReaderPrincipalIds array = []

@description('Principal granted "Key Vault Secrets Officer" (deployment operator / CI).')
param operatorPrincipalId string = ''

@secure()
@description('HMAC key for signed cookies and OTP hashing (generated per environment).')
param appSecretKey string

@description('Allow public network access (only for bootstrap from outside the VNet).')
param publicNetworkAccess string = 'Disabled'

var secretsUserRole = '4633458b-17de-408a-b874-0445c86b69e6'
var secretsOfficerRole = 'b86a8fe4-44ce-4948-aee5-eccb2c155cd7'

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  tags: tags
  properties: {
    tenantId: tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enablePurgeProtection: true
    publicNetworkAccess: publicNetworkAccess
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
  }
}

resource appSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'APP-SECRET-KEY'
  properties: { value: appSecretKey, contentType: 'text/plain' }
}

resource readers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in secretReaderPrincipalIds: {
  scope: vault
  name: guid(vault.id, principalId, secretsUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsUserRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource officer 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(operatorPrincipalId)) {
  scope: vault
  name: guid(vault.id, operatorPrincipalId, secretsOfficerRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', secretsOfficerRole)
    principalId: operatorPrincipalId
  }
}

module endpoint 'private-endpoint.bicep' = {
  name: '${name}-pe'
  params: {
    name: '${name}-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: vault.id
    groupId: 'vault'
    privateDnsZoneIds: [ privateDnsZoneId ]
  }
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: vault
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'audit', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = vault.id
output name string = vault.name
output uri string = vault.properties.vaultUri
