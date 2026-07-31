import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

class FakePage extends EventEmitter {
  constructor() {
    super()
    this.contextEmitter = new EventEmitter()
    this.waitedFor = ''
    this.contentValue = '<main>final DOM</main>'
    this.onContent = null
  }

  context() {
    return this.contextEmitter
  }

  async waitForLoadState(state) {
    this.waitedFor = state
  }

  async content() {
    await this.onContent?.()
    return this.contentValue
  }
}

function assertSafeErrorChain(error, sensitiveValues) {
  const observed = []
  const visited = new Set()
  const visit = value => {
    if (!value || (typeof value !== 'object' && typeof value !== 'function')) {
      return
    }
    if (visited.has(value)) return
    visited.add(value)
    for (const field of ['message', 'stack']) {
      if (typeof value[field] === 'string') observed.push(value[field])
    }
    visit(value.cause)
  }
  visit(error)
  const rendered = observed.join('\n')
  for (const sensitive of sensitiveValues) {
    assert.equal(rendered.includes(sensitive), false)
  }
}

test('observer captures network evidence from its context and leaves page-only network emits uncounted', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, { quietWindowMs: 1 })
  assert.equal(observer.listenersAttached(), true)
  const contextRequest = {
    method: () => 'POST',
    url: () => 'http://127.0.0.1:8000/api/context-observed',
    allHeaders: async () => ({}),
    postData: () => '',
    failure: () => ({ errorText: 'context failure' }),
  }
  const pageRequest = {
    method: () => 'POST',
    url: () => 'http://127.0.0.1:8000/api/page-ignored',
    allHeaders: async () => ({}),
    postData: () => '',
    failure: () => ({ errorText: 'page failure' }),
  }
  const contextResponse = fakeResponse({
    url: contextRequest.url(),
    method: 'POST',
    request: () => contextRequest,
    body: '{"source":"context"}',
  })
  const pageResponse = fakeResponse({
    url: pageRequest.url(),
    method: 'POST',
    request: () => pageRequest,
    body: '{"source":"page"}',
  })

  page.emit('request', pageRequest)
  page.emit('requestfinished', pageRequest)
  page.emit('response', pageResponse)
  page.emit('requestfailed', pageRequest)
  assert.equal(observer.observationStage(pageRequest), 'unseen')
  assert.equal(observer.observationStage(pageResponse), 'unseen')
  assert.equal(observer.requestObservationMatches(pageRequest, 'POST', '/api/page-ignored'), false)
  assert.equal(observer.responseObservationMatches(pageResponse, 'POST', '/api/page-ignored', 200), false)
  page.context().emit('request', contextRequest)
  page.context().emit('requestfinished', contextRequest)
  page.context().emit('response', contextResponse)
  page.context().emit('requestfailed', contextRequest)
  assert.equal(observer.observationStage(contextRequest), 'scheduled')
  assert.equal(observer.observationStage(contextResponse), 'scheduled')
  assert.equal(observer.requestObservationMatches(contextRequest, 'POST', '/api/context-observed'), true)
  assert.equal(observer.requestObservationMatches(contextRequest, 'PUT', '/api/context-observed'), false)
  assert.equal(observer.requestObservationMatches(contextRequest, 'POST', '/api/other'), false)
  assert.equal(observer.responseObservationMatches(contextResponse, 'POST', '/api/context-observed', 200), true)
  assert.equal(observer.responseObservationMatches(contextResponse, 'POST', '/api/context-observed', 201), false)
  assert.equal(observer.responseObservationMatches(contextResponse, 'PUT', '/api/context-observed', 200), false)
  assert.equal(observer.responseObservationMatches(contextResponse, 'POST', '/api/other', 200), false)
  page.emit('console', { type: () => 'error', text: () => 'page console event' })
  page.emit('pageerror', new Error('page error event'))

  const evidence = await observer.finish()

  assert.deepEqual(evidence.requests.map(record => record.url), [contextRequest.url()])
  assert.deepEqual(evidence.responses.map(record => record.url), [contextRequest.url()])
  assert.deepEqual(evidence.apiResponses.map(record => record.url), [contextRequest.url()])
  assert.deepEqual(evidence.requestFailures, [`POST ${contextRequest.url()} context failure`])
  assert.deepEqual(evidence.consoleErrors, ['error: page console event'])
  assert.deepEqual(evidence.pageErrors, ['page error event'])
  for (const event of ['request', 'requestfinished', 'response', 'requestfailed']) {
    assert.equal(page.context().listenerCount(event), 0)
    assert.equal(page.listenerCount(event), 0)
  }
  assert.equal(page.listenerCount('console'), 0)
  assert.equal(page.listenerCount('pageerror'), 0)
  assert.equal(observer.listenersAttached(), false)
  assert.equal(observer.observationStage(contextRequest), 'scheduled')
  assert.equal(observer.observationStage(contextResponse), 'scheduled')
})

test('observer listener check includes each page diagnostic listener', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  for (const event of ['console', 'pageerror']) {
    const page = new FakePage()
    const observer = observeRuntime(page, { quietWindowMs: 1 })
    page.removeAllListeners(event)
    assert.equal(observer.listenersAttached(), false, `${event} listener must remain attached`)
    await observer.finish()
  }
})

function fakeResponse({
  url = 'http://127.0.0.1:8000/api/health',
  method = 'GET',
  status = 200,
  headers = { 'content-type': 'application/json' },
  body = '{}',
  allHeaders,
  text,
} = {}) {
  return {
    url: () => url,
    status: () => status,
    request: () => ({ method: () => method }),
    allHeaders: allHeaders || (async () => headers),
    text: text || (async () => body),
  }
}

