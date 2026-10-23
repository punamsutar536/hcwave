// -----------------------------------------------------------------------------
// Monitoring: Log Analytics (logs), Application Insights (APM + Foundry LLM
// tracing) and an action group for operational alerts.
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}

@description('Days to retain logs (DPDP/NABH audits usually need ≥ 90 days hot).')
param retentionInDays int = 90

@description('Email addresses that receive operational alerts.')
param alertEmails array = []

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-log'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
    features: { enableLogAccessUsingOnlyResourcePermissions: true }
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${namePrefix}-appi'
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    // Local (key) auth off: ingestion uses Entra ID where supported.
    DisableLocalAuth: false
    IngestionMode: 'LogAnalytics'
  }
}

resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${namePrefix}-ag-ops'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'hcwave-ops'
    enabled: true
    emailReceivers: [for (email, i) in alertEmails: {
      name: 'email-${i}'
      emailAddress: email
      useCommonAlertSchema: true
    }]
  }
}

// Failed Logic Apps runs, unhandled API exceptions and dead-lettered events
// are the signals that a reminder/report/feedback job stopped working.
resource failedJobsAlert 'Microsoft.Insights/scheduledQueryRules@2023-03-15-preview' = {
  name: '${namePrefix}-alert-app-errors'
  location: location
  tags: tags
  properties: {
    displayName: 'hcwave: application errors'
    severity: 2
    enabled: true
    evaluationFrequency: 'PT15M'
    windowSize: 'PT15M'
    scopes: [ appInsights.id ]
    criteria: {
      allOf: [
        {
          query: 'union exceptions, (requests | where success == false and resultCode startswith "5") | summarize count()'
          timeAggregation: 'Total'
          metricMeasureColumn: 'count_'
          operator: 'GreaterThan'
          threshold: 10
          failingPeriods: { numberOfEvaluationPeriods: 1, minFailingPeriodsToAlert: 1 }
        }
      ]
    }
    actions: { actionGroups: [ actionGroup.id ] }
  }
}

output workspaceId string = workspace.id
output workspaceName string = workspace.name
output appInsightsId string = appInsights.id
output appInsightsConnectionString string = appInsights.properties.ConnectionString
output actionGroupId string = actionGroup.id
