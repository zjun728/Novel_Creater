import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import {
  defaultBaseUrls,
  providerPresets,
  providerTypeOptions,
} from '../../src/api/ai/providerPresets.js'
import {
  buildProviderCreatePayload,
  buildProviderUpdatePayload,
  normalizePublicProvider,
  useProviderStore,
} from '../../src/stores/providerStore.js'

const FORBIDDEN_KEYS = new Set([
  'apiKey', 'api_key', 'baseURL', 'base_url',
  'authorization', 'token', 'password',
])

function assertPublic(value) {
  if (Array.isArray(value)) {
    for (const item of value) assertPublic(item)
    return
  }
  if (!value || typeof value !== 'object') return
  for (const [key, item] of Object.entries(value)) {
    assert.equal(FORBIDDEN_KEYS.has(key), false, `forbidden public key: ${key}`)
    assertPublic(item)
  }
}

function publicProvider(overrides = {}) {
  return {
    id: 'provider-1',
    name: '联通云',
    providerType: 'openai-compatible',
    model: 'deepseek-v4-flash',
    enabled: true,
    hasKey: true,
    hasBaseURL: true,
    lifecycleStatus: 'active',
    revision: 4,
    ...overrides,
  }
}

test('selectable provider presets expose only generation-capable types', () => {
  assert.deepEqual(
    providerTypeOptions.map(option => option.value),
    ['openai-compatible'],
  )
  assert.equal(Object.hasOwn(defaultBaseUrls, 'anthropic'), false)
  assert.equal(
    providerPresets.some(preset => preset.providerType === 'anthropic'),
    false,
  )
  assert.equal(
    providerPresets.find(preset => preset.name === '联通云-DeepSeek-V4-Flash')
      .providerType,
    'openai-compatible',
  )
})

test('public provider state recursively strips every forbidden response key', () => {
  const provider = normalizePublicProvider({
    ...publicProvider(),
    apiKey: 'top-level-secret',
    base_url: 'top-level-url',
    thinking: {
      authorization: 'nested-secret',
      token: 'nested-token',
      password: 'nested-password',
      credentials: { API_KEY: 'case-secret', region: 'local' },
      transport: { 'base-url': 'case-url', mode: 'safe' },
    },
  })

  assertPublic(provider)
  assert.equal(provider.hasKey, true)
  assert.equal(provider.hasBaseURL, true)
  assert.equal(provider.revision, 4)
  assert.equal(provider.lifecycleStatus, 'active')
  assert.deepEqual(provider.thinking, {
    credentials: { region: 'local' },
    transport: { mode: 'safe' },
  })
})

test('blank secret inputs preserve stored values and clear flags never enter update transport', () => {
  const preserved = buildProviderUpdatePayload({
    name: '联通云',
    model: 'deepseek-v4-flash',
    apiKey: '   ',
    baseURL: '',
    clearApiKey: true,
    clearBaseURL: true,
  })
  assertPublic(preserved)
  assert.equal(Object.hasOwn(preserved, 'clearApiKey'), false)
  assert.equal(Object.hasOwn(preserved, 'clearBaseURL'), false)

  const immutableType = buildProviderUpdatePayload({ providerType: 'anthropic' })
  assert.equal(Object.hasOwn(immutableType, 'providerType'), false)
  const created = buildProviderCreatePayload({
    providerType: 'anthropic',
    apiKey: 'request-only',
    baseURL: 'https://provider.example/v1',
  })
  assert.equal(created.providerType, 'anthropic')
})