test('API response body capture fails closed after its bounded read timeout', async () => {
  const { captureApiResponse } = await import('../../frontend/e2e/runtime-observer.mjs')
  assert.equal(typeof captureApiResponse, 'function')
  const response = fakeResponse({
    text: async () => new Promise(() => {}),
  })

  const captured = await captureApiResponse(response, {
    url: response.url(),
    method: 'GET',
    status: 200,
  }, 5)

  assert.equal(captured.body, '')
  assert.equal(captured.bodyReadError, 'response body read timed out')
})

test('request and response header capture fail closed after bounded read timeouts', async () => {
  const { captureApiResponse, captureRequest } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  assert.equal(typeof captureRequest, 'function')
  const request = {
    allHeaders: async () => new Promise(() => {}),
    postData: () => '',
  }
  const response = fakeResponse({
    allHeaders: async () => new Promise(() => {}),
  })

  const [capturedRequest, capturedResponse] = await Promise.all([
    captureRequest(request, {
      url: 'http://127.0.0.1:5173/api/projects/project-1',
      method: 'GET',
    }, 5),
    captureApiResponse(response, {
      url: response.url(),
      method: 'GET',
      status: 200,
    }, 5),
  ])

  assert.equal(capturedRequest.headersReadError, 'request headers read timed out')
  assert.equal(capturedResponse.headersReadError, 'response headers read timed out')
})

test('observer keeps listeners through DOM capture, drains again, then detaches', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  let resolveFirstBody
  const firstBody = new Promise(resolve => { resolveFirstBody = resolve })
  const second = fakeResponse({
    url: 'http://127.0.0.1:8000/api/projects/project-1',
    headers: { 'x-second': 'yes' },
    body: '{"id":"project-1"}',
  })
  const first = fakeResponse({
    headers: { 'x-first': 'yes' },
    text: async () => {
      const value = await firstBody
      page.context().emit('response', second)
      return value
    },
  })
  const capturedDuringContent = fakeResponse({
    url: 'http://127.0.0.1:8000/api/late-timer',
    headers: { 'x-content': 'yes' },
    body: '{"late":true}',
  })
  page.onContent = async () => {
    await new Promise(resolve => setTimeout(resolve, 0))
    page.context().emit('response', capturedDuringContent)
    page.emit('console', { type: () => 'error', text: () => 'content timer console' })
    page.emit('pageerror', new Error('content timer page error'))
    page.context().emit('requestfailed', {
      method: () => 'GET',
      url: () => 'http://127.0.0.1:5173/content-timer',
      failure: () => ({ errorText: 'content timer request failure' }),
    })
  }

  const observer = observeRuntime(page)
  page.context().emit('response', first)
  const finishing = observer.finish()
  resolveFirstBody('{"ok":true}')
  const evidence = await finishing

  assert.equal(page.waitedFor, 'networkidle')
  assert.equal(evidence.apiResponses.length, 3)
  assert.deepEqual(
    evidence.apiResponses.map(response => response.headers),
    [{ 'x-first': 'yes' }, { 'x-second': 'yes' }, { 'x-content': 'yes' }],
  )
  assert.equal(evidence.pageContent, '<main>final DOM</main>')
  assert.deepEqual(evidence.consoleErrors, ['error: content timer console'])
  assert.deepEqual(evidence.pageErrors, ['content timer page error'])
  assert.deepEqual(evidence.requestFailures, [
    'GET http://127.0.0.1:5173/content-timer content timer request failure',
  ])
  for (const event of ['request', 'requestfinished', 'response', 'requestfailed']) {
    assert.equal(page.context().listenerCount(event), 0)
  }
  for (const event of ['console', 'pageerror']) assert.equal(page.listenerCount(event), 0)
})

test('observer can settle captured bodies before a navigation boundary', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  let resolveBody
  const body = new Promise(resolve => { resolveBody = resolve })
  const observer = observeRuntime(page)
  page.context().emit('response', fakeResponse({
    url: 'http://127.0.0.1:8000/api/projects/project-1',
    text: async () => body,
  }))

  const settling = observer.settle()
  resolveBody('{"id":"project-1"}')
  await settling
  const evidence = await observer.finish()

  assert.equal(evidence.apiResponses.length, 1)
  assert.equal(evidence.apiResponses[0].body, '{"id":"project-1"}')
  assert.equal(evidence.apiResponses[0].bodyReadError, '')
})

test('observer settle includes API activity that starts on the next event-loop turn', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, { quietWindowMs: 5 })
  let bodyCaptured = false
  const request = {
    method: () => 'GET',
    url: () => 'http://127.0.0.1:8000/api/projects/project-1',
    allHeaders: async () => ({}),
    postData: () => '',
  }

  setTimeout(() => {
    page.context().emit('request', request)
    page.context().emit('response', fakeResponse({
      url: request.url(),
      text: async () => {
        bodyCaptured = true
        return '{"id":"project-1"}'
      },
    }))
    setTimeout(() => page.context().emit('requestfinished', request), 1)
  }, 0)

  await observer.settle()

  assert.equal(bodyCaptured, true)
  const evidence = await observer.finish()
  assert.equal(evidence.apiResponses[0].bodyReadError, '')
})

test('observer settle deadline bounds a stalled request evidence drain', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, {
    quietWindowMs: 1,
    settleTimeoutMs: 5,
  })
  page.context().emit('request', {
    method: () => 'GET',
    url: () => 'http://127.0.0.1:8000/api/projects/project-1',
    allHeaders: async () => new Promise(() => {}),
    postData: () => '',
  })
  const startedAt = Date.now()

  await assert.rejects(
    observer.settle(),
    /runtime evidence did not settle before its deadline/u,
  )

  assert.ok(Date.now() - startedAt < 250)
  page.context().removeAllListeners()
})

