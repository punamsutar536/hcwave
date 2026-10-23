// -----------------------------------------------------------------------------
// Azure Front Door Premium + WAF (optional global edge in front of AGC):
// TLS for branded domains, OWASP/bot managed rules, rate limits on webhooks
// and report links, optional country allow-list.
// -----------------------------------------------------------------------------
param namePrefix string
param tags object = {}

@description('Origin host name (the AGC frontend FQDN).')
param originHostName string

@description('Countries allowed to reach the platform (ISO codes); [] = all.')
param allowedCountries array = [ 'IN' ]

@description('Requests per minute per client IP for /webhooks and /r paths.')
param rateLimitPerMinute int = 300

@allowed([ 'Prevention', 'Detection' ])
param wafMode string = 'Prevention'

resource waf 'Microsoft.Network/FrontDoorWebApplicationFirewallPolicies@2024-02-01' = {
  name: replace('${namePrefix}fdwaf', '-', '')
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
  properties: {
    policySettings: { enabledState: 'Enabled', mode: wafMode, requestBodyCheck: 'Enabled' }
    managedRules: {
      managedRuleSets: [
        { ruleSetType: 'Microsoft_DefaultRuleSet', ruleSetVersion: '2.1', ruleSetAction: 'Block' }
        { ruleSetType: 'Microsoft_BotManagerRuleSet', ruleSetVersion: '1.1', ruleSetAction: 'Block' }
      ]
    }
    customRules: {
      rules: concat(
        [
          {
            name: 'RateLimitPublicPaths'
            priority: 10
            ruleType: 'RateLimitRule'
            rateLimitDurationInMinutes: 1
            rateLimitThreshold: rateLimitPerMinute
            action: 'Block'
            matchConditions: [
              { matchVariable: 'RequestUri', operator: 'RegEx', matchValue: [ '/(webhooks|r)/' ] }
            ]
          }
        ],
        empty(allowedCountries) ? [] : [
          {
            name: 'GeoAllowList'
            priority: 20
            ruleType: 'MatchRule'
            action: 'Block'
            matchConditions: [
              { matchVariable: 'RemoteAddr', operator: 'GeoMatch', negateCondition: true, matchValue: allowedCountries }
            ]
          }
        ]
      )
    }
  }
}

resource profile 'Microsoft.Cdn/profiles@2024-02-01' = {
  name: '${namePrefix}-afd'
  location: 'global'
  tags: tags
  sku: { name: 'Premium_AzureFrontDoor' }
}

resource endpoint 'Microsoft.Cdn/profiles/afdEndpoints@2024-02-01' = {
  parent: profile
  name: '${namePrefix}-edge'
  location: 'global'
  properties: { enabledState: 'Enabled' }
}

resource originGroup 'Microsoft.Cdn/profiles/originGroups@2024-02-01' = {
  parent: profile
  name: 'agc'
  properties: {
    loadBalancingSettings: { sampleSize: 4, successfulSamplesRequired: 3 }
    healthProbeSettings: { probePath: '/healthz', probeRequestType: 'GET', probeProtocol: 'Https', probeIntervalInSeconds: 60 }
  }
}

resource origin 'Microsoft.Cdn/profiles/originGroups/origins@2024-02-01' = {
  parent: originGroup
  name: 'agc-frontend'
  properties: {
    hostName: originHostName
    originHostHeader: originHostName
    httpsPort: 443
    priority: 1
    weight: 1000
    enforceCertificateNameCheck: true
  }
}

resource route 'Microsoft.Cdn/profiles/afdEndpoints/routes@2024-02-01' = {
  parent: endpoint
  name: 'all'
  properties: {
    originGroup: { id: originGroup.id }
    supportedProtocols: [ 'Https' ]
    httpsRedirect: 'Enabled'
    forwardingProtocol: 'HttpsOnly'
    patternsToMatch: [ '/*' ]
    linkToDefaultDomain: 'Enabled'
  }
  dependsOn: [ origin ]
}

resource securityPolicy 'Microsoft.Cdn/profiles/securityPolicies@2024-02-01' = {
  parent: profile
  name: 'waf'
  properties: {
    parameters: {
      type: 'WebApplicationFirewall'
      wafPolicy: { id: waf.id }
      associations: [ { domains: [ { id: endpoint.id } ], patternsToMatch: [ '/*' ] } ]
    }
  }
}

output endpointHostName string = endpoint.properties.hostName
output profileId string = profile.id
