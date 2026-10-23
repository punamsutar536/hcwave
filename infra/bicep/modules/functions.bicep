// -----------------------------------------------------------------------------
// Azure Functions (Python, Elastic Premium) for Durable Functions workflows
// such as "wait 3 h after the visit → send feedback → escalate if no reply".
// Private inbound (private endpoint) + Entra ID authentication; outbound via
// VNet integration to the backend's internal API.
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}
param subnetId string
param privateEndpointSubnetId string
param sitesPrivateDnsZoneId string
param identityId string
param identityClientId string
param runtimeStorageName string
@secure()
param appInsightsConnectionString string
param internalApiUrl string
param internalApiAudience string
param tenantId string = subscription().tenantId

@description('Entra app registration (audience) that callers must present – the backend identity gets tokens for it.')
param authAudience string

@description('Client IDs allowed to call the Function App (backend workload identity).')
param allowedClientIds array = []

param sku string = 'EP1'

resource runtimeStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: runtimeStorageName
}

var storageConnection = 'DefaultEndpointsProtocol=https;AccountName=${runtimeStorage.name};AccountKey=${runtimeStorage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${namePrefix}-func-plan'
  location: location
  tags: tags
  sku: { name: sku, tier: 'ElasticPremium' }
  kind: 'elastic'
  properties: { reserved: true, maximumElasticWorkerCount: 5 }
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: '${namePrefix}-func'
  location: location
  tags: tags
  kind: 'functionapp,linux'
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    reserved: true
    virtualNetworkSubnetId: subnetId
    vnetRouteAllEnabled: true
    publicNetworkAccess: 'Disabled'
    keyVaultReferenceIdentity: identityId
    siteConfig: {
      linuxFxVersion: 'Python|3.11'
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'python' }
        { name: 'AzureWebJobsStorage', value: storageConnection }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageConnection }
        { name: 'WEBSITE_CONTENTSHARE', value: toLower('${namePrefix}-func') }
        { name: 'WEBSITE_CONTENTOVERVNET', value: '1' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'DURABLE_TASK_HUB', value: replace('${namePrefix}hub', '-', '') }
        { name: 'HCWAVE_INTERNAL_URL', value: internalApiUrl }
        { name: 'HCWAVE_INTERNAL_AUDIENCE', value: internalApiAudience }
        { name: 'AZURE_CLIENT_ID', value: identityClientId }
        { name: 'FEEDBACK_OPD_DELAY_HOURS', value: '3' }
        { name: 'FEEDBACK_DISCHARGE_DELAY_HOURS', value: '24' }
        { name: 'FEEDBACK_REPLY_TIMEOUT_HOURS', value: '24' }
      ]
    }
  }
}

// App Service Authentication: only Entra tokens for our audience, issued to
// allowed callers, reach the HTTP starter.
resource auth 'Microsoft.Web/sites/config@2024-04-01' = {
  parent: functionApp
  name: 'authsettingsV2'
  properties: {
    platform: { enabled: true }
    globalValidation: { requireAuthentication: true, unauthenticatedClientAction: 'Return401' }
    identityProviders: {
      azureActiveDirectory: {
        enabled: true
        // Managed-identity tokens are v1 tokens issued by sts.windows.net.
        registration: { openIdIssuer: 'https://sts.windows.net/${tenantId}/', clientId: authAudience }
        validation: {
          allowedAudiences: [ authAudience ]
          defaultAuthorizationPolicy: { allowedApplications: allowedClientIds }
        }
      }
    }
  }
}

module endpoint 'private-endpoint.bicep' = {
  name: '${namePrefix}-func-pe'
  params: {
    name: '${namePrefix}-func-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: functionApp.id
    groupId: 'sites'
    privateDnsZoneIds: [ sitesPrivateDnsZoneId ]
  }
}

output name string = functionApp.name
output feedbackStartUrl string = 'https://${functionApp.properties.defaultHostName}/api/feedback/start'
