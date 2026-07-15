import { types as utilTypes } from 'node:util'

const ENVELOPE_KEYS = new Set([
  'backendBaseUrl',
  'taskName',
  'projectId',
  'providerId',
  'messages',
  'options'
])
const MESSAGE_KEYS = new Set(['role', 'content'])
const MESSAGE_ROLES = new Set(['system', 'user', 'assistant'])
const FACTORY_KEYS = new Set(['fetchImpl', 'timeoutMs'])
const OUTBOUND_KEYS = new Set([
  'messages',
  'stream',
  'taskName',
  'projectId',
  'providerId',
  'temperature',
  'maxTokens',
  'top_p',
  'response_format',
  'includeUsage'
])
const OPTION_KEYS = new Set([
  'temperature',
  'maxTokens',
  'topP',
  'responseFormat',
  'includeUsage'
])
const FORBIDDEN_NORMALIZED_KEYS = new Set([
  'apikey',
  'baseurl',
  'authorization',
  'headers',
  'provideradapter',
  'applyadapter'
])
const DIAGNOSTIC_KEYS = [
  'requestId',
  'taskId',
  'taskKey',
  'providerId',
  'providerName',
  'modelName',
  'httpStatus',
  'upstreamStatus',
  'elapsedMs',
  'retryable',
  'retriesAttempted',
  'retrySucceeded'
]
const MAX_MESSAGE_BYTES = 2 * 1024 * 1024
const MAX_INPUT_DEPTH = 8
const MAX_INPUT_NODES = 512
const MAX_INPUT_ARRAY_ITEMS = 200

export class AiProxyGatewayError extends Error {
  constructor(message, { code, status = 0, diagnostics = {} } = {}) {
    super(message)
    this.name = 'AiProxyGatewayError'
    this.code = code
    this.status = status
    this.diagnostics = diagnostics
  }
}

function invalidInput() {
  throw new AiProxyGatewayError('The gateway input is invalid.', {
    code: 'invalid_gateway_input'
  })
}

function snapshotGatewayInput(input) {
  try {
    const budget = { active: new WeakSet(), nodes: 0 }
    const envelope = inspectInputRecord(
      input,
      ENVELOPE_KEYS,
      ['backendBaseUrl', 'taskName', 'messages'],
      budget,
      0
    )

    if (typeof envelope.backendBaseUrl.value !== 'string' ||
        envelope.backendBaseUrl.value.length === 0 ||
        !isBoundedString(envelope.taskName.value, 120)) {
      invalidInput()
    }
    const hasProjectId = Object.hasOwn(envelope, 'projectId')
    const hasProviderId = Object.hasOwn(envelope, 'providerId')
    if (!hasProjectId && !hasProviderId) invalidInput()
    if (hasProjectId && !isBoundedString(envelope.projectId.value, 120)) invalidInput()
    if (hasProviderId && !isBoundedString(envelope.providerId.value, 120)) invalidInput()

    const options = Object.hasOwn(envelope, 'options')
      ? snapshotInputOptions(envelope.options.value, budget, 1)
      : undefined
    const messages = snapshotInputMessages(envelope.messages.value, budget, 1)

    const snapshot = Object.create(null)
    snapshot.backendBaseUrl = envelope.backendBaseUrl.value
    snapshot.taskName = envelope.taskName.value
    if (hasProjectId) snapshot.projectId = envelope.projectId.value
    if (hasProviderId) snapshot.providerId = envelope.providerId.value
    snapshot.messages = messages
    if (options !== undefined) snapshot.options = options
    return snapshot
  } catch (error) {
    if (error instanceof AiProxyGatewayError) throw error
    invalidInput()
  }
}

function hasInheritedToJson(value) {
  let prototype = Object.getPrototypeOf(value)
  while (prototype !== null) {
    if (Object.hasOwn(prototype, 'toJSON')) return true
    prototype = Object.getPrototypeOf(prototype)
  }
  return false
}

function consumeInputNode(budget, depth) {
  if (depth > MAX_INPUT_DEPTH) invalidInput()
  budget.nodes += 1
  if (budget.nodes > MAX_INPUT_NODES) invalidInput()
}

function forbiddenInput() {
  throw new AiProxyGatewayError('The gateway input contains a forbidden key.', {
    code: 'forbidden_gateway_key'
  })
}

