import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

import {
  AiProxyGatewayError,
  createAiProxyGateway
} from '../ai-proxy-gateway.mjs'

function fakeJsonResponse(body, { status = 200 } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async text() {
      return JSON.stringify(body)
    }
  }
}

function validInput() {
  return {
    backendBaseUrl: 'http://127.0.0.1:8000',
    taskName: 'draft_generation',
    projectId: 'project-1',
    messages: [{ role: 'user', content: 'hello' }],
    options: {}
  }
}

test('requires an explicitly injected fetch implementation', async () => {
  assert.equal(typeof AiProxyGatewayError, 'function')
  assert.equal(typeof createAiProxyGateway, 'function')
  assert.throws(
    () => createAiProxyGateway(),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'A fetch implementation is required.')
      assert.equal(error.code, 'invalid_gateway_input')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      return true
    }
  )
})

function assertInvalidGatewayConfiguration(create) {
  assert.throws(
    create,
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The gateway configuration is invalid.')
      assert.equal(error.code, 'invalid_gateway_input')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      assert.equal(`${error.message} ${JSON.stringify(error)}`.includes('DEMO_SECRET'), false)
      return true
    }
  )
}

test('maps a null factory configuration to a fixed typed error', () => {
  assertInvalidGatewayConfiguration(() => createAiProxyGateway(null))
})

for (const timeoutMs of [
  0,
  -1,
  1.5,
  2147483648,
  Number.NaN,
  Number.POSITIVE_INFINITY,
  'DEMO_SECRET',
  null,
  true
]) {
  test(`rejects invalid timeoutMs ${String(timeoutMs)} with a fixed typed error`, () => {
    assertInvalidGatewayConfiguration(() => createAiProxyGateway({
      fetchImpl: async () => assert.fail('fetch must not be called'),
      timeoutMs
    }))
  })
}

test('accepts the maximum supported timeoutMs', () => {
  const gateway = createAiProxyGateway({
    fetchImpl: async () => assert.fail('fetch must not be called'),
    timeoutMs: 2147483647
  })
  assert.equal(typeof gateway.chatCompletion, 'function')
})

for (const key of ['extra', 'apiKey', 'baseURL', 'headers', 'providerAdapter']) {
  test(`rejects factory configuration key ${key} with a fixed typed error`, () => {
    assertInvalidGatewayConfiguration(() => createAiProxyGateway({
      fetchImpl: async () => assert.fail('fetch must not be called'),
      [key]: 'DEMO_SECRET'
    }))
  })
}

test('rejects hidden factory configuration properties', () => {
  for (const key of ['fetchImpl', 'extra']) {
    const configuration = {}
    Object.defineProperty(configuration, key, {
      enumerable: false,
      value: key === 'fetchImpl'
        ? async () => assert.fail('fetch must not be called')
        : 'DEMO_SECRET'
    })
    if (key !== 'fetchImpl') {
      configuration.fetchImpl = async () => assert.fail('fetch must not be called')
    }
    assertInvalidGatewayConfiguration(() => createAiProxyGateway(configuration))
  }
})

test('rejects symbol factory configuration properties', () => {
  const configuration = {
    fetchImpl: async () => assert.fail('fetch must not be called')
  }
  configuration[Symbol('apiKey')] = 'DEMO_SECRET'
  assertInvalidGatewayConfiguration(() => createAiProxyGateway(configuration))
})

for (const key of ['fetchImpl', 'timeoutMs']) {
  test(`rejects a factory ${key} accessor without invoking it`, () => {
    let readCount = 0
    const configuration = key === 'fetchImpl'
      ? {}
      : { fetchImpl: async () => assert.fail('fetch must not be called') }
    Object.defineProperty(configuration, key, {
      enumerable: true,
      get() {
        readCount += 1
        throw new Error('DEMO_SECRET getter')
      }
    })

    assertInvalidGatewayConfiguration(() => createAiProxyGateway(configuration))
    assert.equal(readCount, 0)
  })
}

test('rejects non-plain and inherited factory configurations', () => {
  const ownConfiguration = {
    fetchImpl: async () => assert.fail('fetch must not be called')
  }
  Object.setPrototypeOf(ownConfiguration, { inherited: 'DEMO_SECRET' })
  assertInvalidGatewayConfiguration(() => createAiProxyGateway(ownConfiguration))

  const inheritedConfiguration = Object.create({
    fetchImpl: async () => assert.fail('fetch must not be called')
  })
  assertInvalidGatewayConfiguration(() => createAiProxyGateway(inheritedConfiguration))
})

test('rejects a factory Proxy before invoking any trap', () => {
  let trapCount = 0
  const configuration = new Proxy({
    fetchImpl: async () => assert.fail('fetch must not be called')
  }, {
    get(target, key, receiver) {
      trapCount += 1
      return Reflect.get(target, key, receiver)
    },
    getOwnPropertyDescriptor(target, key) {
      trapCount += 1
      return Reflect.getOwnPropertyDescriptor(target, key)
    },
    getPrototypeOf(target) {
      trapCount += 1
      return Reflect.getPrototypeOf(target)
    },
    ownKeys(target) {
      trapCount += 1
      return Reflect.ownKeys(target)
    }
  })

  assertInvalidGatewayConfiguration(() => createAiProxyGateway(configuration))
  assert.equal(trapCount, 0)
})

test('accepts a null-prototype factory data configuration', () => {
  const configuration = Object.assign(Object.create(null), {
    fetchImpl: async () => assert.fail('fetch must not be called'),
    timeoutMs: 1
  })
  const gateway = createAiProxyGateway(configuration)
  assert.equal(typeof gateway.chatCompletion, 'function')
})