test('observer settle rejects when an API request never emits a terminal event', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, {
    quietWindowMs: 1,
    settleTimeoutMs: 5,
  })
  page.context().emit('request', {
    method: () => 'GET',
    url: () => 'http://127.0.0.1:8000/api/projects/project-1',
    allHeaders: async () => ({}),
    postData: () => '',
  })
  const startedAt = Date.now()

  await assert.rejects(
    observer.settle(),
    /runtime evidence did not settle before its deadline/u,
  )

  assert.ok(Date.now() - startedAt < 250)
  page.context().removeAllListeners()
})

test('failed API requests leave no active request that can block settlement', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, {
    quietWindowMs: 1,
    settleTimeoutMs: 100,
  })
  const request = {
    method: () => 'GET',
    url: () => 'http://127.0.0.1:8000/api/projects/project-1',
    allHeaders: async () => ({}),
    postData: () => '',
    failure: () => ({ errorText: 'connection reset' }),
  }
  page.context().emit('request', request)
  setTimeout(() => page.context().emit('requestfailed', request), 0)

  await observer.settle()
  const evidence = await observer.finish()

  assert.deepEqual(evidence.requestFailures, [
    'GET http://127.0.0.1:8000/api/projects/project-1 connection reset',
  ])
})

test('navigation boundary waits for network idle before settling runtime evidence', async () => {
  const { settleNavigationBoundary } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  assert.equal(typeof settleNavigationBoundary, 'function')
  const calls = []
  const page = {
    async waitForLoadState(state) {
      calls.push(`page:${state}`)
    },
  }
  const runtime = {
    async settle() {
      calls.push('runtime:settle')
    },
  }

  await settleNavigationBoundary(page, runtime)

  assert.deepEqual(calls, ['page:networkidle', 'runtime:settle'])
})


test('observer finish reports only safe pending HTTP request diagnostics when network idle times out', async () => {
  const { observeRuntime, runtimeFailureDiagnostic } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const secrets = {
    username: 'pending-request-user-secret',
    password: 'pending-request-password-secret',
    query: 'pending-request-query-secret',
    hash: 'pending-request-hash-secret',
    error: 'pending-request-load-error-secret',
    body: 'pending-request-body-secret',
    header: 'pending-request-header-secret',
    dsn: 'mysql://pending-request-dsn-secret',
  }
  const loadFailure = new Error(`network idle timed out: ${secrets.error}`)
  loadFailure.cause = new Error(`nested cause: ${secrets.dsn}`)
  page.waitForLoadState = async () => { throw loadFailure }
  const observer = observeRuntime(page)
  const request = {
    method: () => 'GET',
    url: () => `http://${secrets.username}:${secrets.password}@127.0.0.1:5173`
      + `/api/projects/project-1?token=${secrets.query}#${secrets.hash}`,
    allHeaders: async () => ({ authorization: secrets.header }),
    postData: () => secrets.body,
  }
  page.context().emit('request', request)

  await assert.rejects(observer.finish(), error => {
    assert.ok(error instanceof Error)
    assert.equal(
      error?.message,
      'Runtime evidence settlement failed: '
        + '{"consoleErrorCount":0,"requestFailureCount":0,"requestFailures":[],'
        + '"responseFailures":[],"apiResponseCount":0,"apiHeaderReadFailures":[],'
        + '"apiBodyReadFailures":[],"requestHeaderReadFailures":[],'
        + '"pendingRequestCount":1,"pendingRequests":[{"method":"GET",'
        + '"path":"/api/projects/project-1","status":"pending"}]}',
    )
    const diagnostic = runtimeFailureDiagnostic(error)
    assert.deepEqual(diagnostic, {
      consoleErrorCount: 0,
      requestFailureCount: 0,
      requestFailures: [],
      responseFailures: [],
      apiResponseCount: 0,
      apiHeaderReadFailures: [],
      apiBodyReadFailures: [],
      requestHeaderReadFailures: [],
      pendingRequestCount: 1,
      pendingRequests: [{
        method: 'GET',
        path: '/api/projects/project-1',
        status: 'pending',
      }],
    })
    diagnostic.pendingRequests[0].path = '/forged'
    assert.equal(
      runtimeFailureDiagnostic(error)?.pendingRequests[0]?.path,
      '/api/projects/project-1',
    )
    assert.equal(
      runtimeFailureDiagnostic(new Error(`forged ${secrets.error}`)),
      null,
    )
    for (const secret of [
      ...Object.values(secrets),
      '127.0.0.1:5173',
    ]) assert.doesNotMatch(error?.message || '', new RegExp(secret, 'u'))
    assertSafeErrorChain(error, Object.values(secrets))
    return true
  })
})


test('observer finish excludes pending external HTTPS requests from safe diagnostics', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const secrets = {
    username: 'external-pending-user-secret',
    password: 'external-pending-password-secret',
    query: 'external-pending-query-secret',
    hash: 'external-pending-hash-secret',
    provider: 'provider-private-original-path',
  }
  const loadFailure = new Error('network idle timed out')
  page.waitForLoadState = async () => { throw loadFailure }
  const observer = observeRuntime(page)
  page.context().emit('request', {
    method: () => 'GET',
    url: () => `https://${secrets.username}:${secrets.password}@provider.example.invalid`
      + `/v1/${secrets.provider}?token=${secrets.query}#${secrets.hash}`,
    allHeaders: async () => ({}),
    postData: () => '',
  })

  await assert.rejects(observer.finish(), error => {
    assert.ok(error instanceof Error)
    assert.equal(
      error?.message,
      'Runtime evidence settlement failed: '
        + '{"consoleErrorCount":0,"requestFailureCount":0,"requestFailures":[],'
        + '"responseFailures":[],"apiResponseCount":0,"apiHeaderReadFailures":[],'
        + '"apiBodyReadFailures":[],"requestHeaderReadFailures":[],'
        + '"pendingRequestCount":0,"pendingRequests":[]}',
    )
    for (const secret of [
      ...Object.values(secrets),
      'provider.example.invalid',
      '/v1/',
    ]) assert.doesNotMatch(error?.message || '', new RegExp(secret, 'u'))
    assertSafeErrorChain(error, Object.values(secrets))
    return true
  })
})


