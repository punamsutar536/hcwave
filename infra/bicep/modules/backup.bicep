// -----------------------------------------------------------------------------
// Azure Backup vault with policies for AKS (cluster state + persistent
// volumes) and operational backup of the reports storage. PostgreSQL uses its
// own automated backups (retention set in postgres.bicep).
// AKS backup also needs the cluster extension + trusted access, installed by
// scripts/install-cluster-addons.sh.
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}

@description('Days to keep daily AKS backups.')
param aksRetentionDays int = 30

@description('Days to keep operational blob backups.')
param blobRetentionDays int = 30

resource vault 'Microsoft.DataProtection/backupVaults@2024-04-01' = {
  name: '${namePrefix}-bvault'
  location: location
  tags: tags
  identity: { type: 'SystemAssigned' }
  properties: {
    storageSettings: [ { datastoreType: 'VaultStore', type: 'ZoneRedundant' } ]
    securitySettings: { softDeleteSettings: { state: 'On', retentionDurationInDays: 14 } }
  }
}

resource aksPolicy 'Microsoft.DataProtection/backupVaults/backupPolicies@2024-04-01' = {
  parent: vault
  name: 'aks-daily'
  properties: {
    objectType: 'BackupPolicy'
    datasourceTypes: [ 'Microsoft.ContainerService/managedClusters' ]
    policyRules: [
      {
        name: 'BackupDaily'
        objectType: 'AzureBackupRule'
        backupParameters: { objectType: 'AzureBackupParams', backupType: 'Incremental' }
        dataStore: { dataStoreType: 'OperationalStore', objectType: 'DataStoreInfoBase' }
        trigger: {
          objectType: 'ScheduleBasedTriggerContext'
          schedule: { repeatingTimeIntervals: [ 'R/2026-01-01T20:30:00+00:00/P1D' ], timeZone: 'India Standard Time' }
          taggingCriteria: [
            { isDefault: true, tagInfo: { tagName: 'Default' }, taggingPriority: 99 }
          ]
        }
      }
      {
        name: 'Default'
        objectType: 'AzureRetentionRule'
        isDefault: true
        lifecycles: [
          {
            deleteAfter: { objectType: 'AbsoluteDeleteOption', duration: 'P${aksRetentionDays}D' }
            sourceDataStore: { dataStoreType: 'OperationalStore', objectType: 'DataStoreInfoBase' }
            targetDataStoreCopySettings: []
          }
        ]
      }
    ]
  }
}

resource blobPolicy 'Microsoft.DataProtection/backupVaults/backupPolicies@2024-04-01' = {
  parent: vault
  name: 'reports-operational'
  properties: {
    objectType: 'BackupPolicy'
    datasourceTypes: [ 'Microsoft.Storage/storageAccounts/blobServices' ]
    policyRules: [
      {
        name: 'Default'
        objectType: 'AzureRetentionRule'
        isDefault: true
        lifecycles: [
          {
            deleteAfter: { objectType: 'AbsoluteDeleteOption', duration: 'P${blobRetentionDays}D' }
            sourceDataStore: { dataStoreType: 'OperationalStore', objectType: 'DataStoreInfoBase' }
            targetDataStoreCopySettings: []
          }
        ]
      }
    ]
  }
}

output vaultId string = vault.id
output vaultPrincipalId string = vault.identity.principalId
output aksPolicyId string = aksPolicy.id
output blobPolicyId string = blobPolicy.id
