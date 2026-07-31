import { computed, nextTick, ref, toRef } from 'vue'

const REASON_GROUPS = {
  selection_missing: '请选择种子后继续。', seed_missing: '请选择种子后继续。',
  contract_missing: '请完成或重新签署创作契约。', contract_not_ready: '请完成或重新签署创作契约。', contract_revision_replaced: '请完成或重新签署创作契约。',
  contract_basis_invalid: '请完成或重新签署创作契约。', contract_unavailable: '请完成或重新签署创作契约。',
  selection_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_identity_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', seed_generation_changed: '内容已固定为项目永久基线，请查看历史记录。', contract_revision_changed: '内容已固定为项目永久基线，请查看历史记录。', creation_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', style_contract_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_policy_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_head_changed: '内容已固定为项目永久基线，请查看历史记录。', bible_revision_replaced: '内容已固定为项目永久基线，请查看历史记录。',
  project_archived: '项目已归档，只能查阅。', bible_read_only: '项目已归档，只能查阅。',
}

export const bibleReasonLabel = reason => REASON_GROUPS[reason] || `状态需重新核对（${reason}）`

const emptyBible = () => ({
  premiseAndPromise: '', powerOrProgressionSystem: '', protagonist: '', toneAndNarrativeBoundaries: '',
  worldRules: [], coreCast: [], factions: [], longTermConflicts: [], relationshipDynamics: [],
  continuityGuardrails: [], openDesignQuestions: [],
})
const clone = value => value == null ? value : JSON.parse(JSON.stringify(value))
const isClientError = failure => Number(failure?.status) >= 400 && Number(failure?.status) < 500

