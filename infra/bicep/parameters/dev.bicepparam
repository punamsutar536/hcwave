// Development environment. Secrets/IDs come from the shell environment so
// nothing tenant-specific is committed: export HCWAVE_ADMIN_GROUP_ID etc.
using '../main.bicep'

param environmentName = 'dev'
param location = 'centralindia'
param aiLocation = readEnvironmentVariable('HCWAVE_AI_LOCATION', 'southindia')
param namePrefix = readEnvironmentVariable('HCWAVE_NAME_PREFIX', 'hcw')
param adminGroupObjectId = readEnvironmentVariable('HCWAVE_ADMIN_GROUP_ID', '')
param adminGroupName = readEnvironmentVariable('HCWAVE_ADMIN_GROUP_NAME', 'hcwave-admins')
param operatorPrincipalId = readEnvironmentVariable('HCWAVE_OPERATOR_PRINCIPAL_ID', '')
param alertEmails = [ readEnvironmentVariable('HCWAVE_ALERT_EMAIL', 'ops@example.com') ]

// Cheaper, simpler dev footprint.
param aksPrivateCluster = false
param aksAuthorizedIpRanges = []
param serviceBusSku = 'Premium'
param searchSku = 'basic'
param enableFrontDoor = false
param enableApim = false
param enableBackup = false
param enableDefender = false
param enablePolicy = true
param keyVaultPublicNetworkAccess = 'Enabled'
param acrPublicNetworkAccess = 'Enabled'
param tags = { owner: 'platform-team', costCenter: 'hcwave-dev' }