test('builds one fixed identifier-only non-stream request', async () => {
  const calls = []
  const gateway = createAiProxyGateway({
    fetchImpl: async (...args) => {
      calls.push(args)
      return fakeJsonResponse({
        choices: [{ message: { content: 'ok' } }],
        proxyDiagnostics: {}
      })
    }
  })

  const result = await gateway.chatCompletion({
    ...validInput(),
    providerId: 'provider-1',
    options: {
      temperature: 0,
      maxTokens: 512,
      topP: 0.8,
      responseFormat: 'json',
      includeUsage: true
    }
  })

  assert.deepEqual(result, { content: 'ok', diagnostics: {} })
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], 'http://127.0.0.1:8000/api/ai/chat-completions')
  assert.equal(calls[0][1].method, 'POST')
  assert.equal(calls[0][1].redirect, 'error')
  assert.deepEqual(calls[0][1].headers, { 'Content-Type': 'application/json' })
  assert.equal(calls[0][1].signal instanceof AbortSignal, true)
  assert.deepEqual(JSON.parse(calls[0][1].body), {
    messages: [{ role: 'user', content: 'hello' }],
    stream: false,
    taskName: 'draft_generation',
    projectId: 'project-1',
    providerId: 'provider-1',
    temperature: 0,
    maxTokens: 512,
    top_p: 0.8,
    response_format: { type: 'json_object' },
    includeUsage: true
  })
  assert.equal('model' in JSON.parse(calls[0][1].body), false)
  assert.equal('thinking' in JSON.parse(calls[0][1].body), false)
  assert.equal('retry' in JSON.parse(calls[0][1].body), false)
})

async function assertInvalidInputBeforeFetch(input) {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({
        choices: [{ message: { content: 'must not be returned' } }]
      })
    }
  })

  await assert.rejects(
    gateway.chatCompletion(input),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The gateway input is invalid.')
      assert.equal(error.code, 'invalid_gateway_input')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      return true
    }
  )
  assert.equal(callCount, 0)
}

const invalidInputCases = [
  ['a null envelope', () => null],
  ['an array envelope', () => []],
  ['an unknown envelope field', () => ({ ...validInput(), model: 'forbidden' })],
  ['a missing backendBaseUrl', () => {
    const input = validInput()
    delete input.backendBaseUrl
    return input
  }],
  ['a missing taskName', () => {
    const input = validInput()
    delete input.taskName
    return input
  }],
  ['an empty taskName', () => ({ ...validInput(), taskName: '' })],
  ['a non-string taskName', () => ({ ...validInput(), taskName: 1 })],
  ['a 121-character taskName', () => ({ ...validInput(), taskName: 't'.repeat(121) })],
  ['a missing project/provider identity', () => {
    const input = validInput()
    delete input.projectId
    return input
  }],
  ['an empty projectId', () => ({ ...validInput(), projectId: '' })],
  ['a non-string projectId', () => ({ ...validInput(), projectId: 1 })],
  ['a 121-character projectId', () => ({ ...validInput(), projectId: 'p'.repeat(121) })],
  ['an empty providerId when projectId is valid', () => ({ ...validInput(), providerId: '' })],
  ['a non-string providerId', () => ({ ...validInput(), providerId: {} })],
  ['a 121-character providerId', () => ({ ...validInput(), providerId: 'p'.repeat(121) })],
  ['non-array messages', () => ({ ...validInput(), messages: {} })],
  ['empty messages', () => ({ ...validInput(), messages: [] })],
  ['201 messages', () => ({
    ...validInput(),
    messages: Array.from({ length: 201 }, () => ({ role: 'user', content: '' }))
  })],
  ['a non-object message', () => ({ ...validInput(), messages: ['hello'] })],
  ['a message missing role', () => ({ ...validInput(), messages: [{ content: 'hello' }] })],
  ['a message missing content', () => ({ ...validInput(), messages: [{ role: 'user' }] })],
  ['an unknown message field', () => ({
    ...validInput(),
    messages: [{ role: 'user', content: 'hello', name: 'extra' }]
  })],
  ['an unsupported message role', () => ({
    ...validInput(),
    messages: [{ role: 'tool', content: 'hello' }]
  })],
  ['non-string message content', () => ({
    ...validInput(),
    messages: [{ role: 'user', content: {} }]
  })],
  ['message content over 2 MiB UTF-8', () => ({
    ...validInput(),
    messages: [{ role: 'user', content: `${'a'.repeat(2 * 1024 * 1024)}b` }]
  })],
  ['non-object options', () => ({ ...validInput(), options: [] })],
  ['an unknown option', () => ({ ...validInput(), options: { thinking: {} } })],
  ['temperature below zero', () => ({ ...validInput(), options: { temperature: -0.1 } })],
  ['temperature above two', () => ({ ...validInput(), options: { temperature: 2.1 } })],
  ['non-finite temperature', () => ({ ...validInput(), options: { temperature: Number.NaN } })],
  ['non-number temperature', () => ({ ...validInput(), options: { temperature: '1' } })],
  ['maxTokens below one', () => ({ ...validInput(), options: { maxTokens: 0 } })],
  ['maxTokens above 65536', () => ({ ...validInput(), options: { maxTokens: 65537 } })],
  ['non-integer maxTokens', () => ({ ...validInput(), options: { maxTokens: 1.5 } })],
  ['topP equal to zero', () => ({ ...validInput(), options: { topP: 0 } })],
  ['topP above one', () => ({ ...validInput(), options: { topP: 1.1 } })],
  ['non-finite topP', () => ({ ...validInput(), options: { topP: Number.POSITIVE_INFINITY } })],
  ['unsupported responseFormat', () => ({ ...validInput(), options: { responseFormat: 'text' } })],
  ['non-boolean includeUsage', () => ({ ...validInput(), options: { includeUsage: 'yes' } })]
]

