import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useCreationAssetStore } from '../../src/stores/creationAssetStore.js'
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

function formalRecommendationResponse({ attemptId, engineOptionId }) {
  return {
    attemptId,
    publicReason: null,
    rankingUnavailable: false,
    fullBrowseAvailable: true,
    assetRecommendations: [],
    corpusRecommendations: [],
    inputManifest: { engineOptionId },
    inputManifestHash: '1'.repeat(64),
    resultHash: '2'.repeat(64),
  }
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
    taxonomyPackageVersion: 'recommendation-taxonomy-v1.0.0',
    taxonomyPackageHash: 'a'.repeat(64),
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
    pending.get('new-project').resolve(jsonResponse(formalRecommendationResponse({
      attemptId: 'attempt-new', engineOptionId: 'engine-new',
    })))
    await newLoad
    pending.get('old-project').resolve(jsonResponse(formalRecommendationResponse({
      attemptId: 'attempt-old', engineOptionId: 'engine-old',
    })))
    await oldLoad

    assert.equal(store.recommendations.attemptId, 'attempt-new')
    assert.equal(store.recommendations.inputManifest.engineOptionId, 'engine-new')
  })
})

test('recommendations derive a narrow typed scope from the persisted contract draft', async () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const requests = []

  await withBrowserGuards(async (url, options) => {
    const parsed = new URL(String(url))
    requests.push({ parsed, options })
    if (parsed.pathname.endsWith('/assets/inventory')) {
      return jsonResponse({
        taxonomyPackageVersion: 'recommendation-taxonomy-v1.0.0',
        taxonomyPackageHash: 'b'.repeat(64),
      })
    }
    if (parsed.pathname.endsWith('/asset-recommendations')) {
      return jsonResponse(formalRecommendationResponse({
        attemptId: 'attempt-1', engineOptionId: 'engine-1',
      }))
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const draft = {
      draftStage: 'style',
      seedHash: 's'.repeat(64),
      engineHash: 'e'.repeat(64),
      primaryStyleRef: { id: 'style-1', revision: 1, contentHash: 'p'.repeat(64) },
      secondaryStyleRef: null,
      genreProfileKey: 'historical',
      channelProfileKey: 'qidian-qq',
      dislikes: ['slow_burn', 'slow_burn', '这条自由文本不是 typed prohibition'],
    }
    await store.loadRecommendations('project-1', 'engine-1', draft, {
      selectionRevision: 7,
    })
    await store.loadRecommendations('project-1', 'engine-1', draft, {
      selectionRevision: 7,
    })
    await store.loadRecommendations('project-1', 'engine-1', draft, {
      selectionRevision: 8,
    })
  })

  assert.deepEqual(
    requests.map(request => [request.options.method, request.parsed.pathname]),
    [
      ['GET', '/api/assets/inventory'],
      ['POST', '/api/projects/project-1/asset-recommendations'],
      ['POST', '/api/projects/project-1/asset-recommendations'],
      ['POST', '/api/projects/project-1/asset-recommendations'],
    ],
  )
  assert.equal(requests[1].parsed.search, '')
  const bodies = requests.slice(1).map(request => JSON.parse(request.options.body))
  assert.equal(bodies[0].idempotencyKey, bodies[1].idempotencyKey)
  assert.notEqual(bodies[1].idempotencyKey, bodies[2].idempotencyKey)
  const body = bodies[0]
  assert.match(body.idempotencyKey, /^[A-Za-z0-9_-]{64}$/u)
  delete body.idempotencyKey
  assert.deepEqual(body, {
    engineOptionId: 'engine-1',
    taxonomyVersion: 'recommendation-taxonomy-v1.0.0',
    taxonomyHash: 'b'.repeat(64),
    genre: 'historical',
    creationStage: 'drafting',
    status: 'active',
    prohibitedDirections: ['slow_burn'],
  })
})

