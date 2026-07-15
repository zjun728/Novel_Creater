import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useCreationAssetStore } from '../../src/stores/creationAssetStore.js'

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
      throw new Error('formal asset state must never read localStorage')
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

test('asset list loads ignore stale responses while immutable details cache by id and hash', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const pendingLists = []
  let detailReads = 0
  const hash = 'a'.repeat(64)

  await withBrowserGuards((url) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/assets/style-templates')) {
      const response = deferred()
      pendingLists.push(response)
      return response.promise
    }
    if (path.endsWith('/assets/style-templates/style-1')) {
      detailReads += 1
      return Promise.resolve(jsonResponse({ id: 'style-1', revision: 3, contentHash: hash }))
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const oldLoad = store.loadStyleTemplates()
    const newLoad = store.loadStyleTemplates()
    pendingLists[1].resolve(jsonResponse([{ id: 'new-style', contentHash: 'b'.repeat(64) }]))
    await newLoad
    pendingLists[0].resolve(jsonResponse([{ id: 'old-style', contentHash: 'c'.repeat(64) }]))
    await oldLoad
    assert.deepEqual(store.styleTemplates.map(item => item.id), ['new-style'])

    const first = await store.getStyleTemplate('style-1', hash)
    const second = await store.getStyleTemplate('style-1', hash)
    assert.deepEqual(second, first)
    assert.equal(detailReads, 1)

    store.invalidateCatalogQueries()
    assert.deepEqual(store.styleTemplates, [])
    assert.deepEqual(await store.getStyleTemplate('style-1', hash), first)
    assert.equal(detailReads, 1, 'list invalidation must preserve immutable detail revisions')
  })
})

test('asset detail cache refuses an id or content-hash mismatch', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  let reads = 0

  await withBrowserGuards(async () => {
    reads += 1
    return jsonResponse({ id: 'card-1', revision: 2, contentHash: 'f'.repeat(64) })
  }, async () => {
    await assert.rejects(
      store.getExperienceCard('card-1', 'e'.repeat(64)),
      /immutable experience card revision changed/i,
    )
    await assert.rejects(
      store.getExperienceCard('card-1', 'e'.repeat(64)),
      /immutable experience card revision changed/i,
    )
  })

  assert.equal(reads, 2, 'mismatched responses must never enter the immutable cache')
})

test('asset recommendations are latest-request guarded backend facts', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const pending = new Map()

  await withBrowserGuards((url) => {
    const parsed = new URL(String(url))
    const projectId = parsed.pathname.split('/')[3]
    const response = deferred()
    pending.set(projectId, response)
    return response.promise
  }, async () => {
    const oldLoad = store.loadRecommendations('old-project', 'engine-old')
    const newLoad = store.loadRecommendations('new-project', 'engine-new')
    pending.get('new-project').resolve(jsonResponse({
      recommendationHash: 'n'.repeat(64), seedRevisionId: 'seed-new', seedHash: 's'.repeat(64),
      engineOptionId: 'engine-new', engineHash: 'e'.repeat(64), styles: [], experienceCards: [],
    }))
    await newLoad
    pending.get('old-project').resolve(jsonResponse({
      recommendationHash: 'o'.repeat(64), seedRevisionId: 'seed-old', seedHash: 't'.repeat(64),
      engineOptionId: 'engine-old', engineHash: 'f'.repeat(64), styles: [], experienceCards: [],
    }))
    await oldLoad

    assert.equal(store.recommendations.engineOptionId, 'engine-new')
    assert.equal(store.recommendations.seedRevisionId, 'seed-new')
  })
})
