// -----------------------------------------------------------------------------
// Azure DNS zone for branded links (reports.<domain>, staff.<domain>,
// api.<domain>) pointing at Front Door or the AGC frontend.
// -----------------------------------------------------------------------------
param zoneName string
param tags object = {}

@description('Target host for the CNAME records (Front Door endpoint or AGC FQDN).')
param targetHostName string

@description('Record names to create, e.g. [ "reports", "staff", "api" ].')
param recordNames array = [ 'reports', 'staff', 'api' ]

resource zone 'Microsoft.Network/dnsZones@2018-05-01' = {
  name: zoneName
  location: 'global'
  tags: tags
}

resource records 'Microsoft.Network/dnsZones/CNAME@2018-05-01' = [for record in recordNames: {
  parent: zone
  name: record
  properties: { TTL: 300, CNAMERecord: { cname: targetHostName } }
}]

output nameServers array = zone.properties.nameServers
