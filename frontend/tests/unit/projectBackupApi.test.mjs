import assert from 'node:assert/strict'
import test from 'node:test'

import { api } from '../../src/api/db/client.js'
import { ApiError } from '../../src/api/db/api-error.js'

function response({ status = 200, blob = new Blob(['backup']), disposition = null, sha256 = null, text = '' } = {}) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: {
      get: name => {
        if (name.toLowerCase() === 'content-disposition') return disposition
        if (name.toLowerCase() === 'x-package-sha256') return sha256
        return null
      },
    },
    blob: async () => blob,
    text: async () => text,
    json: async () => JSON.parse(text),
  }
}

function signalSpy() {
  const listeners = new Set()
  const signal = {
    aborted: false,
    addEventListener: (_event, listener) => listeners.add(listener),
    removeEventListener: (_event, listener) => listeners.delete(listener),
  }
  return {
    signal,
    get listenerCount() { return listeners.size },
    abort() {
      signal.aborted = true
      for (const listener of [...listeners]) listener()
    },
  }
}

test('project backup posts only the lifecycle revision and returns the untouched binary metadata', async () => {
  const originalFetch = global.fetch
  const content = new Blob(['PK\u0003\u0004not-json'])
  Object.defineProperty(content, 'text', {
    value: async () => { throw new Error('ZIP body must not be parsed') },
  })
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return response({
      blob: content,
      disposition: "attachment; filename*=UTF-8''%E9%A1%B9%E7%9B%AE.zip",
      sha256: 'a'.repeat(64),
    })
  }
  try {
    const downloaded = await api.projectBackups.create('project/1', 7, {
      ignored: 'must-not-cross',
    })
    assert.equal(calls.length, 1)
    assert.equal(new URL(calls[0].url).pathname, '/api/projects/project%2F1/backup')
    assert.equal(calls[0].options.method, 'POST')
    assert.deepEqual(calls[0].options.headers, { 'Content-Type': 'application/json' })
    assert.deepEqual(JSON.parse(calls[0].options.body), { expectedLifecycleRevision: 7 })
    assert.deepEqual(downloaded, {
      blob: content,
      contentDisposition: "attachment; filename*=UTF-8''%E9%A1%B9%E7%9B%AE.zip",
      packageSha256: 'a'.repeat(64),
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('project backup maps HTTP, external abort, and network failures to fixed ApiErrors', async () => {
  const originalFetch = global.fetch
  try {
    global.fetch = async () => response({
      status: 409,
      text: JSON.stringify({ code: 'ProjectPackageConflict', message: 'busy' }),
    })
    await assert.rejects(
      () => api.projectBackups.create('p', 2),
      error => error instanceof ApiError
        && error.status === 409
        && error.code === 'ProjectPackageConflict',
    )

    global.fetch = async () => { throw new DOMException('private abort detail', 'AbortError') }
    const controller = new AbortController()
    controller.abort()
    await assert.rejects(
      () => api.projectBackups.create('p', 2, { signal: controller.signal }),
      error => error instanceof ApiError
        && error.code === 'request_aborted'
        && error.message === '请求已取消',
    )

    global.fetch = async () => { throw new Error('tcp://private.example') }
    await assert.rejects(
      () => api.projectBackups.create('p', 2),
      error => error instanceof ApiError
        && error.status === 0
        && error.message === '请求失败',
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('project backup removes external listeners and clears timers on success and abort', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  const timers = []
  const cleared = []
  global.setTimeout = (callback, delay) => {
    const timer = { callback, delay }
    timers.push(timer)
    return timer
  }
  global.clearTimeout = timer => cleared.push(timer)
  try {
    const success = signalSpy()
    global.fetch = async () => response()
    await api.projectBackups.create('p', 3, { signal: success.signal })
    assert.equal(success.listenerCount, 0)
    assert.equal(cleared.includes(timers[0]), true)

    const aborted = signalSpy()
    global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })
    const pending = api.projectBackups.create('p', 3, { signal: aborted.signal })
    aborted.abort()
    await assert.rejects(
      pending,
      error => error instanceof ApiError && error.code === 'request_aborted',
    )
    assert.equal(aborted.listenerCount, 0)
    assert.equal(cleared.includes(timers[1]), true)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }
})

test('project backup reports the fixed internal 1200-second timeout without waiting', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  let timeoutCallback
  let scheduledDelay
  let cleared = false
  const timer = { name: 'backup-timeout' }
  global.setTimeout = (callback, delay) => {
    timeoutCallback = callback
    scheduledDelay = delay
    return timer
  }
  global.clearTimeout = value => { cleared = value === timer }
  global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('timeout detail', 'AbortError')))
  })
  try {
    const pending = api.projectBackups.create('p', 4)
    assert.equal(typeof timeoutCallback, 'function')
    assert.equal(scheduledDelay, 1_200_000)
    timeoutCallback()
    await assert.rejects(
      pending,
      error => error instanceof ApiError
        && error.code === 'request_timeout'
        && error.message === '请求超时 (1200s)',
    )
    assert.equal(cleared, true)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }
})

test('project backup timeout does not change other binary request timeouts', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  const delays = []
  global.setTimeout = (_callback, delay) => {
    delays.push(delay)
    return { delay }
  }
  global.clearTimeout = () => {}
  global.fetch = async () => response()
  try {
    await api.projectBackups.create('p', 4)
    await api.novelDownloads.download('p', { scope: 'book', format: 'txt' })
    assert.deepEqual(delays, [1_200_000, 30_000])
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }
})
