import assert from 'node:assert/strict'
import { EventEmitter } from 'node:events'
import test from 'node:test'

class FakePage extends EventEmitter {
  constructor() {
    super()
    this.waitedFor = ''
    this.contentValue = '<main>final DOM</main>'
    this.onContent = null
  }

  async waitForLoadState(state) {
    this.waitedFor = state
  }

  async content() {
    await this.onContent?.()
    return this.contentValue
  }
}

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
      page.emit('response', second)
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
    page.emit('response', capturedDuringContent)
    page.emit('console', { type: () => 'error', text: () => 'content timer console' })
    page.emit('pageerror', new Error('content timer page error'))
    page.emit('requestfailed', {
      method: () => 'GET',
      url: () => 'http://127.0.0.1:5173/content-timer',
      failure: () => ({ errorText: 'content timer request failure' }),
    })
  }

  const observer = observeRuntime(page)
  page.emit('response', first)
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
  for (const event of ['response', 'console', 'pageerror', 'requestfailed']) {
    assert.equal(page.listenerCount(event), 0)
  }
})

test('observer records fail-closed header body response console page and request evidence', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page)
  page.emit('response', fakeResponse({
    method: 'POST',
    status: 503,
    allHeaders: async () => { throw new Error('headers unavailable') },
    text: async () => { throw new Error('body unavailable') },
  }))
  page.emit('console', { type: () => 'log', text: () => 'ordinary log' })
  page.emit('console', { type: () => 'error', text: () => 'console failed' })
  page.emit('pageerror', new Error('page failed'))
  page.emit('requestfailed', {
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

test('observer excludes Vite source paths containing api and accepts cache revalidation', async () => {
  const { observeRuntime } = await import('../../frontend/e2e/runtime-observer.mjs')
  const page = new FakePage()
  const observer = observeRuntime(page)
  page.emit('response', fakeResponse({
    url: 'http://127.0.0.1:5173/src/api/db/client.js',
    status: 304,
    text: async () => { throw new Error('304 response body is unavailable') },
  }))
  page.emit('response', fakeResponse({
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

test('observer enforces exact write method path status and count allowlists', async () => {
  const { assertExactWrites } = await import('../../frontend/e2e/runtime-observer.mjs')
  const evidence = {
    apiResponses: [
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

test('runtime scan values include all fixed sentinels and the dynamic corpus root', async () => {
  const { runtimeSensitiveValues } = await import('../../frontend/e2e/runtime-observer.mjs')
  const environment = {
    BROWSER_SECRET_SENTINEL: 'fixed-secret',
    BROWSER_PRIVATE_PROVIDER_URL: 'fixed-provider-url',
    BROWSER_CORPUS_ROOT_SENTINEL: 'fixed-corpus-root',
    BROWSER_ACTUAL_CORPUS_ROOT_SENTINEL: 'dynamic-corpus-root',
  }

  assert.deepEqual(runtimeSensitiveValues(environment), [
    'fixed-secret',
    'fixed-provider-url',
    'fixed-corpus-root',
    'dynamic-corpus-root',
  ])
})
