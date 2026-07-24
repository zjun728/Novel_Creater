import { defineStore } from 'pinia'
import { ref, shallowRef } from 'vue'

import { api } from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function clone(value) {
  return value == null ? value : structuredClone(value)
}

function editableNode(node, fields) {
  const result = {}
  for (const field of [
    'id',
    'clientNodeKey',
    'revision',
    'contentHash',
    'lifecycle',
    ...fields,
  ]) {
    if (node?.[field] !== undefined) result[field] = clone(node[field])
  }
  return result
}

function editableContent(content) {
  if (!content) return null
  return {
    activeStoryBlockRef: content.activeStoryBlockId ?? null,
    volumes: (content.volumes || []).map(volume => editableNode(volume, [
      'order',
      'title',
      'coreChange',
      'mainPressure',
      'ensembleFocus',
      'forbiddenEvents',
    ])),
    plots: (content.plots || []).map(plot => editableNode(plot, [
      'order',
      'title',
      'plotType',
      'storyQuestion',
      'futureDirection',
      'expectedPayoff',
      'relatedCharacters',
    ])),
    storyBlocks: (content.storyBlocks || []).map(block => ({
      ...editableNode(block, [
        'order',
        'title',
        'entrySituation',
        'blockGoal',
        'mainPressure',
        'expectedChange',
        'openQuestions',
        'involvedCharacters',
      ]),
      volumeRef: block.volumeId,
      plotRefs: clone(block.plotIds || []),
      stages: (block.stages || []).map(stage => ({
        ...editableNode(stage, [
          'order',
          'title',
          'purpose',
          'dramaticQuestion',
        ]),
        sceneTasks: (stage.sceneTasks || []).map(task => editableNode(task, [
          'order',
          'task',
          'completionEvidence',
        ])),
      })),
    })),
  }
}

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

