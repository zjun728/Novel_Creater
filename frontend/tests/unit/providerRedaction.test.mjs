import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  buildProviderCreatePayload,
  buildProviderUpdatePayload,
  normalizePublicProvider,
} from '../../src/stores/providerStore.js'

test('public provider state retains configuration flags without inventing secrets', () => {
  const provider = normalizePublicProvider({
    id: 'provider-1',
    name: '联通云',
    providerType: 'openai-compatible',
    model: 'deepseek-v4-flash',
    hasKey: true,
    hasBaseURL: true,
    thinking: {
      credentials: { API_KEY: 'nested-secret', region: 'local' },
      transport: { 'base-url': 'nested-secret', mode: 'safe' },
    },
  })

  assert.equal(provider.hasKey, true)
  assert.equal(provider.hasBaseURL, true)
  assert.equal(Object.hasOwn(provider, 'apiKey'), false)
  assert.equal(Object.hasOwn(provider, 'baseURL'), false)
  assert.deepEqual(provider.thinking, {
    credentials: { region: 'local' },
    transport: { mode: 'safe' },
  })
})

test('blank secret inputs preserve stored values and clear flags never enter transport', () => {
  const preserved = buildProviderUpdatePayload({
    name: '联通云',
    model: 'deepseek-v4-flash',
    apiKey: '   ',
    baseURL: '',
  })
  assert.equal(Object.hasOwn(preserved, 'apiKey'), false)
  assert.equal(Object.hasOwn(preserved, 'baseURL'), false)
  assert.equal(Object.hasOwn(preserved, 'clearApiKey'), false)
  assert.equal(Object.hasOwn(preserved, 'clearBaseURL'), false)

  const cleared = buildProviderUpdatePayload({
    name: '联通云',
    model: 'deepseek-v4-flash',
    clearApiKey: true,
    clearBaseURL: true,
  })
  assert.equal(Object.hasOwn(cleared, 'clearApiKey'), false)
  assert.equal(Object.hasOwn(cleared, 'clearBaseURL'), false)
  assert.equal(Object.hasOwn(cleared, 'apiKey'), false)
  assert.equal(Object.hasOwn(cleared, 'baseURL'), false)

  const immutableType = buildProviderUpdatePayload({ providerType: 'anthropic' })
  assert.equal(Object.hasOwn(immutableType, 'providerType'), false)
  const created = buildProviderCreatePayload({
    providerType: 'anthropic', apiKey: 'request-only', baseURL: 'https://provider.example/v1',
  })
  assert.equal(created.providerType, 'anthropic')
})

test('the active API client contains no retired or secret-bearing endpoint', async () => {
  const source = await readFile(new URL('../../src/api/db/client.js', import.meta.url), 'utf8')
  for (const forbidden of [
    'includeApiKeys', '/export/full', '/import/full', '/canon-facts',
    '/settings/change-events', '/versions/', '/temp-draft',
    '/chapter-beat-plan', '/story-blocks', '/correction-tasks', '/ai/',
  ]) {
    assert.equal(source.includes(forbidden), false, `retired client endpoint remains: ${forbidden}`)
  }
  assert.doesNotMatch(source, /['"`]\/chapters(?:[/?#]|['"`])/)
})
