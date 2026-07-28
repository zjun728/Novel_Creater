import { defineStore } from 'pinia'
import { ref, shallowRef, toRaw } from 'vue'

import {
  api,
  isSafePlanningIdempotencyKey,
} from '../api/db/client.js'
import { createLatestRequestGuard } from '../utils/latestRequest.js'

function clone(value) {
  return value == null ? value : structuredClone(toRaw(value))
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

export function canonicalPlanningContentForUi(content) {
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

const OUTLINE_CONTENT_FIELDS = Object.freeze([
  'schemaVersion',
  'volumeRef',
  'storyBlockRef',
  'stageRefs',
  'sceneTaskRefs',
  'chapterGoal',
  'expectedCharacters',
  'continuation',
  'plannedTasks',
  'scenes',
  'forbiddenEarlyEvents',
])

export function canonicalOutlineContentForUi(content) {
  if (!content) return null
  const result = {}
  for (const field of OUTLINE_CONTENT_FIELDS) {
    if (content[field] !== undefined) result[field] = clone(content[field])
  }
  return result
}

function publicError(error) {
  return {
    status: Number(error?.status || 0),
    code: String(error?.code || 'request_failed'),
    message: String(error?.message || '请求失败'),
    correlationId: String(error?.correlationId || ''),
  }
}

function chapterOutlineHistoryFailure(failure) {
  return Object.assign(new Error('章节小纲历史暂时无法加载'), {
    status: Number(failure?.status || 0),
    code: 'ChapterOutlineHistoryLoadFailed',
    correlationId: String(failure?.correlationId || ''),
  })
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
  const generationRecoveryKey = ref('')
  const generationOutcomeUnknown = ref(false)
  const awaitingAuthoritativeReload = ref(false)
  const outlineState = shallowRef(null)
  const outlineHistory = ref([])
  const outlineLocalContent = shallowRef(null)
  const outlineDirty = ref(false)
  const outlineError = shallowRef(null)
  const outlineLoading = ref(false)
  const outlineSaving = ref(false)
  const outlineConfirming = ref(false)
  const outlineGenerating = ref(false)
  const outlineReconciling = ref(false)
  const outlineOperation = shallowRef(null)
  const outlineRecoveryKey = ref('')
  const outlineOutcomeUnknown = ref(false)
  const outlineAwaitingAuthority = ref(false)
  const loadGuard = createLatestRequestGuard()
  const mutationGuard = createLatestRequestGuard()
  const generationGuard = createLatestRequestGuard()
  const outlineLoadGuard = createLatestRequestGuard()
  const outlineMutationGuard = createLatestRequestGuard()
  const outlineGenerationGuard = createLatestRequestGuard()
  let stateGeneration = 0
  let outlineContextGeneration = 0
  let outlineLocalEditGeneration = 0
  let outlineAuthorityWriteEpoch = 0

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (!normalized) throw new TypeError('projectId is required')
    if (projectId.value !== normalized) {
      stateGeneration += 1
      loadGuard.invalidate()
      mutationGuard.invalidate()
      generationGuard.invalidate()
      outlineLoadGuard.invalidate()
      outlineMutationGuard.invalidate()
      outlineGenerationGuard.invalidate()
      outlineContextGeneration += 1
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
      generationRecoveryKey.value = ''
      generationOutcomeUnknown.value = false
      awaitingAuthoritativeReload.value = false
      outlineState.value = null
      outlineHistory.value = []
      replaceOutlineLocal(null)
      outlineError.value = null
      outlineLoading.value = false
      outlineSaving.value = false
      outlineConfirming.value = false
      outlineGenerating.value = false
      outlineReconciling.value = false
      outlineOperation.value = null
      outlineRecoveryKey.value = ''
      outlineOutcomeUnknown.value = false
      outlineAwaitingAuthority.value = false
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
    localContent.value = canonicalPlanningContentForUi(loaded?.draft?.content)
    dirty.value = false
    error.value = null
  }

  function acceptDraftWrite(draft) {
    state.value = {
      ...(state.value || { projectId: projectId.value }),
      draft,
      capabilities: {
        ...(state.value?.capabilities || {}),
        confirm: false,
      },
    }
    localContent.value = canonicalPlanningContentForUi(draft?.content)
    dirty.value = false
    error.value = null
  }

  async function refreshStateAfterDraftWrite({
    requestGeneration,
    targetProjectId,
    targetGeneration,
    failureMessage,
  }) {
    try {
      const loaded = await api.planning.get(targetProjectId)
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        acceptState(loaded)
      }
    } catch (failure) {
      if (isCurrent(
        mutationGuard,
        requestGeneration,
        targetProjectId,
        targetGeneration,
      )) {
        error.value = {
          ...publicError(failure),
          code: 'PlanningRefreshFailed',
          message: failureMessage,
        }
      }
    }
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
      options?.force === true
      && projectId.value === targetProjectId
      && generationOutcomeUnknown.value
    ) {
      throw new Error('生成结果未知，请先使用原幂等键重新核对')
    }
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
    return await load(targetProjectId)
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
        acceptDraftWrite(created)
        await refreshStateAfterDraftWrite({
          requestGeneration,
          targetProjectId,
          targetGeneration,
          failureMessage: '规划工作稿已创建，但刷新失败；请稍后重新加载',
        })
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
    if (generationOutcomeUnknown.value) {
      throw new Error('生成结果未知，请先使用原幂等键恢复后再保存')
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
        acceptDraftWrite(saved)
        await refreshStateAfterDraftWrite({
          requestGeneration,
          targetProjectId,
          targetGeneration,
          failureMessage: '规划工作稿已保存，但刷新失败；请稍后重新加载',
        })
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

  function outcomeUnknownFailure() {
    const failure = new Error(
      '生成结果未知；本地内容已保留，请使用原幂等键重新核对',
    )
    failure.code = 'PlanningGenerationOutcomeUnknown'
    failure.status = 0
    return failure
  }

  function isUnknownTransportFailure(failure) {
    const status = Number(failure?.status || 0)
    const code = String(failure?.code || '')
    return (
      status >= 500
      || (
        status === 0
        && (
          !code
          || code === 'request_failed'
          || code === 'request_timeout'
          || code === 'invalid_response'
        )
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

      const nextLocalContent = canonicalPlanningContentForUi(loaded.draft.content)
      state.value = loaded
      localContent.value = nextLocalContent
      dirty.value = false
      error.value = null
      generationRecoveryKey.value = ''
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
      generationOutcomeUnknown.value = true
      awaitingAuthoritativeReload.value = false
      generating.value = true
      error.value = null
      return result
    }

    if (!(result.status === 'succeeded' && result.loaded === true)) {
      generationRecoveryKey.value = ''
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
    if (!isSafePlanningIdempotencyKey(command?.idempotencyKey)) {
      throw new TypeError('Invalid Planning idempotency key')
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
    generationRecoveryKey.value = command.idempotencyKey
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
        generationRecoveryKey.value = ''
        generationOutcomeUnknown.value = false
        awaitingAuthoritativeReload.value = false
        error.value = publicError(failure)
        throw failure
      }
      generationOperation.value = null
      generationOutcomeUnknown.value = true
      awaitingAuthoritativeReload.value = false
      generating.value = true
      const publicFailure = outcomeUnknownFailure()
      error.value = publicError(publicFailure)
      throw publicFailure
    }
  }

  async function reconcileGeneration() {
    const targetProjectId = projectId.value
    const operationId = generationOperation.value?.operationId
    const recoveryKey = generationRecoveryKey.value
    const targetDraftId = state.value?.draft?.draftId
    const recoverByKey = (
      !operationId
      && generationOutcomeUnknown.value
      && Boolean(recoveryKey)
    )
    if (
      !targetProjectId
      || !targetDraftId
      || (!operationId && !recoverByKey)
    ) {
      throw new Error('没有可重新核对的规划生成操作')
    }
    if (reconciling.value) {
      throw new Error('规划生成结果正在核对')
    }

    const requestGeneration = generationGuard.begin()
    reconciling.value = true
    generating.value = true
    try {
      const result = recoverByKey
        ? await api.planning.getOperationByIdempotencyKey(
          targetProjectId,
          recoveryKey,
        )
        : await api.planning.getOperation(
          targetProjectId,
          operationId,
        )
      if (
        !generationIsCurrent(requestGeneration, targetProjectId)
        || (
          recoverByKey
            ? (
              generationOperation.value !== null
              || generationRecoveryKey.value !== recoveryKey
            )
            : generationOperation.value?.operationId !== operationId
        )
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
        && (
          recoverByKey
            ? (
              generationOperation.value === null
              && generationRecoveryKey.value === recoveryKey
            )
            : generationOperation.value?.operationId === operationId
        )
      ) {
        generationOutcomeUnknown.value = true
        generating.value = true
        error.value = publicError(failure)
      }
      throw failure
    } finally {
      if (generationIsCurrent(requestGeneration, targetProjectId)) {
        reconciling.value = false
      }
    }
  }

  function outlineIsCurrent(
    guard,
    requestGeneration,
    targetProjectId,
    targetContextGeneration,
  ) {
    return (
      projectId.value === targetProjectId
      && outlineContextGeneration === targetContextGeneration
      && guard.isCurrent(requestGeneration)
    )
  }

  function outlineDraftIdentityIsCurrent({
    targetChapterNumber,
    targetDraftId,
    targetDraftRevision,
    targetDraftHash,
  }) {
    if (
      outlineState.value?.authoritativeChapterNumber !== targetChapterNumber
    ) return false
    const draft = outlineState.value?.draft
    if (targetDraftId === null) return draft === null
    return (
      draft?.draftId === targetDraftId
      && draft?.draftRevision === targetDraftRevision
      && draft?.contentHash === targetDraftHash
    )
  }

  function outlineMutationIsCurrent(
    requestGeneration,
    targetProjectId,
    targetContextGeneration,
    targetIdentity,
  ) {
    return (
      outlineIsCurrent(
        outlineMutationGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )
      && outlineDraftIdentityIsCurrent(targetIdentity)
    )
  }

  function replaceOutlineLocal(content, { dirty: nextDirty = false } = {}) {
    outlineLocalEditGeneration += 1
    outlineLocalContent.value = canonicalOutlineContentForUi(content)
    outlineDirty.value = nextDirty
  }

  function commitOutlineAuthorityState(
    loaded,
    { authorityWrite = false } = {},
  ) {
    outlineState.value = loaded
    if (authorityWrite) outlineAuthorityWriteEpoch += 1
  }

  function acceptOutlineState(
    loaded,
    {
      preserveDirty = false,
      authorityWrite = false,
    } = {},
  ) {
    commitOutlineAuthorityState(loaded, { authorityWrite })
    if (!preserveDirty || !outlineDirty.value) {
      replaceOutlineLocal(loaded?.draft?.content)
    }
    outlineError.value = null
  }

  function installServerPendingOutlineOperation(loaded) {
    const pendingOperation = loaded?.pendingOperation
    if (
      pendingOperation?.status !== 'pending'
      || typeof pendingOperation.operationId !== 'string'
      || !pendingOperation.operationId
    ) return
    const localOperation = outlineOperation.value
    const localOperationIsProtected = (
      localOperation?.status === 'pending'
      || outlineReconciling.value
      || outlineAwaitingAuthority.value
      || outlineOutcomeUnknown.value
      || (
        outlineGenerating.value
        && (
          localOperation !== null
          || outlineRecoveryKey.value !== ''
        )
      )
    )
    if (
      localOperation?.operationId === pendingOperation.operationId
      || localOperationIsProtected
    ) return
    outlineOperation.value = {
      operationId: pendingOperation.operationId,
      status: 'pending',
    }
    outlineOutcomeUnknown.value = true
    outlineGenerating.value = true
    outlineAwaitingAuthority.value = false
    outlineRecoveryKey.value = ''
    outlineError.value = null
  }

  function outlineLoadAuthorityIsCurrent(
    requestGeneration,
    targetProjectId,
    targetContextGeneration,
    targetAuthorityWriteEpoch,
  ) {
    return (
      outlineIsCurrent(
        outlineLoadGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )
      && outlineAuthorityWriteEpoch === targetAuthorityWriteEpoch
    )
  }

  async function loadOutline(nextProjectId, options = {}) {
    const targetProjectId = enterProject(nextProjectId)
    const requestGeneration = outlineLoadGuard.begin()
    const targetContextGeneration = outlineContextGeneration
    const targetAuthorityWriteEpoch = outlineAuthorityWriteEpoch
    let authorityAccepted = false
    outlineLoading.value = true
    try {
      const loaded = await api.chapterOutlines.current(targetProjectId)
      const chapterNumber = loaded?.authoritativeChapterNumber
      if (
        loaded?.projectId !== targetProjectId
        || !Number.isInteger(chapterNumber)
        || chapterNumber < 1
      ) {
        throw new TypeError('Invalid ChapterOutline authority state')
      }
      if (!outlineLoadAuthorityIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetAuthorityWriteEpoch,
      )) return loaded
      acceptOutlineState(loaded, {
        preserveDirty: (
          options?.preserveLocalEdits === true
          && outlineDirty.value
        ),
      })
      installServerPendingOutlineOperation(loaded)
      authorityAccepted = true

      let historyPage
      try {
        historyPage = await api.chapterOutlines.history(
          targetProjectId,
          chapterNumber,
        )
      } catch (failure) {
        const safeFailure = chapterOutlineHistoryFailure(failure)
        if (outlineLoadAuthorityIsCurrent(
          requestGeneration,
          targetProjectId,
          targetContextGeneration,
          targetAuthorityWriteEpoch,
        )) {
          outlineError.value = publicError(safeFailure)
        }
        throw safeFailure
      }
      if (outlineLoadAuthorityIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetAuthorityWriteEpoch,
      )) {
        outlineHistory.value = Array.isArray(historyPage?.items)
          ? historyPage.items
          : []
      }
      return loaded
    } catch (failure) {
      if (!authorityAccepted && outlineLoadAuthorityIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetAuthorityWriteEpoch,
      )) {
        outlineError.value = options?.authorityRefresh === true
          ? {
              ...publicError(failure),
              code: 'ChapterOutlineRefreshFailed',
              message: '重新读取章节小纲权威状态失败',
            }
          : publicError(failure)
      }
      throw failure
    } finally {
      if (outlineIsCurrent(
        outlineLoadGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )) {
        outlineLoading.value = false
      }
    }
  }

  async function ensureOutlineLoaded(nextProjectId, options = {}) {
    const targetProjectId = String(nextProjectId || '')
    if (!targetProjectId) throw new TypeError('projectId is required')
    if (
      options?.force !== true
      && projectId.value === targetProjectId
      && outlineState.value !== null
    ) {
      return outlineState.value
    }
    return await loadOutline(targetProjectId, {
      preserveLocalEdits: options?.force === true,
      authorityRefresh: options?.force === true,
    })
  }

  async function refreshOutlineAuthority({
    guard,
    requestGeneration,
    targetProjectId,
    targetContextGeneration,
    targetIdentity,
    preserveLocalEditsSinceGeneration = null,
    failureCode,
    failureMessage,
  }) {
    try {
      const loaded = await api.chapterOutlines.current(targetProjectId)
      const requestIsCurrent = targetIdentity
        ? outlineMutationIsCurrent(
            requestGeneration,
            targetProjectId,
            targetContextGeneration,
            targetIdentity,
          )
        : outlineIsCurrent(
            guard,
            requestGeneration,
            targetProjectId,
            targetContextGeneration,
          )
      if (requestIsCurrent) {
        const preserveDirty = (
          Number.isInteger(preserveLocalEditsSinceGeneration)
          && outlineLocalEditGeneration !== preserveLocalEditsSinceGeneration
          && outlineDirty.value
        )
        acceptOutlineState(loaded, {
          preserveDirty,
          authorityWrite: true,
        })
      }
      return loaded
    } catch (failure) {
      const requestIsCurrent = targetIdentity
        ? outlineMutationIsCurrent(
            requestGeneration,
            targetProjectId,
            targetContextGeneration,
            targetIdentity,
          )
        : outlineIsCurrent(
            guard,
            requestGeneration,
            targetProjectId,
            targetContextGeneration,
          )
      if (requestIsCurrent) {
        outlineError.value = {
          ...publicError(failure),
          code: failureCode,
          message: failureMessage,
        }
      }
      return null
    }
  }

  async function createOutlineDraft(nextProjectId) {
    const targetProjectId = enterProject(nextProjectId)
    const chapterNumber = outlineState.value?.authoritativeChapterNumber
    const sourceDraft = outlineState.value?.draft
    if (!Number.isInteger(chapterNumber) || chapterNumber < 1) {
      throw new TypeError('ChapterOutline authority is required')
    }
    if (
      outlineSaving.value
      || outlineConfirming.value
      || outlineGenerating.value
    ) {
      throw new Error('已有小纲操作正在进行')
    }
    const requestGeneration = outlineMutationGuard.begin()
    const targetContextGeneration = outlineContextGeneration
    const targetIdentity = {
      targetChapterNumber: chapterNumber,
      targetDraftId: sourceDraft?.draftId ?? null,
      targetDraftRevision: sourceDraft?.draftRevision ?? null,
      targetDraftHash: sourceDraft?.contentHash ?? null,
    }
    outlineSaving.value = true
    try {
      const created = await api.chapterOutlines.createDraft(
        targetProjectId,
        chapterNumber,
      )
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        commitOutlineAuthorityState({
          ...outlineState.value,
          draft: created,
          capabilities: {
            ...(outlineState.value?.capabilities || {}),
            createDraft: false,
            editDraft: true,
            confirm: false,
          },
        }, { authorityWrite: true })
        replaceOutlineLocal(created?.content)
        outlineError.value = null
        await refreshOutlineAuthority({
          guard: outlineMutationGuard,
          requestGeneration,
          targetProjectId,
          targetContextGeneration,
          targetIdentity: {
            targetChapterNumber: chapterNumber,
            targetDraftId: created?.draftId,
            targetDraftRevision: created?.draftRevision,
            targetDraftHash: created?.contentHash,
          },
          failureCode: 'ChapterOutlineRefreshFailed',
          failureMessage: '章节小纲工作稿已创建，但刷新失败',
        })
      }
      return created
    } catch (failure) {
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        outlineError.value = publicError(failure)
      }
      throw failure
    } finally {
      if (outlineIsCurrent(
        outlineMutationGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )) {
        outlineSaving.value = false
      }
    }
  }

  function editOutlineLocal(content) {
    if (!outlineState.value?.draft) {
      throw new TypeError('An active ChapterOutline draft is required')
    }
    replaceOutlineLocal(content, { dirty: true })
  }

  async function saveOutlineDraft() {
    const currentDraft = outlineState.value?.draft
    const targetProjectId = projectId.value
    const chapterNumber = outlineState.value?.authoritativeChapterNumber
    if (
      !targetProjectId
      || !currentDraft
      || !outlineLocalContent.value
      || !Number.isInteger(chapterNumber)
    ) {
      throw new TypeError('An active ChapterOutline draft is required')
    }
    if (outlineOutcomeUnknown.value || outlineAwaitingAuthority.value) {
      throw new Error('请先核对小纲生成的权威结果')
    }
    if (outlineSaving.value || outlineConfirming.value) {
      throw new Error('已有小纲操作正在进行')
    }
    const requestGeneration = outlineMutationGuard.begin()
    const targetContextGeneration = outlineContextGeneration
    const targetIdentity = {
      targetChapterNumber: chapterNumber,
      targetDraftId: currentDraft.draftId,
      targetDraftRevision: currentDraft.draftRevision,
      targetDraftHash: currentDraft.contentHash,
    }
    const targetLocalEditGeneration = outlineLocalEditGeneration
    outlineSaving.value = true
    try {
      const saved = await api.chapterOutlines.saveDraft(
        targetProjectId,
        chapterNumber,
        currentDraft.draftId,
        {
          expectedDraftRevision: currentDraft.draftRevision,
          expectedDraftHash: currentDraft.contentHash,
          content: clone(outlineLocalContent.value),
        },
      )
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        const preserveNewerLocal = (
          outlineLocalEditGeneration !== targetLocalEditGeneration
          && outlineDirty.value
        )
        commitOutlineAuthorityState({
          ...outlineState.value,
          draft: saved,
          capabilities: {
            ...(outlineState.value?.capabilities || {}),
            confirm: false,
          },
        }, { authorityWrite: true })
        if (!preserveNewerLocal) replaceOutlineLocal(saved?.content)
        outlineError.value = null
        await refreshOutlineAuthority({
          guard: outlineMutationGuard,
          requestGeneration,
          targetProjectId,
          targetContextGeneration,
          targetIdentity: {
            targetChapterNumber: chapterNumber,
            targetDraftId: saved?.draftId,
            targetDraftRevision: saved?.draftRevision,
            targetDraftHash: saved?.contentHash,
          },
          preserveLocalEditsSinceGeneration: targetLocalEditGeneration,
          failureCode: 'ChapterOutlineRefreshFailed',
          failureMessage: '章节小纲工作稿已保存，但刷新失败',
        })
      }
      return saved
    } catch (failure) {
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        outlineError.value = publicError(failure)
      }
      throw failure
    } finally {
      if (outlineIsCurrent(
        outlineMutationGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )) {
        outlineSaving.value = false
      }
    }
  }

  async function confirmOutlineDraft(command) {
    const currentDraft = outlineState.value?.draft
    const targetProjectId = projectId.value
    const chapterNumber = outlineState.value?.authoritativeChapterNumber
    if (!targetProjectId || !currentDraft || !Number.isInteger(chapterNumber)) {
      throw new TypeError('An active ChapterOutline draft is required')
    }
    if (outlineDirty.value) throw new Error('请先保存本地小纲修改，再确认')
    if (
      outlineSaving.value
      || outlineConfirming.value
      || outlineGenerating.value
      || outlineOutcomeUnknown.value
      || outlineAwaitingAuthority.value
    ) {
      throw new Error('已有小纲操作正在进行')
    }
    const requestGeneration = outlineMutationGuard.begin()
    const targetContextGeneration = outlineContextGeneration
    const targetIdentity = {
      targetChapterNumber: chapterNumber,
      targetDraftId: currentDraft.draftId,
      targetDraftRevision: currentDraft.draftRevision,
      targetDraftHash: currentDraft.contentHash,
    }
    outlineConfirming.value = true
    try {
      const confirmed = await api.chapterOutlines.confirmDraft(
        targetProjectId,
        chapterNumber,
        currentDraft.draftId,
        {
          expectedDraftRevision: currentDraft.draftRevision,
          expectedDraftHash: currentDraft.contentHash,
          expectedHeadRevision: currentDraft.baseHeadRevision,
          idempotencyKey: command.idempotencyKey,
        },
      )
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        commitOutlineAuthorityState({
          ...outlineState.value,
          confirmedOutline: confirmed,
          draft: null,
          capabilities: {
            ...(outlineState.value?.capabilities || {}),
            editDraft: false,
            generate: false,
            confirm: false,
          },
        }, { authorityWrite: true })
        outlineHistory.value = [
          confirmed,
          ...outlineHistory.value.filter(item => (
            item.outlineRevisionId !== confirmed.outlineRevisionId
          )),
        ]
        replaceOutlineLocal(null)
        const loaded = await refreshOutlineAuthority({
          guard: outlineMutationGuard,
          requestGeneration,
          targetProjectId,
          targetContextGeneration,
          targetIdentity: {
            targetChapterNumber: chapterNumber,
            targetDraftId: null,
            targetDraftRevision: null,
            targetDraftHash: null,
          },
          failureCode: 'ChapterOutlineRefreshFailed',
          failureMessage: '章节小纲已确认，但刷新失败',
        })
        if (loaded && outlineState.value === loaded && outlineIsCurrent(
          outlineMutationGuard,
          requestGeneration,
          targetProjectId,
          targetContextGeneration,
        )) {
          const historyPage = await api.chapterOutlines.history(
            targetProjectId,
            chapterNumber,
          )
          if (outlineState.value === loaded && outlineIsCurrent(
            outlineMutationGuard,
            requestGeneration,
            targetProjectId,
            targetContextGeneration,
          )) {
            outlineHistory.value = Array.isArray(historyPage?.items)
              ? historyPage.items
              : []
          }
        }
      }
      return confirmed
    } catch (failure) {
      if (outlineMutationIsCurrent(
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
        targetIdentity,
      )) {
        outlineError.value = publicError(failure)
      }
      throw failure
    } finally {
      if (outlineIsCurrent(
        outlineMutationGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )) {
        outlineConfirming.value = false
      }
    }
  }

  function outlineUnknownFailure() {
    const failure = new Error(
      '小纲生成结果未知；本地内容已保留，请核对原操作',
    )
    failure.code = 'ChapterOutlineGenerationOutcomeUnknown'
    failure.status = 0
    return failure
  }

  function outlineAuthorityFingerprint(value) {
    return JSON.stringify({
      chapterNumber: value?.authoritativeChapterNumber,
      planningRevisionId: value?.planningAuthority?.planningRevisionId,
      planningRevision: value?.planningAuthority?.revision,
      planningHash: value?.planningAuthority?.contentHash,
      canonRevision: value?.canonProjectionAuthority?.canonRevision,
      projectionRevision: value?.canonProjectionAuthority?.projectionRevision,
      projectionHash: value?.canonProjectionAuthority?.contentHash,
    })
  }

  function exactGeneratedOutlineState(
    loaded,
    {
      targetProjectId,
      targetChapterNumber,
      targetDraftId,
      loadedDraftRevision,
      authorityFingerprint,
    },
  ) {
    const draft = loaded?.draft
    return (
      loaded?.projectId === targetProjectId
      && loaded?.authoritativeChapterNumber === targetChapterNumber
      && outlineAuthorityFingerprint(loaded) === authorityFingerprint
      && draft?.projectId === targetProjectId
      && draft?.chapterNumber === targetChapterNumber
      && draft?.draftId === targetDraftId
      && draft?.draftRevision === loadedDraftRevision
      && draft?.status === 'current'
      && typeof draft?.contentHash === 'string'
      && /^[0-9a-f]{64}$/i.test(draft.contentHash)
      && draft?.content?.schemaVersion === 'chapter-outline-draft-v1'
    )
  }

  function outlineGenerationIsCurrent(
    requestGeneration,
    targetProjectId,
    targetContextGeneration,
    targetChapterNumber,
    targetDraftId,
    targetDraftRevision,
    targetDraftHash,
  ) {
    return (
      outlineIsCurrent(
        outlineGenerationGuard,
        requestGeneration,
        targetProjectId,
        targetContextGeneration,
      )
      && outlineDraftIdentityIsCurrent({
        targetChapterNumber,
        targetDraftId,
        targetDraftRevision,
        targetDraftHash,
      })
    )
  }

  function outlineReconciliationIdentityIsCurrent(context) {
    return context.recoverByKey
      ? (
          outlineOperation.value === null
          && outlineRecoveryKey.value === context.recoveryKey
        )
      : outlineOperation.value?.operationId === context.operationId
  }

  async function reloadOutlineGenerationAuthority(
    result,
    context,
  ) {
    try {
      const loaded = await api.chapterOutlines.current(context.targetProjectId)
      if (
        !outlineGenerationIsCurrent(
          context.requestGeneration,
          context.targetProjectId,
          context.targetContextGeneration,
          context.targetChapterNumber,
          context.targetDraftId,
          context.targetDraftRevision,
          context.targetDraftHash,
        )
        || outlineOperation.value?.operationId !== result.operationId
      ) {
        return false
      }
      if (
        !exactGeneratedOutlineState(loaded, {
          ...context,
          loadedDraftRevision: result.loadedDraftRevision,
        })
        || outlineDirty.value
      ) {
        outlineAwaitingAuthority.value = true
        outlineGenerating.value = true
        outlineError.value = {
          status: 0,
          code: outlineDirty.value
            ? 'ChapterOutlineGenerationLocalEditPending'
            : 'ChapterOutlineGenerationReloadMismatch',
          message: outlineDirty.value
            ? '生成已完成，但存在未保存的小纲修改；本地内容已保留'
            : '生成已完成，但权威小纲状态不匹配；本地内容已保留',
          correlationId: '',
        }
        return false
      }
      commitOutlineAuthorityState(loaded, { authorityWrite: true })
      replaceOutlineLocal(loaded.draft.content)
      outlineError.value = null
      outlineRecoveryKey.value = ''
      outlineOutcomeUnknown.value = false
      outlineAwaitingAuthority.value = false
      outlineGenerating.value = false
      installServerPendingOutlineOperation(outlineState.value)
      return true
    } catch (failure) {
      if (outlineGenerationIsCurrent(
        context.requestGeneration,
        context.targetProjectId,
        context.targetContextGeneration,
        context.targetChapterNumber,
        context.targetDraftId,
        context.targetDraftRevision,
        context.targetDraftHash,
      )) {
        outlineAwaitingAuthority.value = true
        outlineGenerating.value = true
        outlineError.value = {
          ...publicError(failure),
          code: 'ChapterOutlineGenerationRefreshFailed',
          message: '生成已完成，但刷新权威小纲失败；本地内容已保留',
        }
      }
      return false
    }
  }

  async function acceptOutlineOperation(result, context) {
    if (!outlineGenerationIsCurrent(
      context.requestGeneration,
      context.targetProjectId,
      context.targetContextGeneration,
      context.targetChapterNumber,
      context.targetDraftId,
      context.targetDraftRevision,
      context.targetDraftHash,
    )) return result
    if (
      context.recoverByKey !== undefined
      && !outlineReconciliationIdentityIsCurrent(context)
    ) return result
    if (
      outlineOperation.value
      && outlineOperation.value.operationId !== result.operationId
    ) return result
    const currentOperation = outlineOperation.value
    if (
      outlineAwaitingAuthority.value
      && currentOperation?.status === 'succeeded'
      && currentOperation.loaded === true
      && (
        result.status !== 'succeeded'
        || result.loaded !== true
        || result.loadedDraftRevision !== currentOperation.loadedDraftRevision
      )
    ) {
      outlineGenerating.value = true
      outlineError.value = {
        status: 0,
        code: 'ChapterOutlineGenerationOperationRegressed',
        message: '小纲生成操作状态与已知结果不一致；请继续核对原操作',
        correlationId: '',
      }
      return result
    }
    outlineOperation.value = result
    if (result.status === 'pending') {
      outlineOutcomeUnknown.value = true
      outlineAwaitingAuthority.value = false
      outlineGenerating.value = true
      outlineError.value = null
      return result
    }
    if (!(result.status === 'succeeded' && result.loaded === true)) {
      outlineRecoveryKey.value = ''
      outlineOutcomeUnknown.value = false
      outlineAwaitingAuthority.value = false
      outlineGenerating.value = false
      outlineError.value = result.status === 'failed'
        ? {
            status: 0,
            code: result.failureCode || 'ChapterOutlineGenerationFailed',
            message: '章节小纲生成失败，本地内容未改变',
            correlationId: '',
          }
        : null
      installServerPendingOutlineOperation(outlineState.value)
      return result
    }
    outlineAwaitingAuthority.value = true
    outlineGenerating.value = true
    await reloadOutlineGenerationAuthority(result, context)
    return result
  }

  async function generateOutlineDraft(command) {
    const currentDraft = outlineState.value?.draft
    const targetProjectId = projectId.value
    const targetChapterNumber = outlineState.value?.authoritativeChapterNumber
    if (
      !targetProjectId
      || !currentDraft
      || !Number.isInteger(targetChapterNumber)
    ) {
      throw new TypeError('An active ChapterOutline draft is required')
    }
    if (!isSafePlanningIdempotencyKey(command?.idempotencyKey)) {
      throw new TypeError('Invalid ChapterOutline idempotency key')
    }
    if (outlineState.value?.capabilities?.generate !== true) {
      throw new Error('章节小纲生成模型未就绪')
    }
    if (outlineDirty.value) throw new Error('请先保存本地小纲修改，再生成')
    if (
      outlineSaving.value
      || outlineConfirming.value
      || outlineGenerating.value
      || outlineReconciling.value
      || outlineOutcomeUnknown.value
      || outlineAwaitingAuthority.value
    ) {
      throw new Error('已有小纲操作正在进行')
    }
    const requestGeneration = outlineGenerationGuard.begin()
    const context = {
      requestGeneration,
      targetProjectId,
      targetContextGeneration: outlineContextGeneration,
      targetChapterNumber,
      targetDraftId: currentDraft.draftId,
      targetDraftRevision: currentDraft.draftRevision,
      targetDraftHash: currentDraft.contentHash,
      authorityFingerprint: outlineAuthorityFingerprint(outlineState.value),
    }
    outlineGenerating.value = true
    outlineOperation.value = null
    outlineRecoveryKey.value = command.idempotencyKey
    outlineOutcomeUnknown.value = false
    outlineAwaitingAuthority.value = false
    outlineError.value = null
    try {
      const result = await api.chapterOutlines.generateDraft(
        targetProjectId,
        targetChapterNumber,
        currentDraft.draftId,
        {
          draftRevision: currentDraft.draftRevision,
          draftHash: currentDraft.contentHash,
          idempotencyKey: command.idempotencyKey,
          authorInstructions: String(command.authorInstructions || ''),
        },
      )
      if (!outlineGenerationIsCurrent(
        requestGeneration,
        targetProjectId,
        context.targetContextGeneration,
        targetChapterNumber,
        currentDraft.draftId,
        currentDraft.draftRevision,
        currentDraft.contentHash,
      )) return result
      outlineOperation.value = result
      return await acceptOutlineOperation(result, context)
    } catch (failure) {
      if (!outlineGenerationIsCurrent(
        requestGeneration,
        targetProjectId,
        context.targetContextGeneration,
        targetChapterNumber,
        currentDraft.draftId,
        currentDraft.draftRevision,
        currentDraft.contentHash,
      )) throw failure
      if (!isUnknownTransportFailure(failure)) {
        outlineGenerating.value = false
        outlineOperation.value = null
        outlineRecoveryKey.value = ''
        outlineOutcomeUnknown.value = false
        outlineAwaitingAuthority.value = false
        outlineError.value = publicError(failure)
        throw failure
      }
      outlineOperation.value = null
      outlineOutcomeUnknown.value = true
      outlineGenerating.value = true
      const publicFailure = outlineUnknownFailure()
      outlineError.value = publicError(publicFailure)
      throw publicFailure
    } finally {
      if (
        outlineIsCurrent(
          outlineGenerationGuard,
          requestGeneration,
          targetProjectId,
          context.targetContextGeneration,
        )
        && !outlineDraftIdentityIsCurrent(context)
        && outlineOperation.value === null
        && outlineRecoveryKey.value === command.idempotencyKey
      ) {
        outlineGenerating.value = false
        outlineRecoveryKey.value = ''
        outlineOutcomeUnknown.value = false
        outlineAwaitingAuthority.value = false
      }
    }
  }

  async function reconcileOutlineGeneration() {
    const targetProjectId = projectId.value
    const targetChapterNumber = outlineState.value?.authoritativeChapterNumber
    const currentDraft = outlineState.value?.draft
    const targetDraftId = currentDraft?.draftId
    const operationId = outlineOperation.value?.operationId
    const recoveryKey = outlineRecoveryKey.value
    const recoverByKey = !operationId && outlineOutcomeUnknown.value && recoveryKey
    if (
      !targetProjectId
      || !Number.isInteger(targetChapterNumber)
      || !targetDraftId
      || (!operationId && !recoverByKey)
    ) {
      throw new Error('没有可核对的章节小纲生成操作')
    }
    if (outlineReconciling.value) throw new Error('小纲生成结果正在核对')
    const requestGeneration = outlineGenerationGuard.begin()
    const context = {
      requestGeneration,
      targetProjectId,
      targetContextGeneration: outlineContextGeneration,
      targetChapterNumber,
      targetDraftId,
      targetDraftRevision: currentDraft.draftRevision,
      targetDraftHash: currentDraft.contentHash,
      authorityFingerprint: outlineAuthorityFingerprint(outlineState.value),
      recoverByKey: Boolean(recoverByKey),
      recoveryKey,
      operationId,
    }
    outlineReconciling.value = true
    outlineGenerating.value = true
    try {
      const result = recoverByKey
        ? await api.chapterOutlines.getOperationByKey(
          targetProjectId,
          recoveryKey,
        )
        : await api.chapterOutlines.getOperation(
          targetProjectId,
          operationId,
        )
      if (!outlineGenerationIsCurrent(
        requestGeneration,
        targetProjectId,
        context.targetContextGeneration,
        targetChapterNumber,
        targetDraftId,
        context.targetDraftRevision,
        context.targetDraftHash,
      ) || !outlineReconciliationIdentityIsCurrent(context)) return result
      return await acceptOutlineOperation(result, context)
    } catch (failure) {
      if (outlineGenerationIsCurrent(
        requestGeneration,
        targetProjectId,
        context.targetContextGeneration,
        targetChapterNumber,
        targetDraftId,
        context.targetDraftRevision,
        context.targetDraftHash,
      ) && outlineReconciliationIdentityIsCurrent(context)) {
        outlineOutcomeUnknown.value = true
        outlineGenerating.value = true
        outlineError.value = publicError(failure)
      }
      throw failure
    } finally {
      if (outlineIsCurrent(
        outlineGenerationGuard,
        requestGeneration,
        targetProjectId,
        context.targetContextGeneration,
      )) {
        outlineReconciling.value = false
        installServerPendingOutlineOperation(outlineState.value)
      }
    }
  }

  function discardOutlineLocal() {
    replaceOutlineLocal(outlineState.value?.draft?.content)
  }

  function discardLocal() {
    localContent.value = canonicalPlanningContentForUi(state.value?.draft?.content)
    dirty.value = false
  }

  function invalidate() {
    stateGeneration += 1
    outlineContextGeneration += 1
    loadGuard.invalidate()
    mutationGuard.invalidate()
    generationGuard.invalidate()
    outlineLoadGuard.invalidate()
    outlineMutationGuard.invalidate()
    outlineGenerationGuard.invalidate()
    loading.value = false
    saving.value = false
    confirming.value = false
    generating.value = false
    reconciling.value = false
    generationOperation.value = null
    generationRecoveryKey.value = ''
    generationOutcomeUnknown.value = false
    awaitingAuthoritativeReload.value = false
    outlineLoading.value = false
    outlineSaving.value = false
    outlineConfirming.value = false
    outlineGenerating.value = false
    outlineReconciling.value = false
    outlineOperation.value = null
    outlineRecoveryKey.value = ''
    outlineOutcomeUnknown.value = false
    outlineAwaitingAuthority.value = false
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
    generationRecoveryKey,
    generationOutcomeUnknown,
    awaitingAuthoritativeReload,
    outlineState,
    outlineHistory,
    outlineLocalContent,
    outlineDirty,
    outlineError,
    outlineLoading,
    outlineSaving,
    outlineConfirming,
    outlineGenerating,
    outlineReconciling,
    outlineOperation,
    outlineRecoveryKey,
    outlineOutcomeUnknown,
    outlineAwaitingAuthority,
    load,
    ensureLoaded,
    createDraft,
    editLocal,
    saveDraft,
    confirmDraft,
    generateDraft,
    reconcileGeneration,
    loadOutline,
    ensureOutlineLoaded,
    createOutlineDraft,
    editOutlineLocal,
    saveOutlineDraft,
    confirmOutlineDraft,
    generateOutlineDraft,
    reconcileOutlineGeneration,
    discardOutlineLocal,
    discardLocal,
    invalidate,
  }
})
