// =============================================================================
// Hospital AI – Wave 1 platform: complete Azure environment (one per stage).
//
//   az deployment sub create -l centralindia -f infra/bicep/main.bicep \
//      -p infra/bicep/parameters/dev.bicepparam
//
// Creates a resource group with a private-by-default landing zone:
// VNet + private endpoints/DNS, AKS (workload identity, KV CSI, policy,
// Defender, KEDA), Application Gateway for Containers + WAF (and optionally
// Front Door Premium), PostgreSQL Flexible Server, Blob Storage, Service Bus,
// Event Grid, ACS (WhatsApp/SMS/Email), Microsoft Foundry (Azure OpenAI),
// AI Search, Content Safety, Translator, Key Vault, ACR, Log Analytics +
// Application Insights, Logic Apps Standard, Azure Functions, Azure Backup,
// optional APIM AI gateway, Grafana, Power BI Embedded, Purview, Data Factory,
// FHIR, plus Defender for Cloud and Azure Policy at subscription scope.
// =============================================================================
targetScope = 'subscription'

// ----------------------------------------------------------------------------
// Core parameters
// ----------------------------------------------------------------------------
@allowed([ 'dev', 'staging', 'prod' ])
param environmentName string

@description('Primary region (Central India keeps data in India).')
param location string = 'centralindia'

@description('Region for Microsoft Foundry/Azure OpenAI (where the models are deployed).')
param aiLocation string = 'southindia'

@description('Short prefix for resource names (lowercase letters/digits).')
@maxLength(6)
param namePrefix string = 'hcw'

param tags object = {}

@description('Entra group that administers AKS and PostgreSQL.')
param adminGroupObjectId string
param adminGroupName string

@description('CI/CD or operator principal that writes Key Vault secrets.')
param operatorPrincipalId string = ''

@description('Operational alert recipients.')
param alertEmails array = []

@secure()
@description('HMAC key for cookies/OTP hashing. Defaults to a new random value per deployment of the vault secret.')
param appSecretKey string = newGuid()

// ----------------------------------------------------------------------------
// Compute and network
// ----------------------------------------------------------------------------
param kubernetesVersion string = '1.31'
param aksPrivateCluster bool = environmentName == 'prod'
param aksAuthorizedIpRanges array = []
param aksSystemNodeVmSize string = 'Standard_D4ds_v5'
param aksUserNodeVmSize string = 'Standard_D4ds_v5'
param aksUserNodeMinCount int = environmentName == 'prod' ? 3 : 1
param aksUserNodeMaxCount int = environmentName == 'prod' ? 8 : 3

@description('Static private IP of the internal job API load balancer (inside the AKS node subnet).')
param internalApiIp string = '10.20.3.250'

@description('Entra application ID URI (audience) of the internal job API.')
param internalApiAudience string = 'api://hcwave-internal-api'

@description('Entra application ID URI (audience) protecting the Function App.')
param functionsAuthAudience string = 'api://hcwave-functions'

param acrPublicNetworkAccess string = 'Enabled'
param keyVaultPublicNetworkAccess string = 'Disabled'

// ----------------------------------------------------------------------------
// Data and AI
// ----------------------------------------------------------------------------
param postgresSkuName string = environmentName == 'prod' ? 'Standard_D4ds_v5' : 'Standard_B2ms'
param postgresSkuTier string = environmentName == 'prod' ? 'GeneralPurpose' : 'Burstable'
param postgresStorageGB int = 128
param postgresHighAvailability bool = environmentName == 'prod'
param postgresGeoRedundantBackup bool = environmentName == 'prod'

@allowed([ 'Standard', 'Premium' ])
param serviceBusSku string = 'Premium'

param openAiDeployments array = [
  { name: 'gpt-5-mini', model: 'gpt-5-mini', version: '2025-08-07', sku: 'Standard', capacity: 50 }
  { name: 'gpt-5', model: 'gpt-5', version: '2025-08-07', sku: 'Standard', capacity: 20 }
  { name: 'text-embedding-3-large', model: 'text-embedding-3-large', version: '1', sku: 'Standard', capacity: 50 }
]

param searchSku string = 'standard'

@description('Delete report PDFs after N days (hospital record-retention policy).')
param reportRetentionDays int = 1825