for (const [name, makeInput] of invalidInputCases) {
  test(`rejects ${name} before fetch`, async () => {
    await assertInvalidInputBeforeFetch(makeInput())
  })
}

test('accepts exact string, message-count, and UTF-8 size maxima', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
    }
  })
  const messages = Array.from(
    { length: 200 },
    (_, index) => ({
      role: index % 3 === 0 ? 'system' : index % 3 === 1 ? 'user' : 'assistant',
      content: index === 0 ? 'a'.repeat(2 * 1024 * 1024) : ''
    })
  )

  const result = await gateway.chatCompletion({
    backendBaseUrl: 'http://localhost:8000/api/',
    taskName: '😀'.repeat(120),
    projectId: 'p'.repeat(120),
    providerId: '供'.repeat(120),
    messages,
    options: {
      temperature: 2,
      maxTokens: 65536,
      topP: 1,
      responseFormat: 'json',
      includeUsage: true
    }
  })

  assert.equal(result.content, 'ok')
  assert.equal(callCount, 1)
})

test('accepts numeric lower endpoints, provider-only identity, and omitted options', async () => {
  const bodies = []
  const gateway = createAiProxyGateway({
    fetchImpl: async (_url, init) => {
      bodies.push(JSON.parse(init.body))
      return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
    }
  })
  const providerOnly = validInput()
  delete providerOnly.projectId
  delete providerOnly.options
  providerOnly.providerId = 'provider-1'

  await gateway.chatCompletion(providerOnly)
  await gateway.chatCompletion({
    ...validInput(),
    options: {
      temperature: 0,
      maxTokens: 1,
      topP: Number.MIN_VALUE,
      includeUsage: false
    }
  })

  assert.equal(bodies.length, 2)
  assert.equal('projectId' in bodies[0], false)
  assert.equal(bodies[0].providerId, 'provider-1')
  assert.equal(bodies[1].temperature, 0)
  assert.equal(bodies[1].maxTokens, 1)
  assert.equal(bodies[1].top_p, Number.MIN_VALUE)
  assert.equal(bodies[1].includeUsage, false)
})

async function assertUnsafeShapeRejectedBeforeFetch(input) {
  const bodies = []
  const gateway = createAiProxyGateway({
    fetchImpl: async (_url, init) => {
      bodies.push(init.body)
      return fakeJsonResponse({ choices: [{ message: { content: 'unexpected' } }] })
    }
  })

  await assert.rejects(
    gateway.chatCompletion(input),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The gateway input is invalid.')
      assert.equal(error.code, 'invalid_gateway_input')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      return true
    }
  )
  assert.equal(bodies.length, 0)
  assert.equal(bodies.some(body => body.includes('apiKey')), false)
  assert.equal(bodies.some(body => body.includes('DEMO_SECRET')), false)
}

async function assertUnknownRejectedWithinInspectionBudget(input, maximumInspections) {
  let callCount = 0
  let inspectionCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({ choices: [{ message: { content: 'unexpected' } }] })
    }
  })
  const originalGetOwnPropertyDescriptors = Object.getOwnPropertyDescriptors
  Object.getOwnPropertyDescriptors = function countedDescriptors(value) {
    inspectionCount += 1
    return originalGetOwnPropertyDescriptors(value)
  }
  try {
    await assert.rejects(
      gateway.chatCompletion(input),
      error => {
        assert.equal(error instanceof AiProxyGatewayError, true)
        assert.equal(error.message, 'The gateway input is invalid.')
        assert.equal(error.code, 'invalid_gateway_input')
        assert.equal(error.status, 0)
        assert.deepEqual(error.diagnostics, {})
        assert.equal('cause' in error, false)
        return true
      }
    )
  } finally {
    Object.getOwnPropertyDescriptors = originalGetOwnPropertyDescriptors
  }
  assert.equal(callCount, 0)
  assert.equal(inspectionCount <= maximumInspections, true)
}

test('rejects a deep unknown root child without traversing it', async () => {
  let unknown = { value: 'DEMO_SECRET' }
  for (let depth = 0; depth < 500; depth += 1) unknown = { next: unknown }
  const input = { ...validInput(), unknown }
  await assertUnknownRejectedWithinInspectionBudget(input, 1)
})

test('rejects a large unknown root child without traversing it', async () => {
  const input = {
    ...validInput(),
    unknown: Array.from({ length: 1000 }, () => ({ value: 'DEMO_SECRET' }))
  }
  await assertUnknownRejectedWithinInspectionBudget(input, 1)
})

test('bounds inspection depth for a deep unknown option child', async () => {
  let nested = { value: 'DEMO_SECRET' }
  for (let depth = 0; depth < 500; depth += 1) nested = { next: nested }
  const input = { ...validInput(), options: { nested } }
  await assertUnknownRejectedWithinInspectionBudget(input, 12)
})

test('rejects an oversized unknown option array before inspecting its children', async () => {
  const input = {
    ...validInput(),
    options: {
      nested: Array.from({ length: 1000 }, () => ({ value: 'DEMO_SECRET' }))
    }
  }
  await assertUnknownRejectedWithinInspectionBudget(input, 3)
})

