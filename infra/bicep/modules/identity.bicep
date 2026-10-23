// -----------------------------------------------------------------------------
// User-assigned managed identities. No keys in code: workloads authenticate
// to every Azure service with these identities (AKS workload identity,
// Logic Apps and Functions managed identity).
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}

resource workload 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id-workload'
  location: location
  tags: tags
}

resource logicApp 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id-logicapp'
  location: location
  tags: tags
}

resource functions 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id-functions'
  location: location
  tags: tags
}

// Used by the Application Gateway for Containers ALB controller in AKS.
resource albController 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${namePrefix}-id-alb-controller'
  location: location
  tags: tags
}

output workloadId string = workload.id
output workloadName string = workload.name
output workloadClientId string = workload.properties.clientId
output workloadPrincipalId string = workload.properties.principalId
output logicAppId string = logicApp.id
output logicAppClientId string = logicApp.properties.clientId
output logicAppPrincipalId string = logicApp.properties.principalId
output functionsId string = functions.id
output functionsClientId string = functions.properties.clientId
output functionsPrincipalId string = functions.properties.principalId
output albControllerId string = albController.id
output albControllerName string = albController.name
output albControllerClientId string = albController.properties.clientId
output albControllerPrincipalId string = albController.properties.principalId