test('formal asset recommendations join exact immutable catalog identities into reactive view models', () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const style = {
    id: 'style-revision-1', stableKey: 'style-direct', revision: 3,
    contentHash: 'a'.repeat(64), name: '直进悬疑型', readingExperience: '线索持续前推',
  }
  const card = {
    id: 'card-revision-1', stableKey: 'card-dialogue-turn', revision: 2,
    contentHash: 'b'.repeat(64), title: '对话转向', category: 'dialogue', method: '让关系发生位移',
  }
  const response = {
    attemptId: 'attempt-1',
    publicReason: null,
    rankingUnavailable: false,
    fullBrowseAvailable: true,
    assetRecommendations: [{
      assetRevisionId: style.id,
      assetType: 'style',
      stableKey: style.stableKey,
      revision: style.revision,
      contentHash: style.contentHash,
      reason: 'semantic-profile',
      confidence: 0.91,
    }, {
      assetRevisionId: card.id,
      assetType: 'experience_card',
      stableKey: card.stableKey,
      revision: card.revision,
      contentHash: card.contentHash,
      reason: 'asset-text-overlap',
      confidence: 0.87,
    }, {
      assetRevisionId: style.id,
      assetType: 'style',
      stableKey: style.stableKey,
      revision: style.revision,
      contentHash: style.contentHash,
      reason: 'duplicate-must-not-render',
      confidence: 0.99,
    }],
    corpusRecommendations: [],
    inputManifest: {},
    inputManifestHash: 'c'.repeat(64),
    resultHash: 'd'.repeat(64),
  }
  store.recommendations = response

  assert.deepEqual(store.recommendations, response, 'formal response must remain available verbatim')
  assert.deepEqual(store.recommendedStyles, [], 'recommendations wait reactively for the catalog')
  assert.deepEqual(store.recommendedExperienceCards, [])

  store.styleTemplates = [style]
  store.experienceCards = [card]
  assert.deepEqual(store.recommendedStyles, [{
    ...style,
    reasonCodes: ['semantic-profile'],
    confidence: 0.91,
  }], 'backend order is preserved and a duplicate immutable revision is shown once')
  assert.deepEqual(store.recommendedExperienceCards, [{
    ...card,
    reasonCodes: ['asset-text-overlap'],
    confidence: 0.87,
  }])

  store.recommendations = {
    ...response,
    assetRecommendations: response.assetRecommendations.map(item => (
      item.assetType === 'style' ? { ...item, contentHash: 'c'.repeat(64) } : item
    )),
  }
  assert.deepEqual(store.recommendedStyles, [], 'drifted style identity must fail safe')
  assert.equal(store.recommendedExperienceCards.length, 1)
})

test('formal corpus recommendations join exact managed source identities reactively', () => {
  setActivePinia(createPinia())
  const store = useCreationAssetStore()
  const corpusStore = useCorpusStore()
  const sourceA = {
    id: 'source-a', revisionId: 'source-a-revision', revision: 3,
    contentHash: 'a'.repeat(64), name: '来源 A', state: 'active',
  }
  const sourceB = {
    id: 'source-b', revisionId: 'source-b-revision', revision: 5,
    contentHash: 'b'.repeat(64), name: '来源 B', state: 'active',
  }
  const recommendation = (source, fragmentId, overrides = {}) => ({
    sourceId: source.id,
    sourceRevision: source.revision,
    sourceHash: source.contentHash,
    chapterId: `${source.id}-chapter`,
    fragmentId,
    fragmentHash: (fragmentId === 'fragment-b' ? 'd' : 'c').repeat(64),
    rangeStart: 12,
    rangeEnd: 42,
    use: '作为结构节奏参照',
    reason: '与当前冲突直接相关',
    confidence: 0.9,
    ...overrides,
  })
  const response = {
    ...formalRecommendationResponse({ attemptId: 'attempt-corpus', engineOptionId: 'engine-1' }),
    corpusRecommendations: [
      recommendation(sourceB, 'fragment-b'),
      recommendation(sourceA, 'fragment-a'),
      recommendation(sourceB, 'fragment-b', { reason: '重复项不得再次显示' }),
      recommendation(sourceA, 'fragment-mismatch', { sourceHash: 'e'.repeat(64) }),
      recommendation(sourceA, 'fragment-revision-mismatch', { sourceRevision: 4 }),
      recommendation(sourceA, 'fragment-source-mismatch', { sourceId: 'source-unknown' }),
    ],
  }
  store.recommendations = response

  assert.deepEqual(store.recommendations, response)
  assert.deepEqual(store.recommendedCorpusFragments, [], 'recommendations wait for managed sources')
  corpusStore.sources = [sourceA, sourceB]
  assert.deepEqual(store.recommendedCorpusFragments.map(item => ({
    sourceName: item.source.name,
    sourceRevisionId: item.source.revisionId,
    fragmentId: item.fragmentId,
    reasonCodes: item.reasonCodes,
  })), [{
    sourceName: '来源 B',
    sourceRevisionId: 'source-b-revision',
    fragmentId: 'fragment-b',
    reasonCodes: ['与当前冲突直接相关'],
  }, {
    sourceName: '来源 A',
    sourceRevisionId: 'source-a-revision',
    fragmentId: 'fragment-a',
    reasonCodes: ['与当前冲突直接相关'],
  }], 'backend order is preserved while duplicates and source drift stay hidden')

  corpusStore.sources = [{ ...sourceA, contentHash: 'f'.repeat(64) }, sourceB]
  assert.deepEqual(
    store.recommendedCorpusFragments.map(item => item.fragmentId),
    ['fragment-b'],
    'a late managed-source identity drift fails safe reactively',
  )
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
        taxonomyPackageHash: 'c'.repeat(64),
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