const hiddenFieldCases = [
  ['envelope', input => input],
  ['message', input => input.messages[0]],
  ['options', input => input.options]
]

for (const [name, select] of hiddenFieldCases) {
  test(`rejects a non-enumerable hidden field on ${name} before fetch`, async () => {
    const input = validInput()
    Object.defineProperty(select(input), 'apiKey', {
      value: 'DEMO_SECRET',
      enumerable: false
    })
    await assertUnsafeShapeRejectedBeforeFetch(input)
  })

  test(`rejects an own non-enumerable toJSON on ${name} before fetch`, async () => {
    const input = validInput()
    Object.defineProperty(select(input), 'toJSON', {
      enumerable: false,
      value() {
        return { apiKey: 'DEMO_SECRET' }
      }
    })
    await assertUnsafeShapeRejectedBeforeFetch(input)
  })

  test(`rejects a symbol key on ${name} before fetch`, async () => {
    const input = validInput()
    select(input)[Symbol('apiKey')] = 'DEMO_SECRET'
    await assertUnsafeShapeRejectedBeforeFetch(input)
  })
}

for (const [name, mutate] of [
  ['envelope', input => Object.setPrototypeOf(input, { inherited: true })],
  ['message', input => Object.setPrototypeOf(input.messages[0], { inherited: true })],
  ['options', input => Object.setPrototypeOf(input.options, { inherited: true })]
]) {
  test(`rejects a non-plain prototype on ${name} before fetch`, async () => {
    const input = validInput()
    mutate(input)
    await assertUnsafeShapeRejectedBeforeFetch(input)
  })
}

for (const [name, makeInput] of [
  ['envelope', () => {
    let reads = 0
    const input = validInput()
    Object.defineProperty(input, 'taskName', {
      enumerable: true,
      get() {
        reads += 1
        return 'draft_generation'
      }
    })
    return { input, readCount: () => reads }
  }],
  ['message', () => {
    let reads = 0
    const input = validInput()
    Object.defineProperty(input.messages[0], 'content', {
      enumerable: true,
      get() {
        reads += 1
        return 'hello'
      }
    })
    return { input, readCount: () => reads }
  }],
  ['options', () => {
    let reads = 0
    const input = validInput()
    Object.defineProperty(input.options, 'temperature', {
      enumerable: true,
      get() {
        reads += 1
        return 0
      }
    })
    return { input, readCount: () => reads }
  }]
]) {
  test(`rejects an accessor on ${name} without invoking its getter`, async () => {
    const { input, readCount } = makeInput()
    await assertUnsafeShapeRejectedBeforeFetch(input)
    assert.equal(readCount(), 0)
  })
}

test('rejects an inherited Object prototype toJSON before fetch', async () => {
  Object.defineProperty(Object.prototype, 'toJSON', {
    configurable: true,
    writable: true,
    value() {
      return { apiKey: 'DEMO_SECRET' }
    }
  })
  try {
    await assertUnsafeShapeRejectedBeforeFetch(validInput())
  } finally {
    delete Object.prototype.toJSON
  }
})

test('rejects messages arrays with enumerable and hidden extra properties', async () => {
  const enumerableInput = validInput()
  enumerableInput.messages.extra = 'DEMO_SECRET'
  await assertUnsafeShapeRejectedBeforeFetch(enumerableInput)

  const hiddenInput = validInput()
  Object.defineProperty(hiddenInput.messages, 'extra', {
    value: 'DEMO_SECRET',
    enumerable: false
  })
  await assertUnsafeShapeRejectedBeforeFetch(hiddenInput)
})

test('rejects an accessor array index without invoking its getter', async () => {
  let reads = 0
  const input = validInput()
  Object.defineProperty(input.messages, '0', {
    enumerable: true,
    get() {
      reads += 1
      return { role: 'user', content: 'hello' }
    }
  })

  await assertUnsafeShapeRejectedBeforeFetch(input)
  assert.equal(reads, 0)
})

test('rejects sparse and non-standard prototype arrays before fetch', async () => {
  const sparseInput = validInput()
  sparseInput.messages = new Array(1)
  await assertUnsafeShapeRejectedBeforeFetch(sparseInput)

  const prototypeInput = validInput()
  Object.setPrototypeOf(prototypeInput.messages, Object.create(Array.prototype))
  await assertUnsafeShapeRejectedBeforeFetch(prototypeInput)
})

test('prevents Array prototype index accessors from changing the serialized message', async () => {
  const assignedValues = new WeakMap()
  const readCounts = new WeakMap()
  let callCount = 0
  let requestBody = null
  Object.defineProperty(Array.prototype, '0', {
    configurable: true,
    get() {
      const assigned = assignedValues.get(this)
      if (assigned === undefined || Array.isArray(assigned)) return assigned
      const count = (readCounts.get(this) || 0) + 1
      readCounts.set(this, count)
      if (count <= 2) return assigned
      return {
        role: 'user',
        content: 'hello',
        apiKey: 'DEMO_SECRET'
      }
    },
    set(value) {
      assignedValues.set(this, value)
    }
  })

  try {
    const gateway = createAiProxyGateway({
      fetchImpl: async (_url, init) => {
        callCount += 1
        requestBody = init.body
        return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
      }
    })
    const result = await gateway.chatCompletion(validInput())
    assert.equal(result.content, 'ok')
  } finally {
    delete Array.prototype[0]
  }

  assert.equal(callCount, 1)
  assert.equal(requestBody.includes('apiKey'), false)
  assert.equal(requestBody.includes('DEMO_SECRET'), false)
})

