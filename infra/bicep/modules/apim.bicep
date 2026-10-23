// -----------------------------------------------------------------------------
// Azure API Management as an AI gateway (optional): one place for LLM rate
// limits / token quotas, usage metrics per hospital and auditing. APIM calls
// Azure OpenAI with its managed identity, so the backend never holds an
// OpenAI key (it uses an APIM subscription key or Entra token instead).
// -----------------------------------------------------------------------------
param namePrefix string
param location string
param tags object = {}
param publisherEmail string
param publisherName string = 'Hospital AI'
param subnetId string
param appInsightsId string
@secure()
param appInsightsConnectionString string

@description('Azure OpenAI endpoint (https://<account>.openai.azure.com/).')
param openAiEndpoint string

@allowed([ 'StandardV2', 'PremiumV2', 'Premium' ])
param sku string = 'StandardV2'

@description('Token budget per minute per hospital (X-Hospital-Id header) or per subscription.')
param tokensPerMinute int = 20000

resource apim 'Microsoft.ApiManagement/service@2024-05-01' = {
  name: '${namePrefix}-apim'
  location: location
  tags: tags
  sku: { name: sku, capacity: 1 }
  identity: { type: 'SystemAssigned' }
  properties: {
    publisherEmail: publisherEmail
    publisherName: publisherName
    virtualNetworkType: 'External'
    virtualNetworkConfiguration: { subnetResourceId: subnetId }
  }
}

resource logger 'Microsoft.ApiManagement/service/loggers@2024-05-01' = {
  parent: apim
  name: 'appinsights'
  properties: {
    loggerType: 'applicationInsights'
    resourceId: appInsightsId
    credentials: { connectionString: appInsightsConnectionString }
  }
}

resource backend 'Microsoft.ApiManagement/service/backends@2024-05-01' = {
  parent: apim
  name: 'azure-openai'
  properties: {
    protocol: 'http'
    url: '${openAiEndpoint}openai'
  }
}

resource api 'Microsoft.ApiManagement/service/apis@2024-05-01' = {
  parent: apim
  name: 'azure-openai'
  properties: {
    displayName: 'Azure OpenAI (AI gateway)'
    path: 'openai'
    protocols: [ 'https' ]
    subscriptionRequired: true
    subscriptionKeyParameterNames: { header: 'api-key', query: 'subscription-key' }
    serviceUrl: '${openAiEndpoint}openai'
  }
}

resource catchAll 'Microsoft.ApiManagement/service/apis/operations@2024-05-01' = [for method in [ 'POST', 'GET' ]: {
  parent: api
  name: 'all-${toLower(method)}'
  properties: { displayName: '${method} /*', method: method, urlTemplate: '/*' }
}]

resource policy 'Microsoft.ApiManagement/service/apis/policies@2024-05-01' = {
  parent: api
  name: 'policy'
  properties: {
    format: 'rawxml'
    // Multi-line Bicep strings cannot interpolate, so the budget is substituted.
    value: replace('''
<policies>
  <inbound>
    <base />
    <set-backend-service backend-id="azure-openai" />
    <authentication-managed-identity resource="https://cognitiveservices.azure.com" />
    <llm-token-limit counter-key="@(context.Request.Headers.GetValueOrDefault(&quot;X-Hospital-Id&quot;, context.Subscription.Id))" tokens-per-minute="__TOKENS_PER_MINUTE__" estimate-prompt-tokens="false" remaining-tokens-header-name="x-remaining-tokens" />
    <llm-emit-token-metric namespace="hcwave">
      <dimension name="Hospital" value="@(context.Request.Headers.GetValueOrDefault(&quot;X-Hospital-Id&quot;, &quot;unknown&quot;))" />
      <dimension name="Subscription ID" />
    </llm-emit-token-metric>
  </inbound>
  <backend><base /></backend>
  <outbound><base /></outbound>
  <on-error><base /></on-error>
</policies>
''', '__TOKENS_PER_MINUTE__', string(tokensPerMinute))
  }
  dependsOn: [ backend ]
}

resource diagnostics 'Microsoft.ApiManagement/service/apis/diagnostics@2024-05-01' = {
  parent: api
  name: 'applicationinsights'
  properties: {
    loggerId: logger.id
    alwaysLog: 'allErrors'
    sampling: { samplingType: 'fixed', percentage: 100 }
    // Never log request/response bodies: prompts can contain patient data.
    frontend: { request: { body: { bytes: 0 } }, response: { body: { bytes: 0 } } }
    backend: { request: { body: { bytes: 0 } }, response: { body: { bytes: 0 } } }
  }
}

resource product 'Microsoft.ApiManagement/service/products@2024-05-01' = {
  parent: apim
  name: 'hcwave'
  properties: { displayName: 'hcwave backend', subscriptionRequired: true, approvalRequired: false, state: 'published' }
}

resource productApi 'Microsoft.ApiManagement/service/products/apis@2024-05-01' = {
  parent: product
  name: api.name
}

resource subscription 'Microsoft.ApiManagement/service/subscriptions@2024-05-01' = {
  parent: apim
  name: 'hcwave-backend'
  properties: { displayName: 'hcwave backend', scope: product.id, state: 'active' }
}

output name string = apim.name
output gatewayUrl string = apim.properties.gatewayUrl
output principalId string = apim.identity.principalId
