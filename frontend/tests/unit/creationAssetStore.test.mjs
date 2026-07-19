import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useCreationAssetStore } from '../../src/stores/creationAssetStore.js'

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
  store.inventory = {
    genres: ['general'],
    channels: ['all'],
    creationStages: ['drafting'],
    writingPurposes: ['style_direction', 'dialogue'],
    prohibitedDirections: [],
    statuses: ['active'],
  }
  const pending = new Map()
  const trustedDraft = {
    draftStage: 'engine',
    genreProfileKey: 'historical',
    channelProfileKey: 'qidian-qq',
    dislikes: null,
  }

  await withBrowserGuards((url) => {
    const parsed = new URL(String(url))
    const projectId = parsed.pathname.split('/')[3]
    const response = deferred()
    pending.set(projectId, response)
    return response.promise
  }, async () => {
    const oldLoad = store.loadRecommendations('old-project', 'engine-old', trustedDraft)
    const newLoad = store.loadRecommendations('new-project', 'engine-new', trustedDraft)
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

test('recommendations derive a narrow typed scope from the persisted contract draft', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const requests = []

  await withBrowserGuards(async url => {
    const parsed = new URL(String(url))
    requests.push(parsed)
    if (parsed.pathname.endsWith('/asset-recommendations')) {
      return jsonResponse({
        recommendationHash: 'r'.repeat(64),
        seedRevisionId: 'seed-1',
        seedHash: 's'.repeat(64),
        engineOptionId: 'engine-1',
        engineHash: 'e'.repeat(64),
        styles: [],
        experienceCards: [],
      })
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.loadRecommendations('project-1', 'engine-1', {
      draftStage: 'style',
      genreProfileKey: 'historical',
      channelProfileKey: 'qidian-qq',
      dislikes: ['slow_burn', '这条自由文本不是 typed prohibition'],
    })
  })

  assert.equal(requests.length, 1)
  const query = requests[0].searchParams
  assert.equal(query.get('engineOptionId'), 'engine-1')
  assert.deepEqual(query.getAll('genres'), ['historical'])
  assert.deepEqual(query.getAll('channels'), ['male_frequency'])
  assert.deepEqual(query.getAll('creationStages'), ['drafting'])
  assert.deepEqual(
    query.getAll('writingPurposes'),
    ['style_direction', 'plot_organization', 'character_arcs', 'long_arc_continuity'],
  )
  assert.deepEqual(query.getAll('prohibitedDirections'), ['slow_burn'])
  assert.equal(query.get('status'), 'active')
})

test('global inventory and canonical filters are backend facts with independent errors', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const requests = []

  await withBrowserGuards(async url => {
    const parsed = new URL(String(url))
    requests.push(`${parsed.pathname}${parsed.search}`)
    if (parsed.pathname.endsWith('/assets/inventory')) {
      return jsonResponse({
        assetPackageVersion: 'writer-core-v1.1.0',
        taxonomyPackageVersion: 'recommendation-taxonomy-v1.0.0',
        styleCount: 10,
        experienceCardCount: 64,
        categories: ['dialogue'],
        genres: ['general'],
        channels: ['all'],
        creationStages: ['drafting'],
        writingPurposes: ['dialogue', 'style_direction'],
        prohibitedDirections: ['slow_burn'],
        statuses: ['active', 'archived'],
      })
    }
    if (parsed.pathname.endsWith('/assets/style-templates')) {
      return jsonResponse([{ id: 'style-1', stableKey: 'direct-propulsive' }])
    }
    if (parsed.pathname.endsWith('/assets/experience-cards')) {
      return jsonResponse([{ id: 'card-1', stableKey: 'dialogue-bargain-real-need' }])
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.loadInventory()
    await store.loadStyleTemplates({
      search: 'direct',
      genre: 'general',
      stage: 'drafting',
      status: 'active',
    })
    await store.loadExperienceCards({
      search: 'bargain',
      category: 'dialogue',
      genre: 'general',
      stage: 'drafting',
      status: 'active',
    })
  })

  assert.equal(store.inventory.styleCount, 10)
  assert.equal(store.inventory.experienceCardCount, 64)
  assert.equal(store.inventory.assetPackageVersion, 'writer-core-v1.1.0')
  assert.equal(store.inventoryError, '')
  assert.equal(store.styleError, '')
  assert.equal(store.cardError, '')
  assert.deepEqual(requests, [
    '/api/assets/inventory',
    '/api/assets/style-templates?search=direct&genre=general&stage=drafting&status=active',
    '/api/assets/experience-cards?search=bargain&category=dialogue&genre=general&stage=drafting&status=active',
  ])
})

test('canonical asset runtime has no retired localStorage truth imports', async () => {
  const [storeSource, styleView, experienceView, styleStep, assetStep] = await Promise.all([
    readFile(path.join(frontendRoot, 'src/stores/creationAssetStore.js'), 'utf8'),
    readFile(path.join(frontendRoot, 'src/views/assets/StyleLibraryView.vue'), 'utf8'),
    readFile(path.join(frontendRoot, 'src/views/assets/ExperienceLibraryView.vue'), 'utf8'),
    readFile(path.join(frontendRoot, 'src/components/project/contract/StyleSelectionStep.vue'), 'utf8'),
    readFile(path.join(frontendRoot, 'src/components/project/contract/AssetScopeStep.vue'), 'utf8'),
  ])
  const canonical = [storeSource, styleView, experienceView, styleStep, assetStep].join('\n')

  assert.doesNotMatch(
    canonical,
    /localStorage|experienceCardProduct|realCorpusExperienceCards\.v3|writingStyleStandards/,
  )
  for (const retired of [
    'src/components/settings/CreationAssetSettings.vue',
    'src/views/ExperienceCardsView.vue',
    'src/data/experienceCardProduct.js',
    'src/data/realCorpusExperienceCards.v3.json',
  ]) {
    await assert.rejects(readFile(path.join(frontendRoot, retired), 'utf8'), /ENOENT/)
  }
})
