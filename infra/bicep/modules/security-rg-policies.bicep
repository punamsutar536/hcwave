// -----------------------------------------------------------------------------
// Policy assignments scoped to the platform resource group.
// -----------------------------------------------------------------------------
param allowedLocations array

// Built-in definition / initiative IDs.
var allowedLocationsPolicy = '/providers/Microsoft.Authorization/policyDefinitions/e56962a6-4747-49cd-b67b-bf8b01975c4c'
var aksPodSecurityBaseline = '/providers/Microsoft.Authorization/policySetDefinitions/a8640138-9b0a-4a28-b8cb-1666c838647d'
var cloudSecurityBenchmark = '/providers/Microsoft.Authorization/policySetDefinitions/1f3afdf9-d0c9-4c3d-847f-89da613e70a8'

resource locations 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'hcwave-allowed-locations'
  properties: {
    displayName: 'hcwave: resources only in India regions'
    policyDefinitionId: allowedLocationsPolicy
    parameters: { listOfAllowedLocations: { value: allowedLocations } }
    enforcementMode: 'Default'
  }
}

resource podSecurity 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'hcwave-aks-pod-baseline'
  properties: {
    displayName: 'hcwave: Kubernetes pod security baseline'
    policyDefinitionId: aksPodSecurityBaseline
    parameters: { effect: { value: 'deny' } }
    enforcementMode: 'Default'
  }
}

resource benchmark 'Microsoft.Authorization/policyAssignments@2024-04-01' = {
  name: 'hcwave-mcsb-audit'
  properties: {
    displayName: 'hcwave: Microsoft cloud security benchmark (audit)'
    policyDefinitionId: cloudSecurityBenchmark
    enforcementMode: 'Default'
  }
}
