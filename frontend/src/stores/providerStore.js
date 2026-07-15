import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
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
  'hasBaseURL', 'createdAt', 'updatedAt',
]

const EDITABLE_PROVIDER_FIELDS = [
  'name', 'providerType', 'model', 'enabled', 'sortOrder', 'stream',
  'maxContextTokens', 'maxOutputTokens', 'temperature', 'topP',
  'supportsJSON', 'supportsStreaming', 'notes', 'thinking',
]

const SENSITIVE_RESPONSE_KEYS = new Set(['apiKey', 'api_key', 'baseURL', 'base_url'])

function stripSensitiveResponseKeys(value) {
  if (Array.isArray(value)) return value.map(stripSensitiveResponseKeys)
  if (!value || typeof value !== 'object') return value
  const result = {}
  for (const [key, item] of Object.entries(value)) {
    if (!SENSITIVE_RESPONSE_KEYS.has(key)) result[key] = stripSensitiveResponseKeys(item)
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

  if (value.clearApiKey === true) payload.clearApiKey = true
  else if (typeof value.apiKey === 'string' && value.apiKey.trim()) payload.apiKey = value.apiKey.trim()

  if (value.clearBaseURL === true) payload.clearBaseURL = true
  else if (typeof value.baseURL === 'string' && value.baseURL.trim()) payload.baseURL = value.baseURL.trim()

  return payload
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
  let loadPromise = null
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
    loadPromise = api.providers.list()
      .then(rows => {
        providers.value = (rows || []).map(normalizePublicProvider)
        loaded.value = true
        return providers.value
      })
      .finally(() => {
        loading.value = false
        loadPromise = null
      })
    return loadPromise
  }

  async function addProvider(config) {
    const payload = buildProviderUpdatePayload(config)
    const created = normalizePublicProvider(await api.providers.create(payload))
    providers.value.push(created)
    loaded.value = true
    return created
  }

  async function updateProvider(provider) {
    const updated = normalizePublicProvider(
      await api.providers.update(provider.id, buildProviderUpdatePayload(provider)),
    )
    const index = providers.value.findIndex(item => item.id === updated.id)
    if (index !== -1) providers.value[index] = updated
    invalidateBindingStatuses()
    return updated
  }

  async function deleteProvider(providerId) {
    await api.providers.delete(providerId)
    providers.value = providers.value.filter(provider => provider.id !== providerId)
    invalidateBindingStatuses()
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
    activateBindingProject(projectId)
    const writeEpoch = bindingProjectEpoch
    const result = normalizeBinding(await api.bindings.replace(projectId, {
      expectedRevision,
      entries: canonicalBindingEntries(entries),
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
    bindingComplete,
    bindingReady,
    bindingReasons,
    providersByType,
    loadProviders,
    addProvider,
    updateProvider,
    deleteProvider,
    getBindings,
    getBindingStatus,
    replaceBindings,
    invalidateBindingStatuses,
    invalidateBindings,
  }
})
