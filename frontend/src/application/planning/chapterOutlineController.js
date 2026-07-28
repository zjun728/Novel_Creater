import { computed, ref } from 'vue'

import {
  planningStoryBlocksPath,
  projectBiblePath,
  projectOverviewPath,
} from '../../router/projectRoutes.js'

const hasText = value => String(value || '').trim().length > 0

export function createChapterOutlineController({
  store,
  projectId,
  keyFactory = () => globalThis.crypto.randomUUID(),
  operationStore = null,
} = {}) {
  if (!store || typeof projectId !== 'function') {
    throw new TypeError('store and projectId are required')
  }

  const historyOpen = ref(false)
  const authorInstructions = ref('')
  const notice = ref('')
  const activeProject = ref('')
  let projectTicket = 0
  const busy = computed(() => Boolean(
    store.outlineLoading
    || store.outlineSaving
    || store.outlineConfirming
    || store.outlineGenerating
    || store.outlineReconciling,
  ))
  const hasCriticalRecovery = computed(() => Boolean(
    store.outlineOutcomeUnknown || store.outlineAwaitingAuthority,
  ))
  const readOnly = computed(() => Boolean(
    store.outlineState?.lifecycle === 'archived'
    || store.outlineState?.draft?.status === 'superseded',
  ))
  const editable = computed(() => (
    !readOnly.value
    && store.outlineState?.capabilities?.editDraft === true
    && store.outlineState?.draft != null
  ))
  const canCreateDraft = computed(() => (
    store.outlineState?.lifecycle === 'active'
    && store.outlineState?.capabilities?.createDraft === true
    && !busy.value
  ))
  const canSave = computed(() => (
    editable.value
    && store.outlineDirty === true
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const canGenerate = computed(() => (
    editable.value
    && store.outlineState?.capabilities?.generate === true
    && store.outlineDirty !== true
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const canConfirm = computed(() => (
    editable.value
    && store.outlineState?.capabilities?.confirm === true
    && store.outlineState?.canonProjectionAuthority?.synchronized === true
    && !(store.outlineState?.reasons || []).some(reason => (
      /canon|projection|sync/i.test(String(reason))
    ))
    && store.outlineDirty !== true
    && !busy.value
    && !hasCriticalRecovery.value
  ))
  const editorLocked = computed(() => busy.value || hasCriticalRecovery.value)
  const localOverlay = computed(() => Boolean(
    store.outlineGenerating || store.outlineReconciling,
  ))
  const generationDisabledReason = computed(() => {
    if (hasCriticalRecovery.value) return '上次小纲生成结果尚未核对，请先恢复权威状态。'
    if (store.outlineDirty) return '请先保存本地修改，再使用 AI 生成。'
    if (!editable.value) return '当前章节小纲不可编辑。'
    if (store.outlineState?.capabilities?.generate !== true) {
      return '小纲模型尚未就绪；手工编辑仍可继续。'
    }
    if (busy.value) return '请等待当前小纲操作完成。'
    return ''
  })
  const recoveryActions = computed(() => {
    const reasons = new Set(store.outlineState?.reasons || [])
    const targetProjectId = String(projectId() || '')
    if (!targetProjectId) return []
    if (
      store.outlineState?.lifecycle === 'archived'
      || [...reasons].some(reason => /archived/i.test(reason))
    ) {
      return [{
        label: '返回项目概览',
        path: projectOverviewPath(targetProjectId),
      }]
    }
    if (reasons.has('planningOrProjectionUnavailable')) {
      return [
        {
          label: '去确认创作圣经',
          path: projectBiblePath(targetProjectId),
        },
        {
          label: '去补齐故事规划',
          path: planningStoryBlocksPath(targetProjectId),
        },
      ]
    }
    return []
  })
  const recovery = computed(() => recoveryActions.value[0] || null)

  function enterProject(nextProjectId) {
    const normalized = String(nextProjectId || '')
    if (normalized === activeProject.value) return false
    projectTicket += 1
    activeProject.value = normalized
    historyOpen.value = false
    authorInstructions.value = ''
    notice.value = ''
    return true
  }

  function operationContext() {
    return {
      projectId: String(projectId() || ''),
      ticket: projectTicket,
    }
  }

  function operationIsCurrent(context) {
    return (
      context.ticket === projectTicket
      && String(projectId() || '') === context.projectId
    )
  }

  async function hydrate({ force = false } = {}) {
    const targetProjectId = String(projectId() || '')
    if (!targetProjectId) return undefined
    enterProject(targetProjectId)
    return force
      ? await store.ensureOutlineLoaded(targetProjectId, { force: true })
      : await store.ensureOutlineLoaded(targetProjectId)
  }

  async function createManualDraft() {
    if (!canCreateDraft.value) return undefined
    const context = operationContext()
    const result = await store.createOutlineDraft(String(projectId()))
    if (operationIsCurrent(context)) {
      notice.value = '已建立空白章节小纲工作稿'
    }
    return result
  }

  function editLocal(content) {
    if (!editable.value || editorLocked.value) return false
    store.editOutlineLocal(content)
    return true
  }

  async function save() {
    if (!canSave.value) return undefined
    const context = operationContext()
    const result = await store.saveOutlineDraft()
    if (operationIsCurrent(context)) notice.value = '章节小纲工作稿已保存'
    return result
  }

  function exactOperationAuthorityIsInstalled(result) {
    const state = store.outlineState
    const draft = state?.draft
    return (
      result?.status === 'succeeded'
      && result?.loaded === true
      && result?.operationId
      && store.outlineOperation?.operationId === result.operationId
      && draft?.projectId === String(projectId() || '')
      && draft?.chapterNumber === state?.authoritativeChapterNumber
      && draft?.draftRevision === result.loadedDraftRevision
      && draft?.status === 'current'
      && !store.outlineOutcomeUnknown
      && !store.outlineAwaitingAuthority
      && !store.outlineGenerating
      && !store.outlineReconciling
      && !store.outlineError
    )
  }

  async function generate(instructions = authorInstructions.value) {
    if (!canGenerate.value) return undefined
    const context = operationContext()
    const result = await store.generateOutlineDraft({
      idempotencyKey: String(keyFactory()),
      authorInstructions: String(instructions || ''),
    })
    if (
      operationIsCurrent(context)
      && exactOperationAuthorityIsInstalled(result)
    ) {
      notice.value = 'AI 小纲已写入当前工作稿'
    }
    return result
  }

  async function reconcile() {
    const context = operationContext()
    const result = await store.reconcileOutlineGeneration()
    if (
      operationIsCurrent(context)
      && exactOperationAuthorityIsInstalled(result)
    ) {
      notice.value = '已恢复并核对小纲生成结果'
    }
    return result
  }

  async function confirm() {
    if (!canConfirm.value) return undefined
    const context = operationContext()
    const operationId = operationStore?.start?.({
      label: '正在确认章节小纲',
      detail: '确认会创建不可变小纲修订',
      blocking: true,
    })
    try {
      const result = await store.confirmOutlineDraft({
        idempotencyKey: String(keyFactory()),
      })
      if (operationIsCurrent(context)) notice.value = '已确认新的章节小纲修订'
      return result
    } finally {
      if (operationId) operationStore?.finish?.(operationId)
    }
  }

  function openHistory() {
    historyOpen.value = true
  }

  function closeHistory() {
    historyOpen.value = false
  }

  function hasCombinedLeaveRisk(planningController) {
    return Boolean(
      store.dirty
      || store.outlineDirty
      || store.generationOutcomeUnknown
      || store.awaitingAuthoritativeReload
      || store.generating
      || store.reconciling
      || store.outlineOutcomeUnknown
      || store.outlineAwaitingAuthority
      || store.outlineGenerating
      || store.outlineReconciling
      || hasText(planningController?.authorInstructions?.value)
      || hasText(authorInstructions.value),
    )
  }

  return {
    historyOpen,
    authorInstructions,
    notice,
    busy,
    hasCriticalRecovery,
    readOnly,
    editable,
    canCreateDraft,
    canSave,
    canGenerate,
    canConfirm,
    editorLocked,
    localOverlay,
    generationDisabledReason,
    recovery,
    recoveryActions,
    enterProject,
    hydrate,
    createManualDraft,
    editLocal,
    save,
    generate,
    reconcile,
    confirm,
    openHistory,
    closeHistory,
    hasCombinedLeaveRisk,
  }
}
