// -----------------------------------------------------------------------------
// Logic Apps Standard (workflow engine – the n8n equivalent): recurrence
// workflows for reminders, feedback, report alerts and the daily briefing.
// Runs on a WS plan with VNet integration and calls the backend's internal
// API privately using its user-assigned managed identity.
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}
param subnetId string
param identityId string
param identityClientId string
param runtimeStorageName string
@secure()
param appInsightsConnectionString string
param internalApiUrl string
param internalApiAudience string
param sku string = 'WS1'

resource runtimeStorage 'Microsoft.Storage/storageAccounts@2023-05-01' existing = {
  name: runtimeStorageName
}

var storageConnection = 'DefaultEndpointsProtocol=https;AccountName=${runtimeStorage.name};AccountKey=${runtimeStorage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: '${namePrefix}-logic-plan'
  location: location
  tags: tags
  sku: { name: sku, tier: 'WorkflowStandard' }
  kind: 'elastic'
  properties: { maximumElasticWorkerCount: 4 }
}

resource logicApp 'Microsoft.Web/sites@2024-04-01' = {
  name: '${namePrefix}-logic'
  location: location
  tags: tags
  kind: 'functionapp,workflowapp'
  identity: { type: 'UserAssigned', userAssignedIdentities: { '${identityId}': {} } }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: subnetId
    vnetRouteAllEnabled: true
    publicNetworkAccess: 'Disabled'
    siteConfig: {
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      http20Enabled: true
      appSettings: [
        { name: 'FUNCTIONS_EXTENSION_VERSION', value: '~4' }
        { name: 'FUNCTIONS_WORKER_RUNTIME', value: 'dotnet' }
        { name: 'APP_KIND', value: 'workflowApp' }
        { name: 'AzureFunctionsJobHost__extensionBundle__id', value: 'Microsoft.Azure.Functions.ExtensionBundle.Workflows' }
        { name: 'AzureFunctionsJobHost__extensionBundle__version', value: '[1.*, 2.0.0)' }
        { name: 'AzureWebJobsStorage', value: storageConnection }
        { name: 'WEBSITE_CONTENTAZUREFILECONNECTIONSTRING', value: storageConnection }
        { name: 'WEBSITE_CONTENTSHARE', value: toLower('${namePrefix}-logic') }
        { name: 'WEBSITE_CONTENTOVERVNET', value: '1' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsightsConnectionString }
        { name: 'HCWAVE_INTERNAL_URL', value: internalApiUrl }
        { name: 'HCWAVE_INTERNAL_AUDIENCE', value: internalApiAudience }
        { name: 'HCWAVE_LOGICAPP_IDENTITY_ID', value: identityId }
        { name: 'AZURE_CLIENT_ID', value: identityClientId }
      ]
    }
  }
}

output name string = logicApp.name
output id string = logicApp.id
