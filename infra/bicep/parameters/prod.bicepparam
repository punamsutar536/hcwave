// Production environment (Central India). Private AKS API, zone-redundant
// PostgreSQL with geo-redundant backups, Front Door + WAF, Defender, Policy.
using '../main.bicep'

param environmentName = 'prod'
param location = 'centralindia'
param aiLocation = readEnvironmentVariable('HCWAVE_AI_LOCATION', 'southindia')
param namePrefix = readEnvironmentVariable('HCWAVE_NAME_PREFIX', 'hcw')
param adminGroupObjectId = readEnvironmentVariable('HCWAVE_ADMIN_GROUP_ID', '')
param adminGroupName = readEnvironmentVariable('HCWAVE_ADMIN_GROUP_NAME', 'hcwave-admins')
param operatorPrincipalId = readEnvironmentVariable('HCWAVE_OPERATOR_PRINCIPAL_ID', '')
param alertEmails = [ readEnvironmentVariable('HCWAVE_ALERT_EMAIL', 'ops@example.com') ]
param dnsZoneName = readEnvironmentVariable('HCWAVE_DNS_ZONE', '')

param aksPrivateCluster = true
param postgresHighAvailability = true
param postgresGeoRedundantBackup = true
param serviceBusSku = 'Premium'
param searchSku = 'standard'
param enableFrontDoor = true
param enableApim = true
param apimPublisherEmail = readEnvironmentVariable('HCWAVE_ALERT_EMAIL', 'ops@example.com')
param enableBackup = true
param enableDefender = true
param enablePolicy = true
param enablePowerBiEmbedded = false
param enablePurview = true
param enableDataFactory = true
param keyVaultPublicNetworkAccess = 'Disabled'
param acrPublicNetworkAccess = 'Disabled'
param tags = { owner: 'platform-team', costCenter: 'hcwave-prod', compliance: 'dpdp-nabh' }