function inspectInputRecord(
  value,
  allowedKeys,
  requiredKeys,
  budget,
  depth,
  scanUnknownValues = false
) {
  if (value === null || typeof value !== 'object') invalidInput()
  if (utilTypes.isProxy(value) || Array.isArray(value)) invalidInput()
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) invalidInput()
  if (hasInheritedToJson(value)) invalidInput()
  consumeInputNode(budget, depth)

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const keys = Reflect.ownKeys(descriptors)
  if (keys.length > MAX_INPUT_NODES) invalidInput()
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    const descriptor = descriptors[key]
    if (typeof key !== 'string' ||
        !descriptor.enumerable ||
        !Object.hasOwn(descriptor, 'value') ||
        key === 'toJSON') {
      invalidInput()
    }
    if (FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) forbiddenInput()
    if (!allowedKeys.has(key)) {
      if (scanUnknownValues) {
        scanUnknownForbiddenKeys(descriptor.value, budget, depth + 1)
      }
      invalidInput()
    }
  }
  for (let position = 0; position < requiredKeys.length; position += 1) {
    if (!Object.hasOwn(descriptors, requiredKeys[position])) invalidInput()
  }
  return descriptors
}

function inspectInputArray(value, budget, depth) {
  if (value === null || typeof value !== 'object') invalidInput()
  if (utilTypes.isProxy(value) || !Array.isArray(value)) invalidInput()
  if (Object.getPrototypeOf(value) !== Array.prototype || hasInheritedToJson(value)) invalidInput()
  consumeInputNode(budget, depth)

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const lengthDescriptor = descriptors.length
  if (!lengthDescriptor ||
      lengthDescriptor.enumerable ||
      !Object.hasOwn(lengthDescriptor, 'value')) {
    invalidInput()
  }
  const length = lengthDescriptor.value
  if (!Number.isInteger(length) || length < 0 || length > MAX_INPUT_ARRAY_ITEMS) {
    invalidInput()
  }
  const keys = Reflect.ownKeys(descriptors)
  let entryCount = 0
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    if (typeof key !== 'string') invalidInput()
    if (key === 'length') continue
    const descriptor = descriptors[key]
    const index = Number(key)
    if (!descriptor.enumerable ||
        !Object.hasOwn(descriptor, 'value') ||
        !Number.isInteger(index) ||
        index < 0 ||
        index >= length ||
        String(index) !== key) {
      invalidInput()
    }
    entryCount += 1
  }
  if (entryCount !== length) invalidInput()
  return descriptors
}

function snapshotInputMessages(value, budget, depth) {
  const descriptors = inspectInputArray(value, budget, depth)
  const length = descriptors.length.value
  if (length < 1) invalidInput()

  const output = new Array(length)
  Object.setPrototypeOf(output, null)
  let totalBytes = 0
  for (let index = 0; index < length; index += 1) {
    const message = inspectInputRecord(
      descriptors[String(index)].value,
      MESSAGE_KEYS,
      ['role', 'content'],
      budget,
      depth + 1
    )
    if (!MESSAGE_ROLES.has(message.role.value) || typeof message.content.value !== 'string') {
      invalidInput()
    }
    totalBytes += Buffer.byteLength(message.content.value, 'utf8')
    if (totalBytes > MAX_MESSAGE_BYTES) invalidInput()
    const messageSnapshot = Object.create(null)
    messageSnapshot.role = message.role.value
    messageSnapshot.content = message.content.value
    Object.defineProperty(output, String(index), {
      configurable: true,
      enumerable: true,
      value: messageSnapshot,
      writable: true
    })
  }
  return output
}

function snapshotInputOptions(value, budget, depth) {
  const descriptors = inspectInputRecord(
    value,
    OPTION_KEYS,
    [],
    budget,
    depth,
    true
  )
  const snapshot = Object.create(null)
  const keys = Reflect.ownKeys(descriptors)
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    const option = descriptors[key].value
    if (key === 'temperature' &&
        (typeof option !== 'number' || !Number.isFinite(option) || option < 0 || option > 2)) {
      invalidInput()
    }
    if (key === 'maxTokens' &&
        (!Number.isInteger(option) || option < 1 || option > 65536)) {
      invalidInput()
    }
    if (key === 'topP' &&
        (typeof option !== 'number' || !Number.isFinite(option) || option <= 0 || option > 1)) {
      invalidInput()
    }
    if (key === 'responseFormat' && option !== 'json') invalidInput()
    if (key === 'includeUsage' && typeof option !== 'boolean') invalidInput()
    snapshot[key] = option
  }
  return snapshot
}

