import { sha256Text } from '../../utils/sha256Text.js'
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const CONTENT_HASH = /^[0-9a-f]{64}$/
const EVENT_TYPES = new Set([
  'started', 'delta', 'heartbeat', 'completed', 'failed', 'cancelled',
])
const TERMINAL_EVENT_TYPES = new Set(['completed', 'failed', 'cancelled'])
const TERMINAL_STATUSES = new Set(['completed', 'failed', 'cancelled', 'expired'])
const OPERATION_STATUSES = new Set([
  'starting', 'running', 'completed', 'failed', 'cancelled', 'expired',
])
const NORMALIZING_TERMINAL_STATUSES = new Set(['completed', 'cancelled'])
const MAX_EVENTS = 2_048
const MAX_PARTIAL_SCALARS = 100_000

function plainObject(value) {
  return Boolean(
    value
    && typeof value === 'object'
    && !Array.isArray(value)
    && (Object.getPrototypeOf(value) === Object.prototype
      || Object.getPrototypeOf(value) === null),
  )
}

function invalid() {
  throw new TypeError('Invalid draft operation timeline')
}

function terminalEvidence(type, revision, resultHash, failureCode, { event = false } = {}) {
  if (type === 'completed') {
    if (
      !Number.isInteger(revision)
      || revision < 1
      || typeof resultHash !== 'string'
      || !CONTENT_HASH.test(resultHash)
      || (!event && failureCode !== null)
    ) invalid()
    return { type, revision, resultHash }
  }
  if (type === 'cancelled') {
    if (
      (revision === null) !== (resultHash === null)
      || (!event && failureCode !== null)
      || (revision !== null && (
        !Number.isInteger(revision)
        || revision < 1
        || typeof resultHash !== 'string'
        || !CONTENT_HASH.test(resultHash)
      ))
    ) invalid()
    return { type, revision, resultHash }
  }
  if (type === 'failed') {
    if (
      (!event && (revision !== null || resultHash !== null))
      || typeof failureCode !== 'string'
      || failureCode.length === 0
    ) invalid()
    return { type, failureCode }
  }
  if (type === 'expired') {
    if (!event && (revision !== null || resultHash !== null || failureCode !== null)) invalid()
    return { type }
  }
  invalid()
}

function sameTerminalEvidence(left, right) {
  if (left === null || right === null || left.type !== right.type) return false
  if (left.type === 'completed' || left.type === 'cancelled') {
    return left.revision === right.revision && left.resultHash === right.resultHash
  }
  return left.failureCode === right.failureCode
}

async function calibratedSnapshot(value, hashText) {
  if (!plainObject(value)) invalid()
  const operationId = value.id
  const status = value.status
  const text = value.partialOutput
  const outputHash = value.partialOutputHash
  const scalars = value.partialOutputScalars
  const sequence = value.lastEventSequence
  const revision = value.resultWorkingDraftRevision
  const resultHash = value.resultContentHash
  const failureCode = value.failureCode
  if (
    typeof operationId !== 'string'
    || !CANONICAL_UUID.test(operationId)
    || !OPERATION_STATUSES.has(status)
    || typeof text !== 'string'
    || typeof outputHash !== 'string'
    || !CONTENT_HASH.test(outputHash)
    || !Number.isInteger(scalars)
    || scalars < 0
    || scalars > MAX_PARTIAL_SCALARS
    || unicodeScalarLength(text) !== scalars
    || !Number.isInteger(sequence)
    || sequence < 1
    || sequence > MAX_EVENTS
  ) invalid()
  const actualHash = await hashText(text)
  if (actualHash !== outputHash) invalid()
  const evidence = TERMINAL_STATUSES.has(status)
    ? terminalEvidence(status, revision, resultHash, failureCode)
    : null
  return {
    operationId,
    status,
    text,
    outputHash,
    scalars,
    sequence,
    evidence,
  }
}

