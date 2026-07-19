import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'


export const TASK_KEYS = Object.freeze([
  'seed', 'planning', 'writing', 'audit',
  'summary', 'extraction', 'polish', 'market',
])


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
  if (
    byTask.size !== TASK_KEYS.length
    || TASK_KEYS.some(taskKey => !byTask.has(taskKey))
  ) {
    throw new TypeError('Bindings must contain each task key exactly once')
  }
  return TASK_KEYS.map(taskKey => ({
    taskKey,
    providerId: byTask.get(taskKey).providerId ?? null,
  }))
}


export const useModelBindingStore = defineStore('model-binding', () => {
  const binding = ref(null)
  const bindingStatus = ref(null)
  const bindingProjectId = ref(null)
  const bindingCache = ref({})
  const bindingStatusCache = ref({})
  const bindingsLoading = ref(false)
  const bindingStatusLoading = ref(false)
  const bindingSaving = ref(false)
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
      const status = normalizeBinding(
        await api.bindings.status(projectId),
        { status: true },
      )
      if (bindingStatusGuard.isCurrent(generation)) {
        bindingStatusCache.value[projectId] = status
        bindingStatus.value = status
      }
      return status
    } finally {
      if (bindingStatusGuard.isCurrent(generation)) {
        bindingStatusLoading.value = false
      }
    }
  }

  async function replaceBindings(projectId, { expectedRevision, entries }) {
    const canonicalEntries = canonicalBindingEntries(entries)
    const signature = JSON.stringify({
      projectId,
      expectedRevision,
      entries: canonicalEntries,
    })
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

  const bindingLoading = computed(
    () => bindingsLoading.value || bindingStatusLoading.value,
  )
  const bindingComplete = computed(
    () => bindingStatus.value?.bindingComplete === true,
  )
  const bindingReasons = computed(
    () => bindingStatus.value?.reasons || [],
  )
  const bindingReady = computed(() => (
    bindingStatus.value?.bindingReady === true
    && bindingReasons.value.length === 0
  ))

  return {
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
    getBindings,
    getBindingStatus,
    replaceBindings,
    invalidateBindingStatuses,
    invalidateBindings,
  }
})
