import assert from 'node:assert/strict'
import test from 'node:test'

function jsonResponse(body = {}) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  })
}

async function captureRequests(run, responseFor = () => ({})) {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse(responseFor({ url: String(url), options }))
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

test('planning actual progress parser remains private to the client module', async () => {
  const client = await import('../../src/api/db/client.js')
  assert.equal(Object.hasOwn(client, 'planningActualProgressItem'), false)
  assert.equal(client.planningActualProgressItem, undefined)
})

function formalChapterOutlineState(overrides = {}) {
  return {
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: 1,
    targetPath: '/projects/project-1/write/chapters/1',
    planningAuthority: null,
    canonProjectionAuthority: null,
    confirmedOutline: null,
    draft: null,
    activeSession: null,
    pendingOperation: null,
    capabilities: {
      view: true,
      createDraft: true,
      editDraft: false,
      generate: false,
      confirm: false,
      startSession: false,
    },
    reasons: [],
    ...overrides,
  }
}

function formalChapterOutlineContent() {
  return {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: null,
    storyBlockRef: null,
    stageRefs: [],
    sceneTaskRefs: [],
    chapterGoal: '',
    expectedCharacters: [],
    continuation: [],
    plannedTasks: [],
    scenes: [],
    forbiddenEarlyEvents: [],
  }
}

function formalChapterOutlineBasis() {
  return {
    planningAuthority: {
      planningRevisionId: 'planning-r1',
      revision: 1,
      contentHash: 'a'.repeat(64),
      content: null,
    },
    canonProjectionAuthority: {
      canonRevision: 1,
      projectionRevision: 1,
      contentHash: 'b'.repeat(64),
      synchronized: true,
    },
  }
}

function formalChapterOutlineDraft(overrides = {}) {
  return {
    projectId: 'project-1',
    chapterNumber: 1,
    draftId: 'outline-draft-1',
    baseHeadRevision: 0,
    draftRevision: 1,
    contentHash: 'c'.repeat(64),
    content: formalChapterOutlineContent(),
    basis: formalChapterOutlineBasis(),
    status: 'current',
    ...overrides,
  }
}

function formalChapterOutlineRevision({
  includeDisplay = true,
  ...overrides
} = {}) {
  return {
    projectId: 'project-1',
    chapterNumber: 1,
    outlineRevisionId: 'outline-revision-1',
    revision: 1,
    parentRevision: 0,
    contentHash: 'c'.repeat(64),
    content: formalChapterOutlineContent(),
    basis: formalChapterOutlineBasis(),
    ...(includeDisplay
      ? { status: 'current', reason: 'currentOutlineHead' }
      : {}),
    ...overrides,
  }
}

const SENSITIVE_PLANNING_KEYS = [
  'sk-TestSentinel123456',
  'sk_TestSentinel123456',
  'ghp_TestSentinel12345678901234567890',
  'gho_TestSentinel12345678901234567890',
  'ghu_TestSentinel12345678901234567890',
  'ghs_TestSentinel12345678901234567890',
  'ghr_TestSentinel12345678901234567890',
  'github_pat_TestSentinel1234567890',
  'AKIAABCDEFGHIJKLMNOP',
  'ASIA1234567890ABCDEF',
  'AIzaTestSentinel12345678901234567890123',
  'Authorization-Bearer-TestSentinel',
  'bearer.TestSentinel',
  'apiKey-TestSentinel',
  'api_key.TestSentinel',
  'access-token-TestSentinel',
  'TOKEN-TestSentinel',
  'planning.secret.attempt',
  'PASSWORD:TestSentinel',
  'passwd-TestSentinel',
  'credential_TestSentinel',
  'DSN.TestSentinel',
  'planning%2Dencoded',
]

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

test('project lifecycle client uses narrow endpoints and CAS request bodies', async () => {
  const calls = await captureRequests(async api => {
    await api.projects.listActive()
    await api.projects.listArchived()
    await api.projects.create({
      title: '  典镇山河  ',
      genre: 'must-not-send',
      apiKey: 'must-not-send',
    })
    await api.projects.get('project/one')
    await api.projects.rename('project/one', {
      title: '山河新章',
      description: 'must-not-send',
    })
    await api.projects.archive('project/one', 3)
    await api.projects.restore('project/one', 4)
    await api.projects.permanentlyDelete('project/one', 5)
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects'],
    ['GET', '/api/projects/archived'],
    ['POST', '/api/projects'],
    ['GET', '/api/projects/project%2Fone'],
    ['PUT', '/api/projects/project%2Fone'],
    ['POST', '/api/projects/project%2Fone/archive'],
    ['POST', '/api/projects/project%2Fone/restore'],
    ['DELETE', '/api/projects/project%2Fone'],
  ])
  assert.equal(bodyOf(calls[0]), undefined)
  assert.equal(bodyOf(calls[1]), undefined)
  assert.deepEqual(bodyOf(calls[2]), { title: '  典镇山河  ' })
  assert.equal(bodyOf(calls[3]), undefined)
  assert.deepEqual(bodyOf(calls[4]), { title: '山河新章' })
  assert.deepEqual(bodyOf(calls[5]), { expectedLifecycleRevision: 3 })
  assert.deepEqual(bodyOf(calls[6]), { expectedLifecycleRevision: 4 })
  assert.deepEqual(bodyOf(calls[7]), { expectedLifecycleRevision: 5 })
  assert.equal(new URL(calls[7].url).search, '')
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

test('asset catalog reads and recommendation writes use the formal narrow contract', async () => {
  const calls = await captureRequests(async api => {
    await api.assets.styleTemplates.list()
    await api.assets.styleTemplates.get('style/revision')
    await api.assets.experienceCards.list({ category: 'dialogue craft' })
    await api.assets.experienceCards.get('card/revision')
    await api.assets.recommendations('project-1', {
      idempotencyKey: 'i'.repeat(64),
      engineOptionId: 'engine option',
      taxonomyVersion: 'recommendation-taxonomy-v1.0.0',
      taxonomyHash: 'a'.repeat(64),
      genre: 'fantasy',
      creationStage: 'drafting',
      prohibitedDirections: ['slow_burn'],
      status: 'active',
      apiKey: 'must-not-send',
      channels: ['must-not-send'],
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/assets/style-templates'],
    ['GET', '/api/assets/style-templates/style%2Frevision'],
    ['GET', '/api/assets/experience-cards'],
    ['GET', '/api/assets/experience-cards/card%2Frevision'],
    ['POST', '/api/projects/project-1/asset-recommendations'],
  ])
  assert.equal(new URL(calls[2].url).searchParams.get('category'), 'dialogue craft')
  assert.equal(new URL(calls[4].url).search, '')
  assert.deepEqual(bodyOf(calls[4]), {
    idempotencyKey: 'i'.repeat(64),
    engineOptionId: 'engine option',
    taxonomyVersion: 'recommendation-taxonomy-v1.0.0',
    taxonomyHash: 'a'.repeat(64),
    genre: 'fantasy',
    creationStage: 'drafting',
    status: 'active',
    prohibitedDirections: ['slow_burn'],
  })
  assert.equal(calls.slice(0, 4).every(call => !('body' in call.options)), true)
})

test('corpus client stays relative-path-only and enforces preview bounds', async () => {
  const calls = await captureRequests(async api => {
    await api.corpus.discovery({ cursor: 'next item', limit: 999 })
    await api.corpus.imports.create({
      idempotencyKey: 'corpus-import-key-0001',
      relativePath: '玄幻/样本.txt',
      sourceId: 'source-1',
      createDistinctSource: false,
      displayName: '北境卷',
      referenceTags: ['玄幻', '战争'],
      notes: '受控短注',
      root: 'C:/private',
      rawText: 'full novel must not send',
    })
    await api.corpus.imports.get('import-1')
    await api.corpus.sources.list({ search: '北境', state: 'archived' })
    await api.corpus.sources.get('source-1', { previewChars: 99999 })
    await api.corpus.sources.versions('source-1', { cursor: 7, limit: 999 })
    await api.corpus.sources.archive('source-1', 3)
    await api.corpus.sources.restore('source-1', 3)
    await api.corpus.sources.permanentlyDelete('source-1', 3, true)
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
    ['GET', '/api/corpus/sources/source-1/versions'],
    ['POST', '/api/corpus/sources/source-1/archive'],
    ['POST', '/api/corpus/sources/source-1/restore'],
    ['DELETE', '/api/corpus/sources/source-1'],
    ['GET', '/api/corpus/sources/source-1/chapters'],
    ['GET', '/api/corpus/chapters/chapter-1/fragments'],
  ])
  assert.equal(new URL(calls[0].url).searchParams.get('cursor'), 'next item')
  assert.equal(new URL(calls[0].url).searchParams.get('limit'), '200')
  assert.deepEqual(bodyOf(calls[1]), {
    idempotencyKey: 'corpus-import-key-0001',
    relativePath: '玄幻/样本.txt',
    sourceId: 'source-1',
    createDistinctSource: false,
    displayName: '北境卷',
    referenceTags: ['玄幻', '战争'],
    notes: '受控短注',
  })
  assert.equal(new URL(calls[3].url).searchParams.get('search'), '北境')
  assert.equal(new URL(calls[3].url).searchParams.get('state'), 'archived')
  assert.equal(new URL(calls[4].url).searchParams.get('previewChars'), '1200')
  assert.equal(new URL(calls[5].url).searchParams.get('cursor'), '7')
  assert.equal(new URL(calls[5].url).searchParams.get('limit'), '100')
  assert.deepEqual(bodyOf(calls[6]), { expectedRevision: 3 })
  assert.deepEqual(bodyOf(calls[7]), { expectedRevision: 3 })
  assert.deepEqual(bodyOf(calls[8]), {
    expectedRevision: 3,
    confirmPermanentDelete: true,
  })
  assert.equal(new URL(calls[10].url).searchParams.get('cursor'), '5')
  assert.equal(new URL(calls[10].url).searchParams.get('limit'), '20')

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
    await api.contracts.history('project-1', { limit: 20, beforeRevision: 81 })
    await api.contracts.clone('project-1', 4)
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/contract-draft'],
    ['PUT', '/api/projects/project-1/contract-draft'],
    ['POST', '/api/projects/project-1/contracts/preview'],
    ['POST', '/api/projects/project-1/contracts/confirm'],
    ['GET', '/api/projects/project-1/contracts/head'],
    ['GET', '/api/projects/project-1/contracts/history'],
    ['POST', '/api/projects/project-1/contracts/4/clone'],
  ])
  assert.deepEqual(bodyOf(calls[1]), { expectedDraftVersion: 3, draft })
  assert.equal(bodyOf(calls[2]), undefined)
  assert.deepEqual(bodyOf(calls[3]), {
    idempotencyKey: 'contract-confirm-1',
    expectedDraftVersion: 4,
    expectedDraftHash: 'a'.repeat(64),
  })
  assert.equal(new URL(calls[5].url).searchParams.get('limit'), '20')
  assert.equal(new URL(calls[5].url).searchParams.get('beforeRevision'), '81')
  assert.equal(bodyOf(calls[6]), undefined)
})

test('style trials use only the strict backend gateway payload', async () => {
  const command = {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
    apiKey: 'must-not-send',
    prompt: 'must-not-send',
    baseURL: 'must-not-send',
  }
  const calls = await captureRequests(async api => {
    await api.styleTrials.generate('project-1', command)
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['POST', '/api/projects/project-1/style-trials'],
  ])
  assert.deepEqual(bodyOf(calls[0]), {
    selectionRevision: 3,
    engineOptionId: 'engine-1',
    engineHash: 'a'.repeat(64),
    primaryStyleRevisionId: 'style-primary',
    primaryStyleHash: 'b'.repeat(64),
    secondaryStyleRevisionId: null,
    secondaryStyleHash: null,
    authorScenario: '主角必须在救人和守住秘密之间做选择。',
    idempotencyKey: 'i'.repeat(64),
  })
  assert.equal(JSON.stringify(calls).includes('must-not-send'), false)
})

test('planning client uses revisioned aggregate paths and strict write allowlists', async () => {
  const calls = await captureRequests(async api => {
    await api.planning.get('project/1')
    await api.planning.history('project/1')
    await api.planning.createDraft('project/1', {
      idempotencyKey: 'planning-create-1',
      apiKey: 'must-not-send',
      rawText: 'must-not-send',
    })
    await api.planning.saveDraft('project/1', 'draft/1', {
      expectedDraftRevision: 2,
      expectedDraftHash: 'a'.repeat(64),
      content: {
        activeStoryBlockRef: null,
        volumes: [],
        plots: [],
        storyBlocks: [],
      },
      idempotencyKey: 'planning-save-1',
      apiKey: 'must-not-send',
      rawText: 'must-not-send',
    })
    await api.planning.confirmDraft('project/1', 'draft/1', {
      expectedDraftRevision: 3,
      expectedDraftHash: 'b'.repeat(64),
      idempotencyKey: 'planning-confirm-1',
      apiKey: 'must-not-send',
      rawText: 'must-not-send',
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project%2F1/planning'],
    ['GET', '/api/projects/project%2F1/planning/history'],
    ['POST', '/api/projects/project%2F1/planning/drafts'],
    ['PUT', '/api/projects/project%2F1/planning/drafts/draft%2F1'],
    ['POST', '/api/projects/project%2F1/planning/drafts/draft%2F1/confirm'],
  ])
  assert.equal(bodyOf(calls[0]), undefined)
  assert.equal(bodyOf(calls[1]), undefined)
  assert.deepEqual(bodyOf(calls[2]), {
    idempotencyKey: 'planning-create-1',
  })
  assert.deepEqual(bodyOf(calls[3]), {
    expectedDraftRevision: 2,
    expectedDraftHash: 'a'.repeat(64),
    content: {
      activeStoryBlockRef: null,
      volumes: [],
      plots: [],
      storyBlocks: [],
    },
    idempotencyKey: 'planning-save-1',
  })
  assert.deepEqual(bodyOf(calls[4]), {
    expectedDraftRevision: 3,
    expectedDraftHash: 'b'.repeat(64),
    idempotencyKey: 'planning-confirm-1',
  })
  assert.equal(JSON.stringify(calls).includes('must-not-send'), false)
})

test('planning GET closes formal Canon actual progress to its six public fields', async () => {
  const originalFetch = global.fetch
  try {
    global.fetch = async () => jsonResponse({
      projectId: 'project-1',
      actualProgress: [{
        revisionNumber: 3,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'plot.gunpowder',
        value: {
          status: 'old',
          evidence: ['第一章', { chapter: 1, active: true }],
        },
        contentHash: 'b'.repeat(64),
        apiKey: 'must-not-reach-planning-state',
        privateReasoning: 'must-not-reach-planning-state',
      }, {
        revisionNumber: 3,
        subjectKey: 'plot-thread',
        entityId: 'thread-1',
        fieldPath: 'plot.gunpowder',
        value: ['已埋下', { chapter: 2 }],
        contentHash: 'b'.repeat(64),
      }],
      canonProjectionStatus: {
        canonRevision: 3,
        projectionRevision: 3,
        contentHash: 'b'.repeat(64),
        synchronized: true,
      },
    })
    const { api } = await import('../../src/api/db/client.js')

    const state = await api.planning.get('project-1')

    assert.deepEqual(state.actualProgress, [{
      revisionNumber: 3,
      subjectKey: '__global__',
      entityId: null,
      fieldPath: 'plot.gunpowder',
      value: {
        status: 'old',
        evidence: ['第一章', { chapter: 1, active: true }],
      },
      contentHash: 'b'.repeat(64),
    }, {
      revisionNumber: 3,
      subjectKey: 'plot-thread',
      entityId: 'thread-1',
      fieldPath: 'plot.gunpowder',
      value: ['已埋下', { chapter: 2 }],
      contentHash: 'b'.repeat(64),
    }])
    assert.equal(JSON.stringify(state.actualProgress).includes('must-not-reach'), false)
    global.fetch = async () => jsonResponse({
      actualProgress: [{
        revisionNumber: 3,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'plot.\na',
        value: null,
        contentHash: 'b'.repeat(64),
      }],
    })
    const newlinePath = await api.planning.get('project-1')
    assert.equal(newlinePath.actualProgress[0].fieldPath, 'plot.\na')

    global.fetch = async () => jsonResponse({
      projectId: 'project-1',
      actualProgress: [{
        revisionNumber: 0,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'plot.gunpowder',
        value: null,
        contentHash: 'a'.repeat(64),
      }],
    })
    await assert.rejects(
      api.planning.get('project-1'),
      /Invalid Planning actual progress response/i,
    )
    global.fetch = async () => jsonResponse({
      actualProgress: [{
        revisionNumber: 1,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'chapter.gunpowder',
        value: false,
        contentHash: 'a'.repeat(64),
      }],
    })
    await assert.rejects(
      api.planning.get('project-1'),
      /Invalid Planning actual progress response/i,
    )
    global.fetch = async () => jsonResponse({
      actualProgress: [{
        revisionNumber: 1,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'plot.',
        value: 1,
        contentHash: 'a'.repeat(64),
      }],
    })
    await assert.rejects(
      api.planning.get('project-1'),
      /Invalid Planning actual progress response/i,
    )
    global.fetch = async () => jsonResponse({
      actualProgress: [{
        revisionNumber: 1,
        subjectKey: '__global__',
        entityId: null,
        fieldPath: 'plot.gunpowder',
        value: true,
        contentHash: 'A'.repeat(64),
      }],
    })
    await assert.rejects(
      api.planning.get('project-1'),
      /Invalid Planning actual progress response/i,
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('planning generation uses encoded paths and closed request and response DTOs', async () => {
  const originalFetch = global.fetch
  const calls = []
  const secret = 'sk-must-not-cross-planning-client'
  const operationId = '123e4567-e89b-12d3-a456-426614174000'
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse({
      operationId,
      status: 'succeeded',
      failureCode: null,
      model: {
        providerId: 'provider-1',
        modelName: 'deepseek-v4-flash',
        apiKey: secret,
        runtime: { baseURL: `https://${secret}@provider.invalid` },
      },
      loaded: true,
      loadedDraftRevision: 3,
      provider: { apiKey: secret },
      prompt: secret,
      rawOutput: secret,
      manifest: { secret },
      dsn: `mysql://root:${secret}@database/novel`,
    })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    const generated = await api.planning.generateDraft(
      'project/1',
      'draft/1',
      {
        draftRevision: 2,
        draftHash: 'a'.repeat(64),
        idempotencyKey: 'planning-generate-1',
        authorInstructions: '加强群像冲突',
        provider: { apiKey: secret },
        model: secret,
        prompt: secret,
        rawOutput: secret,
        manifest: { secret },
        dsn: secret,
      },
    )
    const queried = await api.planning.getOperation('project/1', operationId)
    const recovered = await api.planning.getOperationByIdempotencyKey(
      'project/1',
      'planning:generate:1',
    )

    assert.deepEqual(calls.map(call => [
      call.options.method,
      new URL(call.url).pathname,
    ]), [
      ['POST', '/api/projects/project%2F1/planning/drafts/draft%2F1/generate'],
      ['GET', `/api/projects/project%2F1/planning/operations/${operationId}`],
      [
        'GET',
        '/api/projects/project%2F1/planning/operations/by-idempotency-key/planning%3Agenerate%3A1',
      ],
    ])
    assert.deepEqual(bodyOf(calls[0]), {
      draftRevision: 2,
      draftHash: 'a'.repeat(64),
      idempotencyKey: 'planning-generate-1',
      authorInstructions: '加强群像冲突',
    })
    assert.equal(bodyOf(calls[1]), undefined)
    assert.equal(bodyOf(calls[2]), undefined)
    const expected = {
      operationId,
      status: 'succeeded',
      failureCode: null,
      model: {
        providerId: 'provider-1',
        modelName: 'deepseek-v4-flash',
      },
      loaded: true,
      loadedDraftRevision: 3,
    }
    assert.deepEqual(generated, expected)
    assert.deepEqual(queried, expected)
    assert.deepEqual(recovered, expected)
    assert.equal(
      JSON.stringify({ generated, queried, recovered }).includes(secret),
      false,
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('planning generation POST uses a model-length timeout and operation GET stays default', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const delays = []
  global.setTimeout = (callback, delay, ...args) => {
    delays.push(delay)
    return originalSetTimeout(callback, delay, ...args)
  }
  global.fetch = async () => jsonResponse({
    operationId: '123e4567-e89b-12d3-a456-426614174000',
    status: 'pending',
    failureCode: null,
    model: { providerId: 'provider-1', modelName: 'deepseek-v4-flash' },
    loaded: false,
    loadedDraftRevision: null,
  })

  try {
    const { api } = await import('../../src/api/db/client.js')
    await api.planning.generateDraft('project-1', 'draft-1', {
      draftRevision: 1,
      draftHash: 'a'.repeat(64),
      idempotencyKey: 'timeout-contract',
      authorInstructions: '',
    })
    await api.planning.getOperation(
      'project-1',
      '123e4567-e89b-12d3-a456-426614174000',
    )

    assert.equal(delays.length, 2)
    assert.ok(delays[0] >= 180_000)
    assert.notEqual(delays[0], 30_000)
    assert.equal(delays[1], 30_000)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
  }
})

test('planning by-key recovery validates the closed idempotency key before GET', async () => {
  const originalFetch = global.fetch
  let calls = 0
  global.fetch = async () => {
    calls += 1
    return jsonResponse()
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const key of ['', 'bad/key', 'bad key', 'x'.repeat(65)]) {
      await assert.rejects(
        api.planning.getOperationByIdempotencyKey('project-1', key),
        /invalid planning idempotency key/i,
      )
    }
    assert.equal(calls, 0)
  } finally {
    global.fetch = originalFetch
  }
})

test('planning generation and recovery reject sensitive keys before body, URL or fetch', async () => {
  const originalFetch = global.fetch
  let calls = 0
  global.fetch = async () => {
    calls += 1
    return jsonResponse()
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const key of SENSITIVE_PLANNING_KEYS) {
      for (const request of [
        () => api.planning.generateDraft('project-1', 'draft-1', {
          draftRevision: 1,
          draftHash: 'a'.repeat(64),
          idempotencyKey: key,
          authorInstructions: '',
        }),
        () => api.planning.getOperationByIdempotencyKey('project-1', key),
      ]) {
        await assert.rejects(request(), error => {
          assert.equal(error.message, 'Invalid Planning idempotency key')
          assert.equal(String(error).includes(key), false)
          return true
        })
      }
    }
    assert.equal(calls, 0)
  } finally {
    global.fetch = originalFetch
  }
})

test('planning operation response fails closed with a fixed secret-safe error', async () => {
  const originalFetch = global.fetch
  const secret = 'sk-malicious-operation-response'
  global.fetch = async () => jsonResponse({
    operationId: 'operation-1',
    status: 'invented',
    failureCode: secret,
    model: { providerId: secret, modelName: secret },
    loaded: true,
    loadedDraftRevision: null,
    rawOutput: secret,
  })

  try {
    const { api } = await import('../../src/api/db/client.js')
    await assert.rejects(
      api.planning.getOperation('project-1', 'operation-1'),
      error => {
        assert.match(error.message, /invalid planning operation response/i)
        assert.equal(String(error).includes(secret), false)
        return true
      },
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('planning operation model summary fail-closes encoded credential text', async () => {
  const originalFetch = global.fetch
  const unsafeModels = [
    `ghp_${'A'.repeat(20)}`,
    `AKIA${'A'.repeat(16)}`,
    'Authoriza%2574ion%253ABearer%2520DOUBLE_ENCODED_SECRET',
    'https%253A%252F%252Froot%253Apassword%2540provider.invalid%252Fv1',
    'Authorization%25253ABearer%252520TOO_DEEPLY_ENCODED_SECRET',
  ]
  let currentProvider = 'provider-1'
  let currentModel = unsafeModels[0]
  global.fetch = async () => jsonResponse({
    operationId: 'operation-1',
    status: 'pending',
    failureCode: null,
    model: { providerId: currentProvider, modelName: currentModel },
    loaded: false,
    loadedDraftRevision: null,
  })

  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const unsafe of unsafeModels) {
      currentModel = unsafe
      const getResult = await api.planning.getOperation('project-1', 'operation-1')
      const postResult = await api.planning.generateDraft('project-1', 'draft-1', {
        draftRevision: 1,
        draftHash: 'a'.repeat(64),
        idempotencyKey: `unsafe-${unsafeModels.indexOf(unsafe)}`,
        authorInstructions: '',
      })
      for (const result of [getResult, postResult]) {
        assert.deepEqual(result.model, {
          providerId: 'unavailable',
          modelName: 'unavailable',
        })
        assert.equal(JSON.stringify(result).includes(unsafe), false)
      }
    }

    for (const safe of ['deepseek-v4-flash', 'model+preview', 'model preview']) {
      currentProvider = 'provider-1'
      currentModel = safe
      const result = await api.planning.getOperation('project-1', 'operation-1')
      assert.deepEqual(result.model, {
        providerId: 'provider-1',
        modelName: safe,
      })
    }

    currentProvider = `ASIA${'Z'.repeat(16)}`
    currentModel = 'deepseek-v4-flash'
    const unsafeProvider = await api.planning.getOperation(
      'project-1',
      'operation-1',
    )
    assert.deepEqual(unsafeProvider.model, {
      providerId: 'unavailable',
      modelName: 'unavailable',
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('planning operation ids are closed opaque values before any GET', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse({
      operationId: 'operation-1',
      status: 'pending',
      failureCode: null,
      model: { providerId: 'provider-1', modelName: 'deepseek-v4-flash' },
      loaded: false,
      loadedDraftRevision: null,
    })
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const unsafeId of [
      'operation%252Fsecret',
      'https://root:password@provider.invalid/operation',
      `ghp_${'A'.repeat(20)}`,
      `ASIA${'A'.repeat(16)}`,
      'operation/token',
    ]) {
      await assert.rejects(
        api.planning.getOperation('project-1', unsafeId),
        /invalid planning operation id/i,
      )
    }
    assert.equal(calls.length, 0)

    const uuid = '123e4567-e89b-12d3-a456-426614174000'
    global.fetch = async (url, options) => {
      calls.push({ url: String(url), options })
      return jsonResponse({
        operationId: uuid,
        status: 'pending',
        failureCode: null,
        model: { providerId: 'provider-1', modelName: 'deepseek-v4-flash' },
        loaded: false,
        loadedDraftRevision: null,
      })
    }
    const result = await api.planning.getOperation('project-1', uuid)
    assert.equal(result.operationId, uuid)
    assert.equal(calls.length, 1)
  } finally {
    global.fetch = originalFetch
  }
})

test('a POST response with a sensitive operation id fails closed safely', async () => {
  const originalFetch = global.fetch
  const secretId = `ghp_${'B'.repeat(20)}`
  global.fetch = async () => jsonResponse({
    operationId: secretId,
    status: 'pending',
    failureCode: null,
    model: { providerId: 'provider-1', modelName: 'deepseek-v4-flash' },
    loaded: false,
    loadedDraftRevision: null,
  })

  try {
    const { api } = await import('../../src/api/db/client.js')
    await assert.rejects(
      api.planning.generateDraft('project-1', 'draft-1', {
        draftRevision: 1,
        draftHash: 'a'.repeat(64),
        idempotencyKey: 'sensitive-operation-id',
        authorInstructions: '',
      }),
      error => {
        assert.match(error.message, /invalid planning operation response/i)
        assert.equal(String(error).includes(secretId), false)
        return true
      },
    )
  } finally {
    global.fetch = originalFetch
  }
})

test('planning save recursively allows only the closed draft DTO fields', async () => {
  const calls = await captureRequests(async api => {
    await api.planning.saveDraft('project-1', 'draft-1', {
      expectedDraftRevision: 1,
      expectedDraftHash: 'a'.repeat(64),
      idempotencyKey: 'planning-save-deep',
      content: {
        activeStoryBlockRef: 'block-1',
        apiKey: 'must-not-send',
        volumes: [{
          id: 'volume-1',
          revision: 1,
          contentHash: 'b'.repeat(64),
          lifecycle: 'active',
          order: 1,
          title: '第一卷',
          coreChange: '站稳脚跟',
          mainPressure: '追兵迫近',
          ensembleFocus: ['主角'],
          forbiddenEvents: [],
          rawOutput: 'must-not-send',
        }],
        plots: [{
          clientNodeKey: 'plot-new',
          lifecycle: 'active',
          order: 1,
          title: '立足',
          plotType: 'main',
          storyQuestion: '如何脱险',
          futureDirection: '转守为攻',
          expectedPayoff: '建立据点',
          relatedCharacters: ['主角'],
          debug: 'must-not-send',
        }],
        storyBlocks: [{
          id: 'block-1',
          revision: 1,
          contentHash: 'c'.repeat(64),
          lifecycle: 'active',
          order: 1,
          title: '夜渡',
          volumeRef: 'volume-1',
          plotRefs: ['plot-new'],
          entrySituation: '受困',
          blockGoal: '穿过封锁',
          mainPressure: '追兵合围',
          expectedChange: '建立信任',
          openQuestions: [],
          involvedCharacters: ['主角'],
          targetChapterCount: 3,
          providerId: 'must-not-send',
          stages: [{
            clientNodeKey: 'stage-new',
            lifecycle: 'active',
            order: 1,
            title: '找缺口',
            purpose: '观察换岗',
            dramaticQuestion: '能否及时脱身',
            completed: true,
            apiKey: 'must-not-send',
            sceneTasks: [{
              clientNodeKey: 'task-new',
              lifecycle: 'active',
              order: 1,
              task: '记录巡逻',
              completionEvidence: '获得换岗间隔',
              actualProgress: 1,
              rawOutput: 'must-not-send',
            }],
          }],
        }],
      },
    })
  })

  const body = bodyOf(calls[0])
  assert.deepEqual(body.content, {
    activeStoryBlockRef: 'block-1',
    volumes: [{
      id: 'volume-1',
      revision: 1,
      contentHash: 'b'.repeat(64),
      lifecycle: 'active',
      order: 1,
      title: '第一卷',
      coreChange: '站稳脚跟',
      mainPressure: '追兵迫近',
      ensembleFocus: ['主角'],
      forbiddenEvents: [],
    }],
    plots: [{
      clientNodeKey: 'plot-new',
      lifecycle: 'active',
      order: 1,
      title: '立足',
      plotType: 'main',
      storyQuestion: '如何脱险',
      futureDirection: '转守为攻',
      expectedPayoff: '建立据点',
      relatedCharacters: ['主角'],
    }],
    storyBlocks: [{
      id: 'block-1',
      revision: 1,
      contentHash: 'c'.repeat(64),
      lifecycle: 'active',
      order: 1,
      title: '夜渡',
      volumeRef: 'volume-1',
      plotRefs: ['plot-new'],
      entrySituation: '受困',
      blockGoal: '穿过封锁',
      mainPressure: '追兵合围',
      expectedChange: '建立信任',
      openQuestions: [],
      involvedCharacters: ['主角'],
      stages: [{
        clientNodeKey: 'stage-new',
        lifecycle: 'active',
        order: 1,
        title: '找缺口',
        purpose: '观察换岗',
        dramaticQuestion: '能否及时脱身',
        sceneTasks: [{
          clientNodeKey: 'task-new',
          lifecycle: 'active',
          order: 1,
          task: '记录巡逻',
          completionEvidence: '获得换岗间隔',
        }],
      }],
    }],
  })
  const serialized = JSON.stringify(body)
  assert.equal(serialized.includes('must-not-send'), false)
  for (const field of ['targetChapterCount', 'completed', 'actualProgress']) {
    assert.equal(serialized.includes(`"${field}"`), false)
  }
})

test('chapter session client separates session draft and explicit candidate writes', async () => {
  const calls = await captureRequests(async api => {
    await api.chapterSessions.get('project-1', 1)
    await api.chapterSessions.create('project-1', 1, {
      chapterNumber: 1,
      expectedPlanningRevision: 1,
      expectedPlanningHash: 'a'.repeat(64),
      expectedOutlineRevision: 3,
      expectedOutlineHash: 'c'.repeat(64),
      expectedCanonRevision: 0,
      apiKey: 'must-not-send',
    })
    await api.chapterSessions.saveWorkingDraft('project-1', 'session-1', {
      expectedRevision: 1,
      expectedContentHash: 'a'.repeat(64),
      content: '正文',
      rawModelOutput: 'must-not-send',
    })
    await api.chapterSessions.saveCandidate('project-1', 'session-1', {
      expectedWorkingDraftRevision: 3,
      expectedContentHash: 'b'.repeat(64),
      idempotencyKey: '11111111-1111-1111-1111-111111111111',
      apiKey: 'must-not-send',
      provider: 'must-not-send',
    })
  })

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project-1/chapter-sessions/1'],
    ['POST', '/api/projects/project-1/chapter-sessions/1'],
    ['PUT', '/api/projects/project-1/chapter-sessions/session-1/working-draft'],
    ['POST', '/api/projects/project-1/chapter-sessions/session-1/candidates'],
  ])
  assert.equal(bodyOf(calls[0]), undefined)
  assert.deepEqual(bodyOf(calls[1]), {
    chapterNumber: 1,
    expectedPlanningRevision: 1,
    expectedPlanningHash: 'a'.repeat(64),
    expectedOutlineRevision: 3,
    expectedOutlineHash: 'c'.repeat(64),
    expectedCanonRevision: 0,
  })
  assert.deepEqual(bodyOf(calls[2]), {
    expectedRevision: 1,
    expectedContentHash: 'a'.repeat(64),
    content: '正文',
  })
  assert.deepEqual(bodyOf(calls[3]), {
    expectedWorkingDraftRevision: 3,
    expectedContentHash: 'b'.repeat(64),
    idempotencyKey: '11111111-1111-1111-1111-111111111111',
  })
})

test('draft operation client uses only formal routes, strict bodies, and closed public DTOs', async () => {
  const originalFetch = global.fetch
  const calls = []
  const projectId = '11111111-1111-4111-8111-111111111111'
  const sessionId = '22222222-2222-4222-8222-222222222222'
  const operationId = '33333333-3333-4333-8333-333333333333'
  const key = '44444444-4444-4444-8444-444444444444'
  const hash = 'a'.repeat(64)
  const secret = 'MUST-NOT-CROSS-DRAFT-OPERATION'
  const operation = {
    operationId,
    projectId,
    chapterSessionId: sessionId,
    operationType: 'generate_new',
    status: 'completed',
    lastEventSequence: 2,
    resultWorkingDraftRevision: 5,
    resultContentHash: hash,
    failureCode: null,
    providerId: 'provider-1',
    modelName: 'writer-model',
    prompt: secret,
    provider: { apiKey: secret },
  }
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    if (new URL(url).pathname.endsWith('/events')) {
      return jsonResponse({
        operationId,
        events: [{
          sequence: 1,
          type: 'started',
          createdAt: 1,
          responseBody: secret,
        }, {
          sequence: 2,
          type: 'completed',
          createdAt: 2,
          resultWorkingDraftRevision: 5,
          resultContentHash: hash,
          messages: secret,
        }],
        debug: true,
      })
    }
    return jsonResponse(operation)
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    const command = {
      operationType: 'generate_new',
      expectedWorkingDraftRevision: 4,
      expectedContentHash: hash,
      idempotencyKey: key,
      authorInstruction: '多一点人物试探',
    }
    const created = await api.chapterSessions.createDraftOperation(
      projectId, sessionId, command,
    )
    const read = await api.chapterSessions.readDraftOperation(
      projectId, sessionId, operationId,
    )
    const events = await api.chapterSessions.listDraftOperationEvents(
      projectId, sessionId, operationId, 0,
    )

    assert.deepEqual(calls.map(call => [
      call.options.method,
      new URL(call.url).pathname + new URL(call.url).search,
    ]), [
      ['POST', `/api/projects/${projectId}/chapter-sessions/${sessionId}/draft-operations`],
      ['GET', `/api/projects/${projectId}/chapter-sessions/${sessionId}/draft-operations/${operationId}`],
      ['GET', `/api/projects/${projectId}/chapter-sessions/${sessionId}/draft-operations/${operationId}/events?after=0`],
    ])
    assert.deepEqual(bodyOf(calls[0]), command)
    const expectedOperation = {
      operationId,
      projectId,
      chapterSessionId: sessionId,
      operationType: 'generate_new',
      status: 'completed',
      lastEventSequence: 2,
      resultWorkingDraftRevision: 5,
      resultContentHash: hash,
      failureCode: null,
      providerId: 'provider-1',
      modelName: 'writer-model',
    }
    assert.deepEqual(created, expectedOperation)
    assert.deepEqual(read, expectedOperation)
    assert.deepEqual(events, {
      operationId,
      events: [{ sequence: 1, type: 'started', createdAt: 1 }, {
        sequence: 2,
        type: 'completed',
        createdAt: 2,
        resultWorkingDraftRevision: 5,
        resultContentHash: hash,
      }],
    })
    assert.equal(JSON.stringify({ created, read, events }).includes(secret), false)
    assert.equal(Object.hasOwn(api.chapterSessions, 'generateWorkingDraft'), false)
  } finally {
    global.fetch = originalFetch
  }
})

test('draft operation client rejects malformed commands, identifiers, cursors, and deep sensitive keys before fetch', async () => {
  const originalFetch = global.fetch
  let calls = 0
  global.fetch = async () => {
    calls += 1
    return jsonResponse()
  }
  const projectId = '11111111-1111-4111-8111-111111111111'
  const sessionId = '22222222-2222-4222-8222-222222222222'
  const operationId = '33333333-3333-4333-8333-333333333333'
  const command = {
    operationType: 'generate_new',
    expectedWorkingDraftRevision: 1,
    expectedContentHash: 'a'.repeat(64),
    idempotencyKey: '44444444-4444-4444-8444-444444444444',
    authorInstruction: '',
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const invalid of [
      { ...command, expectedWorkingDraftRevision: true },
      { ...command, expectedContentHash: 'A'.repeat(64) },
      { ...command, idempotencyKey: '44444444-4444-4444-8444-44444444444A' },
      { ...command, authorInstruction: 'x'.repeat(2001) },
      { ...command, prompt: { messages: [{ provider: { apiKey: 'secret' } }] } },
    ]) {
      await assert.rejects(
        () => api.chapterSessions.createDraftOperation(projectId, sessionId, invalid),
        TypeError,
      )
    }
    for (const invalidRequest of [
      () => api.chapterSessions.createDraftOperation('project/1', sessionId, command),
      () => api.chapterSessions.readDraftOperation(projectId, sessionId, 'not-a-uuid'),
      () => api.chapterSessions.listDraftOperationEvents(projectId, sessionId, operationId, -1),
      () => api.chapterSessions.listDraftOperationEvents(projectId, sessionId, operationId, 2147483648),
      () => api.chapterSessions.listDraftOperationEvents(projectId, sessionId, operationId, true),
    ]) await assert.rejects(invalidRequest(), TypeError)
    assert.equal(calls, 0)
  } finally {
    global.fetch = originalFetch
  }
})

test('every shared client path segment is encoded without changing route structure', async () => {
  const calls = await captureRequests(async api => {
    await api.projects.get('project/one')
    await api.projects.rename('project/one', { title: 'Renamed' })
    await api.projects.archive('project/one', 1)
    await api.projects.restore('project/one', 2)
    await api.projects.permanentlyDelete('project/one', 3)
    await api.providers.update('provider/one', {})
    await api.providers.delete('provider/one')
    await api.writerCore.state('project/one')
    await api.planning.get('project/one')
    await api.planning.history('project/one')
    await api.planning.createDraft('project/one', {
      idempotencyKey: 'planning-1',
    })
    await api.planning.saveDraft('project/one', 'draft/one', {
      expectedDraftRevision: 1,
      expectedDraftHash: 'a'.repeat(64),
      content: {
        activeStoryBlockRef: null,
        volumes: [],
        plots: [],
        storyBlocks: [],
      },
      idempotencyKey: 'planning-save-1',
    })
    await api.planning.confirmDraft('project/one', 'draft/one', {
      expectedDraftRevision: 2,
      expectedDraftHash: 'b'.repeat(64),
      idempotencyKey: 'planning-confirm-1',
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
    '/api/projects/project%2Fone',
    '/api/projects/project%2Fone/archive',
    '/api/projects/project%2Fone/restore',
    '/api/projects/project%2Fone',
    '/api/providers/provider%2Fone',
    '/api/providers/provider%2Fone',
    '/api/projects/project%2Fone/writer-core/state',
    '/api/projects/project%2Fone/planning',
    '/api/projects/project%2Fone/planning/history',
    '/api/projects/project%2Fone/planning/drafts',
    '/api/projects/project%2Fone/planning/drafts/draft%2Fone',
    '/api/projects/project%2Fone/planning/drafts/draft%2Fone/confirm',
    '/api/projects/project%2Fone/canon/head',
    '/api/projects/project%2Fone/canon/entities',
    '/api/projects/project%2Fone/canon/entities/entity%2Fone',
    '/api/projects/project%2Fone/canon/aliases/resolve',
    '/api/projects/project%2Fone/projections/head',
  ])
  assert.equal(new URL(calls[16].url).searchParams.get('name'), '张 三/别名')
  assert.equal(new URL(calls[12].url).search, '')
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
    title: 'Project',
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
    qualityCharterVersion: 'v1', targetTotalWords: 1_500_000,
    expectedVolumeCount: 8, expectedChapterCount: 500,
    chapterWordRangePreference: [2800, 3400],
    prohibitedDirections: ['不写无代价升级'], authorNotes: '人物选择优先。',
    primaryStyleRef: ref,
    secondaryStyleRef: null, experienceCardRefs: [ref],
    corpusSourceRefs: [{
      ...ref,
      revisionId: 'source-revision-1',
      selectionMode: 'author',
      pinnedHistoricalRevision: false,
      fragments: [{
        chapterId: 'chapter-1', fragmentId: 'fragment-1', fragmentHash: 'c'.repeat(64),
        chapterCharStart: 10, chapterCharEnd: 210, referenceUse: 'style',
        rawText: 'must-not-send',
      }],
      rawText: 'must-not-send',
    }],
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
  assert.deepEqual(bodyOf(calls[3]).draft.corpusSourceRefs[0], {
    id: 'asset-1', revisionId: 'source-revision-1', revision: 1,
    contentHash: 'a'.repeat(64), selectionMode: 'author',
    pinnedHistoricalRevision: false,
    fragments: [{
      chapterId: 'chapter-1', fragmentId: 'fragment-1', fragmentHash: 'c'.repeat(64),
      chapterCharStart: 10, chapterCharEnd: 210, referenceUse: 'style',
    }],
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
    targetTotalWords: 1_500_000,
    expectedVolumeCount: 8,
    expectedChapterCount: 500,
    chapterWordRangePreference: [2800, 3400],
    prohibitedDirections: [],
    authorNotes: null,
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

test('bible client encodes project paths and sends only closed Bible commands', async () => {
  const bible = {
    premiseAndPromise: '一个承诺', worldRules: [{ id: 'rule-1', text: '规则' }],
    powerOrProgressionSystem: '成长', protagonist: '主角',
    coreCast: [{ id: 'cast-1', text: '同伴' }], factions: [{ id: 'faction-1', text: '势力' }],
    longTermConflicts: [{ id: 'conflict-1', text: '冲突' }],
    relationshipDynamics: [{ id: 'relationship-1', text: '关系' }],
    toneAndNarrativeBoundaries: '克制', continuityGuardrails: [{ id: 'guardrail-1', text: '连续性' }],
    openDesignQuestions: [{ id: 'question-1', text: '问题' }],
  }
  const calls = await captureRequests(async api => {
    await api.bible.head('project/one')
    await api.bible.draft.get('project/one')
    await api.bible.draft.save('project/one', { expectedDraftVersion: 3, draft: { ...bible, secret: 'must-not-send' }, extra: 'must-not-send' })
    await api.bible.draft.clone('project/one', { sourceDraftId: 'draft-1' })
    await api.bible.confirm('project/one', { idempotencyKey: 'bible-confirm-1', expectedDraftVersion: 4, expectedHeadRevision: 2, rawText: 'must-not-send' })
    await api.bible.generate('project/one', {
      authorInstructions: '强调群像',
      expectedDraftVersion: 4,
      expectedHeadRevision: 2,
      idempotencyKey: 'bible-generation-1',
      providerId: 'must-not-send',
      model: 'must-not-send',
      assets: ['must-not-send'],
    })
    await api.bible.generationAttempt('project/one', 'attempt/one')
    await api.bible.history('project/one', { limit: 20, beforeRevision: 81 })
    await api.bible.historyDetail('project/one', 4)
  })
  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project%2Fone/bible/head'], ['GET', '/api/projects/project%2Fone/bible/draft'],
    ['PUT', '/api/projects/project%2Fone/bible/draft'], ['POST', '/api/projects/project%2Fone/bible/draft/clone'],
    ['POST', '/api/projects/project%2Fone/bible/confirm'], ['POST', '/api/projects/project%2Fone/bible/generate'],
    ['GET', '/api/projects/project%2Fone/bible/generation-attempts/attempt%2Fone'],
    ['GET', '/api/projects/project%2Fone/bible/history'],
    ['GET', '/api/projects/project%2Fone/bible/history/4'],
  ])
  assert.deepEqual(bodyOf(calls[2]), { expectedDraftVersion: 3, draft: bible })
  assert.deepEqual(bodyOf(calls[3]), { sourceDraftId: 'draft-1' })
  assert.deepEqual(bodyOf(calls[4]), { idempotencyKey: 'bible-confirm-1', expectedDraftVersion: 4, expectedHeadRevision: 2 })
  assert.deepEqual(bodyOf(calls[5]), {
    authorInstructions: '强调群像',
    expectedDraftVersion: 4,
    expectedHeadRevision: 2,
    idempotencyKey: 'bible-generation-1',
  })
  assert.equal(new URL(calls[7].url).searchParams.get('limit'), '20')
  assert.equal(new URL(calls[7].url).searchParams.get('beforeRevision'), '81')
})

test('chapter outline client exposes the exact canonical endpoints and closed commands', async () => {
  const content = {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: { id: 'volume-1', revision: 2, contentHash: 'a'.repeat(64) },
    storyBlockRef: { id: 'block-1', revision: 3, contentHash: 'b'.repeat(64) },
    stageRefs: [{ id: 'stage-1', revision: 4, contentHash: 'c'.repeat(64) }],
    sceneTaskRefs: [{ id: 'task-1', revision: 5, contentHash: 'd'.repeat(64) }],
    chapterGoal: '取得残卷',
    expectedCharacters: ['沈砚'],
    continuation: ['追兵逼近'],
    plannedTasks: ['潜入县衙'],
    scenes: ['城门盘查'],
    forbiddenEarlyEvents: ['不揭示残卷来源'],
    prompt: 'must-not-send',
  }
  const calls = await captureRequests(
    async api => {
      await api.chapterOutlines.current('project/1')
      await api.chapterOutlines.get('project/1', 3)
      await api.chapterOutlines.history('project/1', 3)
      await api.chapterOutlines.createDraft('project/1', 3)
      await api.chapterOutlines.saveDraft('project/1', 3, 'draft-1', {
        expectedDraftRevision: 2,
        expectedDraftHash: 'e'.repeat(64),
        content,
        idempotencyKey: 'must-not-send',
      })
      await api.chapterOutlines.confirmDraft('project/1', 3, 'draft-1', {
        expectedDraftRevision: 3,
        expectedDraftHash: 'f'.repeat(64),
        expectedHeadRevision: 1,
        idempotencyKey: 'outline-confirm-1',
        provider: 'must-not-send',
      })
    },
    ({ url, options }) => {
      const pathname = new URL(url).pathname
      if (pathname.endsWith('/history')) return { items: [] }
      if (pathname.endsWith('/confirm')) {
        return formalChapterOutlineRevision({ includeDisplay: false })
      }
      if (
        pathname.endsWith('/drafts')
        || options.method === 'PUT'
      ) {
        return formalChapterOutlineDraft()
      }
      return formalChapterOutlineState()
    },
  )

  assert.deepEqual(calls.map(call => [call.options.method, new URL(call.url).pathname]), [
    ['GET', '/api/projects/project%2F1/chapter-outlines/current'],
    ['GET', '/api/projects/project%2F1/chapter-outlines/3'],
    ['GET', '/api/projects/project%2F1/chapter-outlines/3/history'],
    ['POST', '/api/projects/project%2F1/chapter-outlines/3/drafts'],
    ['PUT', '/api/projects/project%2F1/chapter-outlines/3/drafts/draft-1'],
    ['POST', '/api/projects/project%2F1/chapter-outlines/3/drafts/draft-1/confirm'],
  ])
  assert.deepEqual(bodyOf(calls[3]), {})
  assert.deepEqual(bodyOf(calls[4]), {
    expectedDraftRevision: 2,
    expectedDraftHash: 'e'.repeat(64),
    content: {
      schemaVersion: 'chapter-outline-draft-v1',
      volumeRef: { id: 'volume-1', revision: 2, contentHash: 'a'.repeat(64) },
      storyBlockRef: { id: 'block-1', revision: 3, contentHash: 'b'.repeat(64) },
      stageRefs: [{ id: 'stage-1', revision: 4, contentHash: 'c'.repeat(64) }],
      sceneTaskRefs: [{ id: 'task-1', revision: 5, contentHash: 'd'.repeat(64) }],
      chapterGoal: '取得残卷',
      expectedCharacters: ['沈砚'],
      continuation: ['追兵逼近'],
      plannedTasks: ['潜入县衙'],
      scenes: ['城门盘查'],
      forbiddenEarlyEvents: ['不揭示残卷来源'],
    },
  })
  assert.equal(JSON.stringify(bodyOf(calls[4])).includes('must-not-send'), false)
  assert.deepEqual(bodyOf(calls[5]), {
    expectedDraftRevision: 3,
    expectedDraftHash: 'f'.repeat(64),
    expectedHeadRevision: 1,
    idempotencyKey: 'outline-confirm-1',
  })
})

test('chapter outline current response is a closed projection with pending recovery only', async () => {
  const originalFetch = global.fetch
  const secret = 'MUST-NOT-CROSS-CURRENT-OUTLINE'
  const hash = 'a'.repeat(64)
  const planningContent = {
    schemaVersion: 'planning-v1',
    activeStoryBlockId: 'block-1',
    volumes: [{
      id: 'volume-1',
      revision: 2,
      contentHash: hash,
      lifecycle: 'active',
      order: 1,
      title: '第一卷',
      coreChange: '主角站稳脚跟',
      mainPressure: '县衙追捕',
      ensembleFocus: ['沈砚', '顾长风'],
      forbiddenEvents: ['不得提前揭示残卷来源'],
    }],
    plots: [{
      id: 'plot-1',
      revision: 3,
      contentHash: hash,
      lifecycle: 'active',
      order: 1,
      title: '残卷疑云',
      plotType: 'main',
      storyQuestion: '残卷为何现世',
      futureDirection: '追查永乐大典散佚线索',
      expectedPayoff: '揭开第一层幕后势力',
      relatedCharacters: ['沈砚'],
    }],
    storyBlocks: [{
      id: 'block-1',
      revision: 4,
      contentHash: hash,
      lifecycle: 'active',
      volumeId: 'volume-1',
      plotIds: ['plot-1'],
      order: 1,
      title: '夜入县衙',
      entrySituation: '追兵封城',
      blockGoal: '取得残卷',
      mainPressure: '巡夜加严',
      expectedChange: '确认残卷线索',
      openQuestions: ['内应是谁'],
      involvedCharacters: ['沈砚', '顾长风'],
      stages: [{
        id: 'stage-1',
        revision: 5,
        contentHash: hash,
        lifecycle: 'active',
        storyBlockId: 'block-1',
        order: 1,
        title: '潜入',
        purpose: '进入档案库',
        dramaticQuestion: '能否避开巡夜',
        sceneTasks: [{
          id: 'task-1',
          revision: 6,
          contentHash: hash,
          lifecycle: 'active',
          stageId: 'stage-1',
          order: 1,
          task: '取得残卷',
          completionEvidence: '残卷进入主角手中',
        }],
      }],
    }],
    contentHash: hash,
  }
  global.fetch = async () => jsonResponse({
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: 8,
    targetPath: '/projects/project-1/write/chapters/8',
    planningAuthority: {
      planningRevisionId: 'planning-r4',
      revision: 4,
      contentHash: hash,
      content: {
        ...planningContent,
        activeStoryBlockRef: 'draft-block-alias',
        apiKey: secret,
        volumes: planningContent.volumes.map(item => ({
          ...item,
          clientNodeKey: 'draft-volume-alias',
          apiKey: secret,
        })),
        plots: planningContent.plots.map(item => ({
          ...item,
          clientNodeKey: 'draft-plot-alias',
          apiKey: secret,
        })),
        storyBlocks: planningContent.storyBlocks.map(block => ({
          ...block,
          clientNodeKey: 'draft-block-alias',
          volumeRef: 'draft-volume-alias',
          plotRefs: ['draft-plot-alias'],
          apiKey: secret,
          stages: block.stages.map(stage => ({
            ...stage,
            clientNodeKey: 'draft-stage-alias',
            apiKey: secret,
            sceneTasks: stage.sceneTasks.map(task => ({
              ...task,
              clientNodeKey: 'draft-task-alias',
              apiKey: secret,
            })),
          })),
        })),
      },
      apiKey: secret,
    },
    canonProjectionAuthority: null,
    confirmedOutline: null,
    draft: null,
    activeSession: null,
    pendingOperation: {
      operationId: '11111111-1111-4111-8111-111111111111',
      status: 'pending',
      providerId: secret,
      model: secret,
      manifest: secret,
      prompt: secret,
      raw: secret,
    },
    capabilities: {
      view: true,
      createDraft: true,
      editDraft: false,
      generate: false,
      confirm: false,
      startSession: false,
      apiKey: secret,
    },
    reasons: ['outlineMissing'],
    api_key: secret,
    authorization: secret,
    password: secret,
    dsn: secret,
  })
  try {
    const { api } = await import('../../src/api/db/client.js')
    const current = await api.chapterOutlines.current('project-1')

    assert.deepEqual(current.pendingOperation, {
      operationId: '11111111-1111-4111-8111-111111111111',
      status: 'pending',
    })
    assert.deepEqual(current.planningAuthority, {
      planningRevisionId: 'planning-r4',
      revision: 4,
      contentHash: hash,
      content: planningContent,
    })
    assert.deepEqual(Object.keys(current), [
      'projectId',
      'lifecycle',
      'authoritativeChapterNumber',
      'targetPath',
      'planningAuthority',
      'canonProjectionAuthority',
      'confirmedOutline',
      'draft',
      'activeSession',
      'pendingOperation',
      'capabilities',
      'reasons',
    ])
    assert.equal(JSON.stringify(current).includes(secret), false)
    assert.doesNotMatch(
      JSON.stringify(current.planningAuthority),
      /activeStoryBlockRef|clientNodeKey|volumeRef|plotRefs/u,
    )

    const responseWithPlanningAuthority = planningAuthority => ({
      projectId: 'project-1',
      lifecycle: 'active',
      authoritativeChapterNumber: 8,
      targetPath: '/projects/project-1/write/chapters/8',
      planningAuthority,
      canonProjectionAuthority: null,
      confirmedOutline: null,
      draft: null,
      activeSession: null,
      pendingOperation: null,
      capabilities: {
        view: true,
        createDraft: true,
        editDraft: false,
        generate: false,
        confirm: false,
        startSession: false,
      },
      reasons: [],
    })
    const authorityFor = content => ({
      planningRevisionId: 'planning-r4',
      revision: 4,
      contentHash: hash,
      content,
    })
    const malformedCases = [
      ['object schema version', content => {
        content.schemaVersion = { apiKey: secret }
      }],
      ['object active StoryBlock id', content => {
        content.activeStoryBlockId = { apiKey: secret }
      }],
      ['object aggregate content hash', content => {
        content.contentHash = { apiKey: secret }
      }],
      ['null Volume node', content => {
        content.volumes = [null]
      }],
      ['array Volume node', content => {
        content.volumes = [[]]
      }],
      ['null Plot node', content => {
        content.plots = [null]
      }],
      ['array StoryBlock node', content => {
        content.storyBlocks = [[]]
      }],
      ['null Stage node', content => {
        content.storyBlocks[0].stages = [null]
      }],
      ['array SceneTask node', content => {
        content.storyBlocks[0].stages[0].sceneTasks = [[]]
      }],
      ['missing own Stages collection', content => {
        delete content.storyBlocks[0].stages
      }],
      ['missing own SceneTasks collection', content => {
        delete content.storyBlocks[0].stages[0].sceneTasks
      }],
      ['object string-array field', content => {
        content.volumes[0].ensembleFocus = { apiKey: secret }
      }],
      ['object string-array item', content => {
        content.volumes[0].forbiddenEvents = [{ apiKey: secret }]
      }],
      ['object scalar field', content => {
        content.volumes[0].title = { apiKey: secret }
      }],
    ]
    for (const [label, mutate] of malformedCases) {
      const malformed = structuredClone(planningContent)
      mutate(malformed)
      global.fetch = async () => jsonResponse(
        responseWithPlanningAuthority(authorityFor(malformed)),
      )
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        failure => {
          assert.equal(failure instanceof TypeError, true, label)
          assert.equal(String(failure).includes(secret), false, label)
          return true
        },
      )
    }

    for (const missingField of [
      'schemaVersion',
      'activeStoryBlockId',
      'contentHash',
      'volumes',
      'plots',
      'storyBlocks',
    ]) {
      const missingRoot = structuredClone(planningContent)
      delete missingRoot[missingField]
      global.fetch = async () => jsonResponse(
        responseWithPlanningAuthority(authorityFor(missingRoot)),
      )
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
        `missing own root field ${missingField}`,
      )
    }

    for (const missingField of [
      'planningRevisionId',
      'revision',
      'contentHash',
      'content',
    ]) {
      const missingAuthority = authorityFor(planningContent)
      delete missingAuthority[missingField]
      global.fetch = async () => jsonResponse(
        responseWithPlanningAuthority(missingAuthority),
      )
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
        `missing own authority field ${missingField}`,
      )
    }
    for (const [field, invalidValue] of [
      ['planningRevisionId', { apiKey: secret }],
      ['revision', { apiKey: secret }],
      ['contentHash', { apiKey: secret }],
      ['content', undefined],
    ]) {
      const malformedAuthority = authorityFor(planningContent)
      malformedAuthority[field] = invalidValue
      global.fetch = async () => jsonResponse(
        responseWithPlanningAuthority(malformedAuthority),
      )
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        failure => {
          assert.equal(failure instanceof TypeError, true, field)
          assert.equal(String(failure).includes(secret), false, field)
          return true
        },
      )
    }

    const expectInheritedFieldsRejected = async (
      inherited,
      planningAuthority,
      label,
    ) => {
      const originalDescriptors = new Map()
      try {
        for (const [field, value] of Object.entries(inherited)) {
          originalDescriptors.set(
            field,
            Object.getOwnPropertyDescriptor(Object.prototype, field),
          )
          Object.defineProperty(Object.prototype, field, {
            configurable: true,
            enumerable: false,
            writable: true,
            value,
          })
        }
        global.fetch = async () => jsonResponse(
          responseWithPlanningAuthority(planningAuthority),
        )
        await assert.rejects(
          () => api.chapterOutlines.current('project-1'),
          TypeError,
          label,
        )
      } finally {
        for (const [field, descriptor] of originalDescriptors) {
          if (descriptor) {
            Object.defineProperty(Object.prototype, field, descriptor)
          } else {
            delete Object.prototype[field]
          }
        }
      }
    }
    await expectInheritedFieldsRejected(
      {
        schemaVersion: planningContent.schemaVersion,
        activeStoryBlockId: planningContent.activeStoryBlockId,
        contentHash: planningContent.contentHash,
        volumes: planningContent.volumes,
        plots: planningContent.plots,
        storyBlocks: planningContent.storyBlocks,
      },
      authorityFor({}),
      'inherited Planning content fields',
    )
    await expectInheritedFieldsRejected(
      {
        planningRevisionId: 'planning-r4',
        revision: 4,
        contentHash: hash,
        content: planningContent,
      },
      {},
      'inherited Planning authority fields',
    )
    const inheritedStages = structuredClone(planningContent)
    delete inheritedStages.storyBlocks[0].stages
    await expectInheritedFieldsRejected(
      {
        stages: planningContent.storyBlocks[0].stages,
      },
      authorityFor(inheritedStages),
      'inherited StoryBlock stages',
    )
    const inheritedSceneTasks = structuredClone(planningContent)
    delete inheritedSceneTasks.storyBlocks[0].stages[0].sceneTasks
    await expectInheritedFieldsRejected(
      {
        sceneTasks: planningContent.storyBlocks[0].stages[0].sceneTasks,
      },
      authorityFor(inheritedSceneTasks),
      'inherited Stage sceneTasks',
    )

    const inheritedAuthorityDescriptors = new Map()
    const inheritedProjection = {
      canonRevision: 3,
      projectionRevision: 3,
      contentHash: hash,
      synchronized: true,
    }
    const outlineContent = {
      schemaVersion: 'chapter-outline-draft-v1',
      volumeRef: { id: 'volume-1', revision: 2, contentHash: hash },
      storyBlockRef: { id: 'block-1', revision: 4, contentHash: hash },
      stageRefs: [{ id: 'stage-1', revision: 5, contentHash: hash }],
      sceneTaskRefs: [{ id: 'task-1', revision: 6, contentHash: hash }],
      chapterGoal: '取得残卷',
      expectedCharacters: ['沈砚'],
      continuation: ['承接追兵'],
      plannedTasks: ['潜入县衙'],
      scenes: ['档案库'],
      forbiddenEarlyEvents: ['不揭示残卷来源'],
    }
    const confirmedOutlineFixture = {
      projectId: 'project-1',
      chapterNumber: 8,
      outlineRevisionId: 'outline-r1',
      revision: 1,
      parentRevision: 0,
      contentHash: hash,
      content: outlineContent,
      basis: {
        planningAuthority: authorityFor(planningContent),
        canonProjectionAuthority: inheritedProjection,
      },
      status: 'confirmed',
      reason: 'currentOutlineHead',
    }
    const draftFixture = {
      projectId: 'project-1',
      chapterNumber: 8,
      draftId: 'outline-d1',
      baseHeadRevision: 1,
      draftRevision: 1,
      contentHash: hash,
      content: outlineContent,
      basis: {
        planningAuthority: authorityFor(planningContent),
        canonProjectionAuthority: inheritedProjection,
      },
      status: 'current',
    }
    try {
      for (const [field, value] of Object.entries({
        planningAuthority: authorityFor(planningContent),
        canonProjectionAuthority: inheritedProjection,
        basis: draftFixture.basis,
        content: outlineContent,
        confirmedOutline: confirmedOutlineFixture,
        draft: draftFixture,
      })) {
        inheritedAuthorityDescriptors.set(
          field,
          Object.getOwnPropertyDescriptor(Object.prototype, field),
        )
        Object.defineProperty(Object.prototype, field, {
          configurable: true,
          enumerable: false,
          writable: true,
          value,
        })
      }
      global.fetch = async () => jsonResponse({
        projectId: 'project-1',
        lifecycle: 'active',
        authoritativeChapterNumber: 8,
        targetPath: '/projects/project-1/write/chapters/8',
        planningAuthority: null,
        canonProjectionAuthority: null,
        confirmedOutline: {
          ...confirmedOutlineFixture,
          content: null,
          basis: {
            planningAuthority: null,
            canonProjectionAuthority: null,
          },
        },
        draft: {
          ...draftFixture,
          content: null,
          basis: {
            planningAuthority: null,
            canonProjectionAuthority: null,
          },
        },
        activeSession: null,
        pendingOperation: null,
        capabilities: {
          view: true,
          createDraft: false,
          editDraft: true,
          generate: true,
          confirm: true,
          startSession: false,
        },
        reasons: [],
      })
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )

      global.fetch = async () => jsonResponse({
        projectId: 'project-1',
        lifecycle: 'active',
        authoritativeChapterNumber: 8,
        targetPath: '/projects/project-1/write/chapters/8',
        activeSession: null,
        pendingOperation: null,
        capabilities: {
          view: true,
          createDraft: true,
          editDraft: false,
          generate: false,
          confirm: false,
          startSession: false,
        },
        reasons: [],
      })
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )
    } finally {
      for (const [field, descriptor] of inheritedAuthorityDescriptors) {
        if (descriptor) {
          Object.defineProperty(Object.prototype, field, descriptor)
        } else {
          delete Object.prototype[field]
        }
      }
    }
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline projection and editable content are strict own-only subtrees', async () => {
  const originalFetch = global.fetch
  const secret = 'MUST-NOT-CROSS-OUTLINE-SUBTREE'
  const hash = 'b'.repeat(64)
  const projection = {
    canonRevision: 3,
    projectionRevision: 3,
    contentHash: hash,
    synchronized: true,
  }
  const content = {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: { id: 'volume-1', revision: 2, contentHash: hash },
    storyBlockRef: { id: 'block-1', revision: 4, contentHash: hash },
    stageRefs: [{ id: 'stage-1', revision: 5, contentHash: hash }],
    sceneTaskRefs: [{ id: 'task-1', revision: 6, contentHash: hash }],
    chapterGoal: '取得残卷',
    expectedCharacters: ['沈砚'],
    continuation: ['承接追兵'],
    plannedTasks: ['潜入县衙'],
    scenes: ['档案库'],
    forbiddenEarlyEvents: ['不揭示残卷来源'],
  }
  const planningAuthority = {
    planningRevisionId: 'planning-r3',
    revision: 3,
    contentHash: hash,
    content: null,
  }
  const basis = canonProjectionAuthority => ({
    planningAuthority,
    canonProjectionAuthority,
  })
  const draft = (draftContent, draftBasis = basis(projection)) => ({
    projectId: 'project-1',
    chapterNumber: 8,
    draftId: 'outline-d1',
    baseHeadRevision: 1,
    draftRevision: 1,
    contentHash: hash,
    content: draftContent,
    basis: draftBasis,
    status: 'current',
  })
  const confirmed = (revisionContent, revisionBasis = basis(projection)) => ({
    projectId: 'project-1',
    chapterNumber: 8,
    outlineRevisionId: 'outline-r1',
    revision: 1,
    parentRevision: 0,
    contentHash: hash,
    content: revisionContent,
    basis: revisionBasis,
    status: 'confirmed',
    reason: 'currentOutlineHead',
  })
  const state = overrides => ({
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: 8,
    targetPath: '/projects/project-1/write/chapters/8',
    planningAuthority: null,
    canonProjectionAuthority: null,
    confirmedOutline: null,
    draft: null,
    activeSession: null,
    pendingOperation: null,
    capabilities: {
      view: true,
      createDraft: true,
      editDraft: false,
      generate: false,
      confirm: false,
      startSession: false,
    },
    reasons: [],
    ...overrides,
  })
  const withPrototype = async (properties, run) => {
    const descriptors = new Map()
    try {
      for (const [field, value] of Object.entries(properties)) {
        descriptors.set(
          field,
          Object.getOwnPropertyDescriptor(Object.prototype, field),
        )
        Object.defineProperty(Object.prototype, field, {
          configurable: true,
          enumerable: false,
          writable: true,
          value,
        })
      }
      await run()
    } finally {
      for (const [field, descriptor] of descriptors) {
        if (descriptor) {
          Object.defineProperty(Object.prototype, field, descriptor)
        } else {
          delete Object.prototype[field]
        }
      }
    }
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    global.fetch = async () => jsonResponse(state({
      canonProjectionAuthority: {
        ...projection,
        apiKey: secret,
      },
      confirmedOutline: confirmed(content),
      draft: draft({
        ...content,
        apiKey: secret,
      }),
    }))
    const valid = await api.chapterOutlines.current('project-1')
    assert.deepEqual(valid.canonProjectionAuthority, projection)
    assert.deepEqual(valid.confirmedOutline.content, content)
    assert.deepEqual(valid.draft.content, content)
    assert.equal(JSON.stringify(valid).includes(secret), false)

    await withPrototype(projection, async () => {
      global.fetch = async () => jsonResponse(state({
        canonProjectionAuthority: {},
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )
      global.fetch = async () => jsonResponse(state({
        draft: draft({}, basis({})),
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )
    })

    await withPrototype({
      chapterGoal: '原型污染目标',
      expectedCharacters: ['原型污染人物'],
    }, async () => {
      global.fetch = async () => jsonResponse(state({
        confirmedOutline: confirmed({}),
        draft: draft({}),
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )
    })

    for (const [label, malformedProjection] of [
      ['missing projection field', {
        canonRevision: 3,
        projectionRevision: 3,
        contentHash: hash,
      }],
      ['object projection revision', {
        ...projection,
        projectionRevision: { apiKey: secret },
      }],
      ['object projection synchronized', {
        ...projection,
        synchronized: { apiKey: secret },
      }],
    ]) {
      global.fetch = async () => jsonResponse(state({
        canonProjectionAuthority: malformedProjection,
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        failure => {
          assert.equal(failure instanceof TypeError, true, label)
          assert.equal(String(failure).includes(secret), false, label)
          return true
        },
      )
    }

    const malformedContentCases = [
      ['missing ref fields', value => {
        value.volumeRef = {}
      }],
      ['object ref id', value => {
        value.volumeRef.id = { apiKey: secret }
      }],
      ['null ref array item', value => {
        value.stageRefs = [null]
      }],
      ['array ref array item', value => {
        value.sceneTaskRefs = [[]]
      }],
      ['object ref array', value => {
        value.stageRefs = { apiKey: secret }
      }],
      ['object string-array item', value => {
        value.expectedCharacters = [{ apiKey: secret }]
      }],
      ['object scalar', value => {
        value.chapterGoal = { apiKey: secret }
      }],
    ]
    for (const [label, mutate] of malformedContentCases) {
      const malformed = structuredClone(content)
      mutate(malformed)
      global.fetch = async () => jsonResponse(state({
        draft: draft(malformed),
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        failure => {
          assert.equal(failure instanceof TypeError, true, label)
          assert.equal(String(failure).includes(secret), false, label)
          return true
        },
      )
    }

    await withPrototype({
      id: 'volume-1',
      revision: 2,
      contentHash: hash,
    }, async () => {
      const inheritedRef = structuredClone(content)
      inheritedRef.volumeRef = {}
      global.fetch = async () => jsonResponse(state({
        draft: draft(inheritedRef),
      }))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
      )
    })
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline state envelope is one strict own-only formal DTO', async () => {
  const originalFetch = global.fetch
  const secret = 'MUST-NOT-CROSS-OUTLINE-STATE'
  const hash = 'c'.repeat(64)
  const projection = {
    canonRevision: 4,
    projectionRevision: 4,
    contentHash: hash,
    synchronized: true,
  }
  const planningAuthority = {
    planningRevisionId: 'planning-r4',
    revision: 4,
    contentHash: hash,
    content: null,
  }
  const basis = {
    planningAuthority,
    canonProjectionAuthority: projection,
  }
  const content = {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: null,
    storyBlockRef: null,
    stageRefs: [],
    sceneTaskRefs: [],
    chapterGoal: '承接上一章',
    expectedCharacters: [],
    continuation: [],
    plannedTasks: [],
    scenes: [],
    forbiddenEarlyEvents: [],
  }
  const draft = {
    projectId: 'project-1',
    chapterNumber: 8,
    draftId: 'outline-d1',
    baseHeadRevision: 1,
    draftRevision: 2,
    contentHash: hash,
    content,
    basis,
    status: 'current',
  }
  const revision = {
    projectId: 'project-1',
    chapterNumber: 8,
    outlineRevisionId: 'outline-r1',
    revision: 1,
    parentRevision: 0,
    contentHash: hash,
    content,
    basis,
    status: 'current',
    reason: 'currentOutlineHead',
  }
  const activeSession = {
    chapterSessionId: 'session-1',
    chapterNumber: 8,
    status: 'active',
    planningRevisionId: 'planning-r4',
    planningRevision: 4,
    planningHash: hash,
    outlineRevisionId: 'outline-r1',
    outlineRevision: 1,
    outlineHash: hash,
  }
  const pendingOperation = {
    operationId: '11111111-1111-4111-8111-111111111111',
    status: 'pending',
  }
  const capabilities = {
    view: true,
    createDraft: false,
    editDraft: true,
    generate: true,
    confirm: true,
    startSession: false,
  }
  const activeState = {
    projectId: 'project-1',
    lifecycle: 'active',
    authoritativeChapterNumber: 8,
    targetPath: '/projects/project-1/write/chapters/8',
    planningAuthority,
    canonProjectionAuthority: projection,
    confirmedOutline: revision,
    draft,
    activeSession,
    pendingOperation,
    capabilities,
    reasons: ['generationPending'],
  }
  const withPrototype = async (properties, run) => {
    const descriptors = new Map()
    try {
      for (const [field, value] of Object.entries(properties)) {
        descriptors.set(
          field,
          Object.getOwnPropertyDescriptor(Object.prototype, field),
        )
        Object.defineProperty(Object.prototype, field, {
          configurable: true,
          enumerable: false,
          writable: true,
          value,
        })
      }
      await run()
    } finally {
      for (const [field, descriptor] of descriptors) {
        if (descriptor) {
          Object.defineProperty(Object.prototype, field, descriptor)
        } else {
          delete Object.prototype[field]
        }
      }
    }
  }
  const expectRejected = async (api, value, label) => {
    global.fetch = async () => jsonResponse(value)
    await assert.rejects(
      () => api.chapterOutlines.current('project-1'),
      failure => {
        assert.equal(failure instanceof TypeError, true, label)
        assert.equal(String(failure).includes(secret), false, label)
        return true
      },
    )
  }

  try {
    const { api } = await import('../../src/api/db/client.js')
    global.fetch = async () => jsonResponse(activeState)
    const active = await api.chapterOutlines.current('project-1')
    assert.deepEqual(active, activeState)

    const archivedState = {
      ...activeState,
      lifecycle: 'archived',
      planningAuthority: null,
      canonProjectionAuthority: null,
      confirmedOutline: null,
      draft: null,
      activeSession: null,
      pendingOperation: null,
      capabilities: {
        view: true,
        createDraft: false,
        editDraft: false,
        generate: false,
        confirm: false,
        startSession: false,
      },
      reasons: ['projectArchived'],
    }
    global.fetch = async () => jsonResponse(archivedState)
    assert.deepEqual(
      await api.chapterOutlines.current('project-1'),
      archivedState,
    )

    await withPrototype(activeState, async () => {
      await expectRejected(api, {}, 'inherited complete state')
    })

    const inheritedChildFields = {
      ...capabilities,
      ...pendingOperation,
      ...activeSession,
      ...draft,
      ...revision,
      ...basis,
    }
    await withPrototype(inheritedChildFields, async () => {
      for (const [label, patch] of [
        ['empty capabilities', { capabilities: {} }],
        ['empty pending operation', { pendingOperation: {} }],
        ['empty active session', { activeSession: {} }],
        ['empty draft', { draft: {} }],
        ['empty confirmed revision', { confirmedOutline: {} }],
        ['empty basis', { draft: { ...draft, basis: {} } }],
      ]) {
        await expectRejected(api, { ...activeState, ...patch }, label)
      }
    })

    for (const [label, mutate] of [
      ['object project id', value => {
        value.projectId = { apiKey: secret }
      }],
      ['object reasons item', value => {
        value.reasons = [{ apiKey: secret }]
      }],
      ['object capability', value => {
        value.capabilities.createDraft = { apiKey: secret }
      }],
      ['object pending id', value => {
        value.pendingOperation.operationId = { apiKey: secret }
      }],
      ['object session hash', value => {
        value.activeSession.planningHash = { apiKey: secret }
      }],
      ['object draft id', value => {
        value.draft.draftId = { apiKey: secret }
      }],
      ['object revision reason', value => {
        value.confirmedOutline.reason = { apiKey: secret }
      }],
    ]) {
      const malformed = structuredClone(activeState)
      mutate(malformed)
      await expectRejected(api, malformed, label)
    }
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline formal artifacts require full content and non-null basis authorities', async () => {
  const originalFetch = global.fetch
  const hash = 'd'.repeat(64)
  const planningAuthority = {
    planningRevisionId: 'planning-r4',
    revision: 4,
    contentHash: hash,
    content: null,
  }
  const projectionAuthority = {
    canonRevision: 4,
    projectionRevision: 4,
    contentHash: hash,
    synchronized: true,
  }
  const content = {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: null,
    storyBlockRef: null,
    stageRefs: [],
    sceneTaskRefs: [],
    chapterGoal: '承接上一章',
    expectedCharacters: [],
    continuation: [],
    plannedTasks: [],
    scenes: [],
    forbiddenEarlyEvents: [],
  }
  const draft = {
    projectId: 'project-1',
    chapterNumber: 8,
    draftId: 'outline-d1',
    baseHeadRevision: 1,
    draftRevision: 2,
    contentHash: hash,
    content,
    basis: {
      planningAuthority,
      canonProjectionAuthority: projectionAuthority,
    },
    status: 'current',
  }
  const state = draftValue => formalChapterOutlineState({
    authoritativeChapterNumber: 8,
    targetPath: '/projects/project-1/write/chapters/8',
    planningAuthority,
    canonProjectionAuthority: projectionAuthority,
    draft: draftValue,
    capabilities: {
      view: true,
      createDraft: false,
      editDraft: true,
      generate: true,
      confirm: true,
      startSession: false,
    },
  })
  try {
    const { api } = await import('../../src/api/db/client.js')
    global.fetch = async () => jsonResponse(state(draft))
    assert.deepEqual(
      (await api.chapterOutlines.current('project-1')).draft,
      draft,
    )

    const malformed = [
      ['null response content', { ...draft, content: null }],
      ['empty response content', { ...draft, content: {} }],
      ['missing response content field', {
        ...draft,
        content: Object.fromEntries(
          Object.entries(content).filter(([field]) => field !== 'scenes'),
        ),
      }],
      ['null Planning basis authority', {
        ...draft,
        basis: {
          ...draft.basis,
          planningAuthority: null,
        },
      }],
      ['null Canon basis authority', {
        ...draft,
        basis: {
          ...draft.basis,
          canonProjectionAuthority: null,
        },
      }],
    ]
    for (const [label, malformedDraft] of malformed) {
      global.fetch = async () => jsonResponse(state(malformedDraft))
      await assert.rejects(
        () => api.chapterOutlines.current('project-1'),
        TypeError,
        label,
      )
    }
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline mutation and history responses cross one closed formal boundary', async () => {
  const originalFetch = global.fetch
  const secret = 'MUST-NOT-CROSS-OUTLINE-MUTATION'
  const hash = 'e'.repeat(64)
  const planningAuthority = {
    planningRevisionId: 'planning-r5',
    revision: 5,
    contentHash: hash,
    content: null,
    apiKey: secret,
  }
  const projectionAuthority = {
    canonRevision: 5,
    projectionRevision: 5,
    contentHash: hash,
    synchronized: true,
    apiKey: secret,
  }
  const content = {
    schemaVersion: 'chapter-outline-draft-v1',
    volumeRef: null,
    storyBlockRef: null,
    stageRefs: [],
    sceneTaskRefs: [],
    chapterGoal: '承接上一章',
    expectedCharacters: [],
    continuation: [],
    plannedTasks: [],
    scenes: [],
    forbiddenEarlyEvents: [],
    apiKey: secret,
  }
  const expectedContent = Object.fromEntries(
    Object.entries(content).filter(([field]) => field !== 'apiKey'),
  )
  const draft = {
    projectId: 'project-1',
    chapterNumber: 8,
    draftId: 'outline-d1',
    baseHeadRevision: 1,
    draftRevision: 2,
    contentHash: hash,
    content,
    basis: {
      planningAuthority,
      canonProjectionAuthority: projectionAuthority,
      apiKey: secret,
    },
    status: 'current',
    apiKey: secret,
  }
  const revision = {
    projectId: 'project-1',
    chapterNumber: 8,
    outlineRevisionId: 'outline-r2',
    revision: 2,
    parentRevision: 1,
    contentHash: hash,
    content,
    basis: draft.basis,
    apiKey: secret,
  }
  const displayRevision = {
    ...revision,
    status: 'current',
    reason: 'currentOutlineHead',
  }
  const expectedBasis = {
    planningAuthority: {
      planningRevisionId: 'planning-r5',
      revision: 5,
      contentHash: hash,
      content: null,
    },
    canonProjectionAuthority: {
      canonRevision: 5,
      projectionRevision: 5,
      contentHash: hash,
      synchronized: true,
    },
  }
  const expectedDraft = {
    projectId: 'project-1',
    chapterNumber: 8,
    draftId: 'outline-d1',
    baseHeadRevision: 1,
    draftRevision: 2,
    contentHash: hash,
    content: expectedContent,
    basis: expectedBasis,
    status: 'current',
  }
  const expectedRevision = {
    projectId: 'project-1',
    chapterNumber: 8,
    outlineRevisionId: 'outline-r2',
    revision: 2,
    parentRevision: 1,
    contentHash: hash,
    content: expectedContent,
    basis: expectedBasis,
  }
  const responses = [
    draft,
    draft,
    revision,
    {
      items: [displayRevision],
      nextCursor: { apiKey: secret },
      apiKey: secret,
    },
  ]
  try {
    const { api } = await import('../../src/api/db/client.js')
    global.fetch = async () => jsonResponse(responses.shift())
    const created = await api.chapterOutlines.createDraft('project-1', 8)
    const saved = await api.chapterOutlines.saveDraft(
      'project-1',
      8,
      'outline-d1',
      {
        expectedDraftRevision: 1,
        expectedDraftHash: hash,
        content: {},
      },
    )
    const confirmed = await api.chapterOutlines.confirmDraft(
      'project-1',
      8,
      'outline-d1',
      {
        expectedDraftRevision: 2,
        expectedDraftHash: hash,
        expectedHeadRevision: 1,
        idempotencyKey: 'outline-confirm-2',
      },
    )
    const history = await api.chapterOutlines.history('project-1', 8)

    assert.deepEqual(created, expectedDraft)
    assert.deepEqual(saved, expectedDraft)
    assert.deepEqual(confirmed, expectedRevision)
    assert.deepEqual(history, {
      items: [{
        ...expectedRevision,
        status: 'current',
        reason: 'currentOutlineHead',
      }],
    })
    assert.equal(
      JSON.stringify({ created, saved, confirmed, history }).includes(secret),
      false,
    )

    for (const [label, method, body] of [
      ['malformed create response', 'createDraft', {
        ...draft,
        content: null,
      }],
      ['malformed save response', 'saveDraft', {
        ...draft,
        basis: {
          ...draft.basis,
          canonProjectionAuthority: null,
        },
      }],
      ['malformed confirm response', 'confirmDraft', {
        ...revision,
        content: {},
      }],
      ['malformed history response', 'history', { items: {} }],
    ]) {
      global.fetch = async () => jsonResponse(body)
      const request = method === 'createDraft'
        ? () => api.chapterOutlines.createDraft('project-1', 8)
        : method === 'saveDraft'
          ? () => api.chapterOutlines.saveDraft(
            'project-1',
            8,
            'outline-d1',
            {
              expectedDraftRevision: 1,
              expectedDraftHash: hash,
              content: {},
            },
          )
          : method === 'confirmDraft'
            ? () => api.chapterOutlines.confirmDraft(
              'project-1',
              8,
              'outline-d1',
              {
                expectedDraftRevision: 2,
                expectedDraftHash: hash,
                expectedHeadRevision: 1,
                idempotencyKey: 'outline-confirm-2',
              },
            )
            : () => api.chapterOutlines.history('project-1', 8)
      await assert.rejects(request, TypeError, label)
    }

    const descriptor = Object.getOwnPropertyDescriptor(Object.prototype, 'items')
    try {
      Object.defineProperty(Object.prototype, 'items', {
        configurable: true,
        enumerable: false,
        writable: true,
        value: [displayRevision],
      })
      global.fetch = async () => jsonResponse({})
      await assert.rejects(
        () => api.chapterOutlines.history('project-1', 8),
        TypeError,
      )
    } finally {
      if (descriptor) {
        Object.defineProperty(Object.prototype, 'items', descriptor)
      } else {
        delete Object.prototype.items
      }
    }
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline generation projects only the public operation and uses GET-only recovery', async () => {
  const originalFetch = global.fetch
  const calls = []
  const secret = 'sk-must-not-cross-outline-client'
  const operationId = '11111111-1111-4111-8111-111111111111'
  global.fetch = async (url, options) => {
    calls.push({ url: String(url), options })
    return jsonResponse({
      operationId,
      status: 'succeeded',
      failureCode: null,
      model: {
        providerId: 'provider-1',
        modelName: 'outline-model',
        apiKey: secret,
      },
      loaded: true,
      loadedDraftRevision: 3,
      manifest: { secret },
      prompt: secret,
      rawOutput: secret,
      provider: { apiKey: secret },
      dsn: `mysql://root:${secret}@database/novel`,
    })
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    const generated = await api.chapterOutlines.generateDraft(
      'project/1',
      3,
      'draft-1',
      {
        draftRevision: 2,
        draftHash: 'a'.repeat(64),
        idempotencyKey: 'outline-generate-1',
        authorInstructions: '强化人物选择',
        prompt: secret,
      },
    )
    const byKey = await api.chapterOutlines.getOperationByKey(
      'project/1',
      'outline:generate:1',
    )
    const byId = await api.chapterOutlines.getOperation('project/1', operationId)

    assert.deepEqual(calls.map(call => [
      call.options.method,
      new URL(call.url).pathname,
    ]), [
      ['POST', '/api/projects/project%2F1/chapter-outlines/3/drafts/draft-1/generate'],
      ['GET', '/api/projects/project%2F1/chapter-outlines/operations/by-key/outline%3Agenerate%3A1'],
      ['GET', `/api/projects/project%2F1/chapter-outlines/operations/${operationId}`],
    ])
    assert.deepEqual(bodyOf(calls[0]), {
      draftRevision: 2,
      draftHash: 'a'.repeat(64),
      idempotencyKey: 'outline-generate-1',
      authorInstructions: '强化人物选择',
    })
    const expected = {
      operationId,
      status: 'succeeded',
      failureCode: null,
      model: { providerId: 'provider-1', modelName: 'outline-model' },
      loaded: true,
      loadedDraftRevision: 3,
    }
    assert.deepEqual(generated, expected)
    assert.deepEqual(byKey, expected)
    assert.deepEqual(byId, expected)
    assert.equal(JSON.stringify({ generated, byKey, byId }).includes(secret), false)
  } finally {
    global.fetch = originalFetch
  }
})

test('chapter outline client rejects non-positive chapters and unsafe opaque identifiers before fetch', async () => {
  const originalFetch = global.fetch
  let calls = 0
  global.fetch = async () => {
    calls += 1
    return jsonResponse()
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    for (const chapterNumber of [0, -1, 1.5, '1', null]) {
      await assert.rejects(
        api.chapterOutlines.get('project-1', chapterNumber),
        /positive chapter number/i,
      )
    }
    for (const request of [
      () => api.chapterOutlines.saveDraft('project-1', 1, 'draft/secret', {}),
      () => api.chapterOutlines.getOperation('project-1', 'operation/token'),
      () => api.chapterOutlines.getOperationByKey('project-1', 'bad/key'),
      () => api.chapterOutlines.generateDraft('project-1', 1, 'draft-1', {
        draftRevision: 1,
        draftHash: 'a'.repeat(64),
        idempotencyKey: 'apiKey-secret',
        authorInstructions: '',
      }),
    ]) {
      await assert.rejects(request(), /invalid chapter outline/i)
    }
    assert.equal(calls, 0)
  } finally {
    global.fetch = originalFetch
  }
})

test('only chapter outline generation receives the model-length timeout', async () => {
  const originalFetch = global.fetch
  const originalSetTimeout = global.setTimeout
  const delays = []
  global.setTimeout = (callback, delay, ...args) => {
    delays.push(delay)
    return originalSetTimeout(callback, delay, ...args)
  }
  global.fetch = async (url, options) => {
    const pathname = new URL(url).pathname
    if (
      pathname.endsWith('/chapter-outlines/current')
      || (
        options.method === 'GET'
        && pathname.endsWith('/chapter-outlines/1')
      )
    ) {
      return jsonResponse(formalChapterOutlineState())
    }
    if (pathname.endsWith('/history')) {
      return jsonResponse({ items: [] })
    }
    if (pathname.endsWith('/confirm')) {
      return jsonResponse(formalChapterOutlineRevision({
        includeDisplay: false,
      }))
    }
    if (
      pathname.endsWith('/drafts')
      || options.method === 'PUT'
    ) {
      return jsonResponse(formalChapterOutlineDraft())
    }
    return jsonResponse({
      operationId: '11111111-1111-4111-8111-111111111111',
      status: 'pending',
      failureCode: null,
      model: { providerId: 'provider-1', modelName: 'outline-model' },
      loaded: false,
      loadedDraftRevision: null,
    })
  }
  try {
    const { api } = await import('../../src/api/db/client.js')
    await api.chapterOutlines.current('project-1')
    await api.chapterOutlines.get('project-1', 1)
    await api.chapterOutlines.history('project-1', 1)
    await api.chapterOutlines.createDraft('project-1', 1)
    await api.chapterOutlines.saveDraft('project-1', 1, 'draft-1', {
      expectedDraftRevision: 1,
      expectedDraftHash: 'a'.repeat(64),
      content: {},
    })
    await api.chapterOutlines.confirmDraft('project-1', 1, 'draft-1', {
      expectedDraftRevision: 1,
      expectedDraftHash: 'a'.repeat(64),
      expectedHeadRevision: 0,
      idempotencyKey: 'outline-confirm',
    })
    await api.chapterOutlines.generateDraft('project-1', 1, 'draft-1', {
      draftRevision: 1,
      draftHash: 'a'.repeat(64),
      idempotencyKey: 'outline-generate',
      authorInstructions: '',
    })
    await api.chapterOutlines.getOperationByKey('project-1', 'outline-generate')
    await api.chapterOutlines.getOperation(
      'project-1',
      '11111111-1111-4111-8111-111111111111',
    )

    assert.deepEqual(delays.filter(delay => delay === 30_000).length, 8)
    assert.ok(delays[6] >= 180_000)
    assert.notEqual(delays[6], 30_000)
  } finally {
    global.fetch = originalFetch
    global.setTimeout = originalSetTimeout
  }
})
