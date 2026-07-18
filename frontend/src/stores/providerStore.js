import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { v4 as uuidv4 } from 'uuid'
import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

export const TASK_KEYS = Object.freeze([
  'seed', 'planning', 'writing', 'audit',
  'summary', 'extraction', 'polish', 'market',
])

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

function normalizeBindingItem(value = {}) {
  return {
    taskKey: value.taskKey,
    resolutionStatus: value.resolutionStatus,
    providerId: value.providerId ?? null,
    providerNameSnapshot: value.providerNameSnapshot ?? null,
    modelNameSnapshot: value.modelNameSnapshot ?? null,
  }
}

function normalizeBinding(value = {}, { status = false } = {}) {
  const result = {
    projectId: value.projectId,
    revision: value.revision,
    contentHash: value.contentHash,
    sourceProjectId: value.sourceProjectId ?? null,
    items: Array.isArray(value.items) ? value.items.map(normalizeBindingItem) : [],
  }
  if (status) {
    result.bindingComplete = value.bindingComplete === true
    result.bindingReady = value.bindingReady === true
    result.reasons = Array.isArray(value.reasons) ? [...value.reasons] : []
  }
  return result
}

function canonicalBindingEntries(entries) {
  if (!Array.isArray(entries) || entries.length !== TASK_KEYS.length) {
    throw new TypeError('Bindings must contain each task key exactly once')
  }
  const byTask = new Map(entries.map(entry => [entry?.taskKey, entry]))
  if (byTask.size !== TASK_KEYS.length || TASK_KEYS.some(taskKey => !byTask.has(taskKey))) {
    throw new TypeError('Bindings must contain each task key exactly once')
  }
  return TASK_KEYS.map(taskKey => ({
    taskKey,
    providerId: byTask.get(taskKey).providerId ?? null,
  }))
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
  const binding = ref(null)
  const bindingStatus = ref(null)
  const bindingProjectId = ref(null)
  const bindingCache = ref({})
  const bindingStatusCache = ref({})
  const bindingsLoading = ref(false)
  const bindingStatusLoading = ref(false)
  const bindingSaving = ref(false)
  let loadPromise = null
  let providerMutationEpoch = 0
  let bindingSavePromise = null
  let bindingSaveSignature = ''
  let bindingProjectEpoch = 0
  const bindingGuard = createLatestRequestGuard()
  const bindingStatusGuard = createLatestRequestGuard()

  function activateBindingProject(projectId) {
    if (bindingProjectId.value === projectId) return
    bindingGuard.invalidate()
    bindingStatusGuard.invalidate()
    bindingProjectEpoch += 1
    bindingProjectId.value = projectId
    binding.value = bindingCache.value[projectId] || null
    bindingStatus.value = bindingStatusCache.value[projectId] || null
    bindingsLoading.value = false
    bindingStatusLoading.value = false
  }

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
      invalidateBindingStatuses()
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
    invalidateBindingStatuses()
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
    invalidateBindingStatuses()
    return updated
  }

  async function testConnection(providerId) {
    return normalizeConnectionResult(
      await api.providers.testConnection(providerId),
    )
  }

  async function getBindings(projectId, { force = false } = {}) {
    if (!projectId) return null
    activateBindingProject(projectId)
    const generation = bindingGuard.begin()
    if (!force && bindingCache.value[projectId]) {
      binding.value = bindingCache.value[projectId]
      bindingsLoading.value = false
      return binding.value
    }
    bindingsLoading.value = true
    try {
      const result = normalizeBinding(await api.bindings.get(projectId))
      if (bindingGuard.isCurrent(generation)) {
        bindingCache.value[projectId] = result
        binding.value = result
      }
      return result
    } finally {
      if (bindingGuard.isCurrent(generation)) bindingsLoading.value = false
    }
  }

  async function getBindingStatus(projectId, { force = false } = {}) {
    if (!projectId) return null
    activateBindingProject(projectId)
    const generation = bindingStatusGuard.begin()
    if (!force && bindingStatusCache.value[projectId]) {
      bindingStatus.value = bindingStatusCache.value[projectId]
      bindingStatusLoading.value = false
      return bindingStatus.value
    }
    bindingStatusLoading.value = true
    try {
      const status = normalizeBinding(await api.bindings.status(projectId), { status: true })
      if (bindingStatusGuard.isCurrent(generation)) {
        bindingStatusCache.value[projectId] = status
        bindingStatus.value = status
      }
      return status
    } finally {
      if (bindingStatusGuard.isCurrent(generation)) bindingStatusLoading.value = false
    }
  }

  async function replaceBindings(projectId, { expectedRevision, entries }) {
    const canonicalEntries = canonicalBindingEntries(entries)
    const signature = JSON.stringify({ projectId, expectedRevision, entries: canonicalEntries })
    if (bindingSavePromise) {
      if (signature === bindingSaveSignature) return bindingSavePromise
      throw new Error('另一份模型绑定正在保存，请等待结果明确后再操作')
    }

    activateBindingProject(projectId)
    const writeEpoch = bindingProjectEpoch
    bindingSaving.value = true
    bindingSaveSignature = signature
    bindingSavePromise = (async () => {
      const result = normalizeBinding(await api.bindings.replace(projectId, {
        expectedRevision,
        entries: canonicalEntries,
      }))
      bindingCache.value[projectId] = result
      const statuses = { ...bindingStatusCache.value }
      delete statuses[projectId]
      bindingStatusCache.value = statuses

      if (
        bindingProjectId.value !== projectId
        || bindingProjectEpoch !== writeEpoch
      ) return result

      bindingGuard.invalidate()
      bindingsLoading.value = false
      binding.value = result
      bindingStatusGuard.invalidate()
      bindingStatus.value = null
      bindingStatusLoading.value = false
      return result
    })()

    try {
      return await bindingSavePromise
    } finally {
      bindingSavePromise = null
      bindingSaveSignature = ''
      bindingSaving.value = false
    }
  }

  function invalidateBindingStatuses() {
    bindingStatusGuard.invalidate()
    bindingStatusCache.value = {}
    bindingStatus.value = null
    bindingStatusLoading.value = false
  }

  function invalidateBindings(projectId = null) {
    bindingGuard.invalidate()
    bindingStatusGuard.invalidate()
    bindingProjectEpoch += 1
    if (projectId) {
      const bindings = { ...bindingCache.value }
      const statuses = { ...bindingStatusCache.value }
      delete bindings[projectId]
      delete statuses[projectId]
      bindingCache.value = bindings
      bindingStatusCache.value = statuses
    } else {
      bindingCache.value = {}
      bindingStatusCache.value = {}
    }
    binding.value = null
    bindingStatus.value = null
    bindingProjectId.value = null
    bindingsLoading.value = false
    bindingStatusLoading.value = false
  }

  const bindingLoading = computed(() => bindingsLoading.value || bindingStatusLoading.value)
  const bindingComplete = computed(() => bindingStatus.value?.bindingComplete === true)
  const bindingReasons = computed(() => bindingStatus.value?.reasons || [])
  const bindingReady = computed(() => (
    bindingStatus.value?.bindingReady === true && bindingReasons.value.length === 0
  ))

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
    binding,
    bindingStatus,
    bindingProjectId,
    bindingCache,
    bindingStatusCache,
    bindingLoading,
    bindingSaving,
    bindingComplete,
    bindingReady,
    bindingReasons,
    availableProviders,
    providersByType,
    loadProviders,
    addProvider,
    updateProvider,
    deleteProvider,
    clearApiKey,
    testConnection,
    getBindings,
    getBindingStatus,
    replaceBindings,
    invalidateBindingStatuses,
    invalidateBindings,
  }
})
