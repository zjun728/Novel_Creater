import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '../api/db/client.js'

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

export function normalizePublicProvider(value = {}) {
  const provider = {}
  for (const field of PUBLIC_PROVIDER_FIELDS) {
    if (value[field] !== undefined) provider[field] = value[field]
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
  const bindingStatusCache = ref({})
  let loadPromise = null

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
    return updated
  }

  async function deleteProvider(providerId) {
    await api.providers.delete(providerId)
    providers.value = providers.value.filter(provider => provider.id !== providerId)
  }

  async function getBindings(projectId) {
    if (!projectId) return null
    return api.bindings.get(projectId)
  }

  async function getBindingStatus(projectId, { force = false } = {}) {
    if (!projectId) return null
    if (!force && bindingStatusCache.value[projectId]) return bindingStatusCache.value[projectId]
    const status = await api.bindings.status(projectId)
    bindingStatusCache.value[projectId] = status
    return status
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

  return {
    providers,
    loading,
    loaded,
    providersByType,
    loadProviders,
    addProvider,
    updateProvider,
    deleteProvider,
    getBindings,
    getBindingStatus,
  }
})
