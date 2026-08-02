import { sha256Text } from '../../utils/sha256Text.js'
import { unicodeScalarLength } from '../../utils/unicodeScalarText.js'

const CANONICAL_UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
const CONTENT_HASH = /^[0-9a-f]{64}$/
const EVENT_TYPES = new Set([
  'started', 'delta', 'heartbeat', 'completed', 'failed', 'cancelled',
])
const TERMINAL_EVENT_TYPES = new Set(['completed', 'failed', 'cancelled'])
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

async function calibratedSnapshot(value, hashText) {
  if (!plainObject(value)) invalid()
  const operationId = value.id
  const text = value.partialOutput
  const outputHash = value.partialOutputHash
  const scalars = value.partialOutputScalars
  const sequence = value.lastEventSequence
  if (
    typeof operationId !== 'string'
    || !CANONICAL_UUID.test(operationId)
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
  return { operationId, text, outputHash, scalars, sequence }
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
  let stateGeneration = 0

  async function calibrate(operation) {
    const generation = stateGeneration
    const snapshot = await calibratedSnapshot(operation, hashText)
    if (generation !== stateGeneration) return
    if (
      currentOperationId !== null
      && currentOperationId !== snapshot.operationId
    ) invalid()
    if (currentOperationId === null || currentCursor > snapshot.sequence) {
      currentOperationId = snapshot.operationId
      currentPreview = snapshot.text
      currentHash = snapshot.outputHash
      currentScalars = snapshot.scalars
      currentCursor = snapshot.sequence
      return
    }
    if (currentCursor === snapshot.sequence && (
      currentPreview !== snapshot.text
      || currentHash !== snapshot.outputHash
      || currentScalars !== snapshot.scalars
    )) invalid()
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
    let terminalIndex = -1
    for (let index = 0; index < events.length; index += 1) {
      const event = events[index]
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
  }

  function reset() {
    stateGeneration += 1
    currentOperationId = null
    currentPreview = ''
    currentHash = null
    currentScalars = 0
    currentCursor = 0
  }

  return Object.freeze({
    calibrate,
    applyPage,
    reset,
    get preview() { return currentPreview },
    get cursor() { return currentCursor },
  })
}