function scanUnknownForbiddenKeys(value, budget, depth) {
  if (value === null || typeof value === 'string' || typeof value === 'boolean') return
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) invalidInput()
    return
  }
  if (typeof value !== 'object' || utilTypes.isProxy(value)) invalidInput()
  if (budget.active.has(value)) invalidInput()
  if (Array.isArray(value)) {
    scanUnknownArray(value, budget, depth)
  } else {
    scanUnknownRecord(value, budget, depth)
  }
}

function scanUnknownRecord(value, budget, depth) {
  const prototype = Object.getPrototypeOf(value)
  if (prototype !== Object.prototype && prototype !== null) invalidInput()
  if (hasInheritedToJson(value)) invalidInput()
  consumeInputNode(budget, depth)
  budget.active.add(value)
  try {
    const descriptors = Object.getOwnPropertyDescriptors(value)
    const keys = Reflect.ownKeys(descriptors)
    if (keys.length > MAX_INPUT_NODES) invalidInput()
    for (let position = 0; position < keys.length; position += 1) {
      const key = keys[position]
      const descriptor = descriptors[key]
      if (typeof key !== 'string' ||
          !descriptor.enumerable ||
          !Object.hasOwn(descriptor, 'value') ||
          key === 'toJSON') {
        invalidInput()
      }
      if (FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) forbiddenInput()
      scanUnknownForbiddenKeys(descriptor.value, budget, depth + 1)
    }
  } finally {
    budget.active.delete(value)
  }
}

function scanUnknownArray(value, budget, depth) {
  if (Object.getPrototypeOf(value) !== Array.prototype || hasInheritedToJson(value)) {
    invalidInput()
  }
  consumeInputNode(budget, depth)
  budget.active.add(value)
  try {
    const descriptors = Object.getOwnPropertyDescriptors(value)
    const lengthDescriptor = descriptors.length
    if (!lengthDescriptor ||
        lengthDescriptor.enumerable ||
        !Object.hasOwn(lengthDescriptor, 'value') ||
        lengthDescriptor.value > MAX_INPUT_ARRAY_ITEMS) {
      invalidInput()
    }
    const keys = Reflect.ownKeys(descriptors)
    let entryCount = 0
    for (let position = 0; position < keys.length; position += 1) {
      const key = keys[position]
      if (typeof key !== 'string') invalidInput()
      if (key === 'length') continue
      const descriptor = descriptors[key]
      if (!descriptor.enumerable || !Object.hasOwn(descriptor, 'value')) invalidInput()
      if (FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) forbiddenInput()
      const index = Number(key)
      if (!Number.isInteger(index) ||
          index < 0 ||
          index >= lengthDescriptor.value ||
          String(index) !== key) {
        invalidInput()
      }
      entryCount += 1
      scanUnknownForbiddenKeys(descriptor.value, budget, depth + 1)
    }
    if (entryCount !== lengthDescriptor.value) invalidInput()
  } finally {
    budget.active.delete(value)
  }
}

function normalizeKey(key) {
  return String(key).toLowerCase().replace(/[_-]/g, '')
}

function scanForbiddenKeys(value, seen = new WeakSet()) {
  if (value === null || typeof value !== 'object') return
  if (seen.has(value)) return
  seen.add(value)

  if (Array.isArray(value)) {
    for (let index = 0; index < value.length; index += 1) {
      scanForbiddenKeys(value[index], seen)
    }
    return
  }

  for (const [key, child] of Object.entries(value)) {
    if (FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) {
      throw new AiProxyGatewayError('The gateway input contains a forbidden key.', {
        code: 'forbidden_gateway_key'
      })
    }
    scanForbiddenKeys(child, seen)
  }
}

