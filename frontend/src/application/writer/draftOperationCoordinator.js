import { ApiError } from '../../api/db/api-error.js'
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'
import { createDraftOperationTimeline } from './draftOperationTimeline.js'

const CONTENT_HASH = /^[0-9a-f]{64}$/
const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'expired'])
const PUBLIC_STATUSES = new Set([
  'starting', 'running', 'completed', 'failed', 'cancelled', 'expired',
])
const FAILURE_CODES = new Set(['DraftProviderFailed', 'DraftProviderResultInvalid'])
const POLL_INTERVAL_MS = 1_000
const MAX_STATUS_READS = 1_200
const RECOVERY_LEASE_STATUS_READS = 1_261
const MAX_BASE_REVISION = 2_147_483_646
const MAX_RESULT_REVISION = 2_147_483_647
const MAX_EVENTS = 2_048
const MAX_PARTIAL_SCALARS = 100_000
const OPERATION_FIELDS = [
  'id', 'projectId', 'chapterSessionId', 'operationType', 'status',
  'lastEventSequence', 'partialOutput', 'partialOutputHash',
  'partialOutputScalars', 'resultWorkingDraftRevision', 'resultContentHash',
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
  const partialOutput = source.partialOutput
  const partialOutputHash = source.partialOutputHash
  const partialOutputScalars = source.partialOutputScalars
  const revision = source.resultWorkingDraftRevision
  const contentHash = source.resultContentHash
  const failureCode = source.failureCode
  const sourceModel = object(source.model, 'draft operation model')
  if (
    source.operationType !== 'generate_new'
    || !PUBLIC_STATUSES.has(status)
    || !Number.isInteger(sequence)
    || sequence < 1
    || sequence > MAX_EVENTS
    || (
      (status === 'starting' || status === 'running' || status === 'expired')
      && sequence === MAX_EVENTS
    )
    || typeof partialOutput !== 'string'
    || typeof partialOutputHash !== 'string'
    || !CONTENT_HASH.test(partialOutputHash)
    || !Number.isInteger(partialOutputScalars)
    || partialOutputScalars < 0
    || partialOutputScalars > MAX_PARTIAL_SCALARS
    || unicodeScalarLength(partialOutput) !== partialOutputScalars
    || Object.keys(sourceModel).length !== MODEL_FIELDS.length
    || MODEL_FIELDS.some(field => !Object.hasOwn(sourceModel, field))
    || typeof sourceModel.providerId !== 'string'
    || sourceModel.providerId.length === 0
    || typeof sourceModel.modelName !== 'string'
    || sourceModel.modelName.length === 0
  ) throw new TypeError('Invalid draft operation response')
  if (
    (status === 'starting' && (
      sequence !== 1 || partialOutput !== '' || partialOutputScalars !== 0
    ))
    || (status === 'running' && sequence === 1 && (
      partialOutput !== '' || partialOutputScalars !== 0
    ))
  ) throw new TypeError('Invalid draft operation response')
  if (status === 'completed') {
    if (
      sequence < 2
      || !Number.isInteger(revision)
      || revision < 1
      || revision > MAX_RESULT_REVISION
      || typeof contentHash !== 'string'
      || !CONTENT_HASH.test(contentHash)
      || contentHash !== partialOutputHash
      || partialOutput === ''
      || partialOutput !== partialOutput.trim()
      || failureCode !== null
    ) throw new TypeError('Invalid draft operation response')
  } else if (status === 'cancelled') {
    const hasResult = revision !== null || contentHash !== null
    if (
      sequence < 2
      || failureCode !== null
      || partialOutput !== partialOutput.trim()
      || Boolean(partialOutput) !== hasResult
      || (revision === null) !== (contentHash === null)
      || (hasResult && (
        !Number.isInteger(revision)
        || revision < 1
        || revision > MAX_RESULT_REVISION
        || typeof contentHash !== 'string'
        || !CONTENT_HASH.test(contentHash)
        || contentHash !== partialOutputHash
      ))
    ) throw new TypeError('Invalid draft operation response')
  } else if (status === 'failed') {
    if (
      sequence < 2
      || revision !== null
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
    partialOutput,
    partialOutputHash,
    partialOutputScalars,
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
  listEvents,
  cancelOperation,
  reloadWorkspace,
  idFactory,
  pollScheduler = defaultPollScheduler,
  onChange = () => {},
} = {}) {
  const start = requireFunction(startOperation, 'startOperation')
  const read = requireFunction(readOperation, 'readOperation')
  const list = requireFunction(listEvents, 'listEvents')
  const cancel = requireFunction(cancelOperation, 'cancelOperation')
  const reload = requireFunction(reloadWorkspace, 'reloadWorkspace')
  const createId = requireFunction(idFactory, 'idFactory')
  const schedulePoll = requireFunction(pollScheduler, 'pollScheduler')
  const notify = requireFunction(onChange, 'onChange')
  const timeline = createDraftOperationTimeline()
  let actionGeneration = 0
  let activeAction = null
  let retryCommand = null
  let currentStatus = 'idle'
  let currentOperation = null
  let currentBusy = false
  let currentFailureCode = null
  let currentReconnecting = false
  let currentCancelling = false
  let disposed = false
  let pendingDelay = null

  function changed() {
    notify()
  }

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
    currentReconnecting = false
    currentCancelling = false
    timeline.reset()
    changed()
  }

  function markUnknown(frozenCommand) {
    retryCommand = frozenCommand || null
    currentStatus = 'unknown'
    currentOperation = null
    currentFailureCode = 'request_unknown'
    changed()
  }

  function markKnownFailure(error) {
    retryCommand = null
    currentStatus = knownFailureCode(error)
    currentOperation = null
    currentFailureCode = currentStatus
    changed()
  }

  function markOperationInvalid() {
    retryCommand = null
    currentStatus = 'operation_invalid'
    currentOperation = null
    currentFailureCode = 'operation_invalid'
    changed()
  }

  function validateOperation(received, expectedOperationId = null) {
    const operation = publicOperation(received)
    if (expectedOperationId !== null && operation.id !== expectedOperationId) {
      throw new TypeError('Invalid draft operation response')
    }
    return operation
  }

  function publishOperation(operation) {
    currentOperation = operation
    currentStatus = operation.status
    currentFailureCode = operation.failureCode
    if (TERMINAL_STATUSES.has(operation.status)) retryCommand = null
    changed()
    return operation
  }

  function acceptOperation(received, expectedOperationId = null) {
    return publishOperation(validateOperation(received, expectedOperationId))
  }

  async function calibrateOperation(token, operation) {
    await timeline.calibrate(operation)
    if (!isCurrent(token)) return false
    changed()
    return true
  }

  async function reloadCompleted(token) {
    try {
      const workspace = await reload()
      if (!isCurrent(token)) return null
      return workspace
    } catch (error) {
      if (!isCurrent(token)) return null
      currentFailureCode = 'workspace_reload_failed'
      changed()
      throw error
    }
  }

  async function settleTerminal(token, operation) {
    if (
      operation.status === 'completed'
      || (
        operation.status === 'cancelled'
        && operation.resultWorkingDraftRevision !== null
      )
    ) return reloadCompleted(token)
    return null
  }

  function classifyFailure(error, frozenCommand) {
    if (isUnknownTransport(error) && frozenCommand) markUnknown(frozenCommand)
    else markKnownFailure(error)
  }

  async function drainEventPages(token, operationId, requiredSequence = timeline.cursor) {
    while (isCurrent(token)) {
      const page = await list(operationId, timeline.cursor)
      if (!isCurrent(token)) return false
      if (activeAction.cancelPromise) return true
      await timeline.applyPage(page)
      if (!isCurrent(token)) return false
      if (activeAction.cancelPromise) return true
      changed()
      if (!page.hasMore) {
        if (timeline.cursor < requiredSequence) {
          throw new TypeError('Invalid draft operation event page')
        }
        return true
      }
    }
    return false
  }

  async function reconcileAfterLease(token, frozenCommand) {
    let received
    try {
      received = await start(frozenCommand)
    } catch (error) {
      if (!isCurrent(token)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      classifyFailure(error, frozenCommand)
      throw error
    }
    if (!isCurrent(token)) return null
    if (activeAction.cancelPromise) return activeAction.cancelPromise
    let operation
    try {
      operation = acceptOperation(received, currentOperation?.id ?? null)
      if (!await calibrateOperation(token, operation)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
    } catch (error) {
      if (!isCurrent(token)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      markKnownFailure(error)
      throw error
    }
    if (TERMINAL_STATUSES.has(operation.status)) {
      return settleTerminal(token, operation)
    }
    markUnknown(frozenCommand)
    return null
  }

  async function recover(token, frozenCommand, initialOperation, reconcileLeaseEnd) {
    let operation = initialOperation
    let reads = 0
    let immediateDrain = true
    const maxReads = reconcileLeaseEnd
      ? RECOVERY_LEASE_STATUS_READS
      : MAX_STATUS_READS
    while (true) {
      if (!isCurrent(token)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      if (reads >= maxReads) {
        if (reconcileLeaseEnd && frozenCommand && isCurrent(token)) {
          return reconcileAfterLease(token, frozenCommand)
        }
        if (isCurrent(token)) markUnknown(frozenCommand)
        return null
      }
      if (reads > 0 && !immediateDrain) {
        try {
          await waitForPoll()
        } catch (error) {
          if (!isCurrent(token)) return null
          if (activeAction.cancelPromise) return activeAction.cancelPromise
          markOperationInvalid()
          throw error
        }
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
      }
      immediateDrain = false
      try {
        if (!await drainEventPages(token, operation.id)) return null
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        classifyFailure(error, frozenCommand)
        throw error
      }
      if (!isCurrent(token)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      let received
      try {
        received = await read(operation.id)
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        classifyFailure(error, frozenCommand)
        throw error
      }
      if (!isCurrent(token)) return null
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      reads += 1
      let candidate
      try {
        candidate = validateOperation(received, operation.id)
        if (candidate.lastEventSequence < timeline.cursor) {
          throw new TypeError('Invalid draft operation response')
        }
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        markKnownFailure(error)
        throw error
      }
      if (candidate.lastEventSequence > timeline.cursor) {
        try {
          if (!await drainEventPages(token, candidate.id, candidate.lastEventSequence)) return null
        } catch (error) {
          if (!isCurrent(token)) return null
          if (activeAction.cancelPromise) return activeAction.cancelPromise
          classifyFailure(error, frozenCommand)
          throw error
        }
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        if (timeline.cursor > candidate.lastEventSequence) {
          operation = candidate
          immediateDrain = true
          continue
        }
      }
      try {
        if (!await calibrateOperation(token, candidate)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        operation = publishOperation(candidate)
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        markKnownFailure(error)
        throw error
      }
      if (TERMINAL_STATUSES.has(operation.status)) {
        return settleTerminal(token, operation)
      }
      immediateDrain = false
    }
  }

  async function submit(frozenCommand, reconcileLeaseEnd = false) {
    if (disposed) throw new TypeError('draft operation coordinator is disposed')
    if (activeAction) throw new TypeError('draft operation is already in progress')
    const token = ++actionGeneration
    activeAction = { token, cancelPromise: null }
    currentStatus = 'starting'
    currentOperation = null
    currentBusy = true
    currentFailureCode = null
    currentReconnecting = false
    currentCancelling = false
    if (!retryCommand || timeline.cursor === 0) timeline.reset()
    changed()
    try {
      let received
      try {
        received = await start(frozenCommand)
      } catch (error) {
        if (!isCurrent(token)) return null
        classifyFailure(error, frozenCommand)
        throw error
      }
      if (!isCurrent(token)) return null
      let operation
      try {
        operation = acceptOperation(received, timeline.cursor > 0 ? currentOperation?.id : null)
        if (!await calibrateOperation(token, operation)) return null
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        markKnownFailure(error)
        throw error
      }
      if (activeAction.cancelPromise) return activeAction.cancelPromise
      if (TERMINAL_STATUSES.has(operation.status)) {
        return await settleTerminal(token, operation)
      }
      return await recover(token, frozenCommand, operation, reconcileLeaseEnd)
    } finally {
      if (isCurrent(token)) {
        activeAction = null
        currentBusy = false
        currentReconnecting = false
        currentCancelling = false
        changed()
      }
    }
  }

  async function resumeKnown(operationId) {
    if (disposed) throw new TypeError('draft operation coordinator is disposed')
    if (activeAction) throw new TypeError('draft operation is already in progress')
    const token = ++actionGeneration
    activeAction = { token, cancelPromise: null }
    retryCommand = null
    currentStatus = 'reconnecting'
    currentOperation = null
    currentBusy = true
    currentFailureCode = null
    currentReconnecting = true
    currentCancelling = false
    timeline.reset()
    changed()
    try {
      let received
      try {
        received = await read(operationId)
      } catch (error) {
        if (!isCurrent(token)) return null
        markKnownFailure(error)
        throw error
      }
      if (!isCurrent(token)) return null
      let operation
      try {
        operation = acceptOperation(received, operationId)
        if (!await calibrateOperation(token, operation)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
      } catch (error) {
        if (!isCurrent(token)) return null
        if (activeAction.cancelPromise) return activeAction.cancelPromise
        markKnownFailure(error)
        throw error
      }
      if (TERMINAL_STATUSES.has(operation.status)) {
        return await settleTerminal(token, operation)
      }
      return await recover(token, null, operation, false)
    } finally {
      if (isCurrent(token)) {
        activeAction = null
        currentBusy = false
        currentReconnecting = false
        currentCancelling = false
        changed()
      }
    }
  }

  function cancelActive() {
    if (disposed) return Promise.reject(new TypeError('draft operation coordinator is disposed'))
    const action = activeAction
    const operation = currentOperation
    if (!action || !operation || TERMINAL_STATUSES.has(operation.status)) {
      return Promise.resolve(false)
    }
    if (action.cancelPromise) return action.cancelPromise
    const token = action.token
    currentCancelling = true
    clearPendingDelay()
    changed()
    action.cancelPromise = (async () => {
      try {
        const received = await cancel(operation.id)
        if (!isCurrent(token)) return null
        const terminal = acceptOperation(received, operation.id)
        if (!TERMINAL_STATUSES.has(terminal.status)) {
          throw new TypeError('Invalid draft operation cancel response')
        }
        timeline.reset()
        if (!await calibrateOperation(token, terminal)) return null
        return await settleTerminal(token, terminal)
      } catch (error) {
        if (!isCurrent(token)) return null
        markKnownFailure(error)
        throw error
      } finally {
        if (isCurrent(token)) {
          currentCancelling = false
          changed()
        }
      }
    })()
    return action.cancelPromise
  }

  return Object.freeze({
    get status() { return currentStatus },
    get operation() { return currentOperation },
    get busy() { return currentBusy },
    get failureCode() { return currentFailureCode },
    get preview() { return timeline.preview },
    get reconnecting() { return currentReconnecting },
    get cancelling() { return currentCancelling },
    get retryAvailable() { return retryCommand !== null },
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
    resume(operationId) {
      return resumeKnown(uuid(operationId, 'draft operation id'))
    },
    cancelActive,
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
