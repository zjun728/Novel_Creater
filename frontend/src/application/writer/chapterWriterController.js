import { computed, ref } from 'vue'

import { generateId } from '../../utils/id.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const IDEMPOTENCY_KEY = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/

function currentBusy(value) {
  return Boolean(typeof value === 'function' ? value() : value?.value ?? value)
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

export function createChapterWriterController({
  autosave,
  freezeCandidate: freezeCandidateRequest,
  generateWorkingDraft: generateWorkingDraftRequest,
  idFactory = generateId,
  writeBusy = false,
} = {}) {
  if (!autosave
    || typeof autosave.edit !== 'function'
    || typeof autosave.flush !== 'function'
    || typeof autosave.reset !== 'function') {
    throw new TypeError('autosave is required')
  }

  let editGeneration = 0
  const actionLock = ref(false)
  const actionBusy = computed(() => actionLock.value)
  const authorInstructionState = ref('')
  const selectionState = ref(null)
  const authorInstruction = computed(() => authorInstructionState.value)
  const selection = computed(() => selectionState.value)

  const beforeUnloadRisk = computed(() => {
    const status = autosave.status?.value
    return Boolean(
      autosave.dirty?.value
      || status === 'saving'
      || status === 'failed'
      || status === 'conflict'
      || actionLock.value
      || currentBusy(writeBusy),
    )
  })

  function resyncIfUnchanged(workspace, flushedGeneration) {
    if (editGeneration === flushedGeneration) {
      autosave.reset(workspace)
    }
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
    const before = autosave.text?.value
    const changed = autosave.edit(nextText)
    if (autosave.text?.value !== before) {
      editGeneration += 1
    }
    return changed
  }

  function setAuthorInstruction(nextInstruction) {
    authorInstructionState.value = String(nextInstruction ?? '')
  }

  function setSelection(nextSelection) {
    selectionState.value = nextSelection ?? null
  }

  function resetContext() {
    authorInstructionState.value = ''
    selectionState.value = null
  }

  function claimAction() {
    if (actionLock.value || currentBusy(writeBusy)) return false
    actionLock.value = true
    return true
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
    if (!claimAction()) return false
    try {
      if (typeof freezeCandidateRequest !== 'function') throw new TypeError('freezeCandidate is required')
      if (!await flushPersistedDraft()) return false
      const flushedGeneration = editGeneration
      const authority = persistedAuthority(autosave)
      const result = await freezeCandidateRequest({
        expectedWorkingDraftRevision: authority.revision,
        expectedContentHash: authority.contentHash,
        idempotencyKey: nextCandidateIdempotencyKey(),
      })
      resyncIfUnchanged(result, flushedGeneration)
      return result
    } finally {
      actionLock.value = false
    }
  }

  async function generateWorkingDraft() {
    if (!claimAction()) return false
    try {
      if (typeof generateWorkingDraftRequest !== 'function') throw new TypeError('generateWorkingDraft is required')
      if (!await flushPersistedDraft()) return false
      const flushedGeneration = editGeneration
      const authority = persistedAuthority(autosave)
      const result = await generateWorkingDraftRequest({
        expectedWorkingDraftRevision: authority.revision,
        authorInstruction: authorInstructionState.value,
      })
      resyncIfUnchanged(result, flushedGeneration)
      return result
    } finally {
      actionLock.value = false
    }
  }

  async function canNavigate() {
    if (actionLock.value || currentBusy(writeBusy)) return false
    if (autosave.status?.value === 'failed' || autosave.status?.value === 'conflict') {
      return false
    }
    return flushPersistedDraft()
  }

  return {
    beforeUnloadRisk,
    saveCandidate,
    generateWorkingDraft,
    canNavigate,
    edit,
    setAuthorInstruction,
    setSelection,
    resetContext,
    actionBusy,
    authorInstruction,
    selection,
  }
}