export function createBibleWorkspaceController({
  store, projectId, isArchived = () => false, keyFactory = () => crypto.randomUUID(),
  planningReady = () => false,
  focusError = () => {}, focusConfirm = () => {}, focusTrigger = () => {}, focusStatus = () => {}, confirmLeave = () => true,
} = {}) {
  if (!store || typeof projectId !== 'function') throw new TypeError('store and projectId are required')
  const working = ref(null); const confirmOpen = ref(false); const historyOpen = ref(false); const errorSummary = ref(null); const confirmTrigger = ref(null)
  const recoveryCommand = ref(null)
  const attempts = new Map()
  let generation = 0
  let activeProject = ''
  const busy = computed(() => Boolean(store.loading || store.saving || store.confirming || store.generating || store.historyLoading))
  const hasDraftBody = computed(() => store.draft?.draft != null)
  const hasHeadBody = computed(() => store.head?.bible != null)
  const mode = computed(() => {
    if (isArchived() || store.readOnly || store.head?.lifecycle === 'archived') return 'archived'
    if (store.draft?.status === 'superseded') return 'superseded'
    if (hasDraftBody.value) return 'draft'
    if (hasHeadBody.value) return 'head'
    return 'first'
  })
  const activeArtifact = computed(() => {
    // Archived projects preserve an unsaved/superseded draft for read-only recovery.
    // Every displayed concern below (body, status, reasons) uses this same artifact.
    if (mode.value === 'archived') return store.draft?.draft != null ? store.draft : store.head
    return mode.value === 'head' ? store.head : store.draft
  })
  const activeBible = computed(() => activeArtifact.value?.draft ?? activeArtifact.value?.bible ?? (store.draft?.canEdit === true ? emptyBible() : null))
  const activeStatus = computed(() => activeArtifact.value?.status || '')
  const activeReasons = computed(() => [...(activeArtifact.value?.reasons || [])])
  const editable = computed(() => (mode.value === 'draft' || mode.value === 'first') && store.canEdit === true)
  const canSave = computed(() => editable.value && store.dirty === true && !busy.value)
  const canConfirm = computed(() => editable.value && store.canConfirm === true && store.dirty !== true && !busy.value)
  const canGenerate = toRef(() => editable.value && planningReady() === true && store.dirty !== true && !busy.value)
  const generationDisabledReason = toRef(() => {
    if (store.dirty === true) return '请先保存本地编辑，再使用 AI 生成。'
    if (!editable.value) return '当前创作圣经不可编辑。'
    if (planningReady() !== true) return '请先为 planning 任务配置可用模型。'
    if (busy.value) return '请等待当前操作完成。'
    return ''
  })
  const confirmPreview = computed(() => clone(store.draft?.draft || null))
  const reasonLabels = computed(() => activeReasons.value.map(bibleReasonLabel))
  function ticket() { return { project: String(projectId() || ''), generation } }
  function current(value) { return value.project === String(projectId() || '') && value.project === activeProject && value.generation === generation }
  function publicFailure(failure) {
    const status = Number(failure?.status || store.error?.status || store.conflict?.status || 0)
    const code = String(failure?.code || store.error?.code || store.conflict?.code || 'request_failed')
    const outcomeUnknown = code === 'outcome_unknown' || code === 'BibleGenerationRetryable'
    return {
      status,
      code,
      message: outcomeUnknown
        ? '结果尚未确认，请先重新核对'
        : status === 409
          ? '保存冲突：本地编辑仍保留，请重新加载权威版本后再继续。'
          : '创作圣经操作失败，请重试。',
      correlationId: String(failure?.correlationId || store.error?.correlationId || ''),
    }
  }
  function rememberRecovery(type, value, params = {}) {
    if (!current(value)) return
    recoveryCommand.value = { type, project: value.project, generation: value.generation, ...params }
  }
  function clearFailure(value) {
    if (!current(value)) return
    errorSummary.value = null
    recoveryCommand.value = null
  }
  function setError(failure, value, recoveryType, params) {
    if (!current(value)) return
    errorSummary.value = publicFailure(failure)
    rememberRecovery(recoveryType, value, params)
    nextTick(() => { if (current(value)) focusError() })
  }
  function attemptKey() { const identity = `${projectId()}:${store.draft?.draftVersion ?? ''}:${store.head?.revision ?? ''}`; if (!attempts.has(identity)) attempts.set(identity, keyFactory()); return [identity, attempts.get(identity)] }

  async function hydrate() {
    const targetProject = String(projectId() || '')
    if (!targetProject) return null
    generation += 1
    activeProject = targetProject
    working.value = null; confirmOpen.value = false; historyOpen.value = false
    errorSummary.value = null; recoveryCommand.value = null; confirmTrigger.value = null; attempts.clear()
    const value = ticket()
    try {
      await store.load(targetProject, { readOnly: isArchived() })
      if (!current(value)) return undefined
      working.value = clone(activeBible.value)
      return working.value
    } catch (failure) {
      if (!current(value)) return undefined
      setError(failure, value, 'hydrate'); throw failure
    }
  }
  function edit(value) { if (!editable.value || busy.value) return; working.value = clone(value); store.edit(working.value) }
  async function save() {
    if (!canSave.value) return undefined
    const value = ticket(); const savedWorking = clone(working.value)
    try {
      const saved = await store.save(value.project, savedWorking)
      if (!current(value)) return undefined
      working.value = clone(saved?.draft || store.draft?.draft || working.value)
      clearFailure(value)
      return saved
    } catch (failure) {
      if (!current(value)) return undefined
      const status = Number(failure?.status || store.error?.status || store.conflict?.status || 0)
      setError(failure, value, status === 409 ? 'reloadAuthoritative' : 'save')
      throw failure
    }
  }
  function openConfirm(trigger) {
    if (!canConfirm.value) return false
    const value = ticket(); confirmTrigger.value = trigger || null; confirmOpen.value = true
    nextTick(() => { if (current(value)) focusConfirm() })
    return true
  }
  function closeConfirm() {
    const value = ticket(); const trigger = confirmTrigger.value
    confirmOpen.value = false
    nextTick(() => { if (current(value)) { focusTrigger(); trigger?.focus?.() } })
  }
  async function confirm() {
    if (!canConfirm.value) return undefined
    const value = ticket()
    const [identity, idempotencyKey] = attemptKey()
    try {
      const result = await store.confirm(value.project, { idempotencyKey })
      if (!current(value)) return undefined
      working.value = clone(result?.bible || store.head?.bible || null)
      confirmOpen.value = false
      clearFailure(value)
      nextTick(() => { if (current(value)) focusStatus() })
      return result
    } catch (failure) {
      if (!current(value)) return undefined
      if (isClientError(failure)) attempts.delete(identity)
      const status = Number(failure?.status || store.error?.status || 0)
      const code = String(failure?.code || store.error?.code || '')
      setError(failure, value, status >= 500 || code === 'outcome_unknown' ? 'confirm' : status === 409 ? 'reloadAuthoritative' : 'reconcile')
      throw failure
    }
  }
  async function generate(authorInstructions = '') {
    if (!canGenerate.value) return undefined
    const value = ticket()
    try {
      const result = await store.generate(value.project, {
        authorInstructions: String(authorInstructions || ''),
        idempotencyKey: keyFactory(),
      })
      if (!current(value)) return undefined
      if (result?.status === 'succeeded') {
        working.value = clone(store.draft?.draft || null)
        clearFailure(value)
        nextTick(() => { if (current(value)) focusStatus() })
      } else if (result?.status === 'failed' || result?.status === 'outcome_unknown') {
        setError({
          status: result.status === 'outcome_unknown' ? 503 : 422,
          code: result.publicErrorCode || result.status,
        }, value, 'reconcile')
      }
      return result
    } catch (failure) {
      if (!current(value)) return undefined
      setError(failure, value, 'reconcile')
      throw failure
    }
  }
  async function openHistory() {
    const value = ticket(); historyOpen.value = true
    try {
      const result = await store.loadHistory(value.project, { append: false })
      if (!current(value)) return undefined
      clearFailure(value); return result
    }
    catch (failure) { if (!current(value)) return undefined; setError(failure, value, 'history'); throw failure }
  }
  async function showHistoryDetail(revision) {
    const value = ticket()
    const safeRevision = Number(revision)
    try {
      const result = await store.loadHistoryDetail(value.project, safeRevision)
      if (!current(value)) return undefined
      clearFailure(value); return result
    }
    catch (failure) { if (!current(value)) return undefined; setError(failure, value, 'historyDetail', { revision: safeRevision }); throw failure }
  }
  async function loadHistoryPage(beforeRevision) {
    const value = ticket(); const safeBeforeRevision = Number(beforeRevision)
    try {
      const result = await store.loadHistory(value.project, { append: true, beforeRevision: safeBeforeRevision })
      if (!current(value)) return undefined
      clearFailure(value); return result
    }
    catch (failure) { if (!current(value)) return undefined; setError(failure, value, 'historyPage', { beforeRevision: safeBeforeRevision }); throw failure }
  }
  function loadMoreHistory() {
    if (busy.value || store.historyNextBeforeRevision == null) return undefined
    return loadHistoryPage(store.historyNextBeforeRevision)
  }
  async function retryFailure() {
    const command = recoveryCommand.value
    if (!command || !current(command) || busy.value) return undefined
    errorSummary.value = null; recoveryCommand.value = null
    if (command.type === 'save') return save()
    if (command.type === 'confirm') return confirm()
    if (command.type === 'history') return openHistory()
    if (command.type === 'historyDetail') return showHistoryDetail(command.revision)
    if (command.type === 'historyPage') return loadHistoryPage(command.beforeRevision)
    if (['hydrate', 'reloadAuthoritative', 'reconcile'].includes(command.type)) return hydrate()
    return undefined
  }
  function requestLeave() { if (busy.value) return false; return store.dirty !== true || confirmLeave() }
  function beforeUnload(event) { if (store.dirty !== true && !busy.value) return undefined; event.preventDefault(); event.returnValue = ''; return '' }
  return { working, confirmOpen, historyOpen, errorSummary, recoveryCommand, busy, mode, activeStatus, activeReasons, editable, canSave, canConfirm, canGenerate, generationDisabledReason, confirmPreview, reasonLabels, hydrate, edit, save, openConfirm, closeConfirm, confirm, generate, openHistory, showHistoryDetail, loadMoreHistory, retryFailure, requestLeave, beforeUnload, confirmLeave: requestLeave }
}
