import { computed, nextTick, ref } from 'vue'

const REASON_LABELS = {
  planning_not_ready: '规划尚未就绪，暂不能确认。',
  bible_edit_denied: '当前状态不允许编辑创作圣经。',
  bible_confirm_denied: '当前状态不允许确认创作圣经。',
  bible_read_only: '归档项目为只读状态。',
}

const emptyBible = () => ({
  premiseAndPromise: '', powerOrProgressionSystem: '', protagonist: '', toneAndNarrativeBoundaries: '',
  worldRules: [], coreCast: [], factions: [], longTermConflicts: [], relationshipDynamics: [],
  continuityGuardrails: [], openDesignQuestions: [],
})

// Bible DTOs are deliberately JSON-shaped. JSON cloning also unwraps Vue's nested proxies.
const clone = value => value == null ? value : JSON.parse(JSON.stringify(value))
const isClientError = failure => Number(failure?.status) >= 400 && Number(failure?.status) < 500

export function createBibleWorkspaceController({
  store, projectId, isArchived = () => false, keyFactory = () => crypto.randomUUID(),
  focusError = () => {}, focusConfirm = () => {}, focusTrigger = () => {}, confirmLeave = () => true,
} = {}) {
  if (!store || typeof projectId !== 'function') throw new TypeError('store and projectId are required')

  const working = ref(null)
  const confirmOpen = ref(false)
  const historyOpen = ref(false)
  const errorSummary = ref(null)
  const confirmTrigger = ref(null)
  const attempts = new Map()
  const busy = computed(() => Boolean(store.loading || store.saving || store.confirming || store.cloning || store.historyLoading))
  const editable = computed(() => !isArchived() && !store.readOnly && store.canEdit === true)
  const canSave = computed(() => editable.value && store.dirty === true && !busy.value)
  const canConfirm = computed(() => !isArchived() && !store.readOnly && store.canConfirm === true && store.dirty !== true && !busy.value)
  const confirmPreview = computed(() => clone(store.draft?.draft || null))
  const reasonLabels = computed(() => (store.reasons || []).map(reason => REASON_LABELS[reason] || reason))

  function setError(failure) {
    errorSummary.value = { message: String(failure?.message || '请求失败'), status: Number(failure?.status || 0) }
    nextTick(focusError)
  }

  function attemptKey() {
    const identity = `${projectId()}:${store.draft?.draftVersion ?? ''}:${store.head?.revision ?? ''}`
    if (!attempts.has(identity)) attempts.set(identity, keyFactory())
    return [identity, attempts.get(identity)]
  }

  async function hydrate() {
    if (!projectId()) return null
    await store.load(projectId(), { readOnly: isArchived() })
    const draft = store.draft?.draft
    working.value = clone(draft == null && store.draft?.canEdit === true ? emptyBible() : draft)
    return working.value
  }

  function edit(value) {
    if (!editable.value || busy.value) return
    working.value = clone(value)
    store.edit(working.value)
  }

  async function save() {
    if (!canSave.value) return undefined
    try {
      const saved = await store.save(projectId(), working.value)
      working.value = clone(saved?.draft || store.draft?.draft || working.value)
      return saved
    } catch (failure) {
      setError(failure)
      throw failure
    }
  }

  function openConfirm(trigger) {
    if (!canConfirm.value) return false
    confirmTrigger.value = trigger || null
    confirmOpen.value = true
    nextTick(focusConfirm)
    return true
  }

  function closeConfirm() {
    confirmOpen.value = false
    nextTick(() => {
      focusTrigger()
      confirmTrigger.value?.focus?.()
    })
  }

  async function confirm() {
    if (!canConfirm.value) return undefined
    const [identity, idempotencyKey] = attemptKey()
    try {
      const result = await store.confirm(projectId(), { idempotencyKey })
      working.value = null
      closeConfirm()
      return result
    } catch (failure) {
      if (isClientError(failure)) attempts.delete(identity)
      setError(failure)
      throw failure
    }
  }

  async function cloneRevision(source) {
    if (busy.value || isArchived() || source?.canClone !== true) return undefined
    try {
      const result = await store.clone(projectId(), { sourceRevision: source.revision })
      working.value = clone(result?.draft || store.draft?.draft || null)
      return result
    } catch (failure) {
      setError(failure)
      throw failure
    }
  }

  async function openHistory() {
    historyOpen.value = true
    return store.loadHistory(projectId(), { append: false })
  }

  async function showHistoryDetail(revision) { return store.loadHistoryDetail(projectId(), revision) }
  async function loadMoreHistory() {
    if (busy.value || store.historyNextBeforeRevision == null) return undefined
    return store.loadHistory(projectId(), { append: true, beforeRevision: store.historyNextBeforeRevision })
  }

  function requestLeave() { return store.dirty !== true || confirmLeave() }
  function beforeUnload(event) {
    if (store.dirty !== true) return undefined
    event.preventDefault()
    event.returnValue = ''
    return ''
  }

  return {
    working, confirmOpen, historyOpen, errorSummary, busy, editable, canSave, canConfirm,
    confirmPreview, reasonLabels, hydrate, edit, save, openConfirm, closeConfirm, confirm,
    clone: cloneRevision, openHistory, showHistoryDetail, loadMoreHistory, requestLeave,
    beforeUnload, confirmLeave: requestLeave,
  }
}
