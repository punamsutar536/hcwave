// -----------------------------------------------------------------------------
// Application Gateway for Containers (AGC) with a WAF policy – the HTTPS front
// door for WhatsApp webhooks, report links and staff screens. The ALB
// controller inside AKS programs it from Gateway API resources (Helm chart).
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}
param subnetId string

@description('VNet and subnet names of the AGC subnet (for a subnet-scoped role).')
param vnetName string
param subnetName string = 'snet-agc'

@description('ALB controller identity principal (gets config rights on AGC).')
param albControllerPrincipalId string

@description('WAF mode: Prevention blocks, Detection only logs.')
@allowed([ 'Prevention', 'Detection' ])
param wafMode string = 'Prevention'

resource waf 'Microsoft.Network/ApplicationGatewayWebApplicationFirewallPolicies@2024-05-01' = {
  name: '${namePrefix}-agc-waf'
  location: location
  tags: tags
  properties: {
    policySettings: {
      state: 'Enabled'
      mode: wafMode
      requestBodyCheck: true
      maxRequestBodySizeInKb: 128
      fileUploadLimitInMb: 10
    }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1' }
      ]
    }
  }
}

resource trafficController 'Microsoft.ServiceNetworking/trafficControllers@2025-01-01' = {
  name: '${namePrefix}-agc'
  location: location
  tags: tags
  properties: {}
}

resource association 'Microsoft.ServiceNetworking/trafficControllers/associations@2025-01-01' = {
  parent: trafficController
  name: 'aks'
  location: location
  properties: {
    associationType: 'subnets'
    subnet: { id: subnetId }
  }
}

resource frontend 'Microsoft.ServiceNetworking/trafficControllers/frontends@2025-01-01' = {
  parent: trafficController
  name: 'public'
  location: location
  properties: {}
}

resource securityPolicy 'Microsoft.ServiceNetworking/trafficControllers/securityPolicies@2025-01-01' = {
  parent: trafficController
  name: 'waf'
  location: location
  properties: {
    wafPolicy: { id: waf.id }
  }
}

// "AppGw for Containers Configuration Manager" on the AGC resource and
// "Network Contributor" on its subnet, for the in-cluster ALB controller.
var agcConfigManagerRole = 'fbc52c3f-28ad-4303-a892-8a056630b8f1'
var networkContributorRole = '4d97b98b-1d4f-4787-a291-c67834d212e7'

resource configManager 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: trafficController
  name: guid(trafficController.id, albControllerPrincipalId, agcConfigManagerRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', agcConfigManagerRole)
    principalId: albControllerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource agcSubnet 'Microsoft.Network/virtualNetworks/subnets@2024-05-01' existing = {
  name: '${vnetName}/${subnetName}'
}

resource networkContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: agcSubnet
  name: guid(agcSubnet.id, albControllerPrincipalId, networkContributorRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributorRole)
    principalId: albControllerPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output id string = trafficController.id
output name string = trafficController.name
output frontendName string = frontend.name
output frontendFqdn string = frontend.properties.fqdn
output securityPolicyId string = securityPolicy.id
output wafPolicyId string = waf.id
