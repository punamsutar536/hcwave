// -----------------------------------------------------------------------------
// AKS cluster hardened for patient data:
//  * Entra ID auth + Azure RBAC, local accounts disabled, optional private API
//  * Azure CNI Overlay + Cilium network policy
//  * Workload identity (OIDC issuer) – pods get Entra tokens, no secrets
//  * Key Vault Secrets Store CSI driver, Azure Policy, Defender, Container
//    Insights, KEDA (scales the worker on Service Bus queue length)
//  * Automatic patch upgrades and node image updates
// -----------------------------------------------------------------------------
param name string
param location string
param tags object = {}
param kubernetesVersion string = '1.31'
param nodeSubnetId string
param logAnalyticsWorkspaceId string

@description('Entra group(s) with cluster-admin through Azure RBAC.')
param adminGroupObjectIds array = []

@description('Private API server (recommended for prod; CI then uses `az aks command invoke`).')
param privateCluster bool = false

@description('Authorised public IP ranges for the API server when not private.')
param authorizedIpRanges array = []

param systemNodeVmSize string = 'Standard_D4ds_v5'
param userNodeVmSize string = 'Standard_D4ds_v5'
param systemNodeCount int = 2
param userNodeMinCount int = 2
param userNodeMaxCount int = 6
param availabilityZones array = [ '1', '2', '3' ]

@description('Workload identity resource name + K8s service account allowed to use it.')
param workloadIdentityName string
param workloadNamespace string = 'hcwave'
param workloadServiceAccount string = 'hcwave'

@description('ALB controller identity for Application Gateway for Containers.')
param albControllerIdentityName string = ''

resource cluster 'Microsoft.ContainerService/managedClusters@2024-09-01' = {
  name: name
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  sku: { name: 'Base', tier: 'Standard' }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: name
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      adminGroupObjectIDs: adminGroupObjectIds
    }
    apiServerAccessProfile: {
      enablePrivateCluster: privateCluster
      authorizedIPRanges: privateCluster ? [] : authorizedIpRanges
    }
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      loadBalancerSku: 'standard'
      podCidr: '192.168.0.0/16'
      serviceCidr: '172.16.0.0/16'
      dnsServiceIP: '172.16.0.10'
    }
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        vmSize: systemNodeVmSize
        count: systemNodeCount
        availabilityZones: availabilityZones
        vnetSubnetID: nodeSubnetId
        osType: 'Linux'
        osSKU: 'AzureLinux'
        nodeTaints: [ 'CriticalAddonsOnly=true:NoSchedule' ]
        enableEncryptionAtHost: false
      }
      {
        name: 'apps'
        mode: 'User'
        vmSize: userNodeVmSize
        enableAutoScaling: true
        minCount: userNodeMinCount
        maxCount: userNodeMaxCount
        availabilityZones: availabilityZones
        vnetSubnetID: nodeSubnetId
        osType: 'Linux'
        osSKU: 'AzureLinux'
      }
    ]
    oidcIssuerProfile: { enabled: true }
    securityProfile: {
      workloadIdentity: { enabled: true }
      defender: {
        logAnalyticsWorkspaceResourceId: logAnalyticsWorkspaceId
        securityMonitoring: { enabled: true }
      }
      imageCleaner: { enabled: true, intervalHours: 48 }
    }
    workloadAutoScalerProfile: { keda: { enabled: true } }
    autoUpgradeProfile: {
      upgradeChannel: 'patch'
      nodeOSUpgradeChannel: 'NodeImage'
    }
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: { enableSecretRotation: 'true', rotationPollInterval: '2m' }
      }
      azurepolicy: { enabled: true }
      omsagent: {
        enabled: true
        config: { logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId, useAADAuth: 'true' }
      }
    }
  }
}

resource workloadIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: workloadIdentityName
}

// Lets pods using the `hcwave` service account exchange their token for
// Entra tokens of the workload identity.
resource workloadFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: workloadIdentity
  name: 'aks-${workloadNamespace}-${workloadServiceAccount}'
  properties: {
    issuer: cluster.properties.oidcIssuerProfile.issuerURL
    subject: 'system:serviceaccount:${workloadNamespace}:${workloadServiceAccount}'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
}

resource albIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = if (!empty(albControllerIdentityName)) {
  name: empty(albControllerIdentityName) ? 'unused' : albControllerIdentityName
}

resource albFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(albControllerIdentityName)) {
  parent: albIdentity
  name: 'aks-alb-controller'
  properties: {
    issuer: cluster.properties.oidcIssuerProfile.issuerURL
    subject: 'system:serviceaccount:azure-alb-system:alb-controller-sa'
    audiences: [ 'api://AzureADTokenExchange' ]
  }
  dependsOn: [ workloadFederation ] // federated credentials on one tenant must not race
}

resource diagnostics 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = {
  scope: cluster
  name: 'to-log-analytics'
  properties: {
    workspaceId: logAnalyticsWorkspaceId
    logs: [
      { category: 'kube-audit-admin', enabled: true }
      { category: 'guard', enabled: true }
    ]
    metrics: [ { category: 'AllMetrics', enabled: true } ]
  }
}

output id string = cluster.id
output name string = cluster.name
output principalId string = cluster.identity.principalId
output kubeletPrincipalId string = cluster.properties.identityProfile.kubeletidentity.objectId
output oidcIssuerUrl string = cluster.properties.oidcIssuerProfile.issuerURL
output nodeResourceGroup string = cluster.properties.nodeResourceGroup
