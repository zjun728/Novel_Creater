import assert from 'node:assert/strict'
import test from 'node:test'

import {
  buildProviderCreatePayload,
  buildProviderUpdatePayload,
  normalizePublicProvider,
} from '../../../frontend/src/stores/providerStore.js'


test('formal provider payloads preserve secrets only in explicit request bodies', () => {
  const update = buildProviderUpdatePayload({
    name: 'Provider',
    providerType: 'anthropic',
    apiKey: '   ',
    baseURL: '',
    clearApiKey: true,
    clearBaseURL: true,
  })
  assert.deepEqual(update, { name: 'Provider' })

  const create = buildProviderCreatePayload({
    name: 'Provider',
    providerType: 'openai-compatible',
    apiKey: 'request-only',
    baseURL: 'https://provider.example/v1',
  })
  assert.equal(create.providerType, 'openai-compatible')
  assert.equal(create.apiKey, 'request-only')
})

test('public provider normalization recursively removes secret field variants', () => {
  const normalized = normalizePublicProvider({
    id: 'provider-1',
    name: 'Provider',
    providerType: 'openai-compatible',
    model: 'model-1',
    hasKey: true,
    hasBaseURL: true,
    apiKey: 'top-level-secret',
    baseURL: 'https://private.example/v1',
    thinking: {
      credentials: { API_KEY: 'nested-secret', region: 'local' },
      transport: { 'base-url': 'nested-secret', mode: 'safe' },
    },
  })
  const encoded = JSON.stringify(normalized)
  assert.equal(encoded.includes('secret'), false)
  assert.equal(encoded.includes('private.example'), false)
  assert.deepEqual(normalized.thinking, {
    credentials: { region: 'local' },
    transport: { mode: 'safe' },
  })
  assert.equal(normalized.hasKey, true)
  assert.equal(normalized.hasBaseURL, true)
})
