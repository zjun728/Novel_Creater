import assert from 'node:assert/strict'
import test from 'node:test'

import { api } from '../../src/api/db/client.js'
import { ApiError } from '../../src/api/db/api-error.js'

const zip = () => new File(['PK\u0003\u0004bytes'], 'backup.zip', { type: 'application/zip' })
const response = ({ status = 200, body = {} } = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => JSON.stringify(body),
  json: async () => body,
})

function signalSpy() {
  const listeners = new Set()
  const signal = {
    aborted: false,
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
  }
  return {
    signal,
    get listenerCount() { return listeners.size },
    abort() { signal.aborted = true; for (const listener of [...listeners]) listener() },
  }
}

test('project import API sends exact multipart fields and recovery is GET-only', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return response({ body: calls.length === 1
      ? { packageHash: 'a'.repeat(64), proposedTitle: '旧书' }
      : { commandId: '11111111-1111-4111-8111-111111111111', status: 'running' } })
  }
  try {
    const file = zip()
    await api.projectImports.preflight(file, { ignored: 'no' })
    await api.projectImports.publish(file, {
      commandId: '11111111-1111-4111-8111-111111111111',
      idempotencyKey: 'import-key-00001',
      expectedPackageHash: 'a'.repeat(64),
      newTitle: '新书',
      ignored: 'no',
    })
    await api.projectImports.get('11111111-1111-4111-8111-111111111111')

    assert.equal(new URL(calls[0].url).pathname, '/api/project-imports/preflight')
    assert.equal(calls[0].options.method, 'POST')
    assert.equal(calls[0].options.headers, undefined)
    assert.deepEqual([...calls[0].options.body.keys()], ['file'])
    assert.equal(calls[0].options.body.get('file'), file)

    assert.equal(new URL(calls[1].url).pathname, '/api/project-imports')
    assert.equal(calls[1].options.method, 'POST')
    assert.deepEqual([...calls[1].options.body.keys()], [
      'file', 'commandId', 'idempotencyKey', 'expectedPackageHash', 'newTitle',
    ])
    assert.equal(calls[1].options.body.get('file'), file)
    assert.equal(calls[1].options.body.get('newTitle'), '新书')

    assert.equal(new URL(calls[2].url).pathname, '/api/project-imports/11111111-1111-4111-8111-111111111111')
    assert.equal(calls[2].options.method, 'GET')
    assert.equal(calls[2].options.body, undefined)
  } finally {
    global.fetch = originalFetch
  }
})

test('project import API accepts only File and maps failures to fixed ApiError', async () => {
  assert.throws(() => api.projectImports.preflight(new Blob(['x'])), TypeError)
  assert.throws(() => api.projectImports.publish({ name: 'fake.zip' }, {}), TypeError)

  const originalFetch = global.fetch
  try {
    global.fetch = async () => response({ status: 409, body: {
      code: 'ProjectImportConflict', message: 'fixed conflict', correlationId: 'safe-id',
    } })
    await assert.rejects(
      () => api.projectImports.preflight(zip()),
      error => error instanceof ApiError && error.status === 409
        && error.code === 'ProjectImportConflict' && error.message === 'fixed conflict',
    )
    global.fetch = async () => { throw new Error('private host and archive path') }
    await assert.rejects(
      () => api.projectImports.get('11111111-1111-4111-8111-111111111111'),
      error => error instanceof ApiError && error.code === 'request_failed'
        && error.message === '请求失败',
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('project import multipart clears timeout and external abort listener on success and abort', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  const timers = []
  const cleared = []
  global.setTimeout = (callback, delay) => { const timer = { callback, delay }; timers.push(timer); return timer }
  global.clearTimeout = timer => cleared.push(timer)
  try {
    const success = signalSpy()
    global.fetch = async () => response({ body: {} })
    await api.projectImports.preflight(zip(), { signal: success.signal })
    assert.equal(success.listenerCount, 0)
    assert.equal(cleared.includes(timers[0]), true)

    const aborted = signalSpy()
    global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('private', 'AbortError')))
    })
    const pending = api.projectImports.preflight(zip(), { signal: aborted.signal })
    aborted.abort()
    await assert.rejects(pending, error => error instanceof ApiError && error.code === 'request_aborted')
    assert.equal(aborted.listenerCount, 0)
    assert.equal(cleared.includes(timers[1]), true)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }
})
