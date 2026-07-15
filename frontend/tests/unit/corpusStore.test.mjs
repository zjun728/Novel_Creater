import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useCorpusStore } from '../../src/stores/corpusStore.js'

const frontendRoot = path.resolve(import.meta.dirname, '../..')

function jsonResponse(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => {
    resolve = yes
    reject = no
  })
  return { promise, resolve, reject }
}

async function withBrowserGuards(fetchImpl, action) {
  const originalFetch = globalThis.fetch
  const localStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new Error('formal corpus state must never read localStorage')
    },
  })
  globalThis.fetch = fetchImpl
  try {
    return await action()
  } finally {
    globalThis.fetch = originalFetch
    if (localStorageDescriptor) {
      Object.defineProperty(globalThis, 'localStorage', localStorageDescriptor)
    } else {
      delete globalThis.localStorage
    }
  }
}

test('corpus source list ignores stale responses and source details cache by immutable identity', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const pendingLists = []
  let detailReads = 0
  const contentHash = 'a'.repeat(64)

  await withBrowserGuards((url) => {
    const parsed = new URL(String(url))
    if (parsed.pathname.endsWith('/corpus/sources')) {
      const response = deferred()
      pendingLists.push(response)
      return response.promise
    }
    if (parsed.pathname.endsWith('/corpus/sources/source-1')) {
      detailReads += 1
      assert.equal(parsed.searchParams.get('previewChars'), '1200')
      return Promise.resolve(jsonResponse({
        id: 'source-1', revision: 3, contentHash, shortHash: contentHash.slice(0, 12), preview: '节选',
      }))
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const oldLoad = store.loadSources()
    const newLoad = store.loadSources()
    pendingLists[1].resolve(jsonResponse({
      items: [{ id: 'new-source', revision: 2, contentHash: 'b'.repeat(64), shortHash: 'b'.repeat(12) }],
    }))
    await newLoad
    pendingLists[0].resolve(jsonResponse({
      items: [{ id: 'old-source', revision: 1, contentHash: 'c'.repeat(64), shortHash: 'c'.repeat(12) }],
    }))
    await oldLoad
    assert.deepEqual(store.sources.map(item => item.id), ['new-source'])

    const first = await store.getSource('source-1', 3, contentHash)
    assert.deepEqual(await store.getSource('source-1', 3, contentHash), first)
    assert.deepEqual(store.toContractRef(first), {
      id: 'source-1', revision: 3, contentHash, selectionMode: 'author',
    })
    store.invalidateQueryState()
    assert.deepEqual(store.sources, [])
    assert.deepEqual(await store.getSource('source-1', 3, contentHash), first)
    assert.equal(detailReads, 1, 'query invalidation must preserve immutable source details')
  })
})

test('corpus import remains relative-path-only and does not auto-retry', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const requests = []

  await withBrowserGuards(async (url, options) => {
    requests.push({ url: String(url), body: options.body && JSON.parse(options.body) })
    return jsonResponse({
      importId: 'import-1', status: 'failed', sourceId: null,
      relativePath: '玄幻/样本.txt', shortHash: '', errorCode: 'CorpusImportFailed',
    })
  }, async () => {
    await assert.rejects(
      store.importSource({ idempotencyKey: 'a'.repeat(32), relativePath: 'C:\\private\\book.txt' }),
      /relative corpus path/i,
    )
    const failed = await store.importSource({
      idempotencyKey: 'b'.repeat(32), relativePath: '玄幻/样本.txt',
    })
    assert.equal(failed.status, 'failed')
  })

  assert.equal(requests.length, 1)
  assert.deepEqual(requests[0].body, {
    idempotencyKey: 'b'.repeat(32), relativePath: '玄幻/样本.txt',
  })
})

test('a succeeded import invalidates only the source list and preserves immutable detail caches', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const contentHash = 'd'.repeat(64)
  let detailReads = 0

  await withBrowserGuards(async (url, options) => {
    const parsed = new URL(String(url))
    if (options.method === 'GET' && parsed.pathname.endsWith('/corpus/sources')) {
      return jsonResponse({ items: [{ id: 'source-1', revision: 1, contentHash }] })
    }
    if (options.method === 'GET' && parsed.pathname.endsWith('/corpus/sources/source-1')) {
      detailReads += 1
      return jsonResponse({ id: 'source-1', revision: 1, contentHash, preview: '不可变节选' })
    }
    if (options.method === 'POST' && parsed.pathname.endsWith('/corpus/imports')) {
      return jsonResponse({
        importId: 'import-2', status: 'succeeded', sourceId: 'source-2',
        relativePath: '仙侠/新书.txt', shortHash: 'new123456789', errorCode: null,
      })
    }
    throw new Error(`unexpected request ${options.method} ${url}`)
  }, async () => {
    await store.loadSources()
    const cached = await store.getSource('source-1', 1, contentHash)
    await store.importSource({
      idempotencyKey: 'c'.repeat(32), relativePath: '仙侠/新书.txt',
    })

    assert.deepEqual(store.sources, [])
    assert.deepEqual(await store.getSource('source-1', 1, contentHash), cached)
    assert.equal(detailReads, 1)
  })
})

