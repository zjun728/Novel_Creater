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
