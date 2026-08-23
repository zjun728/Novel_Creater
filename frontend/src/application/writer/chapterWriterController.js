import { computed, ref } from 'vue'

import { generateId } from '../../utils/id.js'
import { sha256Text } from '../../utils/sha256Text.js'
import { createDraftOperationCoordinator } from './draftOperationCoordinator.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const IDEMPOTENCY_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const LOCAL_OPERATION_TYPES = new Set([
  'rewrite_selection', 'polish_selection',
  'expand_selection', 'compress_selection',
])

function currentBusy(value) {
  const resolved = typeof value === 'function' ? value() : value
  return Boolean(resolved?.value ?? resolved)
}

function persistedAuthority(autosave) {
  const revision = autosave.persistedRevision?.value
  const contentHash = autosave.persistedHash?.value
  if (
    !Number.isInteger(revision)
    || revision < 1
    || typeof contentHash !== 'string'
    || !CONTENT_HASH.test(contentHash)
  ) {
    throw new TypeError('persisted working draft authority is required')
  }
  return { revision, contentHash }
}

function unavailable(label) {
  return () => Promise.reject(new TypeError(`${label} is required`))
}

function candidateSnapshot(value) {
  if (
    !value
    || typeof value.id !== 'string'
    || !value.id
    || typeof value.content !== 'string'
    || typeof value.contentHash !== 'string'
    || !CONTENT_HASH.test(value.contentHash)
  ) throw new TypeError('candidate is required')
  return Object.freeze({
    id: value.id,
    content: value.content,
    contentHash: value.contentHash,
  })
}

function requireCandidateLoadResult(result, candidate, authority) {
  const sessionId = result?.session?.id
  const draft = result?.workingDraft
  const returnedCandidate = Array.isArray(result?.candidates)
    ? result.candidates.find(item => item?.id === candidate.id)
    : null
  if (
    typeof result?.projectId !== 'string'
    || !result.projectId
    || result.activeDraftOperationId !== null
    || typeof sessionId !== 'string'
    || !sessionId
    || draft?.chapterSessionId !== sessionId
    || draft?.revision !== authority.revision + 1
    || draft?.content !== candidate.content
    || draft?.contentHash !== candidate.contentHash
    || returnedCandidate?.content !== candidate.content
    || returnedCandidate?.contentHash !== candidate.contentHash
  ) throw new TypeError('Invalid candidate load workspace')
  return result
}

