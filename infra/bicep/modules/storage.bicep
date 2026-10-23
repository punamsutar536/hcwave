// -----------------------------------------------------------------------------
// Storage for report PDFs and HIS file drops: private endpoint only, shared
// keys disabled (signed links are user-delegation SAS minted with Entra ID),
// TLS 1.2, infrastructure encryption, soft delete + versioning, lifecycle
// tiering. Event Grid forwards new report files to the worker queue.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param blobPrivateDnsZoneId string
param logAnalyticsWorkspaceId string

@description('Principals that read/write blobs and mint user-delegation SAS (workload identity).')
param dataContributorPrincipalIds array = []

@description('Principals that only write HIS imports (e.g. Data Factory).')
param importWriterPrincipalIds array = []

@description('Move reports to the cool tier after N days.')
param coolAfterDays int = 30

@description('Delete report PDFs after N days (align with the hospital record-retention policy).')
param deleteAfterDays int = 1825

@description('Service Bus queue ID that receives BlobCreated events for HIS report drops ("" = off).')
param reportEventsQueueId string = ''

var blobDataContributor = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
var blobDelegator = 'db58b8e5-c6ad-4a2a-8342-4190687cbf4a'

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_ZRS' }
  properties: {
    accessTier: 'Hot'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    defaultToOAuthAuthentication: true
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    publicNetworkAccess: 'Disabled'
    networkAcls: { defaultAction: 'Deny', bypass: 'AzureServices' }
    encryption: {
      requireInfrastructureEncryption: true
      keySource: 'Microsoft.Storage'
      services: { blob: { enabled: true, keyType: 'Account' }, file: { enabled: true, keyType: 'Account' } }
    }
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
  properties: {
    isVersioningEnabled: true
    changeFeed: { enabled: true }
    deleteRetentionPolicy: { enabled: true, days: 30 }
    containerDeleteRetentionPolicy: { enabled: true, days: 30 }
  }
}

resource reports 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'reports'
  properties: { publicAccess: 'None' }
}

resource imports 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'his-imports'
  properties: { publicAccess: 'None' }
}

resource lifecycle 'Microsoft.Storage/storageAccounts/managementPolicies@2023-05-01' = {
  parent: account
  name: 'default'
  properties: {
    policy: {
      rules: [
        {
          name: 'reports-tiering-and-retention'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: [ 'blockBlob' ], prefixMatch: [ 'reports/' ] }
            actions: {
              baseBlob: {
                tierToCool: { daysAfterModificationGreaterThan: coolAfterDays }
                delete: { daysAfterModificationGreaterThan: deleteAfterDays }
              }
            }
          }
        }
        {
          name: 'imports-cleanup'
          enabled: true
          type: 'Lifecycle'
          definition: {
            filters: { blobTypes: [ 'blockBlob' ], prefixMatch: [ 'his-imports/' ] }
            actions: { baseBlob: { delete: { daysAfterModificationGreaterThan: 90 } } }
          }
        }
      ]
    }
  }
}

resource contributors 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataContributorPrincipalIds: {
  scope: account
  name: guid(account.id, principalId, blobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource delegators 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataContributorPrincipalIds: {
  scope: account
  name: guid(account.id, principalId, blobDelegator)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDelegator)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource importWriters 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in importWriterPrincipalIds: {
  scope: imports
  name: guid(imports.id, principalId, blobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', blobDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

module endpoint 'private-endpoint.bicep' = {
  name: '${name}-blob-pe'
  params: {
    name: '${name}-blob-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: account.id
    groupId: 'blob'
    privateDnsZoneIds: [ blobPrivateDnsZoneId ]
  }
}

// New report PDFs dropped under his-imports/<hospital>/reports/ trigger an
// incremental report sync in the worker (in addition to the scheduled pull).
resource systemTopic 'Microsoft.EventGrid/systemTopics@2024-06-01-preview' = if (!empty(reportEventsQueueId)) {
  name: '${name}-events'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    source: account.id
    topicType: 'Microsoft.Storage.StorageAccounts'
  }
}

// The topic identity must be able to send to the queue before subscribing.
module topicSender 'role-assignment.bicep' = if (!empty(reportEventsQueueId)) {
  name: '${name}-events-sender'
  params: {
    namespaceName: split(reportEventsQueueId, '/')[8]
    queueName: split(reportEventsQueueId, '/')[10]
    principalId: systemTopic!.identity.principalId
    roleDefinitionId: '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39' // Azure Service Bus Data Sender
  }
}

resource reportDrops 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2024-06-01-preview' = if (!empty(reportEventsQueueId)) {
  parent: systemTopic
  name: 'report-drops'
  properties: {
    eventDeliverySchema: 'EventGridSchema'
    filter: {
      includedEventTypes: [ 'Microsoft.Storage.BlobCreated' ]
      subjectBeginsWith: '/blobServices/default/containers/his-imports/blobs/'
      subjectEndsWith: '.pdf'
    }
    deliveryWithResourceIdentity: {
      identity: { type: 'SystemAssigned' }
      destination: {
        endpointType: 'ServiceBusQueue'
        properties: { resourceId: reportEventsQueueId }
      }
    }
    retryPolicy: { maxDeliveryAttempts: 30, eventTimeToLiveInMinutes: 1440 }
  }
  dependsOn: [ topicSender ]
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: blobService
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'audit', enabled: true } ]
    metrics: [ { category: 'Transaction', enabled: true } ]
  }
}

output id string = account.id
output name string = account.name
output blobEndpoint string = account.properties.primaryEndpoints.blob
output eventTopicPrincipalId string = !empty(reportEventsQueueId) ? systemTopic!.identity.principalId : ''
