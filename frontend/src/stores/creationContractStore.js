import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api } from '../api/db/client.js'
import { contractReady as isContractReady } from '../domain/creation-contract/wizard-state.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

function isMissingDraft(error) {
  return Number(error?.status) === 404 || error?.code === 'ContractNotFound'
}

function isConflict(error) {
  return Number(error?.status) === 409
}

function missingDraftError() {
  const error = new Error('请先保存创作契约草稿')
  error.code = 'contract_draft_missing'
  return error
}

export const useCreationContractStore = defineStore('creationContract', () => {
  const projectId = ref('')
  const draft = shallowRef(null)
  const previewResult = shallowRef(null)
  const confirmed = shallowRef(null)
  const head = shallowRef(null)
  const engineBatch = shallowRef(null)
  const conflict = shallowRef(null)
  const error = shallowRef(null)
  const requiresReload = ref(false)
  const hasUnsavedChanges = ref(false)

  const loading = ref(false)
  const saving = ref(false)
  const previewing = ref(false)
  const confirming = ref(false)
  const cloning = ref(false)
  const reconciling = ref(false)

  const loadGuard = createLatestRequestGuard()
  const saveGuard = createLatestRequestGuard()
  const previewGuard = createLatestRequestGuard()
  const confirmGuard = createLatestRequestGuard()
  const cloneGuard = createLatestRequestGuard()
  const reconcileGuard = createLatestRequestGuard()
  const guards = [
    loadGuard, saveGuard, previewGuard, confirmGuard, cloneGuard,
    reconcileGuard,
  ]
  const confirmCommands = new Map()
  let contractStateGeneration = 0

  const lastSavedStage = computed(() => (
    draft.value?.draftStage || draft.value?.draft?.draftStage || null
  ))

  const activeReadiness = computed(() => {
    if (draft.value) return previewResult.value
    return confirmed.value || head.value
  })

  const readiness = computed(() => {
    const source = activeReadiness.value
    return {
      ready: source?.contractReady === true,
      reasons: Array.isArray(source?.reasons) ? [...source.reasons] : [],
      seedRevisionId: source?.seedRef?.revisionId ?? null,
      seedHash: source?.seedRef?.contentHash ?? null,
      bindingRevision: source?.bindingRef?.revision ?? null,
      bindingHash: source?.bindingRef?.contentHash ?? null,
    }
  })
  const contractReady = computed(() => isContractReady({ readiness: readiness.value }))
  const readinessReasons = computed(() => [...readiness.value.reasons])
  const providerOutcomeUnknown = computed(() => (
    engineBatch.value?.status === 'outcome_unknown'
  ))

  function clearProjectState() {
    draft.value = null
    previewResult.value = null
    confirmed.value = null
    head.value = null
    engineBatch.value = null
    conflict.value = null
    error.value = null
    requiresReload.value = false
    hasUnsavedChanges.value = false
    loading.value = false
    saving.value = false
    previewing.value = false
    confirming.value = false
    cloning.value = false
    reconciling.value = false
    confirmCommands.clear()
  }

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (!normalized) throw new TypeError('projectId is required')
    if (projectId.value !== normalized) {
      contractStateGeneration += 1
      for (const guard of guards) guard.invalidate()
      clearProjectState()
      projectId.value = normalized
    }
    return normalized
  }

  function current(guard, generation, targetProjectId) {
    return projectId.value === targetProjectId && guard.isCurrent(generation)
  }

  function markUnsavedChanges() {
    hasUnsavedChanges.value = true
  }

  function discardUnsavedChanges() {
    hasUnsavedChanges.value = false
  }

  function currentContractState(guard, generation, targetProjectId, stateGeneration) {
    return current(guard, generation, targetProjectId)
      && contractStateGeneration === stateGeneration
  }

  function recordFailure(
    failure,
    guard,
    generation,
    targetProjectId,
    stateGeneration = null,
  ) {
    if (!current(guard, generation, targetProjectId)) return
    if (stateGeneration !== null && contractStateGeneration !== stateGeneration) return
    const safe = publicError(failure)
    error.value = safe
    if (isConflict(failure)) {
      conflict.value = safe
      requiresReload.value = true
    }
  }

  async function readDraft(targetProjectId) {
    try {
      return await api.contracts.draft.get(targetProjectId)
    } catch (failure) {
      if (isMissingDraft(failure)) return null
      throw failure
    }
  }

  async function load(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = loadGuard.begin()
    const stateGeneration = ++contractStateGeneration
    loading.value = true
    try {
      const [loadedDraft, loadedHead] = await Promise.all([
        readDraft(targetProjectId),
        api.contracts.head(targetProjectId),
      ])
      if (currentContractState(loadGuard, generation, targetProjectId, stateGeneration)) {
        draft.value = loadedDraft
        head.value = loadedHead
        confirmed.value = null
        previewResult.value = null
        conflict.value = null
        error.value = null
        requiresReload.value = false
        hasUnsavedChanges.value = false
      }
      return { draft: loadedDraft, head: loadedHead }
    } catch (failure) {
      recordFailure(failure, loadGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(loadGuard, generation, targetProjectId)) loading.value = false
    }
  }

  async function saveDraft(nextProjectId, values) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = saveGuard.begin()
    const stateGeneration = ++contractStateGeneration
    const expectedDraftVersion = Number(draft.value?.draftVersion || 0)
    saving.value = true
    try {
      const saved = await api.contracts.draft.save(targetProjectId, {
        expectedDraftVersion,
        draft: values,
      })
      if (currentContractState(saveGuard, generation, targetProjectId, stateGeneration)) {
        draft.value = saved
        previewResult.value = null
        confirmed.value = null
        conflict.value = null
        error.value = null
        requiresReload.value = false
        hasUnsavedChanges.value = false
      }
      return saved
    } catch (failure) {
      recordFailure(failure, saveGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(saveGuard, generation, targetProjectId)) saving.value = false
    }
  }

  async function preview(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = previewGuard.begin()
    const stateGeneration = contractStateGeneration
    previewing.value = true
    try {
      const result = await api.contracts.preview(targetProjectId)
      if (currentContractState(previewGuard, generation, targetProjectId, stateGeneration)) {
        previewResult.value = result
        error.value = null
      }
      return result
    } catch (failure) {
      recordFailure(failure, previewGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(previewGuard, generation, targetProjectId)) previewing.value = false
    }
  }

  async function confirm(nextProjectId, { idempotencyKey } = {}) {
    const targetProjectId = enterProject(nextProjectId)
    const commandKey = `${targetProjectId}:${String(idempotencyKey || '')}`
    let command = confirmCommands.get(commandKey)
    if (!command) {
      if (!draft.value) throw missingDraftError()
      command = {
        idempotencyKey,
        expectedDraftVersion: draft.value.draftVersion,
        expectedDraftHash: draft.value.contentHash,
      }
      confirmCommands.set(commandKey, command)
    }

    const generation = confirmGuard.begin()
    const stateGeneration = ++contractStateGeneration
    confirming.value = true
    try {
      const result = await api.contracts.confirm(targetProjectId, command)
      if (currentContractState(confirmGuard, generation, targetProjectId, stateGeneration)) {
        confirmed.value = result
        head.value = result
        draft.value = null
        previewResult.value = null
        conflict.value = null
        error.value = null
        requiresReload.value = false
        hasUnsavedChanges.value = false
      }
      return result
    } catch (failure) {
      recordFailure(failure, confirmGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(confirmGuard, generation, targetProjectId)) confirming.value = false
    }
  }

  async function cloneRevision(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = cloneGuard.begin()
    const stateGeneration = ++contractStateGeneration
    cloning.value = true
    try {
      const result = await api.contracts.clone(targetProjectId)
      if (currentContractState(cloneGuard, generation, targetProjectId, stateGeneration)) {
        draft.value = result
        previewResult.value = null
        confirmed.value = null
        conflict.value = null
        error.value = null
        requiresReload.value = false
        hasUnsavedChanges.value = false
        confirmCommands.clear()
      }
      return result
    } catch (failure) {
      recordFailure(failure, cloneGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(cloneGuard, generation, targetProjectId)) cloning.value = false
    }
  }

  async function reconcileBatch(nextProjectId, batchId) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = reconcileGuard.begin()
    reconciling.value = true
    try {
      const result = await api.storyEngines.reconcile(targetProjectId, batchId)
      if (current(reconcileGuard, generation, targetProjectId)) {
        engineBatch.value = result
        error.value = null
      }
      return result
    } catch (failure) {
      recordFailure(failure, reconcileGuard, generation, targetProjectId)
      throw failure
    } finally {
      if (current(reconcileGuard, generation, targetProjectId)) reconciling.value = false
    }
  }

  return {
    projectId,
    draft,
    previewResult,
    confirmed,
    head,
    engineBatch,
    conflict,
    error,
    requiresReload,
    hasUnsavedChanges,
    loading,
    saving,
    previewing,
    confirming,
    cloning,
    reconciling,
    lastSavedStage,
    readiness,
    contractReady,
    readinessReasons,
    providerOutcomeUnknown,
    markUnsavedChanges,
    discardUnsavedChanges,
    load,
    saveDraft,
    preview,
    confirm,
    cloneRevision,
    reconcileBatch,
  }
})
