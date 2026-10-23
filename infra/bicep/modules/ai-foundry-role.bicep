// -----------------------------------------------------------------------------
// Grants "Cognitive Services OpenAI User" on the Foundry account to one
// principal (used for the APIM AI gateway identity).
// -----------------------------------------------------------------------------
param accountName string
param principalId string

var openAiUserRole = '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'

resource account 'Microsoft.CognitiveServices/accounts@2025-04-01-preview' existing = {
  name: accountName
}

resource assignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, principalId, openAiUserRole)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', openAiUserRole)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