test('rejects a Proxy before its trap can install a serialization hook', async () => {
  let trapCount = 0
  let callCount = 0
  let requestBody = null
  const input = new Proxy(validInput(), {
    ownKeys(target) {
      trapCount += 1
      Object.defineProperty(Object.prototype, 'toJSON', {
        configurable: true,
        value() {
          return { apiKey: 'DEMO_SECRET' }
        }
      })
      return Reflect.ownKeys(target)
    }
  })
  const gateway = createAiProxyGateway({
    fetchImpl: async (_url, init) => {
      callCount += 1
      requestBody = init.body
      return fakeJsonResponse({ choices: [{ message: { content: 'unexpected' } }] })
    }
  })

  let rejection
  try {
    await gateway.chatCompletion(input)
  } catch (error) {
    rejection = error
  } finally {
    delete Object.prototype.toJSON
  }

  assert.equal(rejection instanceof AiProxyGatewayError, true)
  assert.equal(rejection.message, 'The gateway input is invalid.')
  assert.equal(rejection.code, 'invalid_gateway_input')
  assert.equal(rejection.status, 0)
  assert.deepEqual(rejection.diagnostics, {})
  assert.equal('cause' in rejection, false)
  assert.equal(trapCount, 0)
  assert.equal(callCount, 0)
  assert.equal(requestBody, null)
})

function observedProxy(target) {
  let trapCount = 0
  return {
    proxy: new Proxy(target, {
      getPrototypeOf(value) {
        trapCount += 1
        return Reflect.getPrototypeOf(value)
      },
      ownKeys(value) {
        trapCount += 1
        return Reflect.ownKeys(value)
      }
    }),
    trapCount: () => trapCount
  }
}

for (const [name, makeInput] of [
  ['envelope', () => {
    const observed = observedProxy(validInput())
    return { input: observed.proxy, trapCount: observed.trapCount }
  }],
  ['message', () => {
    const input = validInput()
    const observed = observedProxy(input.messages[0])
    input.messages[0] = observed.proxy
    return { input, trapCount: observed.trapCount }
  }],
  ['options', () => {
    const input = validInput()
    const observed = observedProxy(input.options)
    input.options = observed.proxy
    return { input, trapCount: observed.trapCount }
  }],
  ['nested value', () => {
    const input = validInput()
    const observed = observedProxy({ value: 'DEMO_SECRET' })
    input.options = { nested: observed.proxy }
    return { input, trapCount: observed.trapCount }
  }]
]) {
  test(`rejects a Proxy on ${name} before any reflection or fetch`, async () => {
    const { input, trapCount } = makeInput()
    await assertUnsafeShapeRejectedBeforeFetch(input)
    assert.equal(trapCount(), 0)
  })
}

test('constructs outbound payload objects with a null prototype', async () => {
  const originalStringify = JSON.stringify
  let payloadPrototype
  let responseFormatPrototype
  JSON.stringify = function stringifyWithInspection(value, ...args) {
    if (value && Object.hasOwn(value, 'stream')) {
      payloadPrototype = Object.getPrototypeOf(value)
      responseFormatPrototype = Object.getPrototypeOf(value.response_format)
    }
    return originalStringify.call(JSON, value, ...args)
  }

  try {
    const gateway = createAiProxyGateway({
      fetchImpl: async () => fakeJsonResponse({
        choices: [{ message: { content: 'ok' } }]
      })
    })
    await gateway.chatCompletion({
      ...validInput(),
      options: { responseFormat: 'json' }
    })
  } finally {
    JSON.stringify = originalStringify
  }

  assert.equal(payloadPrototype, null)
  assert.equal(responseFormatPrototype, null)
})

test('accepts pure data objects with a null prototype', async () => {
  let callCount = 0
  const message = Object.assign(Object.create(null), {
    role: 'user',
    content: 'hello'
  })
  const options = Object.assign(Object.create(null), { temperature: 0 })
  const input = Object.assign(Object.create(null), validInput(), {
    messages: [message],
    options
  })
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
    }
  })

  const result = await gateway.chatCompletion(input)

  assert.equal(result.content, 'ok')
  assert.equal(callCount, 1)
})

for (const key of [
  'apiKey',
  'API_KEY',
  'base-url',
  'Authorization',
  'headers',
  'provider-adapter',
  'apply_adapter'
]) {
  test(`rejects nested forbidden key ${key} without revealing it`, async () => {
    let callCount = 0
    const gateway = createAiProxyGateway({
      fetchImpl: async () => {
        callCount += 1
        return fakeJsonResponse({ choices: [{ message: { content: 'unexpected' } }] })
      }
    })

    await assert.rejects(
      gateway.chatCompletion({
        ...validInput(),
        options: { nested: [{ deeper: { [key]: 'SECRET' } }] }
      }),
      error => {
        assert.equal(error instanceof AiProxyGatewayError, true)
        assert.equal(error.message, 'The gateway input contains a forbidden key.')
        assert.equal(error.code, 'forbidden_gateway_key')
        assert.equal(error.status, 0)
        assert.deepEqual(error.diagnostics, {})
        assert.equal('cause' in error, false)
        assert.equal(error.message.includes(key), false)
        assert.equal(JSON.stringify(error).includes('SECRET'), false)
        return true
      }
    )
    assert.equal(callCount, 0)
  })
}