export const usePlanningStore = defineStore('planning', () => {
  const projectId = ref('')
  const state = shallowRef(null)
  const history = ref([])
  const localContent = shallowRef(null)
  const dirty = ref(false)
  const error = shallowRef(null)
  const loading = ref(false)
  const saving = ref(false)
  const confirming = ref(false)
  const generating = ref(false)
  const reconciling = ref(false)
  const generationOperation = shallowRef(null)
  const generationOutcomeUnknown = ref(false)
  const awaitingAuthoritativeReload = ref(false)
  const loadGuard = createLatestRequestGuard()
  const mutationGuard = createLatestRequestGuard()
  const generationGuard = createLatestRequestGuard()
  let stateGeneration = 0

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (!normalized) throw new TypeError('projectId is required')
    if (projectId.value !== normalized) {
      stateGeneration += 1
      loadGuard.invalidate()
      mutationGuard.invalidate()
      generationGuard.invalidate()
      projectId.value = normalized
      state.value = null
      history.value = []
      localContent.value = null
      dirty.value = false
      error.value = null
      loading.value = false
      saving.value = false
      confirming.value = false
      generating.value = false
      reconciling.value = false
      generationOperation.value = null
      generationOutcomeUnknown.value = false
      awaitingAuthoritativeReload.value = false
    }
    return normalized
  }

  function isCurrent(guard, requestGeneration, targetProjectId, targetGeneration) {
    return (
      projectId.value === targetProjectId
      && guard.isCurrent(requestGeneration)
      && stateGeneration === targetGeneration
    )
  }

  function acceptState(loaded) {
    state.value = loaded
    localContent.value = editableContent(loaded?.draft?.content)
    dirty.value = false
    error.value = null
  }

  async function load(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const requestGeneration = loadGuard.begin()
    const targetGeneration = ++stateGeneration
    loading.value = true
    try {
      const [loaded, historyPage] = await Promise.all([
        api.planning.get(targetProjectId),
        api.planning.history(targetProjectId),
      ])
      if (isCurrent(
        loadGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        acceptState(loaded)
        history.value = Array.isArray(historyPage?.items)
          ? historyPage.items
          : []
      }
      return loaded
    } catch (failure) {
      if (isCurrent(
        loadGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && loadGuard.isCurrent(requestGeneration)
      ) {
        loading.value = false
      }
    }
  }

  async function ensureLoaded(nextProjectId, options = {}) {
    const targetProjectId = String(nextProjectId || '')
    if (!targetProjectId) throw new TypeError('projectId is required')
    if (
      options?.force !== true
      && projectId.value === targetProjectId
      && state.value !== null
    ) {
      return state.value
    }
    if (
      options?.force === true
      && projectId.value === targetProjectId
      && awaitingAuthoritativeReload.value
      && generationOperation.value?.status === 'succeeded'
      && generationOperation.value?.loaded === true
    ) {
      const operationId = generationOperation.value.operationId
      const targetDraftId = state.value?.draft?.draftId
      const requestGeneration = generationGuard.begin()
      reconciling.value = true
      generating.value = true
      try {
        await reloadGenerationAuthority(generationOperation.value, {
          requestGeneration,
          targetProjectId,
          targetDraftId,
          allowDirtyDiscard: true,
        })
      } finally {
        if (
          generationIsCurrent(requestGeneration, targetProjectId)
          && generationOperation.value?.operationId === operationId
        ) {
          reconciling.value = false
        }
      }
      return state.value
    }
    const loaded = await load(targetProjectId)
    if (
      options?.force === true
      && projectId.value === targetProjectId
      && !generationOperation.value?.operationId
    ) {
      generationOutcomeUnknown.value = false
    }
    return loaded
  }

  async function createDraft(nextProjectId, command) {
    const targetProjectId = enterProject(nextProjectId)
    if (saving.value || confirming.value || generating.value) {
      throw new Error('已有操作正在进行')
    }
    const requestGeneration = mutationGuard.begin()
    const targetGeneration = ++stateGeneration
    saving.value = true
    try {
      const created = await api.planning.createDraft(targetProjectId, {
        idempotencyKey: command.idempotencyKey,
      })
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        state.value = {
          ...(state.value || { projectId: targetProjectId }),
          draft: created,
        }
        localContent.value = editableContent(created.content)
        dirty.value = false
        error.value = null
      }
      return created
    } catch (failure) {
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && mutationGuard.isCurrent(requestGeneration)
      ) {
        saving.value = false
      }
    }
  }

  function editLocal(content) {
    if (!state.value?.draft) {
      throw new TypeError('An active Planning draft is required')
    }
    localContent.value = clone(content)
    dirty.value = true
  }

  async function saveDraft(command) {
    const currentDraft = state.value?.draft
    const targetProjectId = projectId.value
    if (!targetProjectId || !currentDraft || !localContent.value) {
      throw new TypeError('An active Planning draft is required')
    }
    if (awaitingAuthoritativeReload.value) {
      throw new Error('正在等待权威工作稿回读，暂不能保存')
    }
    if (saving.value || confirming.value) {
      throw new Error('已有操作正在进行')
    }
    const requestGeneration = mutationGuard.begin()
    const targetGeneration = ++stateGeneration
    saving.value = true
    try {
      const saved = await api.planning.saveDraft(
        targetProjectId,
        currentDraft.draftId,
        {
          expectedDraftRevision: currentDraft.draftRevision,
          expectedDraftHash: currentDraft.contentHash,
          content: clone(localContent.value),
          idempotencyKey: command.idempotencyKey,
        },
      )
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        state.value = { ...state.value, draft: saved }
        localContent.value = editableContent(saved.content)
        dirty.value = false
        error.value = null
      }
      return saved
    } catch (failure) {
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        projectId.value === targetProjectId
        && mutationGuard.isCurrent(requestGeneration)
      ) {
        saving.value = false
      }
    }
  }

  async function confirmDraft(command) {
    const currentDraft = state.value?.draft
    const targetProjectId = projectId.value
    if (!targetProjectId || !currentDraft) {
      throw new TypeError('An active Planning draft is required')
    }
    if (dirty.value) {
      throw new Error('请先保存本地修改，再确认规划')
    }
    if (saving.value || confirming.value || generating.value) {
      throw new Error('已有操作正在进行')
    }
    const requestGeneration = mutationGuard.begin()
    const targetGeneration = ++stateGeneration
    confirming.value = true
    let confirmed
    try {
      confirmed = await api.planning.confirmDraft(
        targetProjectId,
        currentDraft.draftId,
        {
          expectedDraftRevision: currentDraft.draftRevision,
          expectedDraftHash: currentDraft.contentHash,
          idempotencyKey: command.idempotencyKey,
        },
      )
    } catch (failure) {
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = publicError(failure)
        confirming.value = false
      }
      throw failure
    }
    if (!isCurrent(
      mutationGuard,
      requestGeneration,
      targetProjectId,
      targetGeneration,
    )) {
      return confirmed
    }

    state.value = {
      ...state.value,
      head: {
        revision: confirmed.revision,
        planningRevisionId: confirmed.planningRevisionId,
        contentHash: confirmed.contentHash,
      },
      draft: null,
      futurePlan: confirmed.content ?? null,
      capabilities: {
        ...(state.value?.capabilities || {}),
        confirm: false,
      },
    }
    history.value = [
      confirmed,
      ...history.value.filter(item => (
        item.planningRevisionId !== confirmed.planningRevisionId
        && item.revision !== confirmed.revision
      )),
    ]
    localContent.value = null
    dirty.value = false
    error.value = null

    try {
      const [loaded, historyPage] = await Promise.all([
        api.planning.get(targetProjectId),
        api.planning.history(targetProjectId),
      ])
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        acceptState(loaded)
        history.value = Array.isArray(historyPage?.items)
          ? historyPage.items
          : []
      }
      return confirmed
    } catch (failure) {
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = {
          status: Number(failure?.status || 0),
          code: 'PlanningRefreshFailed',
          message: '规划确认成功，但刷新失败；请稍后重新加载',
          correlationId: String(failure?.correlationId || ''),
        }
      }
      return confirmed
    } finally {
      if (
        projectId.value === targetProjectId
        && mutationGuard.isCurrent(requestGeneration)
      ) {
        confirming.value = false
      }
    }
  }

  function generationIsCurrent(requestGeneration, targetProjectId) {
    return (
      projectId.value === targetProjectId
      && generationGuard.isCurrent(requestGeneration)
    )
  }

  function safeRecoveryOperationId(failure) {
    const value = failure?.operationId
    if (
      typeof value !== 'string'
      || !value
      || value.length > 128
      || !/^[A-Za-z0-9][A-Za-z0-9._~-]*$/.test(value)
      || /(?:authorization|api[-_]?key|credential|password|secret|token|dsn)/i.test(value)
      || /(?:^|[^A-Za-z0-9])(?:(?:sk|rk|pk)[-_][A-Za-z0-9._~+/=-]{8,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AIza[A-Za-z0-9_-]{20,}|(?:AKIA|ASIA)[A-Z0-9]{16})(?:$|[^A-Za-z0-9])/i.test(value)
    ) {
      return ''
    }
    return value
  }

  function outcomeUnknownFailure(hasOperationId) {
    const failure = new Error(
      hasOperationId
        ? '生成结果未知，请使用操作编号重新核对'
        : '生成结果未知且没有操作编号；本地内容已保留，请重新加载后恢复',
    )
    failure.code = 'PlanningGenerationOutcomeUnknown'
    failure.status = 0
    return failure
  }

  function isUnknownTransportFailure(failure) {
    const status = Number(failure?.status || 0)
    const code = String(failure?.code || '')
    return (
      status === 0
      && (
        !code
        || code === 'request_failed'
        || code === 'request_timeout'
        || code === 'invalid_response'
      )
    )
  }

  function isExactGeneratedDraftState(
    loaded,
    {
      targetProjectId,
      targetDraftId,
      loadedDraftRevision,
    },
  ) {
    const loadedDraft = loaded?.draft
    const content = loadedDraft?.content
    return (
      loaded
      && typeof loaded === 'object'
      && !Array.isArray(loaded)
      && loaded.projectId === targetProjectId
      && loadedDraft
      && typeof loadedDraft === 'object'
      && !Array.isArray(loadedDraft)
      && loadedDraft.projectId === targetProjectId
      && loadedDraft.draftId === targetDraftId
      && loadedDraft.draftRevision === loadedDraftRevision
      && typeof loadedDraft.contentHash === 'string'
      && /^[0-9a-f]{64}$/i.test(loadedDraft.contentHash)
      && content
      && typeof content === 'object'
      && !Array.isArray(content)
      && content.schemaVersion === 'planning-v1'
      && content.contentHash === loadedDraft.contentHash
      && Array.isArray(content.volumes)
      && Array.isArray(content.plots)
      && Array.isArray(content.storyBlocks)
    )
  }

  async function reloadGenerationAuthority(
    result,
    {
      requestGeneration,
      targetProjectId,
      targetDraftId,
      allowDirtyDiscard = false,
    },
  ) {
    try {
      const loaded = await api.planning.get(targetProjectId)
      if (
        !generationIsCurrent(requestGeneration, targetProjectId)
        || generationOperation.value?.operationId !== result.operationId
      ) {
        return false
      }
      if (!isExactGeneratedDraftState(loaded, {
        targetProjectId,
        targetDraftId,
        loadedDraftRevision: result.loadedDraftRevision,
      })) {
        awaitingAuthoritativeReload.value = true
        generating.value = true
        error.value = {
          status: 0,
          code: 'PlanningGenerationReloadMismatch',
          message: '生成已完成，但权威工作稿状态不匹配；本地内容已保留',
          correlationId: '',
        }
        return false
      }
      if (dirty.value && !allowDirtyDiscard) {
        awaitingAuthoritativeReload.value = true
        generating.value = true
        error.value = {
          status: 0,
          code: 'PlanningGenerationLocalEditPending',
          message: '生成已完成，但存在未保存的本地修改；请重新核对后恢复',
          correlationId: '',
        }
        return false
      }

      const nextLocalContent = editableContent(loaded.draft.content)
      state.value = loaded
      localContent.value = nextLocalContent
      dirty.value = false
      error.value = null
      generationOutcomeUnknown.value = false
      awaitingAuthoritativeReload.value = false
      generating.value = false
      return true
    } catch (failure) {
      if (
        generationIsCurrent(requestGeneration, targetProjectId)
        && generationOperation.value?.operationId === result.operationId
      ) {
        awaitingAuthoritativeReload.value = true
        generating.value = true
        error.value = {
          status: Number(failure?.status || 0),
          code: 'PlanningGenerationRefreshFailed',
          message: '生成已完成，但刷新权威工作稿失败；本地内容已保留',
          correlationId: String(failure?.correlationId || ''),
        }
      }
      return false
    }
  }

  async function acceptGenerationOperation(
    result,
    {
      requestGeneration,
      targetProjectId,
      targetDraftId,
    },
  ) {
    if (!generationIsCurrent(requestGeneration, targetProjectId)) return result
    if (
      generationOperation.value
      && generationOperation.value.operationId !== result.operationId
    ) {
      return result
    }
    const currentOperation = generationOperation.value
    if (
      awaitingAuthoritativeReload.value
      && currentOperation?.status === 'succeeded'
      && currentOperation.loaded === true
      && (
        result.status !== 'succeeded'
        || result.loaded !== true
        || result.loadedDraftRevision !== currentOperation.loadedDraftRevision
      )
    ) {
      generating.value = true
      error.value = {
        status: 0,
        code: 'PlanningGenerationOperationRegressed',
        message: '生成操作状态与已知结果不一致；请继续核对原操作',
        correlationId: '',
      }
      return result
    }

    generationOperation.value = result
    if (result.status === 'pending') {
      generationOutcomeUnknown.value = false
      awaitingAuthoritativeReload.value = false
      generating.value = true
      error.value = null
      return result
    }

    if (!(result.status === 'succeeded' && result.loaded === true)) {
      generationOutcomeUnknown.value = false
      awaitingAuthoritativeReload.value = false
      generating.value = false
      if (result.status === 'failed') {
        error.value = {
          status: 0,
          code: result.failureCode || 'PlanningGenerationFailed',
          message: '规划生成失败，本地内容未改变',
          correlationId: '',
        }
      } else {
        error.value = null
      }
      return result
    }

    awaitingAuthoritativeReload.value = true
    generating.value = true
    await reloadGenerationAuthority(result, {
      requestGeneration,
      targetProjectId,
      targetDraftId,
    })
    return result
  }

  async function generateDraft(command) {
    const currentDraft = state.value?.draft
    const targetProjectId = projectId.value
    if (!targetProjectId || !currentDraft) {
      throw new TypeError('An active Planning draft is required')
    }
    if (awaitingAuthoritativeReload.value) {
      throw new Error('正在等待权威工作稿回读，请先重新核对')
    }
    if (generationOutcomeUnknown.value) {
      throw new Error('上次生成结果未知，请先重新加载后再生成')
    }
    if (generating.value || reconciling.value) {
      throw new Error('已有规划生成正在进行')
    }
    if (state.value?.capabilities?.generate !== true) {
      throw new Error('规划生成模型未就绪')
    }
    if (dirty.value) {
      throw new Error('请先保存本地修改，再生成规划')
    }
    if (saving.value || confirming.value) {
      throw new Error('已有操作正在进行')
    }

    const targetDraftId = currentDraft.draftId
    const requestGeneration = generationGuard.begin()
    generating.value = true
    generationOperation.value = null
    generationOutcomeUnknown.value = false
    awaitingAuthoritativeReload.value = false
    error.value = null
    try {
      const result = await api.planning.generateDraft(
        targetProjectId,
        targetDraftId,
        {
          draftRevision: currentDraft.draftRevision,
          draftHash: currentDraft.contentHash,
          idempotencyKey: command.idempotencyKey,
          authorInstructions: command.authorInstructions,
        },
      )
      if (!generationIsCurrent(requestGeneration, targetProjectId)) {
        return result
      }
      generationOperation.value = result
      return await acceptGenerationOperation(result, {
        requestGeneration,
        targetProjectId,
        targetDraftId,
      })
    } catch (failure) {
      if (!generationIsCurrent(requestGeneration, targetProjectId)) {
        throw failure
      }
      if (!isUnknownTransportFailure(failure)) {
        generating.value = false
        generationOperation.value = null
        generationOutcomeUnknown.value = false
        awaitingAuthoritativeReload.value = false
        error.value = publicError(failure)
        throw failure
      }
      const operationId = safeRecoveryOperationId(failure)
      if (operationId) {
        generationOperation.value = { operationId }
        generationOutcomeUnknown.value = true
        awaitingAuthoritativeReload.value = false
        generating.value = true
      } else {
        generationOperation.value = null
        generationOutcomeUnknown.value = true
        awaitingAuthoritativeReload.value = false
        generating.value = false
      }
      const publicFailure = outcomeUnknownFailure(Boolean(operationId))
      error.value = publicError(publicFailure)
      throw publicFailure
    }
  }

  async function reconcileGeneration() {
    const targetProjectId = projectId.value
    const operationId = generationOperation.value?.operationId
    const targetDraftId = state.value?.draft?.draftId
    if (!targetProjectId || !operationId || !targetDraftId) {
      throw new Error('没有可重新核对的规划生成操作')
    }
    if (reconciling.value) {
      throw new Error('规划生成结果正在核对')
    }

    const requestGeneration = generationGuard.begin()
    reconciling.value = true
    generating.value = true
    try {
      const result = await api.planning.getOperation(
        targetProjectId,
        operationId,
      )
      if (
        !generationIsCurrent(requestGeneration, targetProjectId)
        || generationOperation.value?.operationId !== operationId
      ) {
        return result
      }
      return await acceptGenerationOperation(result, {
        requestGeneration,
        targetProjectId,
        targetDraftId,
      })
    } catch (failure) {
      if (
        generationIsCurrent(requestGeneration, targetProjectId)
        && generationOperation.value?.operationId === operationId
      ) {
        generationOutcomeUnknown.value = true
        generating.value = true
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (
        generationIsCurrent(requestGeneration, targetProjectId)
        && generationOperation.value?.operationId === operationId
      ) {
        reconciling.value = false
      }
    }
  }

  function discardLocal() {
    localContent.value = editableContent(state.value?.draft?.content)
    dirty.value = false
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    mutationGuard.invalidate()
    generationGuard.invalidate()
    loading.value = false
    saving.value = false
    confirming.value = false
    generating.value = false
    reconciling.value = false
    generationOperation.value = null
    generationOutcomeUnknown.value = false
    awaitingAuthoritativeReload.value = false
  }

  return {
    projectId,
    state,
    history,
    localContent,
    dirty,
    error,
    loading,
    saving,
    confirming,
    generating,
    reconciling,
    generationOperation,
    generationOutcomeUnknown,
    awaitingAuthoritativeReload,
    load,
    ensureLoaded,
    createDraft,
    editLocal,
    saveDraft,
    confirmDraft,
    generateDraft,
    reconcileGeneration,
    discardLocal,
    invalidate,
  }
})
