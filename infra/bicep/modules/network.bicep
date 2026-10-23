// -----------------------------------------------------------------------------
// Virtual network and subnets. Every data and AI service is reached through
// private endpoints in `snet-private-endpoints`; PostgreSQL uses VNet
// integration (delegated subnet); Logic Apps/Functions integrate outbound.
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}

@description('VNet address space.')
param addressPrefix string = '10.20.0.0/16'

@description('Subnet prefixes keyed by role.')
param subnets object = {
  aksNodes: '10.20.0.0/22'
  agc: '10.20.4.0/24'
  privateEndpoints: '10.20.5.0/24'
  postgres: '10.20.6.0/24'
  logicApps: '10.20.7.0/24'
  functions: '10.20.8.0/24'
  apim: '10.20.9.0/24'
}

resource nsgDefault 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-nsg-default'
  location: location
  tags: tags
  properties: { securityRules: [] }
}

// APIM StandardV2 VNet integration needs outbound HTTPS to Azure services.
resource nsgApim 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: '${namePrefix}-nsg-apim'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'allow-storage-outbound'
        properties: {
          priority: 100
          direction: 'Outbound'
          access: 'Allow'
          protocol: 'Tcp'
          sourceAddressPrefix: 'VirtualNetwork'
          sourcePortRange: '*'
          destinationAddressPrefix: 'Storage'
          destinationPortRange: '443'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: '${namePrefix}-vnet'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: [ addressPrefix ] }
    subnets: [
      {
        name: 'snet-aks-nodes'
        properties: {
          addressPrefix: subnets.aksNodes
          networkSecurityGroup: { id: nsgDefault.id }
        }
      }
      {
        // Application Gateway for Containers requires a dedicated, delegated subnet.
        name: 'snet-agc'
        properties: {
          addressPrefix: subnets.agc
          delegations: [ { name: 'agc', properties: { serviceName: 'Microsoft.ServiceNetworking/trafficControllers' } } ]
        }
      }
      {
        name: 'snet-private-endpoints'
        properties: {
          addressPrefix: subnets.privateEndpoints
          privateEndpointNetworkPolicies: 'Enabled'
          networkSecurityGroup: { id: nsgDefault.id }
        }
      }
      {
        name: 'snet-postgres'
        properties: {
          addressPrefix: subnets.postgres
          delegations: [ { name: 'postgres', properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' } } ]
          networkSecurityGroup: { id: nsgDefault.id }
        }
      }
      {
        name: 'snet-logicapps'
        properties: {
          addressPrefix: subnets.logicApps
          delegations: [ { name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
          networkSecurityGroup: { id: nsgDefault.id }
        }
      }
      {
        name: 'snet-functions'
        properties: {
          addressPrefix: subnets.functions
          delegations: [ { name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
          networkSecurityGroup: { id: nsgDefault.id }
        }
      }
      {
        name: 'snet-apim'
        properties: {
          addressPrefix: subnets.apim
          delegations: [ { name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } } ]
          networkSecurityGroup: { id: nsgApim.id }
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output vnetName string = vnet.name
output aksSubnetId string = '${vnet.id}/subnets/snet-aks-nodes'
output agcSubnetId string = '${vnet.id}/subnets/snet-agc'
output privateEndpointSubnetId string = '${vnet.id}/subnets/snet-private-endpoints'
output postgresSubnetId string = '${vnet.id}/subnets/snet-postgres'
output logicAppsSubnetId string = '${vnet.id}/subnets/snet-logicapps'
output functionsSubnetId string = '${vnet.id}/subnets/snet-functions'
output apimSubnetId string = '${vnet.id}/subnets/snet-apim'