function isObject(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function assertExactKeys(value, allowed) {
  if (!isObject(value)) invalidInput()
  for (const key of Object.keys(value)) {
    if (!allowed.has(key)) invalidInput()
  }
}

function isBoundedString(value, maximum) {
  return typeof value === 'string' &&
    [...value].length >= 1 &&
    [...value].length <= maximum
}

function validateMessages(messages) {
  if (!Array.isArray(messages) || messages.length < 1 || messages.length > 200) {
    invalidInput()
  }

  let totalBytes = 0
  for (let index = 0; index < messages.length; index += 1) {
    const message = messages[index]
    assertExactKeys(message, MESSAGE_KEYS)
    if (!MESSAGE_ROLES.has(message.role) || typeof message.content !== 'string') {
      invalidInput()
    }
    totalBytes += Buffer.byteLength(message.content, 'utf8')
    if (totalBytes > MAX_MESSAGE_BYTES) invalidInput()
  }
}

function validateOptions(options) {
  assertExactKeys(options, OPTION_KEYS)

  if (options.temperature !== undefined &&
      (typeof options.temperature !== 'number' ||
       !Number.isFinite(options.temperature) ||
       options.temperature < 0 ||
       options.temperature > 2)) {
    invalidInput()
  }
  if (options.maxTokens !== undefined &&
      (!Number.isInteger(options.maxTokens) ||
       options.maxTokens < 1 ||
       options.maxTokens > 65536)) {
    invalidInput()
  }
  if (options.topP !== undefined &&
      (typeof options.topP !== 'number' ||
       !Number.isFinite(options.topP) ||
       options.topP <= 0 ||
       options.topP > 1)) {
    invalidInput()
  }
  if (options.responseFormat !== undefined && options.responseFormat !== 'json') {
    invalidInput()
  }
  if (options.includeUsage !== undefined && typeof options.includeUsage !== 'boolean') {
    invalidInput()
  }
}

function validateGatewayInput(input) {
  assertExactKeys(input, ENVELOPE_KEYS)
  if (typeof input.backendBaseUrl !== 'string' || input.backendBaseUrl.length === 0) {
    invalidInput()
  }
  if (!isBoundedString(input.taskName, 120)) invalidInput()

  const hasProjectId = Object.hasOwn(input, 'projectId')
  const hasProviderId = Object.hasOwn(input, 'providerId')
  if (!hasProjectId && !hasProviderId) invalidInput()
  if (hasProjectId && !isBoundedString(input.projectId, 120)) invalidInput()
  if (hasProviderId && !isBoundedString(input.providerId, 120)) invalidInput()

  validateMessages(input.messages)
  validateOptions(input.options === undefined ? {} : input.options)
}

function normalizeBackendApiBase(raw) {
  let url
  try {
    url = new URL(raw)
  } catch {
    invalidInput()
  }

  const normalizedHostname = url.hostname === '[::1]' ? '::1' : url.hostname
  const allowedHosts = new Set(['localhost', '127.0.0.1', '::1'])
  if (url.protocol !== 'http:' ||
      url.username ||
      url.password ||
      !allowedHosts.has(normalizedHostname) ||
      raw.includes('?') ||
      raw.includes('#') ||
      !['/', '/api', '/api/'].includes(url.pathname)) {
    invalidInput()
  }

  return `${url.origin}/api`
}

function pickDiagnostics(value) {
  const output = []
  if (!isObject(value)) return {}
  for (const key of DIAGNOSTIC_KEYS) {
    if (!Object.hasOwn(value, key)) continue
    const diagnosticValue = value[key]
    if (isSafeDiagnosticValue(key, diagnosticValue)) {
      output.push([key, diagnosticValue])
    }
  }
  return Object.fromEntries(output)
}

function isSafeDiagnosticValue(key, value) {
  if (['requestId', 'taskId', 'taskKey', 'providerId', 'providerName', 'modelName'].includes(key)) {
    return typeof value === 'string' &&
      [...value].length <= 256 &&
      Buffer.byteLength(value, 'utf8') <= 1024 &&
      !/[\u0000-\u001f\u007f-\u009f]/u.test(value)
  }
  if (key === 'httpStatus' || key === 'upstreamStatus') {
    return Number.isInteger(value) && value >= 100 && value <= 599
  }
  if (key === 'elapsedMs') {
    return Number.isInteger(value) && value >= 0 && value <= 86400000
  }
  if (key === 'retriesAttempted') {
    return Number.isInteger(value) && value >= 0 && value <= 100
  }
  if (key === 'retryable' || key === 'retrySucceeded') {
    return typeof value === 'boolean'
  }
  return false
}

function invalidGatewayConfiguration() {
  throw new AiProxyGatewayError('The gateway configuration is invalid.', {
    code: 'invalid_gateway_input'
  })
}

function snapshotGatewayConfiguration(configuration) {
  if (configuration === null || typeof configuration !== 'object') {
    invalidGatewayConfiguration()
  }
  if (utilTypes.isProxy(configuration) || Array.isArray(configuration)) {
    invalidGatewayConfiguration()
  }
  const prototype = Object.getPrototypeOf(configuration)
  if (prototype !== Object.prototype && prototype !== null) {
    invalidGatewayConfiguration()
  }

  const descriptors = Object.getOwnPropertyDescriptors(configuration)
  const keys = Reflect.ownKeys(descriptors)
  const snapshot = Object.create(null)
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    if (typeof key !== 'string' ||
        !FACTORY_KEYS.has(key) ||
        FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) {
      invalidGatewayConfiguration()
    }
    const descriptor = descriptors[key]
    if (!descriptor.enumerable || !Object.hasOwn(descriptor, 'value')) {
      invalidGatewayConfiguration()
    }
    Object.defineProperty(snapshot, key, {
      configurable: true,
      enumerable: true,
      value: descriptor.value,
      writable: true
    })
  }
  return snapshot
}

