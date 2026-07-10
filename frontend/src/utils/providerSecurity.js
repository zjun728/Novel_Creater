const providerUpdateFields = [
  'name',
  'providerType',
  'baseURL',
  'model',
  'stream',
  'maxContextTokens',
  'maxOutputTokens',
  'temperature',
  'topP',
  'supportsJSON',
  'supportsStreaming',
  'notes',
  'thinking'
]

export function buildProviderUpdatePayload(provider = {}) {
  const payload = {}

  for (const field of providerUpdateFields) {
    if (provider[field] !== undefined) payload[field] = provider[field]
  }

  if (typeof provider.apiKey === 'string' && provider.apiKey.length > 0) {
    payload.apiKey = provider.apiKey
  }

  return payload
}

export function isProviderConfigured(provider) {
  return Boolean(provider?.hasApiKey && provider?.model)
}

export function buildSecretFreeExportPath(projectId = '') {
  const params = new URLSearchParams()
  if (projectId) params.set('projectId', projectId)
  const query = params.toString()
  return `/export/full${query ? `?${query}` : ''}`
}
