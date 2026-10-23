// -----------------------------------------------------------------------------
// Azure Communication Services: WhatsApp (Advanced Messaging), SMS and Email,
// with data stored in India. Inbound WhatsApp messages and delivery receipts
// flow ACS → Event Grid → Service Bus (no public webhook needed).
//
// The WhatsApp channel itself is connected in the portal (Meta embedded
// sign-up: ACS → Channels → WhatsApp) – it cannot be created by IaC.
// -----------------------------------------------------------------------------
param namePrefix string
param tags object = {}

@description('ACS data location (India keeps message data in-country).')
param dataLocation string = 'India'

@description('Service Bus namespace and queue names for inbound events.')
param serviceBusNamespaceName string
param inboundQueueName string = 'inbound-messages'
param deliveryQueueName string = 'delivery-status'

@description('Principals allowed to use ACS with Entra ID (workload identity).')
param senderPrincipalIds array = []

@description('Email domain: AzureManaged (DoNotReply@<guid>.azurecomm.net) or a verified custom domain name.')
param emailDomain string = 'AzureManagedDomain'

resource emailService 'Microsoft.Communication/emailServices@2023-04-01' = {
  name: '${namePrefix}-email'
  location: 'global'
  tags: tags
  properties: { dataLocation: dataLocation }
}

resource emailDomainResource 'Microsoft.Communication/emailServices/domains@2023-04-01' = {
  parent: emailService
  name: emailDomain
  location: 'global'
  properties: {
    domainManagement: emailDomain == 'AzureManagedDomain' ? 'AzureManaged' : 'CustomerManaged'
    userEngagementTracking: 'Disabled'
  }
}

resource communication 'Microsoft.Communication/communicationServices@2023-04-01' = {
  name: '${namePrefix}-acs'
  location: 'global'
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    dataLocation: dataLocation
    linkedDomains: [ emailDomainResource.id ]
  }
}

// Data-plane access with Entra ID (no access keys in the app).
var contributorRole = 'b24988ac-6180-42a0-ab88-20f7382dd24c'
resource senders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in senderPrincipalIds: {
  scope: communication
  name: guid(communication.id, principalId, contributorRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', contributorRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource systemTopic 'Microsoft.EventGrid/systemTopics@2024-06-01-preview' = {
  name: '${namePrefix}-acs-events'
  location: 'global'
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    source: communication.id
    topicType: 'Microsoft.Communication.CommunicationServices'
  }
}

var serviceBusSender = '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'

module inboundSender 'role-assignment.bicep' = {
  name: '${namePrefix}-acs-inbound-sender'
  params: {
    namespaceName: serviceBusNamespaceName
    queueName: inboundQueueName
    principalId: systemTopic.identity.principalId
    roleDefinitionId: serviceBusSender
  }
}

module deliverySender 'role-assignment.bicep' = {
  name: '${namePrefix}-acs-delivery-sender'
  params: {
    namespaceName: serviceBusNamespaceName
    queueName: deliveryQueueName
    principalId: systemTopic.identity.principalId
    roleDefinitionId: serviceBusSender
  }
}

resource inboundSubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2024-06-01-preview' = {
  parent: systemTopic
  name: 'whatsapp-inbound'
  properties: {
    eventDeliverySchema: 'EventGridSchema'
    filter: { includedEventTypes: [ 'Microsoft.Communication.AdvancedMessageReceived' ] }
    deliveryWithResourceIdentity: {
      identity: { type: 'SystemAssigned' }
      destination: {
        endpointType: 'ServiceBusQueue'
        properties: { resourceId: resourceId('Microsoft.ServiceBus/namespaces/queues', serviceBusNamespaceName, inboundQueueName) }
      }
    }
    retryPolicy: { maxDeliveryAttempts: 30, eventTimeToLiveInMinutes: 1440 }
  }
  dependsOn: [ inboundSender ]
}

resource deliverySubscription 'Microsoft.EventGrid/systemTopics/eventSubscriptions@2024-06-01-preview' = {
  parent: systemTopic
  name: 'whatsapp-delivery'
  properties: {
    eventDeliverySchema: 'EventGridSchema'
    filter: { includedEventTypes: [ 'Microsoft.Communication.AdvancedMessageDeliveryStatusUpdated' ] }
    deliveryWithResourceIdentity: {
      identity: { type: 'SystemAssigned' }
      destination: {
        endpointType: 'ServiceBusQueue'
        properties: { resourceId: resourceId('Microsoft.ServiceBus/namespaces/queues', serviceBusNamespaceName, deliveryQueueName) }
      }
    }
    retryPolicy: { maxDeliveryAttempts: 30, eventTimeToLiveInMinutes: 1440 }
  }
  dependsOn: [ deliverySender ]
}

output id string = communication.id
output name string = communication.name
output endpoint string = 'https://${communication.properties.hostName}'
output emailSenderAddress string = 'DoNotReply@${emailDomainResource.properties.mailFromSenderDomain}'
