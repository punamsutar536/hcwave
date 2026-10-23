// -----------------------------------------------------------------------------
// Grants a role on one subnet (e.g. AKS identity → Network Contributor so it
// can place the internal load balancer for the job API in the node subnet).
// -----------------------------------------------------------------------------
param vnetName string
param subnetName string
param principalId string
param roleDefinitionId string

resource subnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: '${vnetName}/${subnetName}'
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: subnet
  name: guid(subnet.id, principalId, roleDefinitionId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleDefinitionId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
