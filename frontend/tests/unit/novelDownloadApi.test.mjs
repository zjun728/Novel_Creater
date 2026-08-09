import assert from 'node:assert/strict'
import test from 'node:test'

import { ApiError } from '../../src/api/db/api-error.js'
import { api } from '../../src/api/db/client.js'

const response = ({ status = 200, text = '', blob, disposition = null } = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => text,
  blob: async () => blob,
  headers: { get: name => name === 'Content-Disposition' ? disposition : null },
  json: async () => JSON.parse(text),
})

test('the existing JSON request still reads text and parses JSON', async () => {
  const originalFetch = global.fetch
  let readText = 0
  let readBlob = false
  global.fetch = async () => ({
    ok: true,
    status: 200,
    text: async () => { readText += 1; return JSON.stringify({ ok: true }) },
    blob: async () => { readBlob = true; throw new Error('JSON request must not read blobs') },
  })
  try {
    const value = await api.health()
    assert.deepEqual(value, { ok: true })
    assert.equal(readText, 1)
    assert.equal(readBlob, false)
  } finally {
    global.fetch = originalFetch
  }
})

test('novel download uses the exact closed query and returns blob plus disposition', async () => {
  const originalFetch = global.fetch
  const content = new Blob(['novel'])
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return response({ blob: content, disposition: "attachment; filename*=UTF-8''%E4%B9%A6.txt" })
  }
  try {
    const downloaded = await api.novelDownloads.download('project/1', {
      scope: 'volume', format: 'markdown', volumeId: 'volume/1',
      chapterNumber: undefined, ignored: 'must-not-cross',
    })
    const url = new URL(calls[0].url)
    assert.equal(calls[0].options.method, 'GET')
    assert.equal(url.pathname, '/api/projects/project%2F1/novel-download')
    assert.equal(url.search, '?scope=volume&format=markdown&volumeId=volume%2F1')
    assert.deepEqual(downloaded, {
      blob: content,
      contentDisposition: "attachment; filename*=UTF-8''%E4%B9%A6.txt",
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('novel download options stays on the JSON path', async () => {
  const originalFetch = global.fetch
  global.fetch = async (url, options) => {
    assert.equal(options.method, 'GET')
    assert.equal(new URL(String(url)).pathname, '/api/projects/p%2F1/novel-download/options')
    return response({ text: JSON.stringify({ available: true, formats: ['txt'] }) })
  }
  try {
    assert.deepEqual(await api.novelDownloads.options('p/1'), {
      available: true, formats: ['txt'],
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('novel download turns HTTP, abort, and network failures into safe ApiErrors', async () => {
  const originalFetch = global.fetch
  try {
    global.fetch = async () => response({ status: 409, text: JSON.stringify({
      code: 'NovelDownloadUnavailable', message: 'unavailable',
    }) })
    await assert.rejects(
      () => api.novelDownloads.download('p', { scope: 'book', format: 'txt' }),
      error => error instanceof ApiError && error.status === 409 && error.code === 'NovelDownloadUnavailable',
    )

    global.fetch = async () => { throw new DOMException('cancelled', 'AbortError') }
    const controller = new AbortController()
    controller.abort()
    await assert.rejects(
      () => api.novelDownloads.download('p', { scope: 'book', format: 'txt' }, { signal: controller.signal }),
      error => error instanceof ApiError && error.code === 'request_aborted',
    )

    global.fetch = async () => { throw new Error('tcp://private.example') }
    await assert.rejects(
      () => api.novelDownloads.download('p', { scope: 'book', format: 'txt' }),
      error => error instanceof ApiError && error.status === 0 && error.message === '请求失败',
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('binary requests remove external listeners and clear timers after success and external abort', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  const timers = []
  const cleared = []
  const signalSpy = () => {
    const listeners = new Set()
    const signal = {
      aborted: false,
      addEventListener: (_event, listener) => listeners.add(listener),
      removeEventListener: (_event, listener) => listeners.delete(listener),
    }
    return {
      signal,
      get listenerCount() { return listeners.size },
      abort: () => {
        signal.aborted = true
        for (const listener of [...listeners]) listener()
      },
    }
  }
  global.setTimeout = (callback, delay) => {
    const timer = { callback, delay }
    timers.push(timer)
    return timer
  }
  global.clearTimeout = timer => cleared.push(timer)
  try {
    const success = signalSpy()
    global.fetch = async () => response({ blob: new Blob(['book']) })
    await api.novelDownloads.download('p', { scope: 'book', format: 'txt' }, {
      signal: success.signal,
    })
    assert.equal(success.listenerCount, 0)
    assert.equal(cleared.includes(timers[0]), true)

    const aborted = signalSpy()
    global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
      signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')))
    })
    const pending = api.novelDownloads.download('p', { scope: 'book', format: 'txt' }, {
      signal: aborted.signal,
    })
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

test('binary request reports an internal 30-second timeout without waiting 30 seconds', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const originalClearTimeout = global.clearTimeout
  let timeoutCallback
  let cleared = false
  const timer = { name: 'download-timeout' }
  global.setTimeout = (callback, delay) => {
    assert.equal(delay, 30_000)
    timeoutCallback = callback
    return timer
  }
  global.clearTimeout = value => { cleared = value === timer }
  global.fetch = (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('timeout', 'AbortError')))
  })
  try {
    const pending = api.novelDownloads.download('p', { scope: 'book', format: 'txt' })
    assert.equal(typeof timeoutCallback, 'function')
    timeoutCallback()
    await assert.rejects(pending, error => error instanceof ApiError && error.code === 'request_timeout')
    assert.equal(cleared, true)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
    global.clearTimeout = originalClearTimeout
  }
})
