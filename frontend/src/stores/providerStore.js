import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api/db/client'

export const useProviderStore = defineStore('provider', () => {
  const providers = ref([])
  const loading = ref(false)
  const loaded = ref(false)
  let loadPromise = null
  const bindingCache = ref({})
  const bindingStatusCache = ref({})
  const lastModelResolution = ref({})

  const bindingKeys = [
    'writingModelId',
    'brainstormModelId',
    'outlineModelId',
    'auditModelId',
    'summaryModelId',
    'extractionModelId',
    'marketModelId',
    'polishModelId'
  ]

  const snakeBindingKeys = {
    writingModelId: 'writing_model_id',
    brainstormModelId: 'brainstorm_model_id',
    outlineModelId: 'outline_model_id',
    auditModelId: 'audit_model_id',
    summaryModelId: 'summary_model_id',
    extractionModelId: 'extraction_model_id',
    marketModelId: 'market_model_id',
    polishModelId: 'polish_model_id'
  }

  function emptyBindings() {
    return Object.fromEntries(bindingKeys.map(key => [key, null]))
  }

  function normalizeBindings(raw) {
    const normalized = emptyBindings()
    if (!raw) return normalized

    for (const key of bindingKeys) {
      const value = raw[key] ?? raw[snakeBindingKeys[key]] ?? null
      normalized[key] = value || null
    }
    return normalized
  }

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
      if (!projectId) return emptyBindings()
      if (bindingCache.value[projectId]) return bindingCache.value[projectId]
      const bindings = await api.bindings.get(projectId)
      const normalized = normalizeBindings(bindings)
      bindingCache.value[projectId] = normalized
      return normalized
    } catch (e) {
      console.error('获取绑定配置失败:', e.message)
      throw e
    }
  }

  async function getBindingStatus(projectId) {
    try {
      if (!projectId) {
        return {
          projectId: '',
          hasBinding: false,
          inherited: false,
          message: '当前项目未配置任务模型映射：请先配置模型。'
        }
      }
      const status = await api.bindings.status(projectId)
      bindingStatusCache.value[projectId] = status
      if (status?.binding) {
        bindingCache.value[projectId] = normalizeBindings(status.binding)
      }
      return status
    } catch (e) {
      console.error('获取模型映射状态失败:', e.message)
      throw e
    }
  }

  async function saveBindings(projectId, bindings) {
    try {
      const payload = normalizeBindings(bindings)
      const result = await api.bindings.save(projectId, payload)
      const normalized = normalizeBindings(result)
      bindingCache.value[projectId] = normalized
      delete bindingStatusCache.value[projectId]
      return normalized
    } catch (e) {
      console.error('保存绑定配置失败:', e.message)
      throw e
    }
  }

  function hasAnyBinding(bindings) {
    return bindingKeys.some(key => Boolean(bindings?.[key]))
  }

  function describeProvider(provider) {
    if (!provider) return ''
    return `${provider.name || provider.id}${provider.model ? ` / ${provider.model}` : ''}`
  }

  async function resolveTaskProvider({
    projectId = '',
    bindingKeys: requestedKeys = [],
    providerId = null,
    taskName = 'AI 任务',
    allowFallback = false
  } = {}) {
    await ensureProvidersLoaded()

    if (providerId) {
      const explicitProvider = providers.value.find(provider => provider.id === providerId)
      if (!explicitProvider) throw new Error('指定的模型配置不存在或已被删除')
      lastModelResolution.value[taskName] = {
        taskName,
        providerId: explicitProvider.id,
        modelName: explicitProvider.model || '',
        providerName: explicitProvider.name || '',
        source: 'explicit',
        message: `使用指定模型 ${describeProvider(explicitProvider)}`
      }
      return { ...explicitProvider, projectId, taskName }
    }

    const bindings = projectId ? await getBindings(projectId) : emptyBindings()
    for (const key of requestedKeys) {
      const modelId = bindings?.[key]
      if (!modelId) continue
      const mappedProvider = providers.value.find(provider => provider.id === modelId)
      if (mappedProvider) {
        lastModelResolution.value[taskName] = {
          taskName,
          projectId,
          bindingKey: key,
          providerId: mappedProvider.id,
          modelName: mappedProvider.model || '',
          providerName: mappedProvider.name || '',
          source: 'project_binding',
          message: `使用当前项目任务模型映射：${describeProvider(mappedProvider)}`
        }
        return { ...mappedProvider, projectId, taskName, bindingKey: key }
      }
    }

    if (hasAnyBinding(bindings)) {
      throw new Error(`当前项目任务模型映射指向的模型不存在：${taskName}。请先在设置页重新配置模型。`)
    }

    if (allowFallback) {
      const fallbackProvider = providers.value[0]
      if (!fallbackProvider) throw new Error('请先在设置中配置模型')
      const message = `当前项目未配置任务模型映射，使用兜底模型 ${describeProvider(fallbackProvider)}`
      lastModelResolution.value[taskName] = {
        taskName,
        projectId,
        providerId: fallbackProvider.id,
        modelName: fallbackProvider.model || '',
        providerName: fallbackProvider.name || '',
        source: 'fallback_first_provider',
        usedFallback: true,
        message
      }
      console.warn(message)
      return { ...fallbackProvider, projectId, taskName, usedFallback: true }
    }

    throw new Error(`当前项目未配置任务模型映射：${taskName}。请先在设置页配置模型。`)
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
    lastModelResolution,
    loadProviders,
    ensureProvidersLoaded,
    emptyBindings,
    normalizeBindings,
    getBindingStatus,
    resolveTaskProvider,
    addProvider,
    updateProvider,
    deleteProvider,
    getBindings,
    saveBindings,
    providersByType
  }
})
