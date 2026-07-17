import assert from 'node:assert/strict'
import test from 'node:test'

function jsonResponse(body = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

async function captureRequests(run) {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse()
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    await run(api)
    return calls
  } finally {
    global.fetch = originalFetch
  }
}

function bodyOf(call) {
  return call.options.body === undefined ? undefined : JSON.parse(call.options.body)
}

test('writer core state performs one read through the product API', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({
      projectId: 'project-1',
      schemaVersion: 'writer-core-v1.0.0',
      canonHeadRevision: 0,
      projectionHeadRevision: 0,
      projectionInSync: true,
    }), { status: 200, headers: { 'content-type': 'application/json' } })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    const state = await api.writerCore.state('project-1')

    assert.equal(state.schemaVersion, 'writer-core-v1.0.0')
    assert.equal(calls.length, 1)
    assert.match(calls[0].url, /\/api\/projects\/project-1\/writer-core\/state$/)
    assert.equal(calls[0].options.method, 'GET')
    assert.equal('body' in calls[0].options, false)
  } finally {
    global.fetch = originalFetch
  }
})

test('project update sends only mutable public fields', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url, options })
    return new Response(JSON.stringify({ id: 'project-1' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    await api.projects.update('project-1', {
      title: 'Changed',
      genre: 'history',
      description: 'Description',
      targetWords: 1000,
      targetChapters: 10,
      currentChapter: 4,
      status: 'drafting',
      unexpected: 'discard me',
    })

    assert.equal(calls.length, 1)
    assert.equal(calls[0].options.method, 'PUT')
    assert.deepEqual(JSON.parse(calls[0].options.body), {
      title: 'Changed',
      genre: 'history',
      description: 'Description',
      targetWords: 1000,
      targetChapters: 10,
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('seed CRUD and selection expose exact CAS payloads', async () => {
  const payload = { title: '永乐大典', genre: '穿越' }
  const calls = await captureRequests(async api => {
    await api.seeds.list('project-1')
    await api.seeds.create('project-1', payload)
    await api.seeds.update('project-1', 'seed-1', {
      payload,
      expectedSeedRevision: 2,
      expectedSelectionRevision: 3,
      apiKey: 'must-not-send',
    })
    await api.seeds.delete('project-1', 'seed-1', {
      expectedSeedRevision: 2,
      expectedSelectionRevision: 3,
      debug: 'must-not-send',
    })
    await api.seeds.selected('project-1')
    await api.seeds.select('project-1', {
      seedId: 'seed-1',
      expectedSeedRevision: 2,
      expectedSelectionRevision: 3,
      rawText: 'must-not-send',
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/seeds'],
    ['POST', '/api/projects/project-1/seeds'],
    ['PUT', '/api/projects/project-1/seeds/seed-1'],
    ['DELETE', '/api/projects/project-1/seeds/seed-1'],
    ['GET', '/api/projects/project-1/selected-seed'],
    ['PUT', '/api/projects/project-1/selected-seed'],
  ])
  assert.deepEqual(bodyOf(calls[1]), { payload })
  assert.deepEqual(bodyOf(calls[2]), {
    payload,
    expectedSeedRevision: 2,
    expectedSelectionRevision: 3,
  })
  assert.deepEqual(bodyOf(calls[3]), {
    expectedSeedRevision: 2,
    expectedSelectionRevision: 3,
  })
  assert.deepEqual(bodyOf(calls[5]), {
    seedId: 'seed-1',
    expectedSeedRevision: 2,
    expectedSelectionRevision: 3,
  })
})

test('bindings and story-engine methods send only explicit revision and idempotency inputs', async () => {
  const entries = [{ taskKey: 'story_engine', providerId: 'provider-1' }]
  const options = [{ name: 'engine-1' }, { name: 'engine-2' }, { name: 'engine-3' }]
  const calls = await captureRequests(async api => {
    await api.bindings.get('project-1')
    await api.bindings.status('project-1')
    await api.bindings.replace('project-1', { expectedRevision: 4, entries, apiKey: 'must-not-send' })
    await api.storyEngines.generate('project-1', {
      idempotencyKey: 'engine-provider-1',
      apiKey: 'must-not-send',
      baseURL: 'https://must-not-send.invalid',
    })
    await api.storyEngines.manual('project-1', {
      idempotencyKey: 'engine-manual-1',
      options,
      apiKey: 'must-not-send',
    })
    await api.storyEngines.recoverable('project-1')
    await api.storyEngines.get('project-1', 'batch-1')
    await api.storyEngines.reconcile('project-1', 'batch-1')
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/bindings'],
    ['GET', '/api/projects/project-1/bindings/status'],
    ['PUT', '/api/projects/project-1/bindings'],
    ['POST', '/api/projects/project-1/story-engine-batches'],
    ['POST', '/api/projects/project-1/story-engine-batches/manual'],
    ['GET', '/api/projects/project-1/story-engine-batches/recoverable'],
    ['GET', '/api/projects/project-1/story-engine-batches/batch-1'],
    ['POST', '/api/projects/project-1/story-engine-batches/batch-1/reconcile'],
  ])
  assert.deepEqual(bodyOf(calls[2]), { expectedRevision: 4, entries })
  assert.deepEqual(bodyOf(calls[3]), { idempotencyKey: 'engine-provider-1' })
  assert.deepEqual(bodyOf(calls[4]), { idempotencyKey: 'engine-manual-1', options })
  assert.equal(bodyOf(calls[5]), undefined)
  assert.equal(bodyOf(calls[7]), undefined)
})

test('asset catalog and recommendations are read-only and query encoded', async () => {
  const calls = await captureRequests(async api => {
    await api.assets.styleTemplates.list()
    await api.assets.styleTemplates.get('style/revision')
    await api.assets.experienceCards.list({ category: 'dialogue craft' })
    await api.assets.experienceCards.get('card/revision')
    await api.assets.recommendations('project-1', 'engine option')
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/assets/style-templates'],
    ['GET', '/api/assets/style-templates/style%2Frevision'],
    ['GET', '/api/assets/experience-cards'],
    ['GET', '/api/assets/experience-cards/card%2Frevision'],
    ['GET', '/api/projects/project-1/asset-recommendations'],
  ])
  assert.equal(new URL(calls[2].url).searchParams.get('category'), 'dialogue craft')
  assert.equal(new URL(calls[4].url).searchParams.get('engineOptionId'), 'engine option')
  assert.equal(calls.every(call => !('body' in call.options)), true)
})

test('corpus client stays relative-path-only and enforces preview bounds', async () => {
  const calls = await captureRequests(async api => {
    await api.corpus.discovery({ cursor: 'next item', limit: 999 })
    await api.corpus.imports.create({
      idempotencyKey: 'corpus-import-key-0001',
      relativePath: '玄幻/样本.txt',
      root: 'C:/private',
      rawText: 'full novel must not send',
    })
    await api.corpus.imports.get('import-1')
    await api.corpus.sources.list()
    await api.corpus.sources.get('source-1', { previewChars: 99999 })
    await api.corpus.sources.chapters('source-1')
    await api.corpus.chapters.fragments('chapter-1', { cursor: 5, limit: 999 })
    assert.throws(
      () => api.corpus.imports.create({
        idempotencyKey: 'corpus-import-key-0002',
        relativePath: 'C:\\private\\book.txt',
      }),
      /relative corpus path/i,
    )
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/corpus/discovery'],
    ['POST', '/api/corpus/imports'],
    ['GET', '/api/corpus/imports/import-1'],
    ['GET', '/api/corpus/sources'],
    ['GET', '/api/corpus/sources/source-1'],
    ['GET', '/api/corpus/sources/source-1/chapters'],
    ['GET', '/api/corpus/chapters/chapter-1/fragments'],
  ])
  assert.equal(new URL(calls[0].url).searchParams.get('cursor'), 'next item')
  assert.equal(new URL(calls[0].url).searchParams.get('limit'), '200')
  assert.deepEqual(bodyOf(calls[1]), {
    idempotencyKey: 'corpus-import-key-0001',
    relativePath: '玄幻/样本.txt',
  })
  assert.equal(new URL(calls[4].url).searchParams.get('previewChars'), '1200')
  assert.equal(new URL(calls[6].url).searchParams.get('cursor'), '5')
  assert.equal(new URL(calls[6].url).searchParams.get('limit'), '20')

})

test('contract draft, preview, confirm, history and clone use the formal endpoints', async () => {
  const draft = { engineOptionId: 'engine-1' }
  const calls = await captureRequests(async api => {
    await api.contracts.draft.get('project-1')
    await api.contracts.draft.save('project-1', {
      expectedDraftVersion: 3,
      draft,
      rawText: 'must-not-send',
    })
    await api.contracts.preview('project-1')
    await api.contracts.confirm('project-1', {
      idempotencyKey: 'contract-confirm-1',
      expectedDraftVersion: 4,
      expectedDraftHash: 'a'.repeat(64),
      debug: 'must-not-send',
    })
    await api.contracts.head('project-1')
    await api.contracts.history('project-1', { limit: 500 })
    await api.contracts.clone('project-1')
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/contract-draft'],
    ['PUT', '/api/projects/project-1/contract-draft'],
    ['POST', '/api/projects/project-1/contracts/preview'],
    ['POST', '/api/projects/project-1/contracts/confirm'],
    ['GET', '/api/projects/project-1/contracts/head'],
    ['GET', '/api/projects/project-1/contracts/history'],
    ['POST', '/api/projects/project-1/contracts/clone'],
  ])
  assert.deepEqual(bodyOf(calls[1]), { expectedDraftVersion: 3, draft })
  assert.equal(bodyOf(calls[2]), undefined)
  assert.deepEqual(bodyOf(calls[3]), {
    idempotencyKey: 'contract-confirm-1',
    expectedDraftVersion: 4,
    expectedDraftHash: 'a'.repeat(64),
  })
  assert.equal(new URL(calls[5].url).searchParams.get('limit'), '100')
  assert.equal(bodyOf(calls[6]), undefined)
})

test('planning client reads state and creates only explicit initial plan payload', async () => {
  const calls = await captureRequests(async api => {
    await api.planning.get('project-1')
    await api.planning.createInitial('project-1', {
      expectedContractRevision: 1,
      idempotencyKey: 'planning-1',
      apiKey: 'must-not-send',
      rawText: 'must-not-send',
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/planning'],
    ['POST', '/api/projects/project-1/planning/initial'],
  ])
  assert.equal(bodyOf(calls[0]), undefined)
  assert.deepEqual(bodyOf(calls[1]), {
    expectedContractRevision: 1,
    idempotencyKey: 'planning-1',
  })
})

test('chapter session client separates session draft and explicit candidate writes', async () => {
  const calls = await captureRequests(async api => {
    await api.chapterSessions.current('project-1')
    await api.chapterSessions.create('project-1', {
      expectedStoryBlockRevision: 1,
      expectedCanonRevision: 0,
      apiKey: 'must-not-send',
    })
    await api.chapterSessions.saveWorkingDraft('project-1', 'session-1', {
      expectedRevision: 1,
      content: '正文',
      rawModelOutput: 'must-not-send',
    })
    await api.chapterSessions.saveCandidate('project-1', 'session-1', {
      expectedWorkingDraftRevision: 2,
      apiKey: 'must-not-send',
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/chapter-sessions/current'],
    ['POST', '/api/projects/project-1/chapter-sessions'],
    ['PUT', '/api/projects/project-1/chapter-sessions/session-1/working-draft'],
    ['POST', '/api/projects/project-1/chapter-sessions/session-1/candidates'],
  ])
  assert.equal(bodyOf(calls[0]), undefined)
  assert.deepEqual(bodyOf(calls[1]), {
    expectedStoryBlockRevision: 1,
    expectedCanonRevision: 0,
  })
  assert.deepEqual(bodyOf(calls[2]), {
    expectedRevision: 1,
    content: '正文',
  })
  assert.deepEqual(bodyOf(calls[3]), { expectedWorkingDraftRevision: 2 })
})

test('every shared client path segment is encoded without changing route structure', async () => {
  const calls = await captureRequests(async api => {
    await api.projects.get('project/one')
    await api.projects.contentState('project/one')
    await api.projects.update('project/one', {})
    await api.projects.delete('project/one')
    await api.providers.update('provider/one', {})
    await api.providers.delete('provider/one')
    await api.writerCore.state('project/one')
    await api.planning.get('project/one')
    await api.planning.createInitial('project/one', {
      expectedContractRevision: 1,
      idempotencyKey: 'planning-1',
    })
    await api.canon.head('project/one')
    await api.canon.entities('project/one', {
      apiKey: 'must-not-send', rawText: 'must-not-send', absolutePath: 'C:/must-not-send',
    })
    await api.canon.entity('project/one', 'entity/one')
    await api.canon.resolveAlias('project/one', '张 三/别名')
    await api.projections.head('project/one')
  })

  assert.deepEqual(calls.map(call => new URL(call.url).pathname), [
    '/api/projects/project%2Fone',
    '/api/projects/project%2Fone/content-state',
    '/api/projects/project%2Fone',
    '/api/projects/project%2Fone',
    '/api/providers/provider%2Fone',
    '/api/providers/provider%2Fone',
    '/api/projects/project%2Fone/writer-core/state',
    '/api/projects/project%2Fone/planning',
    '/api/projects/project%2Fone/planning/initial',
    '/api/projects/project%2Fone/canon/head',
    '/api/projects/project%2Fone/canon/entities',
    '/api/projects/project%2Fone/canon/entities/entity%2Fone',
    '/api/projects/project%2Fone/canon/aliases/resolve',
    '/api/projects/project%2Fone/projections/head',
  ])
  assert.equal(new URL(calls[12].url).searchParams.get('name'), '张 三/别名')
  assert.equal(new URL(calls[8].url).search, '')
})

test('project and provider writes use explicit transport allowlists', async () => {
  const calls = await captureRequests(async api => {
    await api.projects.create({
      title: 'Project', genre: '玄幻', description: 'Description',
      targetWords: 100000, targetChapters: 100,
      rawText: 'must-not-send', absolutePath: 'C:/must-not-send',
    })
    await api.providers.create({
      name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
      baseURL: 'https://provider.example/v1', apiKey: 'request-only-secret',
      enabled: true, debug: 'must-not-send', rawText: 'must-not-send',
    })
    await api.providers.update('provider-1', {
      name: '联通云', providerType: 'anthropic', apiKey: 'replacement-request-only-secret',
      baseURL: 'https://provider.example/v2', unexpected: 'must-not-send',
    })
  })

  assert.deepEqual(bodyOf(calls[0]), {
    title: 'Project', genre: '玄幻', description: 'Description',
    targetWords: 100000, targetChapters: 100,
  })
  assert.deepEqual(bodyOf(calls[1]), {
    name: '联通云', providerType: 'openai-compatible', model: 'deepseek-v4-flash',
    baseURL: 'https://provider.example/v1', apiKey: 'request-only-secret', enabled: true,
  })
  assert.deepEqual(bodyOf(calls[2]), {
    name: '联通云', baseURL: 'https://provider.example/v2',
    apiKey: 'replacement-request-only-secret',
  })
})

test('nested frozen DTOs discard secret and debug fields before transport', async () => {
  const seedPayload = {
    title: '典镇山河', genre: '历史穿越', logline: 'Logline', protagonist: 'Protagonist',
    desire: 'Desire', coreConflict: 'Conflict', worldPressure: 'Pressure',
    openingHook: 'Hook', differentiation: 'Different', apiKey: 'must-not-send',
  }
  const engineOption = {
    name: 'Engine', storyPromise: 'Promise', protagonistDesire: 'Desire',
    sustainedPressure: 'Pressure', growthDirection: 'Growth', conflictLoop: 'Loop',
    ensembleRoles: [{ role: 'Role', purpose: 'Purpose', baseURL: 'must-not-send' }],
    advantageAndCost: 'Cost', satisfactionSources: ['Source'],
    longFormVariation: ['Variation'], endingAnchor: 'Anchor', risks: ['Risk'],
    differentiation: 'Different', apiKey: 'must-not-send',
  }
  const ref = { id: 'asset-1', revision: 1, contentHash: 'a'.repeat(64), debug: 'must-not-send' }
  const draft = {
    schemaVersion: 'contract-draft-v2', draftStage: 'assets', engineOptionId: 'engine-1',
    engineHash: 'b'.repeat(64), channelProfileKey: 'qidian', genreProfileKey: 'xuanhuan',
    qualityCharterVersion: 'v1', totalWordRange: [1000000, 2000000],
    chapterCapacityPolicy: 'Manual chapter finalization', primaryStyleRef: ref,
    secondaryStyleRef: null, experienceCardRefs: [ref],
    corpusSourceRefs: [{ ...ref, selectionMode: 'author', rawText: 'must-not-send' }],
    likes: ['丰满'], dislikes: ['干巴'], apiKey: 'must-not-send',
  }
  const calls = await captureRequests(async api => {
    await api.seeds.create('project-1', seedPayload)
    await api.bindings.replace('project-1', {
      expectedRevision: 1,
      entries: [{ taskKey: 'seed', providerId: 'provider-1', apiKey: 'must-not-send' }],
    })
    await api.storyEngines.manual('project-1', {
      idempotencyKey: 'engine-manual-1',
      options: [engineOption, engineOption, engineOption],
    })
    await api.contracts.draft.save('project-1', { expectedDraftVersion: 0, draft })
  })

  assert.deepEqual(bodyOf(calls[0]).payload, {
    title: '典镇山河', genre: '历史穿越', logline: 'Logline', protagonist: 'Protagonist',
    desire: 'Desire', coreConflict: 'Conflict', worldPressure: 'Pressure',
    openingHook: 'Hook', differentiation: 'Different',
  })
  assert.deepEqual(bodyOf(calls[1]).entries, [{ taskKey: 'seed', providerId: 'provider-1' }])
  assert.deepEqual(bodyOf(calls[2]).options[0].ensembleRoles, [{ role: 'Role', purpose: 'Purpose' }])
  assert.equal(JSON.stringify(bodyOf(calls[2])).includes('must-not-send'), false)
  assert.equal(JSON.stringify(bodyOf(calls[3])).includes('must-not-send'), false)
  assert.deepEqual(bodyOf(calls[3]).draft.primaryStyleRef, {
    id: 'asset-1', revision: 1, contentHash: 'a'.repeat(64),
  })
})

test('progressive contract drafts preserve explicit null downstream fields', async () => {
  const draft = {
    schemaVersion: 'contract-draft-v2',
    draftStage: 'engine',
    engineOptionId: 'engine-1',
    engineHash: 'b'.repeat(64),
    channelProfileKey: 'qidian',
    genreProfileKey: 'xuanhuan',
    qualityCharterVersion: 'v1',
    totalWordRange: [1000000, 2000000],
    chapterCapacityPolicy: 'Manual chapter finalization',
    primaryStyleRef: null,
    secondaryStyleRef: null,
    experienceCardRefs: null,
    corpusSourceRefs: null,
    likes: null,
    dislikes: null,
  }

  const calls = await captureRequests(async api => {
    await api.contracts.draft.save('project-1', {
      expectedDraftVersion: 0,
      draft,
    })
  })

  assert.deepEqual(bodyOf(calls[0]), {
    expectedDraftVersion: 0,
    draft,
  })
})

test('corpus discovery rejects an oversized cursor before fetch', async () => {
  const calls = await captureRequests(async api => {
    assert.throws(() => api.corpus.discovery({ cursor: 'x'.repeat(4097) }), /cursor/i)
    await api.corpus.discovery({ cursor: 'x'.repeat(4096) })
  })
  assert.equal(calls.length, 1)
  assert.equal(new URL(calls[0].url).searchParams.get('cursor').length, 4096)
})
