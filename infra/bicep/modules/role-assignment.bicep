// -----------------------------------------------------------------------------
// Grants one role on a Service Bus queue (used for Event Grid identities,
// which only exist after their system topics are created).
// -----------------------------------------------------------------------------
param namespaceName string
param queueName string
param principalId string
param roleDefinitionId string

resource queue 'Microsoft.ServiceBus/namespaces/queues@2024-01-01' existing = {
  name: '${namespaceName}/${queueName}'
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: queue
  name: guid(queue.id, principalId, roleDefinitionId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
