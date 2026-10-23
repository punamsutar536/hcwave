// -----------------------------------------------------------------------------
// Optional services, each behind a switch:
//  * Azure Managed Grafana        – dashboard alternative to Power BI
//  * Power BI Embedded capacity   – management dashboard inside the staff app
//  * Microsoft Purview            – sensitive-data classification (DPDP/NABH)
//  * Azure Data Factory           – HIS CSV/database pulls into Blob Storage
//  * Azure Health Data Services   – FHIR R4 (later waves)
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}

param enableGrafana bool = false
param enablePowerBiEmbedded bool = false
param enablePurview bool = false
param enableDataFactory bool = false
param enableFhir bool = false

@description('Power BI capacity administrators (UPNs or object IDs).')
param powerBiAdmins array = []
param powerBiSku string = 'A1'

@description('Reports storage account (Data Factory writes HIS imports there).')
param storageAccountId string = ''

@description('Principals granted FHIR Data Reader (workload identity).')
param fhirReaderPrincipalIds array = []

resource grafana 'Microsoft.Dashboard/grafana@2023-09-01' = if (enableGrafana) {
  name: '${namePrefix}-grafana'
  location: location
  tags: tags
  sku: { name: 'Standard' }
  identity: { type: 'SystemAssigned' }
  properties: {
    apiKey: 'Disabled'
    deterministicOutboundIP: 'Enabled'
    publicNetworkAccess: 'Enabled'
    zoneRedundancy: 'Disabled'
  }
}

resource powerBi 'Microsoft.PowerBIDedicated/capacities@2021-01-01' = if (enablePowerBiEmbedded) {
  name: replace('${namePrefix}pbi', '-', '')
  location: location
  tags: tags
  sku: { name: powerBiSku, tier: 'PBIE_Azure' }
  properties: { administration: { members: powerBiAdmins } }
}

resource purview 'Microsoft.Purview/accounts@2021-12-01' = if (enablePurview) {
  name: '${namePrefix}-purview'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: { publicNetworkAccess: 'Enabled', managedResourceGroupName: '${namePrefix}-purview-managed' }
}

resource dataFactory 'Microsoft.DataFactory/factories@2018-06-01' = if (enableDataFactory) {
  name: '${namePrefix}-adf'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: { publicNetworkAccess: 'Disabled' }
}

// Managed VNet + managed private endpoint so ADF reaches storage privately.
resource adfVnet 'Microsoft.DataFactory/factories/managedVirtualNetworks@2018-06-01' = if (enableDataFactory) {
  parent: dataFactory
  name: 'default'
  properties: {}
}

resource adfRuntime 'Microsoft.DataFactory/factories/integrationRuntimes@2018-06-01' = if (enableDataFactory) {
  parent: dataFactory
  name: 'managed-vnet-ir'
  properties: {
    type: 'Managed'
    managedVirtualNetwork: { referenceName: 'default', type: 'ManagedVirtualNetworkReference' }
    typeProperties: { computeProperties: { location: 'AutoResolve' } }
  }
  dependsOn: [ adfVnet ]
}

resource adfStoragePe 'Microsoft.DataFactory/factories/managedVirtualNetworks/managedPrivateEndpoints@2018-06-01' = if (enableDataFactory && !empty(storageAccountId)) {
  parent: adfVnet
  name: 'reports-storage-blob'
  properties: { privateLinkResourceId: storageAccountId, groupId: 'blob' }
}

resource adfBlob 'Microsoft.DataFactory/factories/linkedservices@2018-06-01' = if (enableDataFactory && !empty(storageAccountId)) {
  parent: dataFactory
  name: 'HisImportsBlob'
  properties: {
    type: 'AzureBlobStorage'
    connectVia: { referenceName: adfRuntime.name, type: 'IntegrationRuntimeReference' }
    typeProperties: { serviceEndpoint: 'https://${last(split(storageAccountId, '/'))}.blob.${environment().suffixes.storage}/' }
  }
}

resource healthWorkspace 'Microsoft.HealthcareApis/workspaces@2024-03-31' = if (enableFhir) {
  name: replace('${namePrefix}hds', '-', '')
  location: location
  tags: tags
  properties: { publicNetworkAccess: 'Disabled' }
}

resource fhir 'Microsoft.HealthcareApis/workspaces/fhirservices@2024-03-31' = if (enableFhir) {
  parent: healthWorkspace
  name: 'fhir'
  location: location
  tags: tags
  kind: 'fhir-R4'
  identity: { type: 'SystemAssigned' }
  properties: {
    authenticationConfiguration: {
      authority: '${environment().authentication.loginEndpoint}${subscription().tenantId}'
      audience: 'https://${replace('${namePrefix}hds', '-', '')}-fhir.fhir.azurehealthcareapis.com'
      smartProxyEnabled: false
    }
    publicNetworkAccess: 'Disabled'
  }
}

var fhirReaderRole = '4c8d0bbc-75d3-4935-991f-5f3c56d81508'
resource fhirReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in (enableFhir ? fhirReaderPrincipalIds : []): {
  scope: fhir
  name: guid(resourceGroup().id, 'fhir', principalId, fhirReaderRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', fhirReaderRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

output grafanaEndpoint string = enableGrafana ? grafana!.properties.endpoint : ''
output dataFactoryPrincipalId string = enableDataFactory ? dataFactory!.identity.principalId : ''
output fhirUrl string = enableFhir ? 'https://${replace('${namePrefix}hds', '-', '')}-fhir.fhir.azurehealthcareapis.com' : ''