export function createDraftOperationTimeline({ hashText = sha256Text } = {}) {
  if (typeof hashText !== 'function') {
    throw new TypeError('hashText is required')
  }
  let currentOperationId = null
  let currentPreview = ''
  let currentHash = null
  let currentScalars = 0
  let currentCursor = 0
  let currentTerminalEvidence = null
  let stateGeneration = 0

  async function calibrate(operation) {
    const generation = stateGeneration
    const snapshot = await calibratedSnapshot(operation, hashText)
    if (generation !== stateGeneration) return false
    if (currentOperationId === null) {
      currentOperationId = snapshot.operationId
      currentPreview = snapshot.text
      currentHash = snapshot.outputHash
      currentScalars = snapshot.scalars
      currentCursor = snapshot.sequence
      currentTerminalEvidence = snapshot.evidence
      return true
    }
    if (
      currentOperationId !== snapshot.operationId
      || currentCursor !== snapshot.sequence
    ) invalid()
    if (TERMINAL_EVENT_TYPES.has(snapshot.status)) {
      if (!sameTerminalEvidence(currentTerminalEvidence, snapshot.evidence)) invalid()
    } else if (snapshot.status === 'expired') {
      if (currentTerminalEvidence?.type !== 'expired' && currentTerminalEvidence !== null) {
        invalid()
      }
    } else if (currentTerminalEvidence !== null) invalid()
    if (currentCursor === snapshot.sequence && (
      currentPreview !== snapshot.text
      || currentHash !== snapshot.outputHash
      || currentScalars !== snapshot.scalars
    )) {
      if (!NORMALIZING_TERMINAL_STATUSES.has(snapshot.status)) invalid()
      currentPreview = snapshot.text
      currentHash = snapshot.outputHash
      currentScalars = snapshot.scalars
    }
    if (TERMINAL_STATUSES.has(snapshot.status)) {
      currentTerminalEvidence = snapshot.evidence
    }
    return true
  }

  async function applyPage(value) {
    const generation = stateGeneration
    if (!plainObject(value) || currentOperationId === null) invalid()
    const events = value.events
    if (
      value.operationId !== currentOperationId
      || !Array.isArray(events)
      || events.length > 100
      || !Number.isInteger(value.lastEventSequence)
      || value.lastEventSequence < currentCursor
      || value.lastEventSequence > MAX_EVENTS
      || !Number.isInteger(value.nextAfter)
      || typeof value.hasMore !== 'boolean'
    ) invalid()

    let nextPreview = currentPreview
    let nextHash = currentHash
    let nextScalars = currentScalars
    let nextCursor = currentCursor
    let nextTerminalEvidence = currentTerminalEvidence
    if (
      nextTerminalEvidence !== null
      && (events.length > 0 || value.lastEventSequence > currentCursor || value.hasMore)
    ) invalid()
    let terminalIndex = -1
    for (let index = 0; index < events.length; index += 1) {
      const event = events[index]
      if (nextTerminalEvidence !== null) invalid()
      if (!plainObject(event)) invalid()
      if (
        !Number.isInteger(event.sequence)
        || event.sequence !== nextCursor + 1
        || !EVENT_TYPES.has(event.type)
        || !Number.isInteger(event.createdAt)
        || event.createdAt < 0
      ) invalid()
      if (event.type === 'started') {
        if (event.sequence !== 1) invalid()
      } else if (event.type === 'delta') {
        const textScalars = unicodeScalarLength(event.text)
        const candidate = nextPreview + event.text
        const candidateScalars = nextScalars + textScalars
        if (
          typeof event.text !== 'string'
          || textScalars < 1
          || !Number.isInteger(event.partialOutputScalars)
          || event.partialOutputScalars !== candidateScalars
          || candidateScalars > MAX_PARTIAL_SCALARS
          || typeof event.partialOutputHash !== 'string'
          || !CONTENT_HASH.test(event.partialOutputHash)
          || await hashText(candidate) !== event.partialOutputHash
        ) invalid()
        nextPreview = candidate
        nextHash = event.partialOutputHash
        nextScalars = candidateScalars
      } else if (TERMINAL_EVENT_TYPES.has(event.type)) {
        if (terminalIndex !== -1) invalid()
        terminalIndex = index
        nextTerminalEvidence = terminalEvidence(
          event.type,
          event.resultWorkingDraftRevision,
          event.resultContentHash,
          event.failureCode,
          { event: true },
        )
      }
      nextCursor = event.sequence
    }
    if (
      value.nextAfter !== nextCursor
      || nextCursor > value.lastEventSequence
      || value.hasMore !== (nextCursor < value.lastEventSequence)
      || (terminalIndex !== -1 && (
        terminalIndex !== events.length - 1
        || nextCursor !== value.lastEventSequence
      ))
    ) invalid()
    if (generation !== stateGeneration) return
    currentPreview = nextPreview
    currentHash = nextHash
    currentScalars = nextScalars
    currentCursor = nextCursor
    currentTerminalEvidence = nextTerminalEvidence
  }

  function reset() {
    stateGeneration += 1
    currentOperationId = null
    currentPreview = ''
    currentHash = null
    currentScalars = 0
    currentCursor = 0
    currentTerminalEvidence = null
  }

  return Object.freeze({
    calibrate,
    applyPage,
    reset,
    get preview() { return currentPreview },
    get cursor() { return currentCursor },
  })
}
