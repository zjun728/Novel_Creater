import { computed, nextTick, ref } from 'vue'

const REASON_GROUPS = {
  selection_missing: '请选择种子后继续。', seed_missing: '请选择种子后继续。',
  contract_missing: '请完成或重新签署创作契约。', contract_not_ready: '请完成或重新签署创作契约。', contract_revision_replaced: '请完成或重新签署创作契约。',
  contract_basis_invalid: '请完成或重新签署创作契约。', contract_unavailable: '请完成或重新签署创作契约。',
  selection_revision_changed: '内容已过期，请调整未来设计。', seed_identity_changed: '内容已过期，请调整未来设计。', seed_revision_changed: '内容已过期，请调整未来设计。', seed_generation_changed: '内容已过期，请调整未来设计。', contract_revision_changed: '内容已过期，请调整未来设计。', creation_contract_changed: '内容已过期，请调整未来设计。', style_contract_changed: '内容已过期，请调整未来设计。', bible_policy_changed: '内容已过期，请调整未来设计。', bible_head_changed: '内容已过期，请调整未来设计。', bible_revision_replaced: '内容已过期，请调整未来设计。',
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
  focusError = () => {}, focusConfirm = () => {}, focusTrigger = () => {}, focusStatus = () => {}, confirmLeave = () => true,
} = {}) {
  if (!store || typeof projectId !== 'function') throw new TypeError('store and projectId are required')
  const working = ref(null); const confirmOpen = ref(false); const historyOpen = ref(false); const errorSummary = ref(null); const confirmTrigger = ref(null)
  const attempts = new Map()
  const busy = computed(() => Boolean(store.loading || store.saving || store.confirming || store.cloning || store.historyLoading))
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
  const confirmPreview = computed(() => clone(store.draft?.draft || null))
  const reasonLabels = computed(() => activeReasons.value.map(bibleReasonLabel))
  const cloneSource = computed(() => {
    if (mode.value === 'superseded' && store.draft?.canClone === true && store.draft?.draftId) return { sourceDraftId: store.draft.draftId }
    if (mode.value === 'head' && store.head?.canClone === true) return { sourceRevision: store.head.revision }
    return null
  })

  function setError(failure) { errorSummary.value = { message: String(failure?.message || '请求失败'), status: Number(failure?.status || 0) }; nextTick(focusError) }
  function attemptKey() { const identity = `${projectId()}:${store.draft?.draftVersion ?? ''}:${store.head?.revision ?? ''}`; if (!attempts.has(identity)) attempts.set(identity, keyFactory()); return [identity, attempts.get(identity)] }

  async function hydrate() {
    if (!projectId()) return null
    try {
      await store.load(projectId(), { readOnly: isArchived() })
      working.value = clone(activeBible.value)
      return working.value
    } catch (failure) { setError(failure); throw failure }
  }
  function edit(value) { if (!editable.value || busy.value) return; working.value = clone(value); store.edit(working.value) }
  async function save() { if (!canSave.value) return undefined; try { const saved = await store.save(projectId(), working.value); working.value = clone(saved?.draft || store.draft?.draft || working.value); return saved } catch (failure) { setError(failure); throw failure } }
  function openConfirm(trigger) { if (!canConfirm.value) return false; confirmTrigger.value = trigger || null; confirmOpen.value = true; nextTick(focusConfirm); return true }
  function closeConfirm() { confirmOpen.value = false; nextTick(() => { focusTrigger(); confirmTrigger.value?.focus?.() }) }
  async function confirm() {
    if (!canConfirm.value) return undefined
    const [identity, idempotencyKey] = attemptKey()
    try {
      const result = await store.confirm(projectId(), { idempotencyKey })
      working.value = clone(result?.bible || store.head?.bible || null)
      confirmOpen.value = false
      nextTick(focusStatus)
      return result
    } catch (failure) { if (isClientError(failure)) attempts.delete(identity); setError(failure); throw failure }
  }
  async function cloneRevision(source = cloneSource.value) {
    if (busy.value || isArchived() || !source) return undefined
    const command = source.sourceDraftId ? { sourceDraftId: source.sourceDraftId }
      : source.sourceRevision ? { sourceRevision: source.sourceRevision }
        : source.draftId ? { sourceDraftId: source.draftId } : { sourceRevision: source.revision }
    try { const result = await store.clone(projectId(), command); working.value = clone(result?.draft || store.draft?.draft || null); return result } catch (failure) { setError(failure); throw failure }
  }
  async function openHistory() { historyOpen.value = true; try { return await store.loadHistory(projectId(), { append: false }) } catch (failure) { setError(failure); throw failure } }
  async function showHistoryDetail(revision) { try { return await store.loadHistoryDetail(projectId(), revision) } catch (failure) { setError(failure); throw failure } }
  async function loadMoreHistory() { if (busy.value || store.historyNextBeforeRevision == null) return undefined; try { return await store.loadHistory(projectId(), { append: true, beforeRevision: store.historyNextBeforeRevision }) } catch (failure) { setError(failure); throw failure } }
  function requestLeave() { return store.dirty !== true || confirmLeave() }
  function beforeUnload(event) { if (store.dirty !== true) return undefined; event.preventDefault(); event.returnValue = ''; return '' }
  return { working, confirmOpen, historyOpen, errorSummary, busy, mode, activeStatus, activeReasons, editable, canSave, canConfirm, confirmPreview, reasonLabels, cloneSource, hydrate, edit, save, openConfirm, closeConfirm, confirm, clone: cloneRevision, openHistory, showHistoryDetail, loadMoreHistory, requestLeave, beforeUnload, confirmLeave: requestLeave }
}
