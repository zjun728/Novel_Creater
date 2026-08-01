import { computed, ref } from 'vue'

import { generateId } from '../../utils/id.js'
import { createDraftOperationCoordinator } from './draftOperationCoordinator.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const IDEMPOTENCY_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

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

export function createChapterWriterController({
  autosave,
  freezeCandidate: freezeCandidateRequest,
  createDraftOperation,
  readDraftOperation,
  reloadWorkspace,
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

  const coordinator = createDraftOperationCoordinator({
    startOperation: createDraftOperation || unavailable('createDraftOperation'),
    readOperation: readDraftOperation || unavailable('readDraftOperation'),
    reloadWorkspace: reloadWorkspace || unavailable('reloadWorkspace'),
    idFactory,
    ...(pollScheduler ? { pollScheduler } : {}),
  })
  let editGeneration = 0
  let contextGeneration = 0
  let actionGeneration = 0
  let activeAction = null
  let retryFence = null
  let disposed = false
  const actionLock = ref(false)
  const coordinatorRevision = ref(0)
  const actionBusy = computed(() => actionLock.value)
  const authorInstructionState = ref('')
  const selectionState = ref(null)
  const authorInstruction = computed(() => authorInstructionState.value)
  const selection = computed(() => selectionState.value)
  const operationStatus = computed(() => {
    coordinatorRevision.value
    return coordinator.status
  })
  const operationRetryAvailable = computed(() => (
    operationStatus.value === 'unknown' && !actionLock.value
  ))
  const operationStatusText = computed(() => {
    const status = operationStatus.value
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
    if (status === 'expired') return '生成结果已失效'
    if (status === 'unknown') return '结果未知，可重试'
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
    ) autosave.reset(workspace)
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
    if (autosave.text?.value !== before) editGeneration += 1
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

  async function generateWorkingDraft() {
    const token = claimAction('generate')
    if (token === null) return false
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
      if (fence) resyncIfUnchanged(result, fence)
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

  return {
    beforeUnloadRisk,
    saveCandidate,
    generateWorkingDraft,
    retryUnknown,
    canNavigate,
    edit,
    setAuthorInstruction,
    setSelection,
    resetContext,
    dispose,
    actionBusy,
    operationStatus,
    operationStatusText,
    operationRetryAvailable,
    authorInstruction,
    selection,
  }
}