test('does not scan forbidden-looking words inside message strings', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
    }
  })

  const result = await gateway.chatCompletion({
    ...validInput(),
    messages: [{
      role: 'user',
      content: 'apiKey base_url Authorization headers providerAdapter apply-adapter'
    }]
  })

  assert.equal(result.content, 'ok')
  assert.equal(callCount, 1)
})

const acceptedBackendUrls = [
  ['http://localhost:8000', 'http://localhost:8000/api/ai/chat-completions'],
  ['http://127.0.0.1:8001/', 'http://127.0.0.1:8001/api/ai/chat-completions'],
  ['http://[::1]:8002/api', 'http://[::1]:8002/api/ai/chat-completions'],
  ['http://LOCALHOST:8003/api/', 'http://localhost:8003/api/ai/chat-completions']
]

for (const [backendBaseUrl, expectedUrl] of acceptedBackendUrls) {
  test(`accepts loopback backend URL ${backendBaseUrl}`, async () => {
    const calls = []
    const gateway = createAiProxyGateway({
      fetchImpl: async (...args) => {
        calls.push(args)
        return fakeJsonResponse({ choices: [{ message: { content: 'ok' } }] })
      }
    })

    await gateway.chatCompletion({ ...validInput(), backendBaseUrl })

    assert.equal(calls.length, 1)
    assert.equal(calls[0][0], expectedUrl)
  })
}

for (const backendBaseUrl of [
  'https://127.0.0.1:8000',
  'ftp://localhost:8000',
  'http://example.com:8000',
  'http://127.0.0.2:8000',
  'http://localhost.:8000',
  'http://user:pass@localhost:8000',
  'http://localhost:8000?secret=SECRET',
  'http://localhost:8000/?',
  'http://localhost:8000#PROMPT',
  'http://localhost:8000/#',
  'http://localhost:8000/api/ai',
  'http://localhost:8000/v1',
  'not a URL'
]) {
  test(`rejects backend URL ${backendBaseUrl} before fetch`, async () => {
    await assertInvalidInputBeforeFetch({ ...validInput(), backendBaseUrl })
  })
}

test('returns only message content and allowlisted proxy diagnostics', async () => {
  const gateway = createAiProxyGateway({
    fetchImpl: async () => fakeJsonResponse({
      choices: [{
        message: {
          content: 'generated',
          rawHead: 'SECRET',
          usage: { prompt_tokens: 99 }
        },
        text: 'must not be used'
      }],
      content: 'must not be used',
      usage: { prompt_tokens: 99 },
      proxyDiagnostics: {
        requestId: 'req-1',
        taskId: 'task-1',
        taskKey: 'task-key-1',
        providerId: 'provider-1',
        providerName: 'Provider',
        modelName: 'Model',
        httpStatus: 200,
        upstreamStatus: 201,
        elapsedMs: 31,
        retryable: false,
        retriesAttempted: 0,
        retrySucceeded: true,
        raw: 'SECRET',
        rawHead: 'SECRET',
        rawTail: 'SECRET',
        upstreamBodyHead: 'PROMPT',
        upstreamBodyTail: 'PROMPT',
        body: 'PROMPT',
        usage: { prompt_tokens: 99 },
        extra: 'SECRET'
      }
    })
  })

  const result = await gateway.chatCompletion(validInput())

  assert.deepEqual(result, {
    content: 'generated',
    diagnostics: {
      requestId: 'req-1',
      taskId: 'task-1',
      taskKey: 'task-key-1',
      providerId: 'provider-1',
      providerName: 'Provider',
      modelName: 'Model',
      httpStatus: 200,
      upstreamStatus: 201,
      elapsedMs: 31,
      retryable: false,
      retriesAttempted: 0,
      retrySucceeded: true
    }
  })
  assert.equal(JSON.stringify(result).includes('SECRET'), false)
  assert.equal(JSON.stringify(result).includes('PROMPT'), false)
  assert.equal(JSON.stringify(result).includes('prompt_tokens'), false)
})

test('drops inherited allowlisted diagnostic properties', async () => {
  Object.defineProperty(Object.prototype, 'requestId', {
    value: 'DEMO_SECRET',
    configurable: true
  })
  try {
    const gateway = createAiProxyGateway({
      fetchImpl: async () => fakeJsonResponse({
        choices: [{ message: { content: 'generated' } }],
        proxyDiagnostics: { elapsedMs: 7 }
      })
    })

    const result = await gateway.chatCompletion(validInput())

    assert.deepEqual(result, {
      content: 'generated',
      diagnostics: { elapsedMs: 7 }
    })
    assert.equal(JSON.stringify(result).includes('DEMO_SECRET'), false)
  } finally {
    delete Object.prototype.requestId
  }
})

test('drops unsafe scalar values from allowlisted diagnostics', async () => {
  const gateway = createAiProxyGateway({
    fetchImpl: async () => fakeJsonResponse({
      choices: [{ message: { content: 'generated' } }],
      proxyDiagnostics: {
        requestId: 'req-safe',
        taskId: { secret: 'DEMO_SECRET' },
        taskKey: ['DEMO_SECRET'],
        providerId: `${'x'.repeat(257)}DEMO_SECRET`,
        providerName: 'Provider\nDEMO_SECRET',
        modelName: false,
        httpStatus: '200-DEMO_SECRET',
        upstreamStatus: 999,
        elapsedMs: 1.5,
        retriesAttempted: -1,
        retryable: 'true-DEMO_SECRET',
        retrySucceeded: 1
      }
    })
  })

  const result = await gateway.chatCompletion(validInput())

  assert.deepEqual(result, {
    content: 'generated',
    diagnostics: { requestId: 'req-safe' }
  })
  assert.equal(JSON.stringify(result).includes('DEMO_SECRET'), false)
})

