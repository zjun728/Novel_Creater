import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/db/client'

export const useProviderStore = defineStore('provider', () => {
  const providers = ref([])
  const loading = ref(false)
  const loaded = ref(false)
  let loadPromise = null
  const bindingCache = ref({})

  async function loadProviders(force = true) {
    if (loading.value && loadPromise) return loadPromise
    if (loaded.value && !force) return providers.value

    loading.value = true
    loadPromise = api.providers.list()
      .then((list) => {
        providers.value = list || []
        loaded.value = true
        return providers.value
      })
      .catch((e) => {
        console.error('加载Provider列表失败:', e.message)
        throw e
      })
      .finally(() => {
        loading.value = false
        loadPromise = null
      })

    return loadPromise
  }

  async function ensureProvidersLoaded() {
    return loadProviders(false)
  }

  async function addProvider(config) {
    try {
      const provider = await api.providers.create({
        name: config.name,
        providerType: config.providerType || 'openai-compatible',
        baseURL: config.baseURL || '',
        apiKey: config.apiKey || '',
        model: config.model || '',
        stream: config.stream !== false,
        maxContextTokens: config.maxContextTokens || 200000,
        maxOutputTokens: config.maxOutputTokens || 4096,
        temperature: config.temperature ?? 0.8,
        topP: config.topP ?? 0.9,
        supportsJSON: config.supportsJSON !== false,
        supportsStreaming: config.supportsStreaming !== false,
        notes: config.notes || '',
        thinking: config.thinking || null
      })
      providers.value.push(provider)
      loaded.value = true
      return provider
    } catch (e) {
      console.error('添加Provider失败:', e.message)
      throw e
    }
  }

  async function updateProvider(provider) {
    try {
      const updated = await api.providers.update(provider.id, {
        name: provider.name,
        providerType: provider.providerType,
        baseURL: provider.baseURL,
        apiKey: provider.apiKey,
        model: provider.model,
        stream: provider.stream,
        maxContextTokens: provider.maxContextTokens,
        maxOutputTokens: provider.maxOutputTokens,
        temperature: provider.temperature,
        topP: provider.topP,
        supportsJSON: provider.supportsJSON,
        supportsStreaming: provider.supportsStreaming,
        notes: provider.notes,
        thinking: provider.thinking
      })
      const idx = providers.value.findIndex(p => p.id === updated.id)
      if (idx !== -1) providers.value[idx] = updated
    } catch (e) {
      console.error('更新Provider失败:', e.message)
      throw e
    }
  }

  async function deleteProvider(id) {
    try {
      await api.providers.delete(id)
      providers.value = providers.value.filter(p => p.id !== id)
    } catch (e) {
      console.error('删除Provider失败:', e.message)
      throw e
    }
  }

  async function getBindings(projectId) {
    try {
      if (bindingCache.value[projectId]) return bindingCache.value[projectId]
      const bindings = await api.bindings.get(projectId)
      bindingCache.value[projectId] = bindings
      return bindings
    } catch (e) {
      console.error('获取绑定配置失败:', e.message)
      throw e
    }
  }

  async function saveBindings(projectId, bindings) {
    try {
      const result = await api.bindings.save(projectId, bindings)
      bindingCache.value[projectId] = result
      return result
    } catch (e) {
      console.error('保存绑定配置失败:', e.message)
      throw e
    }
  }

  const providersByType = computed(() => {
    const map = {}
    for (const p of providers.value) {
      if (!map[p.providerType]) map[p.providerType] = []
      map[p.providerType].push(p)
    }
    return map
  })

  return {
    providers,
    loading,
    loaded,
    loadProviders,
    ensureProvidersLoaded,
    addProvider,
    updateProvider,
    deleteProvider,
    getBindings,
    saveBindings,
    providersByType
  }
})
