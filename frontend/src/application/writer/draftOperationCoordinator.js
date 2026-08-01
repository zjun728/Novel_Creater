const CONTENT_HASH = /^[0-9a-f]{64}$/
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'expired'])
const PUBLIC_STATUSES = new Set(['starting', 'running', 'completed', 'failed', 'expired'])
const FAILURE_CODES = new Set(['DraftProviderFailed', 'DraftProviderResultInvalid'])

function requireFunction(value, label) {
  if (typeof value !== 'function') throw new TypeError(`${label} is required`)
  return value
}

function object(value, label) {
  if (
    !value
    || typeof value !== 'object'
    || Array.isArray(value)
    || (Object.getPrototypeOf(value) !== Object.prototype
      && Object.getPrototypeOf(value) !== null)
  ) throw new TypeError(`Invalid ${label}`)
  return value
}

function uuid(value, label) {
  if (typeof value !== 'string' || !CANONICAL_UUID.test(value)) {
    throw new TypeError(`Invalid ${label}`)
  }
  return value
}

function command(value, idFactory) {
  const source = object(value, 'draft operation command')
  const fields = [
    'expectedWorkingDraftRevision', 'expectedContentHash', 'authorInstruction',
  ]
  if (
    Object.keys(source).length !== fields.length
    || fields.some(field => !Object.hasOwn(source, field))
    || !Number.isInteger(source.expectedWorkingDraftRevision)
    || source.expectedWorkingDraftRevision < 1
    || typeof source.expectedContentHash !== 'string'
    || !CONTENT_HASH.test(source.expectedContentHash)
    || typeof source.authorInstruction !== 'string'
    || source.authorInstruction.length > 2000
  ) throw new TypeError('Invalid draft operation command')
  return Object.freeze({
    operationType: 'generate_new',
    expectedWorkingDraftRevision: source.expectedWorkingDraftRevision,
    expectedContentHash: source.expectedContentHash,
    idempotencyKey: uuid(idFactory(), 'draft operation idempotency key'),
    authorInstruction: source.authorInstruction,
  })
}

function publicOperation(value) {
  const source = object(value, 'draft operation response')
  const operationId = uuid(source.operationId, 'draft operation id')
  const projectId = uuid(source.projectId, 'draft operation project id')
  const chapterSessionId = uuid(source.chapterSessionId, 'draft operation session id')
  const status = source.status
  const sequence = source.lastEventSequence
  const revision = source.resultWorkingDraftRevision
  const contentHash = source.resultContentHash
  const failureCode = source.failureCode
  if (
    source.operationType !== 'generate_new'
    || !PUBLIC_STATUSES.has(status)
    || !Number.isInteger(sequence)
    || sequence !== ((status === 'completed' || status === 'failed') ? 2 : 1)
    || typeof source.providerId !== 'string'
    || source.providerId.length === 0
    || typeof source.modelName !== 'string'
    || source.modelName.length === 0
  ) throw new TypeError('Invalid draft operation response')
  if (status === 'completed') {
    if (
      !Number.isInteger(revision)
      || revision < 1
      || typeof contentHash !== 'string'
      || !CONTENT_HASH.test(contentHash)
      || failureCode !== null
    ) throw new TypeError('Invalid draft operation response')
  } else if (status === 'failed') {
    if (
      revision !== null
      || contentHash !== null
      || !FAILURE_CODES.has(failureCode)
    ) throw new TypeError('Invalid draft operation response')
  } else if (revision !== null || contentHash !== null || failureCode !== null) {
    throw new TypeError('Invalid draft operation response')
  }
  return Object.freeze({
    operationId,
    projectId,
    chapterSessionId,
    operationType: 'generate_new',
    status,
    lastEventSequence: sequence,
    resultWorkingDraftRevision: revision,
    resultContentHash: contentHash,
    failureCode,
    providerId: source.providerId,
    modelName: source.modelName,
  })
}

export function createDraftOperationCoordinator({
  startOperation,
  readOperation,
  reloadWorkspace,
  idFactory,
} = {}) {
  const start = requireFunction(startOperation, 'startOperation')
  requireFunction(readOperation, 'readOperation')
  const reload = requireFunction(reloadWorkspace, 'reloadWorkspace')
  const createId = requireFunction(idFactory, 'idFactory')
  let actionGeneration = 0
  let activeAction = null
  let retryCommand = null
  let currentStatus = 'idle'
  let currentOperation = null
  let currentBusy = false
  let currentFailureCode = null
  let disposed = false

  function isCurrent(token) {
    return !disposed && activeAction?.token === token && actionGeneration === token
  }

  function clearPublicState(nextStatus = 'idle') {
    currentStatus = nextStatus
    currentOperation = null
    currentBusy = false
    currentFailureCode = null
  }

  async function submit(frozenCommand) {
    if (disposed) throw new TypeError('draft operation coordinator is disposed')
    if (activeAction) throw new TypeError('draft operation is already in progress')
    const token = ++actionGeneration
    activeAction = { token }
    currentStatus = 'starting'
    currentOperation = null
    currentBusy = true
    currentFailureCode = null
    try {
      let received
      try {
        received = await start(frozenCommand)
      } catch (error) {
        if (!isCurrent(token)) return null
        retryCommand = frozenCommand
        currentStatus = 'unknown'
        currentOperation = null
        currentFailureCode = 'request_unknown'
        throw error
      }
      if (!isCurrent(token)) return null
      let operation
      try {
        operation = publicOperation(received)
      } catch (error) {
        currentStatus = 'invalid'
        currentOperation = null
        currentFailureCode = 'operation_invalid'
        throw error
      }
      currentOperation = operation
      currentStatus = operation.status
      currentFailureCode = operation.failureCode
      if (TERMINAL_STATUSES.has(operation.status)) retryCommand = null
      if (operation.status !== 'completed') return null
      if (!isCurrent(token)) return null
      try {
        const workspace = await reload()
        if (!isCurrent(token)) return null
        return workspace
      } catch (error) {
        if (isCurrent(token)) currentFailureCode = 'workspace_reload_failed'
        throw error
      }
    } finally {
      if (isCurrent(token)) {
        activeAction = null
        currentBusy = false
      }
    }
  }

  return Object.freeze({
    get status() { return currentStatus },
    get operation() { return currentOperation },
    get busy() { return currentBusy },
    get failureCode() { return currentFailureCode },
    generateNew(value) {
      if (disposed) throw new TypeError('draft operation coordinator is disposed')
      if (activeAction) return Promise.reject(new TypeError('draft operation is already in progress'))
      return submit(command(value, createId))
    },
    retryUnknown() {
      if (disposed) throw new TypeError('draft operation coordinator is disposed')
      if (!retryCommand) return Promise.reject(new TypeError('no unknown draft operation to retry'))
      return submit(retryCommand)
    },
    resetContext() {
      actionGeneration += 1
      activeAction = null
      retryCommand = null
      clearPublicState()
    },
    dispose() {
      disposed = true
      actionGeneration += 1
      activeAction = null
      retryCommand = null
      clearPublicState('disposed')
    },
  })
}