test('keeps diagnostic scalar boundary values', async () => {
  const gateway = createAiProxyGateway({
    fetchImpl: async () => fakeJsonResponse({
      choices: [{ message: { content: 'generated' } }],
      proxyDiagnostics: {
        requestId: 'r'.repeat(256),
        httpStatus: 100,
        upstreamStatus: 599,
        elapsedMs: 86400000,
        retriesAttempted: 100,
        retryable: true,
        retrySucceeded: false
      }
    })
  })

  const result = await gateway.chatCompletion(validInput())

  assert.deepEqual(result.diagnostics, {
    requestId: 'r'.repeat(256),
    httpStatus: 100,
    upstreamStatus: 599,
    elapsedMs: 86400000,
    retriesAttempted: 100,
    retryable: true,
    retrySucceeded: false
  })
})

test('maps an HTTP failure to one fixed safe allowlisted error without retry', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return fakeJsonResponse({
        detail: {
          message: 'SECRET provider failure PROMPT',
          requestId: 'req-502',
          providerId: 'provider-1',
          upstreamStatus: 503,
          elapsedMs: 27,
          retryable: true,
          raw: 'SECRET',
          rawHead: 'SECRET',
          rawTail: 'SECRET',
          upstreamBodyHead: 'PROMPT',
          upstreamBodyTail: 'PROMPT',
          body: 'PROMPT',
          usage: { prompt_tokens: 99 },
          extra: 'SECRET'
        }
      }, { status: 502 })
    }
  })

  await assert.rejects(
    gateway.chatCompletion(validInput()),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The AI proxy request failed.')
      assert.equal(error.code, 'ai_proxy_http_error')
      assert.equal(error.status, 502)
      assert.deepEqual(error.diagnostics, {
        requestId: 'req-502',
        providerId: 'provider-1',
        upstreamStatus: 503,
        elapsedMs: 27,
        retryable: true
      })
      assert.equal('cause' in error, false)
      const serialized = `${error.message} ${JSON.stringify(error)}`
      assert.equal(serialized.includes('SECRET'), false)
      assert.equal(serialized.includes('PROMPT'), false)
      assert.equal(serialized.includes('prompt_tokens'), false)
      return true
    }
  )
  assert.equal(callCount, 1)
})

test('rejects a redirect response even when fake fetch marks it ok', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      return {
        ok: true,
        status: 302,
        async text() {
          return JSON.stringify({
            detail: {
              requestId: 'req-302',
              retryable: false,
              rawHead: 'SECRET',
              upstreamBodyHead: 'PROMPT'
            }
          })
        }
      }
    }
  })

  await assert.rejects(
    gateway.chatCompletion(validInput()),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The AI proxy redirect was rejected.')
      assert.equal(error.code, 'ai_proxy_redirect_rejected')
      assert.equal(error.status, 302)
      assert.deepEqual(error.diagnostics, {
        requestId: 'req-302',
        retryable: false
      })
      assert.equal('cause' in error, false)
      const serialized = `${error.message} ${JSON.stringify(error)}`
      assert.equal(serialized.includes('SECRET'), false)
      assert.equal(serialized.includes('PROMPT'), false)
      return true
    }
  )
  assert.equal(callCount, 1)
})

test('aborts one fetch on timeout and returns a fixed safe error', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 5,
    fetchImpl: async (_url, { signal }) => {
      callCount += 1
      return await new Promise((_resolve, reject) => {
        signal.addEventListener('abort', () => {
          const rawError = new Error('SECRET PROMPT')
          rawError.name = 'AbortError'
          reject(rawError)
        }, { once: true })
      })
    }
  })

  await assert.rejects(
    gateway.chatCompletion(validInput()),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The AI proxy request timed out.')
      assert.equal(error.code, 'ai_proxy_timeout')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, { retryable: true })
      assert.equal('cause' in error, false)
      const serialized = `${error.message} ${JSON.stringify(error)}`
      assert.equal(serialized.includes('SECRET'), false)
      assert.equal(serialized.includes('PROMPT'), false)
      return true
    }
  )
  assert.equal(callCount, 1)
})

function assertSafeTimeoutError(error) {
  assert.equal(error instanceof AiProxyGatewayError, true)
  assert.equal(error.message, 'The AI proxy request timed out.')
  assert.equal(error.code, 'ai_proxy_timeout')
  assert.equal(error.status, 0)
  assert.deepEqual(error.diagnostics, { retryable: true })
  assert.equal('cause' in error, false)
  return true
}

function watchdog(promise, milliseconds = 100) {
  let timer
  const guard = new Promise((_resolve, reject) => {
    timer = setTimeout(() => reject(new Error('Gateway deadline was not enforced.')), milliseconds)
  })
  return Promise.race([promise, guard]).finally(() => clearTimeout(timer))
}

test('enforces timeout when fake fetch ignores signal and resolves late', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 5,
    fetchImpl: async () => {
      callCount += 1
      return await new Promise(resolve => {
        setTimeout(() => resolve(fakeJsonResponse({
          choices: [{ message: { content: 'late success' } }]
        })), 40)
      })
    }
  })

  await assert.rejects(gateway.chatCompletion(validInput()), assertSafeTimeoutError)
  assert.equal(callCount, 1)
})

test('enforces timeout when fake fetch ignores signal and never settles', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 5,
    fetchImpl: async () => {
      callCount += 1
      return await new Promise(() => {})
    }
  })

  await assert.rejects(
    watchdog(gateway.chatCompletion(validInput())),
    assertSafeTimeoutError
  )
  assert.equal(callCount, 1)
})

