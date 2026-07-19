import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import { api } from '../api/db/client.js'

const PUBLIC_PROVIDER_FIELDS = [
  'id', 'name', 'providerType', 'model', 'enabled', 'sortOrder', 'stream',
  'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking', 'hasKey',
  'hasBaseURL', 'lifecycleStatus', 'revision', 'ready', 'createdAt', 'updatedAt',
]

const EDITABLE_PROVIDER_FIELDS = [
  'name', 'model', 'enabled', 'sortOrder', 'stream',
  'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking',
]

const SENSITIVE_RESPONSE_KEYS = new Set([
  'apikey', 'baseurl', 'authorization', 'token', 'password',
])

function isSensitiveResponseKey(key) {
  return typeof key === 'string'
    && SENSITIVE_RESPONSE_KEYS.has(key.toLowerCase().replaceAll('_', '').replaceAll('-', ''))
}

function stripSensitiveResponseKeys(value) {
  if (Array.isArray(value)) return value.map(stripSensitiveResponseKeys)
  if (!value || typeof value !== 'object') return value
  const result = {}
  for (const [key, item] of Object.entries(value)) {
    if (!isSensitiveResponseKey(key)) result[key] = stripSensitiveResponseKeys(item)
  }
  return result
}

export function normalizePublicProvider(value = {}) {
  const provider = {}
  for (const field of PUBLIC_PROVIDER_FIELDS) {
    if (value[field] !== undefined) provider[field] = stripSensitiveResponseKeys(value[field])
  }
  provider.hasKey = Boolean(value.hasKey)
  provider.hasBaseURL = Boolean(value.hasBaseURL)
  return provider
}

export function buildProviderUpdatePayload(value = {}) {
  const payload = {}
  for (const field of EDITABLE_PROVIDER_FIELDS) {
    if (value[field] !== undefined) payload[field] = value[field]
  }

  if (typeof value.apiKey === 'string' && value.apiKey.trim()) payload.apiKey = value.apiKey.trim()

  if (typeof value.baseURL === 'string' && value.baseURL.trim()) payload.baseURL = value.baseURL.trim()

  return payload
}

export function buildProviderCreatePayload(value = {}) {
  const payload = buildProviderUpdatePayload(value)
  if (typeof value.providerType === 'string' && value.providerType.trim()) {
    payload.providerType = value.providerType.trim()
  }
  if (!payload.apiKey || !payload.baseURL) {
    throw new TypeError('新增 Provider 必须输入 API Key 与 Base URL')
  }
  return payload
}

function clearRequestSecrets(payload) {
  if (!payload || typeof payload !== 'object') return
  if (Object.hasOwn(payload, 'apiKey')) payload.apiKey = ''
  if (Object.hasOwn(payload, 'baseURL')) payload.baseURL = ''
}

function idempotencyKey() {
  return uuidv4()
}

function normalizeConnectionResult(value = {}) {
  const code = typeof value.code === 'string' ? value.code : 'provider_failed'
  const messages = {
    connected: '连接成功',
    provider_timeout: '连接超时',
    provider_unreachable: '无法连接 Provider',
    provider_rejected: 'Provider 拒绝连接',
    provider_unconfigured: 'Provider 未配置',
    provider_unsupported: '不支持的 Provider 类型',
    provider_failed: '连接测试失败',
  }
  const publicCode = Object.hasOwn(messages, code) ? code : 'provider_failed'
  const latency = Number(value.latencyMs)
  return {
    ok: value.ok === true && publicCode === 'connected',
    code: publicCode,
    latencyMs: Number.isFinite(latency)
      ? Math.min(30000, Math.max(0, Math.trunc(latency)))
      : 0,
    publicMessage: messages[publicCode],
  }
}

export const useProviderStore = defineStore('provider', () => {
  const providers = ref([])
  const loading = ref(false)
  const loaded = ref(false)
  let loadPromise = null
  let providerMutationEpoch = 0

  async function loadProviders(force = true) {
    if (loading.value && loadPromise) return loadPromise
    if (loaded.value && !force) return providers.value
    loading.value = true
    const mutationEpoch = providerMutationEpoch
    const request = api.providers.list()
      .then(rows => {
        const normalized = (rows || []).map(normalizePublicProvider)
        if (providerMutationEpoch === mutationEpoch) {
          providers.value = normalized
          loaded.value = true
        }
        return normalized
      })
      .finally(() => {
        if (loadPromise === request) {
          loading.value = false
          loadPromise = null
        }
      })
    loadPromise = request
    return request
  }

  async function addProvider(config) {
    const payload = buildProviderCreatePayload(config)
    payload.idempotencyKey = idempotencyKey()
    try {
      const created = normalizePublicProvider(await api.providers.create(payload))
      providerMutationEpoch += 1
      providers.value.push(created)
      loaded.value = true
      return created
    } finally {
      clearRequestSecrets(payload)
    }
  }

  async function updateProvider(providerOrId, maybeChanges) {
    const providerId = typeof providerOrId === 'string' ? providerOrId : providerOrId?.id
    const changes = maybeChanges || providerOrId || {}
    const current = providers.value.find(provider => provider.id === providerId)
    const payload = buildProviderUpdatePayload(changes)
    payload.expectedRevision = changes.expectedRevision ?? changes.revision ?? current?.revision ?? 0
    payload.idempotencyKey = idempotencyKey()
    try {
      const updated = normalizePublicProvider(
        await api.providers.update(providerId, payload),
      )
      providerMutationEpoch += 1
      const index = providers.value.findIndex(item => item.id === updated.id)
      if (index !== -1) providers.value[index] = updated
      return updated
    } finally {
      clearRequestSecrets(payload)
    }
  }

  async function deleteProvider(providerOrId, expectedRevision) {
    const providerId = typeof providerOrId === 'string' ? providerOrId : providerOrId?.id
    const current = providers.value.find(provider => provider.id === providerId)
    const revision = expectedRevision ?? providerOrId?.revision ?? current?.revision ?? 0
    await api.providers.delete(providerId, {
      expectedRevision: revision,
      idempotencyKey: idempotencyKey(),
    })
    providerMutationEpoch += 1
    providers.value = providers.value.filter(provider => provider.id !== providerId)
  }

  async function clearApiKey(providerId, expectedRevision) {
    const updated = normalizePublicProvider(
      await api.providers.clearApiKey(providerId, {
        expectedRevision,
        idempotencyKey: idempotencyKey(),
      }),
    )
    providerMutationEpoch += 1
    const index = providers.value.findIndex(provider => provider.id === updated.id)
    if (index !== -1) providers.value[index] = updated
    return updated
  }

  async function testConnection(providerId) {
    return normalizeConnectionResult(
      await api.providers.testConnection(providerId),
    )
  }

  const providersByType = computed(() => {
    const result = {}
    for (const provider of providers.value) {
      const type = provider.providerType || 'unknown'
      if (!result[type]) result[type] = []
      result[type].push(provider)
    }
    return result
  })
  const availableProviders = computed(() => providers.value.filter(provider => (
    provider.ready === true
    && provider.enabled === true
    && provider.hasKey === true
    && provider.hasBaseURL === true
  )))

  return {
    providers,
    loading,
    loaded,
    availableProviders,
    providersByType,
    loadProviders,
    addProvider,
    updateProvider,
    deleteProvider,
    clearApiKey,
    testConnection,
  }
})
