import { ApiError } from '../../api/db/api-error.js'
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'expired'])
const PUBLIC_STATUSES = new Set(['starting', 'running', 'completed', 'failed', 'expired'])
const FAILURE_CODES = new Set(['DraftProviderFailed', 'DraftProviderResultInvalid'])
const POLL_INTERVAL_MS = 1_000
const MAX_STATUS_READS = 1_200
const RECOVERY_LEASE_STATUS_READS = 1_261
const MAX_BASE_REVISION = 2_147_483_646
const MAX_RESULT_REVISION = 2_147_483_647
const OPERATION_FIELDS = [
  'id', 'projectId', 'chapterSessionId', 'operationType', 'status',
  'lastEventSequence', 'resultWorkingDraftRevision', 'resultContentHash',
  'failureCode', 'model',
]
const MODEL_FIELDS = ['providerId', 'modelName']

function defaultPollScheduler(delayMs) {
  let resolve
  const promise = new Promise(nextResolve => {
    resolve = nextResolve
  })
  const timer = setTimeout(resolve, delayMs)
  return Object.freeze({
    promise,
    cancel() {
      clearTimeout(timer)
      resolve()
    },
  })
}

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
    || source.expectedWorkingDraftRevision > MAX_BASE_REVISION
    || typeof source.expectedContentHash !== 'string'
    || !CONTENT_HASH.test(source.expectedContentHash)
    || typeof source.authorInstruction !== 'string'
    || unicodeScalarLength(source.authorInstruction) > 2000
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
  if (
    Object.keys(source).length !== OPERATION_FIELDS.length
    || OPERATION_FIELDS.some(field => !Object.hasOwn(source, field))
  ) throw new TypeError('Invalid draft operation response')
  const operationId = uuid(source.id, 'draft operation id')
  const projectId = uuid(source.projectId, 'draft operation project id')
  const chapterSessionId = uuid(source.chapterSessionId, 'draft operation session id')
  const status = source.status
  const sequence = source.lastEventSequence
  const revision = source.resultWorkingDraftRevision
  const contentHash = source.resultContentHash
  const failureCode = source.failureCode
  const sourceModel = object(source.model, 'draft operation model')
  if (
    source.operationType !== 'generate_new'
    || !PUBLIC_STATUSES.has(status)
    || !Number.isInteger(sequence)
    || sequence !== ((status === 'completed' || status === 'failed') ? 2 : 1)
    || Object.keys(sourceModel).length !== MODEL_FIELDS.length
    || MODEL_FIELDS.some(field => !Object.hasOwn(sourceModel, field))
    || typeof sourceModel.providerId !== 'string'
    || sourceModel.providerId.length === 0
    || typeof sourceModel.modelName !== 'string'
    || sourceModel.modelName.length === 0
  ) throw new TypeError('Invalid draft operation response')
  if (status === 'completed') {
    if (
      !Number.isInteger(revision)
      || revision < 1
      || revision > MAX_RESULT_REVISION
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
  const model = Object.freeze({
    providerId: sourceModel.providerId,
    modelName: sourceModel.modelName,
  })
  return Object.freeze({
    id: operationId,
    projectId,
    chapterSessionId,
    operationType: 'generate_new',
    status,
    lastEventSequence: sequence,
    resultWorkingDraftRevision: revision,
    resultContentHash: contentHash,
    failureCode,
    model,
  })
}

function isUnknownTransport(error) {
  return error instanceof ApiError && (
    error.status === 0
    || (error.status === 502 && error.code === 'DraftOperationUnavailable')
  )
}

function knownFailureCode(error) {
  return error instanceof TypeError ? 'operation_invalid' : 'request_rejected'
}

export function createDraftOperationCoordinator({
  startOperation,
  readOperation,
  reloadWorkspace,
  idFactory,
  pollScheduler = defaultPollScheduler,
} = {}) {
  const start = requireFunction(startOperation, 'startOperation')
  const read = requireFunction(readOperation, 'readOperation')
  const reload = requireFunction(reloadWorkspace, 'reloadWorkspace')
  const createId = requireFunction(idFactory, 'idFactory')
  const schedulePoll = requireFunction(pollScheduler, 'pollScheduler')
  let actionGeneration = 0
  let activeAction = null
  let retryCommand = null
  let currentStatus = 'idle'
  let currentOperation = null
  let currentBusy = false
  let currentFailureCode = null
  let disposed = false
  let pendingDelay = null

  function isCurrent(token) {
    return !disposed && activeAction?.token === token && actionGeneration === token
  }

  function clearPendingDelay() {
    if (!pendingDelay) return
    const pending = pendingDelay
    pendingDelay = null
    pending.cancel()
  }

  function waitForPoll() {
    const pending = schedulePoll(POLL_INTERVAL_MS)
    if (
      !pending
      || typeof pending.promise?.then !== 'function'
      || typeof pending.cancel !== 'function'
    ) throw new TypeError('Invalid draft operation poll scheduler')
    pendingDelay = pending
    return pending.promise.finally(() => {
      if (pendingDelay === pending) pendingDelay = null
    })
  }

  function clearPublicState(nextStatus = 'idle') {
    currentStatus = nextStatus
    currentOperation = null
    currentBusy = false
    currentFailureCode = null
  }

  function markUnknown(frozenCommand) {
    retryCommand = frozenCommand
    currentStatus = 'unknown'
    currentOperation = null
    currentFailureCode = 'request_unknown'
  }

  function markKnownFailure(error) {
    retryCommand = null
    currentStatus = knownFailureCode(error)
    currentOperation = null
    currentFailureCode = currentStatus
  }

  function markOperationInvalid() {
    retryCommand = null
    currentStatus = 'operation_invalid'
    currentOperation = null
    currentFailureCode = 'operation_invalid'
  }

  function acceptOperation(received) {
    const operation = publicOperation(received)
    currentOperation = operation
    currentStatus = operation.status
    currentFailureCode = operation.failureCode
    if (TERMINAL_STATUSES.has(operation.status)) retryCommand = null
    return operation
  }

  async function reloadCompleted(token) {
    try {
      const workspace = await reload()
      if (!isCurrent(token)) return null
      return workspace
    } catch (error) {
      if (!isCurrent(token)) return null
      currentFailureCode = 'workspace_reload_failed'
      throw error
    }
  }

  async function reconcileAfterLease(token, frozenCommand) {
    let received
    try {
      received = await start(frozenCommand)
    } catch (error) {
      if (!isCurrent(token)) return null
      if (isUnknownTransport(error)) markUnknown(frozenCommand)
      else markKnownFailure(error)
      throw error
    }
    if (!isCurrent(token)) return null
    let operation
    try {
      operation = acceptOperation(received)
    } catch (error) {
      if (isCurrent(token)) markKnownFailure(error)
      throw error
    }
    if (operation.status === 'completed') return reloadCompleted(token)
    if (TERMINAL_STATUSES.has(operation.status)) return null
    markUnknown(frozenCommand)
    return null
  }

  async function recover(token, frozenCommand, initialOperation, reconcileLeaseEnd) {
    let operation = initialOperation
    let reads = 0
    const maxReads = reconcileLeaseEnd
      ? RECOVERY_LEASE_STATUS_READS
      : MAX_STATUS_READS
    while (!TERMINAL_STATUSES.has(operation.status)) {
      if (reads >= maxReads) {
        if (reconcileLeaseEnd && isCurrent(token)) {
          return reconcileAfterLease(token, frozenCommand)
        }
        if (isCurrent(token)) markUnknown(frozenCommand)
        return null
      }
      if (reads > 0) {
        try {
          await waitForPoll()
        } catch (error) {
          if (!isCurrent(token)) return null
          markOperationInvalid()
          throw error
        }
        if (!isCurrent(token)) return null
      }
      reads += 1
      let received
      try {
        received = await read(operation.id)
      } catch (error) {
        if (!isCurrent(token)) return null
        if (isUnknownTransport(error)) markUnknown(frozenCommand)
        else markKnownFailure(error)
        throw error
      }
      if (!isCurrent(token)) return null
      try {
        operation = acceptOperation(received)
      } catch (error) {
        if (isCurrent(token)) markKnownFailure(error)
        throw error
      }
    }
    if (operation.status !== 'completed') return null
    if (!isCurrent(token)) return null
    return reloadCompleted(token)
  }

  async function submit(frozenCommand, reconcileLeaseEnd = false) {
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
        if (isUnknownTransport(error)) markUnknown(frozenCommand)
        else markKnownFailure(error)
        throw error
      }
      if (!isCurrent(token)) return null
      let operation
      try {
        operation = acceptOperation(received)
      } catch (error) {
        if (isCurrent(token)) markKnownFailure(error)
        throw error
      }
      if (operation.status === 'completed') return await reloadCompleted(token)
      if (TERMINAL_STATUSES.has(operation.status)) return null
      return await recover(
        token,
        frozenCommand,
        operation,
        reconcileLeaseEnd,
      )
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
      if (retryCommand) return Promise.reject(new TypeError('draft operation recovery is pending'))
      return submit(command(value, createId))
    },
    retryUnknown() {
      if (disposed) throw new TypeError('draft operation coordinator is disposed')
      if (!retryCommand) return Promise.reject(new TypeError('no unknown draft operation to retry'))
      return submit(retryCommand, true)
    },
    resetContext() {
      if (disposed) return
      actionGeneration += 1
      clearPendingDelay()
      activeAction = null
      retryCommand = null
      clearPublicState()
    },
    dispose() {
      if (disposed) return
      disposed = true
      actionGeneration += 1
      clearPendingDelay()
      activeAction = null
      retryCommand = null
      clearPublicState('disposed')
    },
  })
}
