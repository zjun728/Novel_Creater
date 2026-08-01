import { computed, ref } from 'vue'

function draftFrom(authority) {
  const draft = authority?.workingDraft || authority
  if (!draft || typeof draft !== 'object') {
    throw new TypeError('working draft authority is required')
  }
  if (!Number.isInteger(draft.revision) || draft.revision < 1) {
    throw new TypeError('working draft revision is required')
  }
  if (typeof draft.contentHash !== 'string' || !draft.contentHash) {
    throw new TypeError('working draft content hash is required')
  }
  return {
    content: String(draft.content ?? ''),
    revision: draft.revision,
    contentHash: draft.contentHash,
  }
}

function isConflict(error) {
  return error?.code === 'ChapterSessionConflict'
}

export function createWorkingDraftAutosave({
  delayMs = 800,
  maxWaitMs = 5000,
  schedule = (callback, delay) => setTimeout(callback, delay),
  cancel = timer => clearTimeout(timer),
  persist,
} = {}) {
  if (typeof persist !== 'function') {
    throw new TypeError('persist is required')
  }
  if (typeof schedule !== 'function' || typeof cancel !== 'function') {
    throw new TypeError('schedule and cancel are required')
  }

  const text = ref('')
  const status = ref('idle')
  const persistedRevision = ref(null)
  const persistedHash = ref('')
  const persistedContent = ref('')
  let editGeneration = 0
  let authorityEpoch = 0
  let debounceTimer = null
  let maxWaitTimer = null
  let inFlight = null
  let inFlightEpoch = null
  let saveQueued = false
  let lastError = null
  let disposed = false

  const dirty = computed(() => text.value !== persistedContent.value)

  function clearTimer(name) {
    if (name === 'debounce' && debounceTimer !== null) {
      cancel(debounceTimer)
      debounceTimer = null
    }
    if (name === 'maxWait' && maxWaitTimer !== null) {
      cancel(maxWaitTimer)
      maxWaitTimer = null
    }
  }

  function clearTimers() {
    clearTimer('debounce')
    clearTimer('maxWait')
  }

  function scheduleSave() {
    if (disposed || !dirty.value || status.value === 'failed' || status.value === 'conflict') {
      return
    }
    clearTimer('debounce')
    debounceTimer = schedule(() => {
      debounceTimer = null
      requestScheduledSave()
    }, delayMs)
    if (maxWaitTimer === null) {
      maxWaitTimer = schedule(() => {
        maxWaitTimer = null
        requestScheduledSave()
      }, maxWaitMs)
    }
    if (inFlight === null || inFlightEpoch !== authorityEpoch) {
      status.value = 'pending'
    }
  }

  function requestScheduledSave() {
    if (disposed || !dirty.value || status.value === 'failed' || status.value === 'conflict') {
      return
    }
    if (inFlight !== null) {
      saveQueued = true
      return
    }
    void startSave()
  }

  function applyPersistedAuthority(authority, snapshot) {
    const draft = draftFrom(authority)
    persistedContent.value = draft.content
    persistedRevision.value = draft.revision
    persistedHash.value = draft.contentHash
    if (snapshot.editGeneration === editGeneration) {
      text.value = draft.content
    }
  }

  function settleAfterRequest() {
    if (disposed) return
    if (status.value === 'failed' || status.value === 'conflict') {
      clearTimers()
      saveQueued = false
      return
    }
    if (!dirty.value) {
      clearTimers()
      saveQueued = false
      status.value = 'saved'
      return
    }
    if (saveQueued) {
      saveQueued = false
      void startSave()
      return
    }
    if (debounceTimer === null && maxWaitTimer === null) {
      scheduleSave()
    } else {
      status.value = 'pending'
    }
  }

  function startSave() {
    if (disposed || status.value === 'conflict') return Promise.resolve(false)
    if (inFlight !== null) return inFlight
    if (!dirty.value) {
      clearTimers()
      status.value = 'saved'
      return Promise.resolve(false)
    }
    clearTimers()
    const requestEpoch = authorityEpoch
    const snapshot = Object.freeze({
      editGeneration,
      expectedRevision: persistedRevision.value,
      expectedContentHash: persistedHash.value,
      content: text.value,
    })
    status.value = 'saving'
    lastError = null
    let response
    try {
      response = persist(snapshot)
    } catch (error) {
      response = Promise.reject(error)
    }
    const request = Promise.resolve(response)
      .then(authority => {
        if (!disposed && requestEpoch === authorityEpoch) {
          applyPersistedAuthority(authority, snapshot)
        }
        return authority
      })
      .catch(error => {
        if (!disposed && requestEpoch === authorityEpoch) {
          lastError = error
          status.value = isConflict(error) ? 'conflict' : 'failed'
        }
        return undefined
      })
      .finally(() => {
        if (inFlight === request) {
          inFlight = null
          inFlightEpoch = null
        }
        settleAfterRequest()
      })
    inFlight = request
    inFlightEpoch = requestEpoch
    return request
  }

  function edit(nextText) {
    if (disposed) return false
    const normalized = String(nextText ?? '')
    if (text.value === normalized) return false
    text.value = normalized
    editGeneration += 1
    if (!dirty.value) {
      clearTimers()
      if (inFlight === null) status.value = 'saved'
      return true
    }
    scheduleSave()
    return true
  }

  function reset(authority) {
    if (disposed) return false
    const draft = draftFrom(authority)
    clearTimers()
    saveQueued = false
    editGeneration += 1
    authorityEpoch += 1
    persistedContent.value = draft.content
    persistedRevision.value = draft.revision
    persistedHash.value = draft.contentHash
    text.value = draft.content
    lastError = null
    status.value = 'saved'
    return true
  }

  async function flush() {
    if (disposed) return false
    clearTimers()
    while (inFlight !== null) await inFlight
    if (!dirty.value) return true
    if (status.value === 'failed' || status.value === 'conflict') {
      throw lastError || new Error('working draft cannot be flushed')
    }
    await startSave()
    if (status.value === 'failed' || status.value === 'conflict') {
      throw lastError || new Error('working draft cannot be flushed')
    }
    return !dirty.value
  }

  async function retry() {
    if (disposed || status.value === 'conflict' || status.value !== 'failed') {
      return false
    }
    clearTimers()
    await startSave()
    return status.value === 'saved'
  }

  async function whenIdle() {
    while (inFlight !== null) await inFlight
  }

  function dispose() {
    if (disposed) return
    disposed = true
    clearTimers()
    saveQueued = false
    status.value = 'disposed'
  }

  const publicText = computed(() => text.value)
  const publicStatus = computed(() => status.value)
  const publicPersistedRevision = computed(() => persistedRevision.value)
  const publicPersistedHash = computed(() => persistedHash.value)

  return {
    text: publicText,
    dirty,
    status: publicStatus,
    persistedRevision: publicPersistedRevision,
    persistedHash: publicPersistedHash,
    edit,
    reset,
    flush,
    retry,
    whenIdle,
    dispose,
  }
}