// ----------------------------------------------------------------------------
// Feature switches
// ----------------------------------------------------------------------------
param enableFrontDoor bool = true
param enableApim bool = false
param apimPublisherEmail string = ''
param enableLogicApps bool = true
param enableFunctions bool = true
param enableBackup bool = true
param enableDefender bool = true
param enablePolicy bool = true
param enableGrafana bool = false
param enablePowerBiEmbedded bool = false
param powerBiAdmins array = []
param enablePurview bool = false
param enableDataFactory bool = false
param enableFhir bool = false

@description('Public DNS zone for branded links ("" = skip).')
param dnsZoneName string = ''

// ----------------------------------------------------------------------------
// Naming
// ----------------------------------------------------------------------------
var base = '${namePrefix}-${environmentName}'
var unique = take(uniqueString(subscription().id, namePrefix, environmentName), 6)
var compact = toLower('${namePrefix}${environmentName}')
var allTags = union({ application: 'hcwave', environment: environmentName, 'data-classification': 'phi' }, tags)

resource rg 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: 'rg-${base}'
  location: location
  tags: allTags
}

// ----------------------------------------------------------------------------
// Foundation
// ----------------------------------------------------------------------------
module monitoring 'modules/monitoring.bicep' = {
  scope: rg
  name: 'monitoring'
  params: { namePrefix: base, location: location, tags: allTags, alertEmails: alertEmails }
}

module network 'modules/network.bicep' = {
  scope: rg
  name: 'network'
  params: { namePrefix: base, location: location, tags: allTags }
}

module dns 'modules/private-dns.bicep' = {
  scope: rg
  name: 'private-dns'
  params: { namePrefix: base, vnetId: network.outputs.vnetId, tags: allTags }
}

module identities 'modules/identity.bicep' = {
  scope: rg
  name: 'identities'
  params: { namePrefix: base, location: location, tags: allTags }
}

module keyVault 'modules/keyvault.bicep' = {
  scope: rg
  name: 'keyvault'
  params: {
    name: '${base}-kv-${unique}'
    location: location
    tags: allTags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.keyVault
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    secretReaderPrincipalIds: [ identities.outputs.workloadPrincipalId ]
    operatorPrincipalId: operatorPrincipalId
    appSecretKey: appSecretKey
    publicNetworkAccess: keyVaultPublicNetworkAccess
  }
}

// ----------------------------------------------------------------------------
// Compute: AKS + registry + ingress (AGC/WAF, optional Front Door)
// ----------------------------------------------------------------------------
module aks 'modules/aks.bicep' = {
  scope: rg
  name: 'aks'
  params: {
    name: '${base}-aks'
    location: location
    tags: allTags
    kubernetesVersion: kubernetesVersion
    nodeSubnetId: network.outputs.aksSubnetId
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    adminGroupObjectIds: [ adminGroupObjectId ]
    privateCluster: aksPrivateCluster
    authorizedIpRanges: aksAuthorizedIpRanges
    systemNodeVmSize: aksSystemNodeVmSize
    userNodeVmSize: aksUserNodeVmSize
    userNodeMinCount: aksUserNodeMinCount
    userNodeMaxCount: aksUserNodeMaxCount
    workloadIdentityName: identities.outputs.workloadName
    albControllerIdentityName: identities.outputs.albControllerName
  }
}

// The cluster identity places the internal load balancer in the node subnet.
module aksSubnetRole 'modules/subnet-role.bicep' = {
  scope: rg
  name: 'aks-subnet-network-contributor'
  params: {
    vnetName: network.outputs.vnetName
    subnetName: 'snet-aks-nodes'
    principalId: aks.outputs.principalId
    roleDefinitionId: '4d97b98b-1d4f-4787-a291-c67834d212e7'
  }
}

module acr 'modules/acr.bicep' = {
  scope: rg
  name: 'acr'
  params: {
    name: '${compact}acr${unique}'
    location: location
    tags: allTags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.acr
    publicNetworkAccess: acrPublicNetworkAccess
    pullPrincipalIds: [ aks.outputs.kubeletPrincipalId ]
  }
}

module agc 'modules/agc.bicep' = {
  scope: rg
  name: 'agc'
  params: {
    namePrefix: base
    location: location
    tags: allTags
    subnetId: network.outputs.agcSubnetId
    vnetName: network.outputs.vnetName
    albControllerPrincipalId: identities.outputs.albControllerPrincipalId
  }
}

module frontDoor 'modules/frontdoor.bicep' = if (enableFrontDoor) {
  scope: rg
  name: 'frontdoor'
  params: { namePrefix: base, tags: allTags, originHostName: agc.outputs.frontendFqdn }
}