export function createAiProxyGateway(configuration = {}) {
  const snapshot = snapshotGatewayConfiguration(configuration)
  const fetchImpl = snapshot.fetchImpl
  const timeoutMs = snapshot.timeoutMs === undefined
    ? 20 * 60 * 1000
    : snapshot.timeoutMs
  if (typeof fetchImpl !== 'function') {
    throw new AiProxyGatewayError('A fetch implementation is required.', {
      code: 'invalid_gateway_input'
    })
  }
  if (!Number.isInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 2147483647) {
    invalidGatewayConfiguration()
  }

  return {
    chatCompletion: input => chatCompletion({ input, fetchImpl, timeoutMs })
  }
}

function buildProxyPayload({ taskName, projectId, providerId, messages, options = {} }) {
  const payload = Object.create(null)
  payload.messages = messages
  payload.stream = false
  payload.taskName = taskName
  if (projectId !== undefined) payload.projectId = projectId
  if (providerId !== undefined) payload.providerId = providerId
  if (options.temperature !== undefined) payload.temperature = options.temperature
  if (options.maxTokens !== undefined) payload.maxTokens = options.maxTokens
  if (options.topP !== undefined) payload.top_p = options.topP
  if (options.responseFormat === 'json') {
    const responseFormat = Object.create(null)
    responseFormat.type = 'json_object'
    payload.response_format = responseFormat
  }
  if (options.includeUsage !== undefined) payload.includeUsage = options.includeUsage
  return payload
}

function auditOutboundRecord(value, allowedKeys, requiredKeys = []) {
  if (value === null || typeof value !== 'object') invalidInput()
  if (utilTypes.isProxy(value) || Array.isArray(value)) invalidInput()
  if (Object.getPrototypeOf(value) !== null) invalidInput()

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const keys = Reflect.ownKeys(descriptors)
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    if (typeof key !== 'string' ||
        !allowedKeys.has(key) ||
        FORBIDDEN_NORMALIZED_KEYS.has(normalizeKey(key))) {
      invalidInput()
    }
    const descriptor = descriptors[key]
    if (!descriptor.enumerable || !Object.hasOwn(descriptor, 'value')) invalidInput()
  }
  for (let position = 0; position < requiredKeys.length; position += 1) {
    if (!Object.hasOwn(descriptors, requiredKeys[position])) invalidInput()
  }
  return descriptors
}

function auditOutboundArray(value) {
  if (value === null || typeof value !== 'object' || utilTypes.isProxy(value) || !Array.isArray(value)) {
    invalidInput()
  }
  if (Object.getPrototypeOf(value) !== null) invalidInput()

  const descriptors = Object.getOwnPropertyDescriptors(value)
  const lengthDescriptor = descriptors.length
  if (!lengthDescriptor ||
      lengthDescriptor.enumerable ||
      !Object.hasOwn(lengthDescriptor, 'value')) {
    invalidInput()
  }
  const keys = Reflect.ownKeys(descriptors)
  let entryCount = 0
  for (let position = 0; position < keys.length; position += 1) {
    const key = keys[position]
    if (typeof key !== 'string') invalidInput()
    if (key === 'length') continue
    const descriptor = descriptors[key]
    const index = Number(key)
    if (!descriptor.enumerable ||
        !Object.hasOwn(descriptor, 'value') ||
        !Number.isInteger(index) ||
        index < 0 ||
        index >= lengthDescriptor.value ||
        String(index) !== key) {
      invalidInput()
    }
    entryCount += 1
  }
  if (entryCount !== lengthDescriptor.value) invalidInput()
  return descriptors
}

