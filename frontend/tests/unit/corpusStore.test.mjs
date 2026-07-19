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

test('library commands search/filter, load versions, CAS archive/restore, and danger-delete once', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  const requests = []
  const source = {
    id: 'source-1',
    revision: 3,
    contentHash: 'a'.repeat(64),
    archivedAt: null,
    deleteEligible: false,
    deleteReason: 'source_not_archived',
  }

  await withBrowserGuards(async (url, options) => {
    const parsed = new URL(String(url))
    const body = options.body ? JSON.parse(options.body) : undefined
    requests.push({ method: options.method, parsed, body })
    if (options.method === 'GET' && parsed.pathname.endsWith('/corpus/sources')) {
      return jsonResponse({ items: [source] })
    }
    if (options.method === 'GET' && parsed.pathname.endsWith('/versions')) {
      assert.equal(parsed.searchParams.get('limit'), '1')
      if (parsed.searchParams.get('cursor') === '3') {
        return jsonResponse({
          items: [{ ...source, revision: 2, isCurrent: false, referenceCount: 0 }],
          nextCursor: null,
        })
      }
      return jsonResponse({
        items: [{ ...source, isCurrent: true, referenceCount: 0 }],
        nextCursor: 3,
      })
    }
    if (options.method === 'POST' && parsed.pathname.endsWith('/archive')) {
      return jsonResponse({ ...source, archivedAt: 123, deleteEligible: true, deleteReason: null })
    }
    if (options.method === 'POST' && parsed.pathname.endsWith('/restore')) {
      return jsonResponse(source)
    }
    if (options.method === 'DELETE' && parsed.pathname.endsWith('/corpus/sources/source-1')) {
      return new Response(null, { status: 204 })
    }
    throw new Error(`unexpected request ${options.method} ${url}`)
  }, async () => {
    await store.loadSources({ search: '玄幻', state: 'archived' })
    const firstPage = await store.loadVersions('source-1', { limit: 1 })
    assert.equal(firstPage.items[0].isCurrent, true)
    assert.equal(firstPage.nextCursor, 3)
    const fullHistory = await store.loadVersions(
      'source-1', { cursor: firstPage.nextCursor, limit: 1 },
    )
    assert.deepEqual(fullHistory.items.map(item => item.revision), [3, 2])
    await store.archiveSource('source-1', 3)
    await store.restoreSource('source-1', 3)
    await store.permanentlyDeleteSource('source-1', 3, true)
  })

  assert.equal(requests[0].parsed.searchParams.get('search'), '玄幻')
  assert.equal(requests[0].parsed.searchParams.get('state'), 'archived')
  assert.deepEqual(requests.slice(3).map(request => [request.method, request.body]), [
    ['POST', { expectedRevision: 3 }],
    ['POST', { expectedRevision: 3 }],
    ['DELETE', { expectedRevision: 3, confirmPermanentDelete: true }],
  ])
  assert.deepEqual(store.sources, [])
  assert.equal(store.sourceVersions['source-1'], undefined)
})

test('import sends bounded revisioned metadata without managed paths or raw bytes', async () => {
  setActivePinia(createPinia())
  const store = useCorpusStore()
  let request

  await withBrowserGuards(async (url, options) => {
    request = { url: String(url), body: JSON.parse(options.body) }
    return jsonResponse({
      importId: 'import-3',
      status: 'succeeded',
      sourceId: 'source-1',
      sourceRevision: 2,
      sourceRevisionId: 'revision-2',
      sourceLabel: 'safe/book.txt',
      shortHash: 'abc123def456',
      errorCode: null,
    })
  }, async () => {
    await store.importSource({
      idempotencyKey: 'z'.repeat(32),
      relativePath: 'safe/book.txt',
      sourceId: 'source-1',
      createDistinctSource: false,
      displayName: '北境卷',
      referenceTags: ['玄幻', '战争'],
      notes: '短注',
      managedRoot: 'C:/private/must-not-send',
      rawBytes: 'must-not-send',
    })
  })

  assert.deepEqual(request.body, {
    idempotencyKey: 'z'.repeat(32),
    relativePath: 'safe/book.txt',
    sourceId: 'source-1',
    createDistinctSource: false,
    displayName: '北境卷',
    referenceTags: ['玄幻', '战争'],
    notes: '短注',
  })
})

test('legacy settings corpus component is removed after canonical asset page replacement', async () => {
  await assert.rejects(
    readFile(path.join(frontendRoot, 'src/components/settings/CorpusSettings.vue'), 'utf8'),
    /ENOENT/,
  )
})