test('an older import status response cannot overwrite a newer terminal result', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const pending = [deferred(), deferred()]
  let readIndex = 0

  await withBrowserGuards(() => pending[readIndex++].promise, async () => {
    const older = store.getImport('import-1')
    const newer = store.getImport('import-1')
    pending[1].resolve(jsonResponse({
      importId: 'import-1', status: 'succeeded', sourceId: 'source-1',
      relativePath: '玄幻/样本.txt', shortHash: 'abc123def456', errorCode: null,
    }))
    await newer
    pending[0].resolve(jsonResponse({
      importId: 'import-1', status: 'running', sourceId: null,
      relativePath: '玄幻/样本.txt', shortHash: '', errorCode: null,
    }))
    await older

    assert.equal(store.importRuns['import-1'].status, 'succeeded')
  })
})

test('corpus previews and fragment pages use the API client bounds', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const calls = []

  await withBrowserGuards(async (url) => {
    const parsed = new URL(String(url))
    calls.push(parsed)
    if (parsed.pathname.endsWith('/corpus/chapters/chapter-1/fragments')) {
      return jsonResponse({ items: [], nextCursor: null })
    }
    if (parsed.pathname.endsWith('/corpus/discovery')) {
      return jsonResponse({ items: [], nextCursor: null, reasonCounts: {}, scanStrategy: 'recursive' })
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.discover({ cursor: 'next page', limit: 999 })
    await store.loadFragments('chapter-1', { cursor: -4, limit: 999 })
  })

  assert.equal(calls[0].searchParams.get('cursor'), 'next page')
  assert.equal(calls[0].searchParams.get('limit'), '200')
  assert.equal(calls[1].searchParams.get('cursor'), '0')
  assert.equal(calls[1].searchParams.get('limit'), '20')
})

test('clearing fragments prevents a late chapter response from crossing into another source', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const pending = deferred()
  assert.equal(typeof store.clearFragments, 'function')

  await withBrowserGuards(() => pending.promise, async () => {
    const staleRead = store.loadFragments('old-chapter', { cursor: 0, limit: 20 })
    assert.equal(store.loadingFragments, true)
    store.clearFragments()
    assert.equal(store.fragmentPage, null)
    assert.equal(store.loadingFragments, false)

    pending.resolve(jsonResponse({
      items: [{ id: 'stale-fragment', order: 1, preview: '旧来源片段' }],
      nextCursor: null,
    }))
    await staleRead
  })

  assert.equal(store.fragmentPage, null)
  assert.equal(store.loadingFragments, false)
})

test('corpus settings keep discovery relative and render previews inside the 240/4800 budget', async () => {
  const source = await readFile(
    path.join(frontendRoot, 'src/components/settings/CorpusSettings.vue'),
    'utf8',
  )

  assert.match(source, /relativePath/)
  assert.match(source, /getSource\(/)
  assert.match(source, /loadFragments\([^)]*\{[^}]*limit:\s*20/s)
  assert.match(source, /PREVIEW_ITEM_LIMIT\s*=\s*240/)
  assert.match(source, /PREVIEW_PAGE_BUDGET\s*=\s*4_800/)
  assert.match(source, /priorRun\?\.status\s*===\s*['"]failed['"][\s\S]*importKeys\.delete\(relativePath\)/)
  assert.match(source, /error\?\.code\s*===\s*['"]CorpusImportFailed['"][\s\S]*importKeys\.delete\(relativePath\)/)
  assert.match(source, /chapterEpoch/)
  assert.match(source, /epoch\s*===\s*chapterEpoch/)
  assert.doesNotMatch(source, /\bfetch\s*\(|localStorage|type=["']file["']/)
  assert.doesNotMatch(source, /\{\{[^}]*contentHash[^}]*\}\}/)
})
