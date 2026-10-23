// -----------------------------------------------------------------------------
// Subscription-level security and compliance:
//  * Microsoft Defender for Cloud plans (containers, databases, storage,
//    Key Vault, ARM, AI services)
//  * Azure Policy: allowed locations (India), AKS pod security baseline,
//    and the Microsoft cloud security benchmark audit initiative
// -----------------------------------------------------------------------------
targetScope = 'subscription'

param enableDefender bool = true
param enablePolicy bool = true

@description('Regions resources may be created in (data residency).')
param allowedLocations array = [ 'centralindia', 'southindia', 'westindia', 'global' ]

@description('Resource group the policies are assigned to.')
param resourceGroupName string

var defenderPlans = [
  'Containers'
  'OpenSourceRelationalDatabases'
  'StorageAccounts'
  'KeyVaults'
  'Arm'
  'AI'
]

@batchSize(1)
resource plans 'Microsoft.Security/pricings@2024-01-01' = [for plan in (enableDefender ? defenderPlans : []): {
  name: plan
  properties: { pricingTier: 'Standard' }
}]

module rgPolicies 'security-rg-policies.bicep' = if (enablePolicy) {
  name: 'hcwave-policies'
  scope: resourceGroup(resourceGroupName)
  params: { allowedLocations: allowedLocations }
}
