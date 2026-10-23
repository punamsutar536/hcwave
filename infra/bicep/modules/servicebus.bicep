// -----------------------------------------------------------------------------
// Service Bus: queues between Event Grid (WhatsApp messages and receipts) and
// the worker, so nothing is lost during spikes or restarts. Local (SAS) auth
// disabled; Premium enables private endpoints. Event Grid delivers through
// the trusted-services path with its managed identity.
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param privateEndpointSubnetId string
param privateDnsZoneId string
param logAnalyticsWorkspaceId string

@allowed([ 'Standard', 'Premium' ])
param sku string = 'Premium'

@description('Queues to create.')
param queueNames array = [ 'inbound-messages', 'delivery-status', 'report-events' ]

@description('Principals that send and receive (workload identity).')
param dataPrincipalIds array = []

var senderRole = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
var receiverRole = '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'

resource namespace 'Microsoft.ServiceBus/namespaces@2024-01-01' = {
  name: name
  location: location
  tags: tags
  sku: { name: sku, tier: sku, capacity: sku == 'Premium' ? 1 : 0 }
  properties: {
    disableLocalAuth: true
    minimumTlsVersion: '1.2'
    publicNetworkAccess: sku == 'Premium' ? 'Disabled' : 'Enabled'
    zoneRedundant: sku == 'Premium'
  }
}

resource networkRules 'Microsoft.ServiceBus/namespaces/networkRuleSets@2024-01-01' = if (sku == 'Premium') {
  parent: namespace
  name: 'default'
  properties: {
    defaultAction: 'Deny'
    publicNetworkAccess: 'Disabled'
    trustedServiceAccessEnabled: true
  }
}

resource queues 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' = [for queue in queueNames: {
  parent: namespace
  name: queue
  properties: {
    lockDuration: 'PT1M'
    maxDeliveryCount: 10
    deadLetteringOnMessageExpiration: true
    defaultMessageTimeToLive: 'P7D'
    requiresDuplicateDetection: true
    duplicateDetectionHistoryTimeWindow: 'PT10M'
  }
}]

resource senders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataPrincipalIds: {
  scope: namespace
  name: guid(namespace.id, principalId, senderRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', senderRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource receivers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataPrincipalIds: {
  scope: namespace
  name: guid(namespace.id, principalId, receiverRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', receiverRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

module endpoint 'private-endpoint.bicep' = if (sku == 'Premium') {
  name: '${name}-pe'
  params: {
    name: '${name}-pe'
    location: location
    tags: tags
    subnetId: privateEndpointSubnetId
    privateLinkResourceId: namespace.id
    groupId: 'namespace'
    privateDnsZoneIds: [ privateDnsZoneId ]
  }
}

// Dead-lettered messages mean an event could not be processed – alert on it.
resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: namespace
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [ { categoryGroup: 'allLogs', enabled: true } ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = namespace.id
output name string = namespace.name
output fullyQualifiedNamespace string = '${namespace.name}.servicebus.windows.net'
output queueIds object = toObject(queueNames, q => q, q => resourceId('Microsoft.ServiceBus/namespaces/queues', name, q))
output senderRoleId string = senderRole