test('Pinia stores only public projections and clears request-local secret payloads in finally', async t => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  const captured = []
  const originalCreate = api.providers.create
  const originalUpdate = api.providers.update
  t.after(() => {
    api.providers.create = originalCreate
    api.providers.update = originalUpdate
  })
  api.providers.create = async payload => {
    captured.push(payload)
    return publicProvider({ id: 'created', revision: 1 })
  }
  api.providers.update = async (_id, payload) => {
    captured.push(payload)
    throw new Error('safe failure')
  }

  await store.addProvider({
    name: '联通云',
    providerType: 'openai-compatible',
    model: 'deepseek-v4-flash',
    apiKey: 'request-create-secret',
    baseURL: 'https://request-create.example/v1',
  })
  await assert.rejects(
    store.updateProvider('created', {
      expectedRevision: 1,
      model: 'model-two',
      apiKey: 'request-update-secret',
      baseURL: 'https://request-update.example/v1',
    }),
    /safe failure/,
  )

  assertPublic(store.providers)
  for (const payload of captured) {
    assert.equal(payload.apiKey, '')
    assert.equal(payload.baseURL, '')
  }
})

test('clear updates only the public projection and connection feedback is never retained in Pinia', async t => {
  setActivePinia(createPinia())
  const store = useProviderStore()
  store.providers = [publicProvider()]
  const calls = []
  const originalClear = api.providers.clearApiKey
  const originalTest = api.providers.testConnection
  t.after(() => {
    api.providers.clearApiKey = originalClear
    api.providers.testConnection = originalTest
  })
  api.providers.clearApiKey = async (id, body) => {
    calls.push(['clear', id, body])
    return publicProvider({
      enabled: false,
      hasKey: false,
      hasBaseURL: true,
      lifecycleStatus: 'unconfigured',
      revision: 5,
    })
  }
  api.providers.testConnection = async id => {
    calls.push(['test', id])
    return {
      ok: true,
      code: 'connected',
      latencyMs: 12,
      publicMessage: '连接成功',
    }
  }

  const testResult = await store.testConnection('provider-1')
  api.providers.testConnection = async () => ({
    ok: false,
    code: 'provider_unsupported',
    latencyMs: 0,
    publicMessage: 'unsafe upstream detail',
  })
  const unsupportedResult = await store.testConnection('provider-1')
  await store.clearApiKey('provider-1', 4)

  assert.deepEqual(testResult, {
    ok: true,
    code: 'connected',
    latencyMs: 12,
    publicMessage: '连接成功',
  })
  assert.deepEqual(unsupportedResult, {
    ok: false,
    code: 'provider_unsupported',
    latencyMs: 0,
    publicMessage: '不支持的 Provider 类型',
  })
  assert.equal(store.providers[0].hasKey, false)
  assert.equal(store.providers[0].hasBaseURL, true)
  assert.equal(store.providers[0].revision, 5)
  assert.equal(Object.hasOwn(store, 'connectionResult'), false)
  assert.equal(Object.hasOwn(store, 'connectionFeedback'), false)
  assert.equal(calls[0][0], 'test')
  assert.equal(calls[1][0], 'clear')
  assert.equal(calls[1][2].expectedRevision, 4)
  assert.match(calls[1][2].idempotencyKey, /^[A-Za-z0-9._:-]{8,64}$/)
})

test('the active API client exposes only backend Provider profile commands', async () => {
  const source = await readFile(new URL('../../src/api/db/client.js', import.meta.url), 'utf8')
  const providerStart = source.indexOf('  providers: {')
  const providerEnd = source.indexOf('  applicationSettings: {', providerStart)
  assert.ok(providerStart >= 0 && providerEnd > providerStart)
  const providerSource = source.slice(providerStart, providerEnd)
  assert.match(providerSource, /\/providers\/\$\{segment\(providerId\)\}\/test-connection/)
  assert.match(providerSource, /\/providers\/\$\{segment\(providerId\)\}\/clear-api-key/)
  for (const forbidden of [
    'includeApiKeys', '/export/full', '/import/full', '/canon-facts',
    '/settings/change-events', '/versions/', '/temp-draft',
    '/chapter-beat-plan', '/story-blocks', '/correction-tasks', '/ai/',
  ]) {
    assert.equal(providerSource.includes(forbidden), false, `retired Provider endpoint remains: ${forbidden}`)
  }
  assert.doesNotMatch(providerSource, /['"`]\/chapters(?:[/?#]|['"`])/)
})