function auditOutboundPayload(payload) {
  const descriptors = auditOutboundRecord(
    payload,
    OUTBOUND_KEYS,
    ['messages', 'stream', 'taskName']
  )
  if (descriptors.stream.value !== false || !isBoundedString(descriptors.taskName.value, 120)) {
    invalidInput()
  }
  if (!Object.hasOwn(descriptors, 'projectId') && !Object.hasOwn(descriptors, 'providerId')) {
    invalidInput()
  }

  const messages = auditOutboundArray(descriptors.messages.value)
  const messageCount = messages.length.value
  if (messageCount < 1 || messageCount > 200) invalidInput()
  for (let index = 0; index < messageCount; index += 1) {
    const message = auditOutboundRecord(
      messages[String(index)].value,
      MESSAGE_KEYS,
      ['role', 'content']
    )
    if (!MESSAGE_ROLES.has(message.role.value) || typeof message.content.value !== 'string') {
      invalidInput()
    }
  }

  if (Object.hasOwn(descriptors, 'response_format')) {
    const responseFormat = auditOutboundRecord(
      descriptors.response_format.value,
      new Set(['type']),
      ['type']
    )
    if (responseFormat.type.value !== 'json_object') invalidInput()
  }
}

async function chatCompletion({ input, fetchImpl, timeoutMs }) {
  const snapshot = snapshotGatewayInput(input)
  scanForbiddenKeys(snapshot)
  validateGatewayInput(snapshot)
  const backendApiBase = normalizeBackendApiBase(snapshot.backendBaseUrl)
  const controller = new AbortController()
  const deadlineSignal = Symbol('gateway-deadline')
  let timedOut = false
  let timeout
  const deadline = new Promise((_resolve, reject) => {
    timeout = setTimeout(() => {
      timedOut = true
      controller.abort()
      reject(deadlineSignal)
    }, timeoutMs)
  })
  const operation = (async () => {
    const payload = buildProxyPayload(snapshot)
    auditOutboundPayload(payload)
    const body = JSON.stringify(payload)
    const response = await fetchImpl(`${backendApiBase}/ai/chat-completions`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      redirect: 'error',
      signal: controller.signal
    })
    return { response, text: await response.text() }
  })()

  try {
    const { response, text } = await Promise.race([operation, deadline])
    let parsed = null
    try {
      parsed = text ? JSON.parse(text) : null
    } catch {
      parsed = null
    }
    if (response.status >= 300 && response.status < 400) {
      throw new AiProxyGatewayError('The AI proxy redirect was rejected.', {
        code: 'ai_proxy_redirect_rejected',
        status: response.status,
        diagnostics: pickDiagnostics(parsed?.detail)
      })
    }
    if (response.status >= 400) {
      throw new AiProxyGatewayError('The AI proxy request failed.', {
        code: 'ai_proxy_http_error',
        status: response.status,
        diagnostics: pickDiagnostics(parsed?.detail)
      })
    }
    const content = parsed?.choices?.[0]?.message?.content
    if (typeof content !== 'string') {
      throw new AiProxyGatewayError('The AI proxy response was invalid.', {
        code: 'ai_proxy_invalid_response',
        status: response.status
      })
    }
    return {
      content,
      diagnostics: pickDiagnostics(parsed.proxyDiagnostics)
    }
  } catch (error) {
    if (error instanceof AiProxyGatewayError) throw error
    if (timedOut) {
      throw new AiProxyGatewayError('The AI proxy request timed out.', {
        code: 'ai_proxy_timeout',
        diagnostics: { retryable: true }
      })
    }
    throw new AiProxyGatewayError('The AI proxy request could not be completed.', {
      code: 'ai_proxy_request_failed'
    })
  } finally {
    clearTimeout(timeout)
  }
}