test('enforces timeout across response text reading', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 5,
    fetchImpl: async () => {
      callCount += 1
      return {
        ok: true,
        status: 200,
        async text() {
          return await new Promise(() => {})
        }
      }
    }
  })

  await assert.rejects(
    watchdog(gateway.chatCompletion(validInput())),
    assertSafeTimeoutError
  )
  assert.equal(callCount, 1)
})

test('does not classify an arbitrary AbortError as a gateway deadline', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 100,
    fetchImpl: async () => {
      callCount += 1
      const rawError = new Error('DEMO_SECRET')
      rawError.name = 'AbortError'
      throw rawError
    }
  })

  await assert.rejects(
    gateway.chatCompletion(validInput()),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The AI proxy request could not be completed.')
      assert.equal(error.code, 'ai_proxy_request_failed')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      assert.equal(`${error.message} ${JSON.stringify(error)}`.includes('DEMO_SECRET'), false)
      return true
    }
  )
  assert.equal(callCount, 1)
})

test('consumes a losing fetch rejection that arrives after the deadline', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    timeoutMs: 5,
    fetchImpl: async () => {
      callCount += 1
      return await new Promise((_resolve, reject) => {
        setTimeout(() => reject(new Error('DEMO_SECRET late rejection')), 25)
      })
    }
  })

  await assert.rejects(gateway.chatCompletion(validInput()), assertSafeTimeoutError)
  await new Promise(resolve => setTimeout(resolve, 40))
  assert.equal(callCount, 1)
})

test('maps an injected fetch failure to a fixed safe error without raw cause', async () => {
  let callCount = 0
  const gateway = createAiProxyGateway({
    fetchImpl: async () => {
      callCount += 1
      throw new Error('SECRET PROMPT')
    }
  })

  await assert.rejects(
    gateway.chatCompletion(validInput()),
    error => {
      assert.equal(error instanceof AiProxyGatewayError, true)
      assert.equal(error.message, 'The AI proxy request could not be completed.')
      assert.equal(error.code, 'ai_proxy_request_failed')
      assert.equal(error.status, 0)
      assert.deepEqual(error.diagnostics, {})
      assert.equal('cause' in error, false)
      const serialized = `${error.message} ${JSON.stringify(error)}`
      assert.equal(serialized.includes('SECRET'), false)
      assert.equal(serialized.includes('PROMPT'), false)
      return true
    }
  )
  assert.equal(callCount, 1)
})

const invalidSuccessBodies = [
  ['', 'an empty body'],
  ['SECRET PROMPT', 'non-JSON text'],
  [JSON.stringify({ content: 'SECRET', usage: { prompt: 'PROMPT' } }), 'top-level content'],
  [JSON.stringify({ choices: [] }), 'empty choices'],
  [JSON.stringify({ choices: [{ message: { content: 42 } }] }), 'non-string message content']
]

for (const [body, name] of invalidSuccessBodies) {
  test(`rejects a successful response with ${name} using a fixed safe error`, async () => {
    let callCount = 0
    const gateway = createAiProxyGateway({
      fetchImpl: async () => {
        callCount += 1
        return {
          ok: true,
          status: 200,
          async text() {
            return body
          }
        }
      }
    })

    await assert.rejects(
      gateway.chatCompletion(validInput()),
      error => {
        assert.equal(error instanceof AiProxyGatewayError, true)
        assert.equal(error.message, 'The AI proxy response was invalid.')
        assert.equal(error.code, 'ai_proxy_invalid_response')
        assert.equal(error.status, 200)
        assert.deepEqual(error.diagnostics, {})
        assert.equal('cause' in error, false)
        const serialized = `${error.message} ${JSON.stringify(error)}`
        assert.equal(serialized.includes('SECRET'), false)
        assert.equal(serialized.includes('PROMPT'), false)
        return true
      }
    )
    assert.equal(callCount, 1)
  })
}

test('defines the exact supported control-plane npm scripts', async () => {
  const packageUrl = new URL('../../../package.json', import.meta.url)
  const packageJson = JSON.parse(await readFile(packageUrl, 'utf8'))

  assert.deepEqual(packageJson.scripts, {
    test: 'npm run test:control-plane',
    'test:control-plane': 'npm run test:control-plane:node && npm run test:control-plane:py',
    'test:control-plane:node': 'node --test "tools/control-plane-qa/tests/*.test.mjs"',
    'test:control-plane:py': 'python -m unittest discover -s backend/tests/control_plane -p "test_*.py"',
    'test:control-plane:db': 'python -m unittest discover -s backend/tests/control_plane -p "mysql_integration_test.py"'
  })
  assert.equal(packageJson.dependencies, undefined)
  assert.equal(packageJson.devDependencies, undefined)
})

test('defines only docstrings in the backend test namespace markers', async () => {
  const backendTestsUrl = new URL('../../../backend/tests/__init__.py', import.meta.url)
  const controlPlaneTestsUrl = new URL(
    '../../../backend/tests/control_plane/__init__.py',
    import.meta.url
  )

  assert.equal(
    (await readFile(backendTestsUrl, 'utf8')).replaceAll('\r\n', '\n'),
    '"""Backend tests."""\n'
  )
  assert.equal(
    (await readFile(controlPlaneTestsUrl, 'utf8')).replaceAll('\r\n', '\n'),
    '"""Deterministic control-plane tests."""\n'
  )
})