test('observer finish excludes external provider details from every public diagnostic path', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const secrets = {
    username: 'external-diagnostic-user-secret',
    password: 'external-diagnostic-password-secret',
    query: 'external-diagnostic-query-secret',
    hash: 'external-diagnostic-hash-secret',
    provider: 'provider-diagnostic-original-path',
    error: 'provider-diagnostic-error-secret',
  }
  const url = `https://${secrets.username}:${secrets.password}@provider.example.invalid`
    + `/api/${secrets.provider}?token=${secrets.query}#${secrets.hash}`
  const request = {
    method: () => 'GET',
    url: () => url,
    allHeaders: async () => { throw new Error(secrets.error) },
    postData: () => '',
    failure: () => ({ errorText: secrets.error }),
  }
  const loadFailure = new Error('network idle timed out')
  page.waitForLoadState = async () => { throw loadFailure }
  const observer = observeRuntime(page, { quietWindowMs: 1 })
  page.context().emit('request', request)
  page.context().emit('response', fakeResponse({
    url,
    status: 503,
    request: () => request,
  }))
  page.context().emit('requestfailed', request)
  await observer.settle()

  await assert.rejects(observer.finish(), error => {
    assert.ok(error instanceof Error)
    assert.equal(
      error?.message,
      'Runtime evidence settlement failed: '
        + '{"consoleErrorCount":0,"requestFailureCount":1,"requestFailures":[],'
        + '"responseFailures":[],"apiResponseCount":1,"apiHeaderReadFailures":[],'
        + '"apiBodyReadFailures":[],"requestHeaderReadFailures":[],'
        + '"pendingRequestCount":0,"pendingRequests":[]}',
    )
    for (const secret of [
      ...Object.values(secrets),
      'provider.example.invalid',
      '/api/',
    ]) assert.doesNotMatch(error?.message || '', new RegExp(secret, 'u'))
    assertSafeErrorChain(error, Object.values(secrets))
    return true
  })
})

test('observer records fail-closed header body response console page and request evidence', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page)
  page.context().emit('response', fakeResponse({
    method: 'POST',
    status: 503,
    allHeaders: async () => { throw new Error('headers unavailable') },
    text: async () => { throw new Error('body unavailable') },
  }))
  page.emit('console', { type: () => 'log', text: () => 'ordinary log' })
  page.emit('console', { type: () => 'error', text: () => 'console failed' })
  page.emit('pageerror', new Error('page failed'))
  page.context().emit('requestfailed', {
    method: () => 'GET',
    url: () => 'http://127.0.0.1:5173/missing',
    failure: () => ({ errorText: 'connection closed' }),
  })

  const evidence = await observer.finish()

  assert.equal(evidence.apiResponses[0].headersReadError, 'headers unavailable')
  assert.equal(evidence.apiResponses[0].bodyReadError, 'body unavailable')
  assert.deepEqual(evidence.apiResponses[0].headers, {})
  assert.deepEqual(evidence.responseFailures, [
    '503 POST http://127.0.0.1:8000/api/health',
  ])
  assert.deepEqual(evidence.consoleMessages, ['log: ordinary log', 'error: console failed'])
  assert.deepEqual(evidence.consoleErrors, ['error: console failed'])
  assert.deepEqual(evidence.pageErrors, ['page failed'])
  assert.deepEqual(evidence.requestFailures, [
    'GET http://127.0.0.1:5173/missing connection closed',
  ])
})

test('observer allows only exact owned loopback origins and accounts every HTTP request', async () => {
  const {
    assertRuntimeEvidenceHealthy,
    observeRuntime,
  } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const allowedOrigin = 'http://127.0.0.1:5173'
  const observer = observeRuntime(page, {
    allowedOrigins: [allowedOrigin],
    quietWindowMs: 1,
  })
  const request = {
    method: () => 'GET',
    url: () => `${allowedOrigin}/assets/index.js`,
    allHeaders: async () => ({}),
    postData: () => '',
  }
  page.context().emit('request', request)
  page.context().emit('response', fakeResponse({
    url: request.url(),
    request: () => request,
  }))
  page.context().emit('requestfinished', request)

  const evidence = await observer.finish()

  assert.deepEqual(assertRuntimeEvidenceHealthy(evidence), {
    healthy: true,
    networkAccess: {
      httpRequestCount: 1,
      allowedRequestCount: 1,
      forbiddenRequestCount: 0,
      forbiddenResponseCount: 0,
    },
  })
})

test('successful external HTTP responses fail closed with secret-safe auditable counts', async () => {
  const {
    assertRuntimeEvidenceHealthy,
    observeRuntime,
    publicRuntimeDiagnostic,
  } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page, {
    allowedOrigins: ['http://127.0.0.1:5173'],
    quietWindowMs: 1,
  })
  const secret = 'external-query-secret-must-not-be-rendered'
  const request = {
    method: () => 'GET',
    url: () => `https://example.invalid/private?token=${secret}`,
    allHeaders: async () => ({}),
    postData: () => '',
  }
  page.context().emit('request', request)
  page.context().emit('response', fakeResponse({
    url: request.url(),
    status: 204,
    request: () => request,
  }))
  page.context().emit('requestfinished', request)

  const evidence = await observer.finish()
  let rejection = null
  try {
    assertRuntimeEvidenceHealthy(evidence)
  } catch (error) {
    rejection = error
  }

  assert.equal(rejection?.message, 'Runtime evidence contains forbidden HTTP access')
  assert.doesNotMatch(rejection?.message || '', new RegExp(secret, 'u'))
  assert.deepEqual(publicRuntimeDiagnostic(evidence).networkAccess, {
    httpRequestCount: 1,
    allowedRequestCount: 0,
    forbiddenRequestCount: 1,
    forbiddenResponseCount: 1,
  })
  assert.doesNotMatch(
    JSON.stringify(publicRuntimeDiagnostic(evidence)),
    new RegExp(secret, 'u'),
  )
})