// ----------------------------------------------------------------------------
// Data
// ----------------------------------------------------------------------------
module postgres 'modules/postgres.bicep' = {
  scope: rg
  name: 'postgres'
  params: {
    name: '${base}-pg-${unique}'
    location: location
    tags: allTags
    delegatedSubnetId: network.outputs.postgresSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.postgres
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    skuName: postgresSkuName
    skuTier: postgresSkuTier
    storageSizeGB: postgresStorageGB
    highAvailability: postgresHighAvailability
    geoRedundantBackup: postgresGeoRedundantBackup
    entraAdminObjectId: adminGroupObjectId
    entraAdminName: adminGroupName
  }
}

module serviceBus 'modules/servicebus.bicep' = {
  scope: rg
  name: 'servicebus'
  params: {
    name: '${base}-sb-${unique}'
    location: location
    tags: allTags
    sku: serviceBusSku
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.serviceBus
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    dataPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module storage 'modules/storage.bicep' = {
  scope: rg
  name: 'storage'
  params: {
    name: '${compact}st${unique}'
    location: location
    tags: allTags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    blobPrivateDnsZoneId: dns.outputs.zoneIds.blob
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    dataContributorPrincipalIds: [ identities.outputs.workloadPrincipalId ]
    deleteAfterDays: reportRetentionDays
    reportEventsQueueId: serviceBus.outputs.queueIds['report-events']
  }
}

// ----------------------------------------------------------------------------
// Messaging channel and AI services
// ----------------------------------------------------------------------------
module acs 'modules/acs.bicep' = {
  scope: rg
  name: 'acs'
  params: {
    namePrefix: base
    tags: allTags
    serviceBusNamespaceName: serviceBus.outputs.name
    senderPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module foundry 'modules/ai-foundry.bicep' = {
  scope: rg
  name: 'ai-foundry'
  params: {
    name: '${base}-ai-${unique}'
    location: aiLocation
    tags: allTags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    zoneIds: dns.outputs.zoneIds
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    deployments: openAiDeployments
    userPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module contentSafety 'modules/cognitive.bicep' = {
  scope: rg
  name: 'content-safety'
  params: {
    name: '${base}-cs-${unique}'
    location: location
    tags: allTags
    kind: 'ContentSafety'
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.cognitive
    userPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module translator 'modules/cognitive.bicep' = {
  scope: rg
  name: 'translator'
  params: {
    name: '${base}-tr-${unique}'
    location: location
    tags: allTags
    kind: 'TextTranslation'
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.cognitive
    userPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module search 'modules/search.bicep' = {
  scope: rg
  name: 'search'
  params: {
    name: '${base}-srch-${unique}'
    location: location
    tags: allTags
    sku: searchSku
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    privateDnsZoneId: dns.outputs.zoneIds.search
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    contributorPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module apim 'modules/apim.bicep' = if (enableApim) {
  scope: rg
  name: 'apim'
  params: {
    namePrefix: base
    location: location
    tags: allTags
    publisherEmail: apimPublisherEmail
    subnetId: network.outputs.apimSubnetId
    appInsightsId: monitoring.outputs.appInsightsId
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    openAiEndpoint: foundry.outputs.endpoint
  }
}

// APIM calls Azure OpenAI with its own identity.
module apimOpenAiAccess 'modules/ai-foundry-role.bicep' = if (enableApim) {
  scope: rg
  name: 'apim-openai-user'
  params: { accountName: foundry.outputs.name, principalId: enableApim ? apim!.outputs.principalId : '' }
}

// ----------------------------------------------------------------------------
// Workflow engines (Logic Apps Standard, Durable Functions)
// ----------------------------------------------------------------------------
var internalApiUrl = 'http://${internalApiIp}:8001'

module runtimeStorage 'modules/runtime-storage.bicep' = if (enableLogicApps || enableFunctions) {
  scope: rg
  name: 'runtime-storage'
  params: {
    name: '${compact}rt${unique}'
    location: location
    tags: allTags
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    zoneIds: dns.outputs.zoneIds
  }
}

module logicApp 'modules/logicapp.bicep' = if (enableLogicApps) {
  scope: rg
  name: 'logic-app'
  params: {
    namePrefix: base
    location: location
    tags: allTags
    subnetId: network.outputs.logicAppsSubnetId
    identityId: identities.outputs.logicAppId
    identityClientId: identities.outputs.logicAppClientId
    runtimeStorageName: '${compact}rt${unique}'
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    internalApiUrl: internalApiUrl
    internalApiAudience: internalApiAudience
  }
  dependsOn: [ runtimeStorage ]
}

module functions 'modules/functions.bicep' = if (enableFunctions) {
  scope: rg
  name: 'functions'
  params: {
    namePrefix: base
    location: location
    tags: allTags
    subnetId: network.outputs.functionsSubnetId
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    sitesPrivateDnsZoneId: dns.outputs.zoneIds.sites
    identityId: identities.outputs.functionsId
    identityClientId: identities.outputs.functionsClientId
    runtimeStorageName: '${compact}rt${unique}'
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
    internalApiUrl: internalApiUrl
    internalApiAudience: internalApiAudience
    authAudience: functionsAuthAudience
    allowedClientIds: [ identities.outputs.workloadClientId ]
  }
  dependsOn: [ runtimeStorage ]
}

// ----------------------------------------------------------------------------
// Resilience, optional services, DNS, compliance
// ----------------------------------------------------------------------------
module backup 'modules/backup.bicep' = if (enableBackup) {
  scope: rg
  name: 'backup'
  params: { namePrefix: base, location: location, tags: allTags }
}

module optional 'modules/optional-services.bicep' = {
  scope: rg
  name: 'optional-services'
  params: {
    namePrefix: base
    location: location
    tags: allTags
    enableGrafana: enableGrafana
    enablePowerBiEmbedded: enablePowerBiEmbedded
    powerBiAdmins: powerBiAdmins
    enablePurview: enablePurview
    enableDataFactory: enableDataFactory
    enableFhir: enableFhir
    storageAccountId: storage.outputs.id
    fhirReaderPrincipalIds: [ identities.outputs.workloadPrincipalId ]
  }
}

module publicDns 'modules/dns.bicep' = if (!empty(dnsZoneName)) {
  scope: rg
  name: 'public-dns'
  params: {
    zoneName: dnsZoneName
    tags: allTags
    targetHostName: enableFrontDoor ? frontDoor!.outputs.endpointHostName : agc.outputs.frontendFqdn
  }
}

module security 'modules/security.bicep' = {
  name: 'security-${environmentName}'
  params: {
    enableDefender: enableDefender
    enablePolicy: enablePolicy
    resourceGroupName: rg.name
  }
}

// ----------------------------------------------------------------------------
// Outputs consumed by scripts/bootstrap.sh → Helm values and app settings
// ----------------------------------------------------------------------------
output resourceGroupName string = rg.name
output tenantId string = tenant().tenantId
output aksName string = aks.outputs.name
output acrLoginServer string = acr.outputs.loginServer
output acrName string = acr.outputs.name
output keyVaultName string = keyVault.outputs.name
output workloadIdentityClientId string = identities.outputs.workloadClientId
output workloadIdentityName string = identities.outputs.workloadName
output albControllerClientId string = identities.outputs.albControllerClientId
output logicAppClientId string = identities.outputs.logicAppClientId
output functionsClientId string = identities.outputs.functionsClientId
output agcId string = agc.outputs.id
output agcFrontendName string = agc.outputs.frontendName
output agcFrontendFqdn string = agc.outputs.frontendFqdn
output agcSecurityPolicyId string = agc.outputs.securityPolicyId
output frontDoorHostName string = enableFrontDoor ? frontDoor!.outputs.endpointHostName : ''
output postgresHost string = postgres.outputs.fqdn
output postgresDatabase string = postgres.outputs.databaseName
output serviceBusNamespace string = serviceBus.outputs.fullyQualifiedNamespace
output storageAccountUrl string = storage.outputs.blobEndpoint
output acsEndpoint string = acs.outputs.endpoint
output acsEmailSender string = acs.outputs.emailSenderAddress
output openAiEndpoint string = enableApim ? '${apim!.outputs.gatewayUrl}/' : foundry.outputs.endpoint
output searchEndpoint string = search.outputs.endpoint
output contentSafetyEndpoint string = contentSafety.outputs.endpoint
output translatorEndpoint string = '${translator.outputs.endpoint}translator/text/v3.0'
output appInsightsConnectionString string = monitoring.outputs.appInsightsConnectionString
output internalApiUrl string = internalApiUrl
output internalApiIp string = internalApiIp
output durableFeedbackStartUrl string = enableFunctions ? functions!.outputs.feedbackStartUrl : ''
output logicAppName string = enableLogicApps ? logicApp!.outputs.name : ''
output functionAppName string = enableFunctions ? functions!.outputs.name : ''
output grafanaEndpoint string = optional.outputs.grafanaEndpoint
output fhirUrl string = optional.outputs.fhirUrl
