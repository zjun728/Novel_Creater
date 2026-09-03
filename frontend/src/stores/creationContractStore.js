import { defineStore } from 'pinia'
import { computed, ref, shallowRef } from 'vue'

import { api } from '../api/db/client.js'
import {
  contractDraftVersion,
  contractReady as isContractReady,
} from '../domain/creation-contract/wizard-state.js'
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

function readOnlyError() {
  const error = new Error('已归档项目仅供只读查看')
  error.code = 'contract_read_only'
  return error
}

function hydrationError() {
  const error = new Error('创作契约权威状态尚未加载')
  error.code = 'contract_hydration_unknown'
  return error
}

function baselineLockedError() {
  const error = new Error('已确认的创作契约是项目永久基线')
  error.code = 'contract_baseline_locked'
  return error
}

function reloadRequiredError() {
  const error = new Error('创作契约权威状态已变化，请先重新加载并核对')
  error.code = 'contract_reload_required'
  return error
}

export const useCreationContractStore = defineStore('creationContract', () => {
  const projectId = ref('')
  const draft = shallowRef(null)
  const previewResult = shallowRef(null)
  const confirmed = shallowRef(null)
  const head = shallowRef(null)
  const engineBatch = shallowRef(null)
  const styleTrial = shallowRef(null)
  const history = shallowRef([])
  const historyNextBeforeRevision = ref(null)
  const recoverableBatches = shallowRef([])
  const reconcilingBatchIds = ref([])
  const conflict = shallowRef(null)
  const error = shallowRef(null)
  const requiresReload = ref(false)
  const hasUnsavedChanges = ref(false)
  const readOnly = ref(false)
  const headHydrated = ref(false)

  const loading = ref(false)
  const saving = ref(false)
  const previewing = ref(false)
  const confirming = ref(false)
  const engineLoading = ref(false)
  const reconciling = ref(false)
  const styleTrialLoading = ref(false)
  const historyLoading = ref(false)

  const loadGuard = createLatestRequestGuard()
  const saveGuard = createLatestRequestGuard()
  const previewGuard = createLatestRequestGuard()
  const confirmGuard = createLatestRequestGuard()
  const engineGuard = createLatestRequestGuard()
  const styleTrialGuard = createLatestRequestGuard()
  const historyGuard = createLatestRequestGuard()
  const guards = [
    loadGuard, saveGuard, previewGuard, confirmGuard,
    engineGuard, styleTrialGuard, historyGuard,
  ]
  const confirmCommands = new Map()
  const recoverableCommands = new Map()
  let contractStateGeneration = 0

  const lastSavedStage = computed(() => (
    draft.value?.draftStage || draft.value?.draft?.draftStage || null
  ))
  const activeDraftVersion = computed(() => contractDraftVersion(draft.value?.draftVersion))
  const savedStage = computed(() => lastSavedStage.value)

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
  const serverCanConfirm = computed(() => contractReady.value)
  const serverReasons = computed(() => [...readiness.value.reasons])
  const providerOutcomeUnknown = computed(() => (
    engineBatch.value?.status === 'outcome_unknown'
  ))
  const baselineLocked = computed(() => Number(head.value?.revision || 0) > 0)

  function clearProjectState() {
    draft.value = null
    previewResult.value = null
    confirmed.value = null
    head.value = null
    headHydrated.value = false
    engineBatch.value = null
    styleTrial.value = null
    history.value = []
    historyNextBeforeRevision.value = null
    recoverableBatches.value = []
    reconcilingBatchIds.value = []
    conflict.value = null
    error.value = null
    requiresReload.value = false
    hasUnsavedChanges.value = false
    loading.value = false
    saving.value = false
    previewing.value = false
    confirming.value = false
    engineLoading.value = false
    reconciling.value = false
    styleTrialLoading.value = false
    historyLoading.value = false
    confirmCommands.clear()
    recoverableCommands.clear()
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
    if (readOnly.value) return
    // A local edit is a newer state boundary than any read already in flight.
    // Without this generation bump, a late load could clear the dirty flag and
    // silently replace the draft underneath the active form.
    contractStateGeneration += 1
    hasUnsavedChanges.value = true
  }

  function setReadOnly(value) {
    readOnly.value = value === true
    if (readOnly.value) hasUnsavedChanges.value = false
  }

  function assertWritable() {
    if (readOnly.value) throw readOnlyError()
    if (!headHydrated.value) throw hydrationError()
    if (baselineLocked.value) throw baselineLockedError()
    if (requiresReload.value) throw reloadRequiredError()
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

  async function load(nextProjectId, { readOnly: requestedReadOnly = false } = {}) {
    const targetProjectId = enterProject(nextProjectId)
    setReadOnly(requestedReadOnly)
    const generation = loadGuard.begin()
    const stateGeneration = ++contractStateGeneration
    loading.value = true
    headHydrated.value = false
    try {
      const readOnlyLoad = requestedReadOnly === true
      const [loadedDraft, loadedHead, recovery] = readOnlyLoad
        ? [null, await api.contracts.head(targetProjectId), { items: [] }]
        : await Promise.all([
          readDraft(targetProjectId),
          api.contracts.head(targetProjectId),
          api.storyEngines.recoverable(targetProjectId),
        ])
      if (currentContractState(loadGuard, generation, targetProjectId, stateGeneration)) {
        draft.value = loadedDraft
        head.value = loadedHead
        headHydrated.value = true
        styleTrial.value = null
        recoverableBatches.value = Array.isArray(recovery?.items)
          ? recovery.items.map(item => ({ ...item }))
          : []
        confirmed.value = null
        previewResult.value = null
        conflict.value = null
        error.value = null
        requiresReload.value = false
        hasUnsavedChanges.value = false
      }
      return { draft: loadedDraft, head: loadedHead, recovery }
    } catch (failure) {
      recordFailure(failure, loadGuard, generation, targetProjectId, stateGeneration)
      throw failure
    } finally {
      if (current(loadGuard, generation, targetProjectId)) loading.value = false
    }
  }

  async function saveDraft(nextProjectId, values) {
    const targetProjectId = enterProject(nextProjectId)
    assertWritable()
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
        styleTrial.value = null
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
    assertWritable()
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
    assertWritable()
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

  async function runEngineRequest(nextProjectId, operation, { reconcile = false } = {}) {
    const targetProjectId = enterProject(nextProjectId)
    assertWritable()
    const generation = engineGuard.begin()
    engineLoading.value = true
    reconciling.value = reconcile
    try {
      const result = await operation(targetProjectId)
      if (current(engineGuard, generation, targetProjectId)) {
        engineBatch.value = result
        error.value = null
      }
      return result
    } catch (failure) {
      recordFailure(failure, engineGuard, generation, targetProjectId)
      throw failure
    } finally {
      if (current(engineGuard, generation, targetProjectId)) {
        engineLoading.value = false
        reconciling.value = false
      }
    }
  }

  function generateEngineBatch(nextProjectId, command) {
    return runEngineRequest(
      nextProjectId,
      targetProjectId => api.storyEngines.generate(targetProjectId, command),
    )
  }

  function createManualEngineBatch(nextProjectId, command) {
    return runEngineRequest(
      nextProjectId,
      targetProjectId => api.storyEngines.manual(targetProjectId, command),
    )
  }

  function loadEngineBatch(nextProjectId, batchId) {
    return runEngineRequest(
      nextProjectId,
      targetProjectId => api.storyEngines.get(targetProjectId, batchId),
    )
  }

  function reconcileBatch(nextProjectId, batchId) {
    return runEngineRequest(
      nextProjectId,
      targetProjectId => api.storyEngines.reconcile(targetProjectId, batchId),
      { reconcile: true },
    )
  }

  async function reconcileRecoverableBatch(nextProjectId, batchId) {
    const targetProjectId = enterProject(nextProjectId)
    assertWritable()
    const normalizedId = String(batchId || '')
    if (!normalizedId) throw new TypeError('batchId is required')
    if (recoverableCommands.has(normalizedId)) return null
    const stateGeneration = contractStateGeneration
    const commandToken = Symbol(normalizedId)
    recoverableCommands.set(normalizedId, commandToken)
    reconcilingBatchIds.value = [...reconcilingBatchIds.value, normalizedId]
    try {
      const result = await api.storyEngines.reconcile(targetProjectId, normalizedId)
      if (
        projectId.value !== targetProjectId
        || contractStateGeneration !== stateGeneration
      ) {
        return result
      }
      if (result.status === 'failed' && result.publicErrorCode === 'not_started') {
        recoverableBatches.value = recoverableBatches.value.filter(
          item => item.id !== normalizedId,
        )
      } else {
        recoverableBatches.value = recoverableBatches.value.map(item => (
          item.id === normalizedId ? { ...item, ...result } : item
        ))
      }
      if (result.status === 'outcome_unknown') engineBatch.value = result
      error.value = null
      return result
    } catch (failure) {
      if (
        projectId.value === targetProjectId
        && contractStateGeneration === stateGeneration
      ) {
        const safe = publicError(failure)
        error.value = safe
        if (isConflict(failure)) {
          conflict.value = safe
          requiresReload.value = true
        }
      }
      throw failure
    } finally {
      if (recoverableCommands.get(normalizedId) === commandToken) {
        recoverableCommands.delete(normalizedId)
        reconcilingBatchIds.value = reconcilingBatchIds.value.filter(
          id => id !== normalizedId,
        )
      }
    }
  }

  async function runStyleTrial(nextProjectId, command) {
    const targetProjectId = enterProject(nextProjectId)
    assertWritable()
    const generation = styleTrialGuard.begin()
    const stateGeneration = contractStateGeneration
    styleTrialLoading.value = true
    try {
      const result = await api.styleTrials.generate(targetProjectId, command)
      if (currentContractState(
        styleTrialGuard,
        generation,
        targetProjectId,
        stateGeneration,
      )) {
        styleTrial.value = result
        error.value = null
      }
      return result
    } catch (failure) {
      recordFailure(
        failure,
        styleTrialGuard,
        generation,
        targetProjectId,
        stateGeneration,
      )
      throw failure
    } finally {
      if (current(styleTrialGuard, generation, targetProjectId)) {
        styleTrialLoading.value = false
      }
    }
  }

  function clearStyleTrial() {
    styleTrialGuard.invalidate()
    styleTrial.value = null
    styleTrialLoading.value = false
  }

  function clearHistory() {
    historyGuard.invalidate()
    history.value = []
    historyNextBeforeRevision.value = null
    historyLoading.value = false
  }

  async function loadHistory(
    nextProjectId,
    { limit = 20, beforeRevision, append = false } = {},
  ) {
    const targetProjectId = enterProject(nextProjectId)
    const generation = historyGuard.begin()
    historyLoading.value = true
    try {
      const params = beforeRevision == null ? { limit } : { limit, beforeRevision }
      const result = await api.contracts.history(targetProjectId, params)
      if (current(historyGuard, generation, targetProjectId)) {
        const incoming = Array.isArray(result?.items)
          ? result.items.map(item => ({ ...item }))
          : []
        const revisions = new Map(
          (append ? [...history.value, ...incoming] : incoming)
            .map(item => [Number(item.revision), item]),
        )
        history.value = [...revisions.values()]
          .sort((left, right) => Number(right.revision) - Number(left.revision))
        historyNextBeforeRevision.value = result?.nextBeforeRevision ?? null
        error.value = null
      }
      return result
    } catch (failure) {
      recordFailure(failure, historyGuard, generation, targetProjectId)
      throw failure
    } finally {
      if (current(historyGuard, generation, targetProjectId)) {
        historyLoading.value = false
      }
    }
  }

  return {
    projectId,
    draft,
    previewResult,
    confirmed,
    head,
    engineBatch,
    styleTrial,
    history,
    historyNextBeforeRevision,
    recoverableBatches,
    reconcilingBatchIds,
    conflict,
    error,
    requiresReload,
    hasUnsavedChanges,
    readOnly,
    headHydrated,
    loading,
    saving,
    previewing,
    confirming,
    engineLoading,
    reconciling,
    styleTrialLoading,
    historyLoading,
    lastSavedStage,
    activeDraftVersion,
    savedStage,
    readiness,
    contractReady,
    readinessReasons,
    serverCanConfirm,
    serverReasons,
    providerOutcomeUnknown,
    baselineLocked,
    markUnsavedChanges,
    discardUnsavedChanges,
    setReadOnly,
    load,
    saveDraft,
    preview,
    confirm,
    generateEngineBatch,
    createManualEngineBatch,
    loadEngineBatch,
    reconcileBatch,
    reconcileRecoverableBatch,
    runStyleTrial,
    clearStyleTrial,
    clearHistory,
    loadHistory,
  }
})
