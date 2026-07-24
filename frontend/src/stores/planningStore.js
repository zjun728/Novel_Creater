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
  const loadGuard = createLatestRequestGuard()
  const mutationGuard = createLatestRequestGuard()
  let stateGeneration = 0

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (!normalized) throw new TypeError('projectId is required')
    if (projectId.value !== normalized) {
      stateGeneration += 1
      loadGuard.invalidate()
      mutationGuard.invalidate()
      projectId.value = normalized
      state.value = null
      history.value = []
      localContent.value = null
      dirty.value = false
      error.value = null
      loading.value = false
      saving.value = false
      confirming.value = false
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

  async function createDraft(nextProjectId, command) {
    const targetProjectId = enterProject(nextProjectId)
    if (saving.value || confirming.value) {
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
    if (saving.value || confirming.value) {
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

  function discardLocal() {
    localContent.value = editableContent(state.value?.draft?.content)
    dirty.value = false
  }

  function invalidate() {
    stateGeneration += 1
    loadGuard.invalidate()
    mutationGuard.invalidate()
    loading.value = false
    saving.value = false
    confirming.value = false
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
    load,
    createDraft,
    editLocal,
    saveDraft,
    confirmDraft,
    discardLocal,
    invalidate,
  }
})