export function createChapterWriterController({
  autosave,
  freezeCandidate: freezeCandidateRequest,
  loadCandidate: loadCandidateRequest,
  createDraftOperation,
  readDraftOperation,
  listDraftOperationEvents,
  cancelDraftOperation,
  reloadWorkspace,
  undoLocalDraft: undoLocalDraftRequest,
  idFactory = generateId,
  pollScheduler,
  writeBusy = false,
} = {}) {
  if (!autosave
    || typeof autosave.edit !== 'function'
    || typeof autosave.flush !== 'function'
    || typeof autosave.reset !== 'function') {
    throw new TypeError('autosave is required')
  }

  const coordinatorRevision = ref(0)
  const coordinator = createDraftOperationCoordinator({
    startOperation: createDraftOperation || unavailable('createDraftOperation'),
    readOperation: readDraftOperation || unavailable('readDraftOperation'),
    listEvents: listDraftOperationEvents || unavailable('listDraftOperationEvents'),
    cancelOperation: cancelDraftOperation || unavailable('cancelDraftOperation'),
    reloadWorkspace: reloadWorkspace || unavailable('reloadWorkspace'),
    idFactory,
    onChange: () => { coordinatorRevision.value += 1 },
    ...(pollScheduler ? { pollScheduler } : {}),
  })
  let editGeneration = 0
  let contextGeneration = 0
  let actionGeneration = 0
  let activeAction = null
  let retryFence = null
  let disposed = false
  const actionLock = ref(false)
  const actionBusy = computed(() => actionLock.value)
  const authorInstructionState = ref('')
  const selectionState = ref(null)
  const undoEligibilityState = ref(null)
  const restoredSelectionState = ref(null)
  const recoveredPartialOperationId = ref(null)
  const authorInstruction = computed(() => authorInstructionState.value)
  const selection = computed(() => selectionState.value)
  const streamingPreview = computed(() => {
    coordinatorRevision.value
    return coordinator.busy && coordinator.previewKind === 'draft'
      ? coordinator.preview
      : null
  })
  const replacementPreview = computed(() => {
    coordinatorRevision.value
    return coordinator.busy && coordinator.previewKind === 'replacement'
      ? coordinator.preview
      : null
  })
  const undoAvailable = computed(() => undoEligibilityState.value !== null)
  const restoredSelection = computed(() => restoredSelectionState.value)
  const operationCancellable = computed(() => {
    coordinatorRevision.value
    const status = coordinator.operation?.status
    return actionLock.value
      && ['generate', 'resume', 'local'].includes(activeAction?.kind)
      && !coordinator.cancelling
      && (status === 'starting' || status === 'running')
  })
  const editorText = computed(() => (
    actionLock.value
    && ['generate', 'resume', 'local'].includes(activeAction?.kind)
    && streamingPreview.value !== null
      ? streamingPreview.value
      : String(autosave.text?.value ?? '')
  ))
  const operationStatus = computed(() => {
    coordinatorRevision.value
    return coordinator.status
  })
  const operationRetryAvailable = computed(() => {
    coordinatorRevision.value
    return coordinator.retryAvailable && !actionLock.value
  })
  const recoverablePartialDraft = computed(() => {
    coordinatorRevision.value
    const operation = coordinator.operation
    if (
      operation?.status !== 'failed'
      || operation.operationType !== 'generate_new'
      || operation.id === recoveredPartialOperationId.value
      || typeof operation.partialOutput !== 'string'
      || operation.partialOutput.trim() === ''
    ) return null
    return Object.freeze({
      operationId: operation.id,
      content: operation.partialOutput,
      scalarCount: operation.partialOutputScalars,
    })
  })
  const operationStatusText = computed(() => {
    coordinatorRevision.value
    const status = operationStatus.value
    if (coordinator.cancelling) return '正在取消'
    if (coordinator.reconnecting) return '正在恢复连接'
    if (
      status === 'failed'
      || status === 'request_rejected'
      || status === 'operation_invalid'
      || coordinator.failureCode === 'workspace_reload_failed'
    ) return '生成失败'
    if (actionLock.value && activeAction?.kind === 'generate' && status === 'idle') {
      return '正在生成'
    }
    if (status === 'starting' || status === 'running') return '正在生成'
    if (status === 'completed') return '生成完成'
    if (status === 'cancelled') {
      return coordinator.operation?.resultWorkingDraftRevision === null
        ? '已停止，正文未改变'
        : '已停止，已保留生成内容'
    }
    if (status === 'expired') return '生成已失效'
    if (status === 'unknown') return '生成失败'
    return ''
  })

  const beforeUnloadRisk = computed(() => {
    const status = autosave.status?.value
    return Boolean(
      autosave.dirty?.value
      || status === 'saving'
      || status === 'failed'
      || status === 'conflict'
      || actionLock.value
      || operationRetryAvailable.value
      || currentBusy(writeBusy)
    )
  })

  function touchCoordinator() {
    coordinatorRevision.value += 1
  }

  function isActionCurrent(token) {
    return !disposed && activeAction?.token === token
  }

  function resyncIfUnchanged(workspace, fence) {
    if (
      workspace
      && editGeneration === fence.editGeneration
      && contextGeneration === fence.contextGeneration
      && autosave.text?.value === fence.visibleText
    ) {
      autosave.reset(workspace)
      return true
    }
    return false
  }

  async function flushPersistedDraft() {
    try {
      const flushed = await autosave.flush()
      const status = autosave.status?.value
      return flushed === true
        && autosave.dirty?.value === false
        && status !== 'failed'
        && status !== 'conflict'
    } catch {
      return false
    }
  }

  function edit(nextText) {
    if (actionLock.value || currentBusy(writeBusy)) {
      editGeneration += 1
      return false
    }
    const before = autosave.text?.value
    const changed = autosave.edit(nextText)
    if (autosave.text?.value !== before) {
      editGeneration += 1
      undoEligibilityState.value = null
      restoredSelectionState.value = null
    }
    return changed
  }

  function setAuthorInstruction(nextInstruction) {
    if (actionLock.value || currentBusy(writeBusy)) return false
    authorInstructionState.value = String(nextInstruction ?? '')
    return true
  }

  function setSelection(nextSelection) {
    if (actionLock.value || currentBusy(writeBusy)) return false
    selectionState.value = nextSelection ?? null
    return true
  }

  function invalidateAction() {
    actionGeneration += 1
    activeAction = null
    actionLock.value = false
  }

  function resetContext() {
    coordinator.resetContext()
    touchCoordinator()
    contextGeneration += 1
    retryFence = null
    invalidateAction()
    authorInstructionState.value = ''
    selectionState.value = null
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    recoveredPartialOperationId.value = null
  }

  function dispose() {
    if (disposed) return
    coordinator.dispose()
    touchCoordinator()
    disposed = true
    contextGeneration += 1
    retryFence = null
    invalidateAction()
    authorInstructionState.value = ''
    selectionState.value = null
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    recoveredPartialOperationId.value = null
  }

  function claimAction(kind) {
    if (disposed || actionLock.value || currentBusy(writeBusy)) return null
    const token = ++actionGeneration
    activeAction = { token, kind }
    actionLock.value = true
    return token
  }

  function releaseAction(token) {
    if (activeAction?.token !== token) return
    activeAction = null
    actionLock.value = false
  }

  function nextCandidateIdempotencyKey() {
    let idempotencyKey
    try {
      idempotencyKey = idFactory()
    } catch {
      throw new TypeError('candidate idempotency key is invalid')
    }
    if (typeof idempotencyKey !== 'string' || !IDEMPOTENCY_KEY.test(idempotencyKey)) {
      throw new TypeError('candidate idempotency key is invalid')
    }
    return idempotencyKey
  }

  async function saveCandidate() {
    const token = claimAction('candidate')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    try {
      if (typeof freezeCandidateRequest !== 'function') throw new TypeError('freezeCandidate is required')
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      const fence = {
        editGeneration,
        contextGeneration,
        visibleText: autosave.text?.value,
      }
      const authority = persistedAuthority(autosave)
      const result = await freezeCandidateRequest({
        expectedWorkingDraftRevision: authority.revision,
        expectedContentHash: authority.contentHash,
        idempotencyKey: nextCandidateIdempotencyKey(),
      })
      if (!isActionCurrent(token)) return null
      resyncIfUnchanged(result, fence)
      return result
    } finally {
      releaseAction(token)
    }
  }

  async function loadCandidate(candidateValue) {
    const token = claimAction('candidate-load')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    try {
      const candidate = candidateSnapshot(candidateValue)
      if (typeof loadCandidateRequest !== 'function') {
        throw new TypeError('loadCandidate is required')
      }
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      const fence = {
        editGeneration,
        contextGeneration,
        visibleText: autosave.text?.value,
      }
      const authority = persistedAuthority(autosave)
      const result = await loadCandidateRequest(candidate.id, {
        expectedWorkingDraftRevision: authority.revision,
        expectedContentHash: authority.contentHash,
      })
      if (!isActionCurrent(token)) return null
      const calibrated = requireCandidateLoadResult(
        result, candidate, authority,
      )
      resyncIfUnchanged(calibrated, fence)
      return calibrated
    } finally {
      releaseAction(token)
    }
  }

  async function generateWorkingDraft() {
    const token = claimAction('generate')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    try {
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      const authority = persistedAuthority(autosave)
      const fence = {
        editGeneration,
        contextGeneration,
        visibleText: autosave.text?.value,
      }
      retryFence = fence
      let request
      try {
        request = coordinator.generateNew({
          expectedWorkingDraftRevision: authority.revision,
          expectedContentHash: authority.contentHash,
          authorInstruction: authorInstructionState.value,
        })
      } finally {
        touchCoordinator()
      }
      const result = await request
      touchCoordinator()
      if (!isActionCurrent(token)) return null
      resyncIfUnchanged(result, fence)
      if (coordinator.status !== 'unknown') retryFence = null
      return result
    } catch (error) {
      touchCoordinator()
      if (coordinator.status !== 'unknown') retryFence = null
      throw error
    } finally {
      releaseAction(token)
      touchCoordinator()
    }
  }

  async function retryUnknown() {
    const token = claimAction('generate')
    if (token === null) return false
    try {
      const fence = retryFence
      let request
      try {
        request = coordinator.retryUnknown()
      } finally {
        touchCoordinator()
      }
      const result = await request
      touchCoordinator()
      if (!isActionCurrent(token)) return null
      if (fence) {
        if (LOCAL_OPERATION_TYPES.has(coordinator.operation?.operationType)) {
          acceptLocalResult(result, fence)
        } else {
          resyncIfUnchanged(result, fence)
        }
      }
      if (coordinator.status !== 'unknown') retryFence = null
      return result
    } catch (error) {
      touchCoordinator()
      if (coordinator.status !== 'unknown') retryFence = null
      throw error
    } finally {
      releaseAction(token)
      touchCoordinator()
    }
  }

  async function resumeDraftOperation(operationId) {
    const token = claimAction('resume')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    const fence = {
      editGeneration,
      contextGeneration,
      visibleText: autosave.text?.value,
    }
    retryFence = null
    try {
      let request
      try {
        request = coordinator.resume(operationId)
      } finally {
        touchCoordinator()
      }
      const result = await request
      touchCoordinator()
      if (!isActionCurrent(token)) return null
      resyncIfUnchanged(result, fence)
      return result
    } catch (error) {
      touchCoordinator()
      throw error
    } finally {
      releaseAction(token)
      touchCoordinator()
    }
  }

  async function cancelGeneration() {
    if (
      !actionLock.value
      || !['generate', 'resume', 'local'].includes(activeAction?.kind)
    ) return false
    try {
      const request = coordinator.cancelActive()
      touchCoordinator()
      const result = await request
      touchCoordinator()
      return result
    } catch (error) {
      touchCoordinator()
      throw error
    }
  }

  async function recoverPartialDraft() {
    const partial = recoverablePartialDraft.value
    if (!partial) return false
    const token = claimAction('recover-partial')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    try {
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      const changed = autosave.edit(partial.content)
      if (changed) editGeneration += 1
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      recoveredPartialOperationId.value = partial.operationId
      return true
    } finally {
      releaseAction(token)
    }
  }

  async function canNavigate() {
    const token = claimAction('navigate')
    if (token === null) return false
    try {
      if (autosave.status?.value === 'failed' || autosave.status?.value === 'conflict') {
        return false
      }
      const flushed = await flushPersistedDraft()
      return flushed && isActionCurrent(token)
    } finally {
      releaseAction(token)
    }
  }

  function frozenSelection(value, text) {
    const scalars = Array.from(String(text ?? ''))
    const startOffset = value?.startOffset
    const endOffset = value?.endOffset
    const selectedText = value?.selectedText
    if (
      !Number.isInteger(startOffset)
      || startOffset < 0
      || !Number.isInteger(endOffset)
      || endOffset <= startOffset
      || endOffset > scalars.length
      || typeof selectedText !== 'string'
      || scalars.slice(startOffset, endOffset).join('') !== selectedText
    ) throw new TypeError('valid draft selection is required')
    return Object.freeze({ startOffset, endOffset, selectedText })
  }

  function acceptLocalResult(result, fence) {
    const operation = coordinator.operation
    if (
      operation?.status !== 'completed'
      || !LOCAL_OPERATION_TYPES.has(operation.operationType)
      || result?.workingDraft?.revision !== operation.resultWorkingDraftRevision
      || result?.workingDraft?.contentHash !== operation.resultContentHash
      || coordinator.resultSelection === null
    ) return false
    if (!resyncIfUnchanged(result, fence)) return false
    undoEligibilityState.value = Object.freeze({
      expectedWorkingDraftRevision: operation.resultWorkingDraftRevision,
      expectedContentHash: operation.resultContentHash,
      sourceOperationId: operation.id,
    })
    restoredSelectionState.value = coordinator.resultSelection
    return true
  }

  async function runSelectionOperation(operationType) {
    if (!LOCAL_OPERATION_TYPES.has(operationType)) {
      throw new TypeError('invalid local draft operation type')
    }
    const token = claimAction('local')
    if (token === null) return false
    undoEligibilityState.value = null
    restoredSelectionState.value = null
    try {
      const captured = frozenSelection(selectionState.value, autosave.text?.value)
      if (!await flushPersistedDraft() || !isActionCurrent(token)) return false
      frozenSelection(captured, autosave.text?.value)
      const authority = persistedAuthority(autosave)
      const fence = {
        editGeneration,
        contextGeneration,
        visibleText: autosave.text?.value,
      }
      retryFence = fence
      let request
      try {
        request = coordinator.runLocal(operationType, {
          expectedWorkingDraftRevision: authority.revision,
          expectedContentHash: authority.contentHash,
          authorInstruction: authorInstructionState.value,
          startOffset: captured.startOffset,
          endOffset: captured.endOffset,
          selectedTextHash: await sha256Text(captured.selectedText),
        })
      } finally {
        touchCoordinator()
      }
      const result = await request
      touchCoordinator()
      if (!isActionCurrent(token)) return null
      acceptLocalResult(result, fence)
      if (coordinator.status !== 'unknown') retryFence = null
      return result
    } catch (error) {
      touchCoordinator()
      if (coordinator.status !== 'unknown') retryFence = null
      throw error
    } finally {
      releaseAction(token)
      touchCoordinator()
    }
  }

  async function undoLastLocal() {
    const eligibility = undoEligibilityState.value
    if (!eligibility) return false
    const token = claimAction('undo')
    if (token === null) return false
    try {
      const request = undoLocalDraftRequest || unavailable('undoLocalDraft')
      try {
        const restored = await request(eligibility)
        if (!isActionCurrent(token)) return null
        autosave.reset(restored)
        undoEligibilityState.value = null
        restoredSelectionState.value = null
        return restored
      } catch (error) {
        if (!isActionCurrent(token)) return null
        const unknown = error instanceof Error && (
          Number(error.status || 0) === 0
          || (Number(error.status || 0) === 502
            && error.code === 'DraftOperationUnavailable')
        )
        if (!unknown) throw error
        undoEligibilityState.value = null
        restoredSelectionState.value = null
        const reconciled = await (reloadWorkspace || unavailable('reloadWorkspace'))()
        if (!isActionCurrent(token)) return null
        autosave.reset(reconciled)
        return reconciled
      }
    } finally {
      releaseAction(token)
    }
  }

  return {
    beforeUnloadRisk,
    saveCandidate,
    loadCandidate,
    generateWorkingDraft,
    retryUnknown,
    resumeDraftOperation,
    cancelGeneration,
    recoverPartialDraft,
    runSelectionOperation,
    undoLastLocal,
    canNavigate,
    edit,
    setAuthorInstruction,
    setSelection,
    resetContext,
    dispose,
    actionBusy,
    operationCancellable,
    editorText,
    streamingPreview,
    replacementPreview,
    operationStatus,
    operationStatusText,
    operationRetryAvailable,
    recoverablePartialDraft,
    authorInstruction,
    selection,
    undoAvailable,
    restoredSelection,
  }
}