test('observer excludes Vite source paths containing api and accepts cache revalidation', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page)
  page.context().emit('response', fakeResponse({
    url: 'http://127.0.0.1:5173/src/api/db/client.js',
    status: 304,
    text: async () => { throw new Error('304 response body is unavailable') },
  }))
  page.context().emit('response', fakeResponse({
    url: 'http://127.0.0.1:8000/api/projects/project-1',
    status: 200,
    body: '{"id":"project-1"}',
  }))

  const evidence = await observer.finish()

  assert.deepEqual(
    evidence.apiResponses.map(response => new URL(response.url).pathname),
    ['/api/projects/project-1'],
  )
  assert.deepEqual(evidence.responseFailures, [])
})

test('runtime health assertion rejects every captured failure category with safe fixed errors', async () => {
  const { assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const capturedSecret = 'private-runtime-evidence-must-not-be-echoed'
  const cleanEvidence = () => ({
    consoleErrors: [],
    responseFailures: [],
    pageErrors: [],
    requestFailures: [],
    apiResponses: [{ headersReadError: '', bodyReadError: '' }],
    requests: [{ headersReadError: '', bodyReadError: '' }],
  })
  const cases = [
    ['console errors', 'Runtime evidence contains console errors', evidence => {
      evidence.consoleErrors.push(capturedSecret)
    }],
    ['response failures', 'Runtime evidence contains response failures', evidence => {
      evidence.responseFailures.push(capturedSecret)
    }],
    ['page errors', 'Runtime evidence contains page errors', evidence => {
      evidence.pageErrors.push(capturedSecret)
    }],
    ['request failures', 'Runtime evidence contains request failures', evidence => {
      evidence.requestFailures.push(capturedSecret)
    }],
    ['API response header read errors', 'Runtime API response headers could not be read', evidence => {
      evidence.apiResponses[0].headersReadError = capturedSecret
    }],
    ['API response body read errors', 'Runtime API response bodies could not be read', evidence => {
      evidence.apiResponses[0].bodyReadError = capturedSecret
    }],
    ['request header read errors', 'Runtime request headers could not be read', evidence => {
      evidence.requests[0].headersReadError = capturedSecret
    }],
    ['request body read errors', 'Runtime request bodies could not be read', evidence => {
      evidence.requests[0].bodyReadError = capturedSecret
    }],
  ]

  assert.deepEqual(assertRuntimeEvidenceHealthy(cleanEvidence()), { healthy: true })
  for (const [label, expectedMessage, contaminate] of cases) {
    const evidence = cleanEvidence()
    contaminate(evidence)
    let error = null
    try {
      assertRuntimeEvidenceHealthy(evidence)
    } catch (failure) {
      error = failure
    }
    assert.ok(error instanceof Error, label)
    assert.equal(error.message, expectedMessage, label)
    assert.equal(error.message.includes(capturedSecret), false, label)
  }
})

test('runtime health assertion allows only exact structured response failure rules', async () => {
  const { assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const responseFailureAllowlist = [{
    status: 404,
    method: 'GET',
    pathname: '/api/projects/project-1/contract-draft',
    count: 1,
  }]
  const evidence = responseFailure => ({
    consoleErrors: [],
    responseFailures: [responseFailure],
    pageErrors: [],
    requestFailures: [],
    apiResponses: [],
    requests: [],
  })
  const assertSafeResponseFailure = responseFailure => {
    let error = null
    try {
      assertRuntimeEvidenceHealthy(evidence(responseFailure), {
        responseFailureAllowlist,
      })
    } catch (failure) {
      error = failure
    }
    assert.ok(error instanceof Error)
    assert.equal(error.message, 'Runtime evidence contains response failures')
    assert.equal(error.message.includes(responseFailure), false)
  }

  assert.deepEqual(assertRuntimeEvidenceHealthy(evidence(
    '404 GET http://127.0.0.1:8000/api/projects/project-1/contract-draft',
  ), { responseFailureAllowlist }), { healthy: true })
  for (const rejected of [
    '404 GET http://127.0.0.1:8000/api/projects/project-2/contract-draft',
    '404 POST http://127.0.0.1:8000/api/projects/project-1/contract-draft',
    '500 GET http://127.0.0.1:8000/api/projects/project-1/contract-draft',
    'not a structured response failure',
  ]) assertSafeResponseFailure(rejected)

  let countError = null
  try {
    assertRuntimeEvidenceHealthy(evidence(
      '404 GET http://127.0.0.1:8000/api/projects/project-1/contract-draft',
    ), {
      responseFailureAllowlist: [{ ...responseFailureAllowlist[0], count: 2 }],
    })
  } catch (failure) {
    countError = failure
  }
  assert.equal(countError?.message, 'Runtime evidence contains response failures')
})

test('runtime health assertion allows one fixed console error only with its consumed response rule', async () => {
  const { assertRuntimeEvidenceHealthy } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const responseRule = {
    status: 404,
    method: 'GET',
    pathname: '/api/projects/project-1/contract-draft',
    count: 1,
  }
  const browserConsoleError = 'error: Failed to load resource: the server responded with a status of 404 (Not Found)'
  const options = {
    responseFailureAllowlist: [responseRule],
    consoleErrorAllowlist: [{
      message: browserConsoleError,
      count: 1,
      linkedResponseFailure: {
        status: responseRule.status,
        method: responseRule.method,
        pathname: responseRule.pathname,
      },
    }],
  }
  const evidence = ({ responseFailures, consoleErrors }) => ({
    consoleErrors,
    responseFailures,
    pageErrors: [],
    requestFailures: [],
    apiResponses: [],
    requests: [],
  })
  const responseFailure = '404 GET http://127.0.0.1:8000/api/projects/project-1/contract-draft'
  assert.deepEqual(assertRuntimeEvidenceHealthy(evidence({
    responseFailures: [responseFailure],
    consoleErrors: [browserConsoleError],
  }), options), { healthy: true })

  const rejected = [{
    label: 'missing linked response',
    responseFailures: [],
    consoleErrors: [browserConsoleError],
    expected: 'Runtime evidence contains response failures',
  }, {
    label: 'different console text',
    responseFailures: [responseFailure],
    consoleErrors: ['error: different public browser failure'],
    expected: 'Runtime evidence contains console errors',
  }, {
    label: 'extra console text',
    responseFailures: [responseFailure],
    consoleErrors: [browserConsoleError, 'error: unrelated failure'],
    expected: 'Runtime evidence contains console errors',
  }, {
    label: 'console count mismatch',
    responseFailures: [responseFailure],
    consoleErrors: [browserConsoleError, browserConsoleError],
    expected: 'Runtime evidence contains console errors',
  }]
  for (const item of rejected) {
    let error = null
    try {
      assertRuntimeEvidenceHealthy(evidence(item), options)
    } catch (failure) {
      error = failure
    }
    assert.ok(error instanceof Error, item.label)
    assert.equal(error.message, item.expected, item.label)
    assert.equal(error.message.includes(item.consoleErrors.at(-1) || ''), false, item.label)
  }
})

test('observer enforces exact write method path status and count allowlists', async () => {
  const { assertExactWrites } = await import('../../frontend/e2e/runtime-observer.mjs')
  const evidence = {
    responses: [
      { method: 'PUT', status: 200, url: 'http://127.0.0.1:8000/api/projects/p1/contract-draft' },
      { method: 'PUT', status: 200, url: 'http://127.0.0.1:8000/api/projects/p1/contract-draft' },
      { method: 'POST', status: 201, url: 'http://127.0.0.1:8000/api/projects/p1/contracts/confirm' },
      { method: 'GET', status: 200, url: 'http://127.0.0.1:8000/api/projects/p1' },
    ],
  }
  const allowlist = [
    { method: 'PUT', path: /\/contract-draft$/, count: 2, statuses: [200] },
    { method: 'POST', path: /\/contracts\/confirm$/, count: 1, statuses: [201] },
  ]

  assert.deepEqual(assertExactWrites(evidence, allowlist), { writeCount: 3 })
  assert.throws(
    () => assertExactWrites(evidence, [{ ...allowlist[0], count: 1 }, allowlist[1]]),
    /count/i,
  )
  assert.throws(
    () => assertExactWrites(evidence, [allowlist[0]]),
    /unmatched/i,
  )
  assert.throws(
    () => assertExactWrites(evidence, [allowlist[0], { ...allowlist[1], statuses: [200] }]),
    /status/i,
  )
  assert.throws(
    () => assertExactWrites(evidence, [allowlist[0], { ...allowlist[0] }]),
    /duplicate|overlap/i,
  )
  assert.throws(
    () => assertExactWrites(evidence, [
      allowlist[0],
      { method: 'PUT', path: /\/projects\/p1\/contract-draft$/, count: 2, statuses: [200] },
      allowlist[1],
    ]),
    /multiple|overlap/i,
  )
})

test('exact write audit derives only API writes from synchronous response metadata', async () => {
  const { assertExactWrites } = await import('../../frontend/e2e/runtime-observer.mjs')
  const path = '/api/projects/p1/planning/drafts'
  const rule = { method: 'POST', path, count: 1, statuses: [201] }
  const response = { method: 'POST', status: 201, url: `http://127.0.0.1:8000${path}` }
  assert.deepEqual(assertExactWrites({ responses: [response], apiResponses: [] }, [rule]), { writeCount: 1 })
  for (const [item, matcher] of [
    [{ ...response, url: 'http://127.0.0.1:8000/assets/write' }, /count/i],
    [{ ...response, method: 'GET' }, /count/i],
    [{ ...response, url: `${response.url}?unexpected=1` }, /unmatched/i],
    [{ ...response, url: `${response.url}#unexpected` }, /unmatched/i],
    [{ ...response, status: 200 }, /status/i],
    [{ ...response, url: 'http://127.0.0.1:8000/api/projects/p1/unmatched' }, /unmatched/i],
  ]) assert.throws(() => assertExactWrites({ responses: [item], apiResponses: [] }, [rule]), matcher)
  assert.throws(
    () => assertExactWrites({
      responses: [{ ...response, method: 'PURGE' }],
      apiResponses: [],
    }, []),
    /Unmatched runtime write: PURGE/,
  )
})

test('exact write allowlists reject query and hash variants of an allowed route', async () => {
  const { assertExactWrites } = await import('../../frontend/e2e/runtime-observer.mjs')
  const rule = {
    method: 'PUT',
    path: /^\/api\/providers\/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u,
    count: 1,
    statuses: [200],
  }
  const providerPath = '/api/providers/11111111-1111-4111-8111-111111111111'

  for (const suffix of ['?unexpected=1', '#unexpected']) {
    assert.throws(
      () => assertExactWrites({
        responses: [{
          method: 'PUT',
          status: 200,
          url: `http://127.0.0.1:8000${providerPath}${suffix}`,
        }],
      }, [rule]),
      /unmatched/i,
    )
  }

  const secret = 'query-secret-must-not-be-rendered'
  let rejection = null
  try {
    assertExactWrites({
      responses: [{
        method: 'PUT',
        status: 200,
        url: `http://127.0.0.1:8000${providerPath}?token=${secret}`,
      }],
    }, [rule])
  } catch (error) {
    rejection = error
  }
  assert.match(rejection?.message || '', /unmatched/i)
  assert.match(rejection?.message || '', new RegExp(providerPath, 'u'))
  assert.doesNotMatch(rejection?.message || '', new RegExp(secret, 'u'))
  assert.doesNotMatch(rejection?.message || '', /\?/u)
})

test('write allowlist rejects invalid rules even when no writes occur', async () => {
  const { assertExactWrites } = await import('../../frontend/e2e/runtime-observer.mjs')
  const evidence = { responses: [] }
  const invalidRules = [
    { method: '', path: '/api/write', count: 1, statuses: [200] },
    { method: 'POST', path: 42, count: 1, statuses: [200] },
    { method: 'POST', path: '/api/write', count: 0, statuses: [200] },
    { method: 'POST', path: '/api/write', count: 1, statuses: [] },
    { method: 'POST', path: '/api/write', count: 1, statuses: [200.5] },
  ]

  for (const rule of invalidRules) {
    assert.throws(() => assertExactWrites(evidence, [rule]), /allowlist|rule|method|path|count|status/i)
  }
  assert.throws(() => assertExactWrites({
    responses: [{ method: 'INVALID', status: 200, url: 'http://127.0.0.1/api/write' }],
  }, [
    { method: 'INVALID', path: '/api/write', count: 1, statuses: [200] },
  ]), /method/i)
})

test('runtime secret scan returns only a match count and covers all evidence surfaces', async () => {
  const { scanRuntimeEvidence } = await import('../../frontend/e2e/runtime-observer.mjs')
  const secret = 'dynamic-private-corpus-root'
  const result = scanRuntimeEvidence({
    requests: [{ url: '/api/import', method: 'POST', headers: { private: secret }, body: secret }],
    apiResponses: [{ url: '/api/import', method: 'POST', status: 200, headers: { private: secret }, body: secret }],
    pageContent: `<main>${secret}</main>`,
    consoleMessages: [`error: ${secret}`],
    consoleErrors: [`error: ${secret}`],
    pageErrors: [secret],
    requestFailures: [`POST /api/import ${secret}`],
    responseFailures: [`500 POST /api/import ${secret}`],
  }, [secret])

  assert.equal(result.matchCount, 10)
  assert.deepEqual(Object.keys(result), ['matchCount'])
  assert.equal(JSON.stringify(result).includes(secret), false)
})

test('private evidence rejection and public diagnostics never echo captured secrets', async () => {
  const {
    assertNoPrivateEvidenceMarkers,
    publicRuntimeDiagnostic,
  } = await import('../../frontend/e2e/runtime-observer.mjs')
  assert.equal(typeof assertNoPrivateEvidenceMarkers, 'function')
  assert.equal(typeof publicRuntimeDiagnostic, 'function')
  const secret = 'diagnostic-secret-must-not-be-rendered'
  let rejection = null
  try {
    assertNoPrivateEvidenceMarkers([`{"apiKey":"${secret}"}`])
  } catch (error) {
    rejection = error
  }
  assert.equal(rejection?.message, 'Runtime evidence contains private fields')
  assert.doesNotMatch(rejection?.message || '', new RegExp(secret, 'u'))

  const diagnostic = publicRuntimeDiagnostic({
    consoleErrors: [secret],
    requestFailures: [secret],
    responseFailures: [`503 GET http://127.0.0.1/api/failure?token=${secret}`],
    responses: [{
      method: 'GET',
      status: 503,
      url: `http://127.0.0.1/api/failure?token=${secret}`,
    }],
    apiResponses: [{
      method: 'GET',
      status: 200,
      url: `http://127.0.0.1/api/current?token=${secret}`,
      headersReadError: secret,
      bodyReadError: secret,
    }],
    requests: [{
      method: 'GET',
      url: `http://127.0.0.1/api/history?token=${secret}`,
      headersReadError: secret,
    }],
  })
  const rendered = JSON.stringify(diagnostic)

  assert.doesNotMatch(rendered, new RegExp(secret, 'u'))
  assert.deepEqual(diagnostic, {
    consoleErrorCount: 1,
    requestFailureCount: 1,
    requestFailures: [{
      method: '[invalid-method]',
      path: '[invalid-path]',
    }],
    responseFailures: [{ method: 'GET', status: 503, path: '/api/failure' }],
    apiResponseCount: 1,
    apiHeaderReadFailures: [{ method: 'GET', status: 200, path: '/api/current' }],
    apiBodyReadFailures: [{ method: 'GET', status: 200, path: '/api/current' }],
    requestHeaderReadFailures: [{ method: 'GET', path: '/api/history' }],
    pendingRequestCount: 0,
    pendingRequests: [],
  })
})

test('private evidence scan rejects manifest and raw provider output key forms without echoing values', async () => {
  const { assertNoPrivateEvidenceMarkers } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const privateKeys = [
    'manifest',
    'inputManifest',
    'rawOutput',
    'providerOutput',
    'rawProviderOutput',
  ]
  for (const [index, key] of privateKeys.entries()) {
    const secret = `private-structure-sentinel-${String(index)}`
    for (const surface of [
      JSON.stringify({ [key]: secret }),
      `info: provider audit ${key}=${secret}`,
    ]) {
      let rejection = null
      try {
        assertNoPrivateEvidenceMarkers([surface])
      } catch (error) {
        rejection = error
      }
      assert.equal(
        rejection?.message,
        'Runtime evidence contains private fields',
        key,
      )
      assert.doesNotMatch(
        rejection?.message || '',
        new RegExp(secret, 'u'),
        key,
      )
    }
  }
})

test('public runtime diagnostics expose failed request methods and paths without URL secrets', async () => {
  const { publicRuntimeDiagnostic } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const secrets = {
    username: 'request-user-secret',
    password: 'request-password-secret',
    query: 'request-query-secret',
    hash: 'request-hash-secret',
    error: 'request-error-secret',
  }
  const diagnostic = publicRuntimeDiagnostic({
    requestFailures: [
      `PATCH https://${secrets.username}:${secrets.password}`
        + '@127.0.0.1:8000/api/projects/project-1/supersession'
        + `?token=${secrets.query}#${secrets.hash} ${secrets.error}`,
    ],
  })
  const rendered = JSON.stringify(diagnostic)

  assert.equal(diagnostic.requestFailureCount, 1)
  assert.deepEqual(diagnostic.requestFailures, [{
    method: 'PATCH',
    path: '/api/projects/project-1/supersession',
  }])
  for (const secret of Object.values(secrets)) {
    assert.doesNotMatch(rendered, new RegExp(secret, 'u'))
  }
})

test('public runtime diagnostics replace malformed request failures without losing count', async () => {
  const { publicRuntimeDiagnostic } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const secret = 'malformed-request-failure-secret'
  const diagnostic = publicRuntimeDiagnostic({
    requestFailures: [secret, null],
  })

  assert.equal(diagnostic.requestFailureCount, 2)
  assert.deepEqual(diagnostic.requestFailures, [{
    method: '[invalid-method]',
    path: '[invalid-path]',
  }, {
    method: '[invalid-method]',
    path: '[invalid-path]',
  }])
  assert.doesNotMatch(JSON.stringify(diagnostic), new RegExp(secret, 'u'))
})

test('public runtime diagnostics reject untrusted request failure methods', async () => {
  const { publicRuntimeDiagnostic } = await import(
    '../../frontend/e2e/runtime-observer.mjs'
  )
  const secrets = {
    method: 'malformed-method-secret',
    query: 'malformed-method-query-secret',
    hash: 'malformed-method-hash-secret',
    error: 'malformed-method-error-secret',
  }
  const diagnostic = publicRuntimeDiagnostic({
    requestFailures: [
      `${secrets.method} https://127.0.0.1/api/fail`
        + `?token=${secrets.query}#${secrets.hash} ${secrets.error}`,
    ],
  })
  const rendered = JSON.stringify(diagnostic)

  assert.equal(diagnostic.requestFailureCount, 1)
  assert.deepEqual(diagnostic.requestFailures, [{
    method: '[invalid-method]',
    path: '[invalid-path]',
  }])
  for (const secret of Object.values(secrets)) {
    assert.doesNotMatch(rendered, new RegExp(secret, 'u'))
  }
})

test('runtime secret scan recursively covers Windows JSON, slash, and URL variants', async () => {
  const { scanRuntimeEvidence } = await import('../../frontend/e2e/runtime-observer.mjs')
  const windowsValue = String.raw`C:\Users\phase2a\private corpus`
  const jsonEscaped = JSON.stringify(windowsValue).slice(1, -1)
  const forwardSlash = windowsValue.replaceAll('\\', '/')
  const urlEncoded = encodeURIComponent(windowsValue)
  const result = scanRuntimeEvidence({
    requests: [{
      body: JSON.stringify({ corpusRoot: windowsValue }),
      nested: {
        values: [jsonEscaped, { forwardSlash }, urlEncoded],
      },
    }],
  }, [windowsValue])

  assert.ok(result.matchCount >= 4)
  assert.deepEqual(Object.keys(result), ['matchCount'])
  const renderedResult = JSON.stringify(result)
  for (const sensitive of [windowsValue, jsonEscaped, forwardSlash, urlEncoded]) {
    assert.equal(renderedResult.includes(sensitive), false)
  }
})

test('runtime scan values include sentinels plus raw and encoded database credentials', async () => {
  const { runtimeSensitiveValues } = await import('../../frontend/e2e/runtime-observer.mjs')
  const environment = {
    BROWSER_SECRET_SENTINEL: 'fixed-secret',
    BROWSER_PRIVATE_PROVIDER_URL: 'fixed-provider-url',
    BROWSER_CORPUS_ROOT_SENTINEL: 'fixed-corpus-root',
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: 'dynamic-corpus-root',
    MYSQL_HOST: '127.0.0.1',
    MYSQL_PORT: '33060',
    MYSQL_USER: 'browser:user',
    MYSQL_PASSWORD: '中文:p@ss/word',
    MYSQL_DB: 'novel_creator_test_0123456789abcdef0123456789abcdef',
  }
  const values = runtimeSensitiveValues(environment)
  const encodedUser = encodeURIComponent(environment.MYSQL_USER)
  const encodedPassword = encodeURIComponent(environment.MYSQL_PASSWORD)
  const encodedDatabase = encodeURIComponent(environment.MYSQL_DB)

  for (const expected of [
    'fixed-secret',
    'fixed-provider-url',
    'fixed-corpus-root',
    'dynamic-corpus-root',
    environment.MYSQL_PASSWORD,
    encodedPassword,
    environment.MYSQL_DB,
    `mysql://${environment.MYSQL_USER}:${environment.MYSQL_PASSWORD}@127.0.0.1:33060/${environment.MYSQL_DB}`,
    `mysql://${encodedUser}:${encodedPassword}@127.0.0.1:33060/${encodedDatabase}`,
    `mysql+aiomysql://${environment.MYSQL_USER}:${environment.MYSQL_PASSWORD}@127.0.0.1:33060/${environment.MYSQL_DB}`,
    `mysql+aiomysql://${encodedUser}:${encodedPassword}@127.0.0.1:33060/${encodedDatabase}`,
  ]) assert.equal(values.includes(expected), true, expected)
  assert.equal(values.includes(environment.MYSQL_HOST), false)
  assert.equal(values.includes(environment.MYSQL_USER), false)
})
