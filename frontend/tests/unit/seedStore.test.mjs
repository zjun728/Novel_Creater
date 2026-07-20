import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useSeedStore } from '../../src/stores/seedStore.js'

const PAYLOAD = Object.freeze({
  title: '典镇山河',
  genre: '历史穿越',
  logline: '一卷永乐大典镇山河',
  protagonist: '沈砚',
  desire: '在乱世活下去',
  coreConflict: '知识、皇权与民生互相拉扯',
  worldPressure: '王朝倾覆与地方豪强',
  openingHook: '抄书即获罪',
  differentiation: '典籍知识每次使用都有现实代价',
})

function jsonResponse(body, status = 200) {
  return new Response(body == null ? '' : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function seed(id, selectionRevision = 0, overrides = {}) {
  return {
    id,
    projectId: 'p1',
    status: 'candidate',
    revision: 1,
    revisionId: `${id}-revision-1`,
    contentHash: 'a'.repeat(64),
    payload: { ...PAYLOAD, title: id },
    isSelected: false,
    selectionRevision,
    capabilities: {
      referenced: false,
      hasFinalChapters: false,
      canEdit: true,
      canSelect: true,
      canArchive: true,
      canRestore: false,
      canPermanentlyDelete: true,
    },
    ...overrides,
  }
}

async function withFetch(fetchImpl, action) {
  const originalFetch = globalThis.fetch
  const localStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, 'localStorage')
  Object.defineProperty(globalThis, 'localStorage', {
    configurable: true,
    get() {
      throw new Error('formal seed state must never read localStorage')
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

test('refresh consumes activeSelection and marks exactly one saved candidate selected', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const a = seed('A', 3)
  const b = seed('B', 3, { isSelected: true })

  await withFetch(async url => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds')) return jsonResponse([a, b])
    if (path.endsWith('/projects/p1/selected-seed')) {
      return jsonResponse({
        activeSelection: {
          projectId: 'p1',
          selectionRevision: 3,
          seedId: 'A',
          seedRevisionId: a.revisionId,
          seedHash: a.contentHash,
          selectedAt: 10,
          updatedAt: 11,
          seed: { ...a, isSelected: true },
        },
        seedReady: false,
        contractReady: false,
        reasons: ['creation_contract_missing'],
      })
    }
    throw new Error(`unexpected request ${url}`)
  }, () => store.refresh('p1'))

  assert.equal(store.activeSelection.seedId, 'A')
  assert.equal(store.selectionRevision, 3)
  assert.deepEqual(
    store.seeds.filter(item => item.isSelected).map(item => item.id),
    ['A'],
  )
  assert.equal(store.selectedSeed.id, 'A')
  assert.equal(store.nextAction.key, 'continue-contract')
  assert.equal(store.nextAction.label, '继续创作契约')
})

test('A to B to A selection uses the returned monotonic aggregate generation without confirmation calls', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const calls = []
  const revisions = [1, 2, 3]

  await withFetch(async (url, options) => {
    const body = JSON.parse(options.body)
    calls.push({ path: String(url), body })
    const id = body.seedId
    return jsonResponse(seed(id, revisions.shift(), {
      isSelected: true,
      selectionRevision: calls.length,
    }))
  }, async () => {
    store.$patch({ seeds: [seed('A'), seed('B')] })
    await store.selectSeed('p1', {
      seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0,
    })
    await store.selectSeed('p1', {
      seedId: 'B', expectedSeedRevision: 1, expectedSelectionRevision: 1,
    })
    await store.selectSeed('p1', {
      seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 2,
    })
  })

  assert.equal(store.activeSelection.seedId, 'A')
  assert.equal(store.selectionRevision, 3)
  assert.deepEqual(calls.map(call => call.body.expectedSelectionRevision), [0, 1, 2])
  assert.ok(calls.every(call => call.path.endsWith('/projects/p1/selected-seed')))
})

test('inspiration remains transient until an explicit Save as Seed command', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const requests = []

  await withFetch(async (url, options) => {
    const path = String(url).replace('http://127.0.0.1:8000/api', '')
    const body = JSON.parse(options.body)
    requests.push({ path, method: options.method, body })
    if (path.endsWith('/seed-inspiration')) {
      return jsonResponse({
        attemptId: 'attempt-1',
        status: 'succeeded',
        assistantTurn: { role: 'assistant', content: '让典籍知识每次救人都产生新的政治债。' },
        resultHash: 'b'.repeat(64),
        publicErrorCode: null,
      })
    }
    return jsonResponse(seed('saved', 0, {
      provenance: {
        kind: 'ai_chat',
        snapshots: [],
        analysis: null,
        inspirationAttempt: null,
      },
    }))
  }, async () => {
    const proposal = await store.requestInspiration('p1', {
      transcript: [{ role: 'user', content: '如何增强人物冲突？' }],
      snapshotIds: ['snapshot-1'],
      analysisId: 'analysis-1',
      idempotencyKey: 'i'.repeat(64),
    })
    assert.equal(proposal.assistantTurn.role, 'assistant')
    assert.equal(store.seeds.length, 0, 'proposal must not create a seed')

    await store.createSeed('p1', PAYLOAD, {
      provenance: {
        kind: 'ai_chat',
        snapshotIds: ['snapshot-1'],
        analysisId: 'analysis-1',
        inspirationAttemptId: 'attempt-1',
        publicNotes: [],
      },
      idempotencyKey: 's'.repeat(64),
    })
  })

  assert.deepEqual(requests.map(item => item.path), [
    '/projects/p1/seed-inspiration',
    '/projects/p1/seeds',
  ])
  assert.equal(requests[1].body.payload.title, '典镇山河')
  assert.equal(requests[1].body.provenance.kind, 'ai_chat')
  assert.equal(requests[1].body.idempotencyKey, 's'.repeat(64))
})

test('edit, archive, restore and eligible permanent delete are explicit writes only', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const requests = []

  await withFetch(async (url, options) => {
    const path = String(url).replace('http://127.0.0.1:8000/api', '')
    requests.push({ path, method: options.method })
    if (options.method === 'DELETE') return jsonResponse({ ok: true })
    const status = path.endsWith('/restore') ? 'candidate' : path.endsWith('/archive') ? 'archived' : 'candidate'
    return jsonResponse(seed('A', 0, {
      status,
      revision: 2,
      capabilities: {
        ...seed('A').capabilities,
        canArchive: status === 'candidate',
        canRestore: status === 'archived',
      },
    }))
  }, async () => {
    store.$patch({ seeds: [seed('A')] })
    await store.updateSeed('p1', 'A', {
      payload: { ...PAYLOAD, title: '校订稿' },
      expectedSeedRevision: 1,
      expectedSelectionRevision: 0,
    })
    await store.archiveSeed('p1', 'A', {
      expectedSeedRevision: 2,
      expectedSelectionRevision: 0,
    })
    await store.restoreSeed('p1', 'A', {
      expectedSeedRevision: 2,
      expectedSelectionRevision: 0,
    })
    await store.permanentlyDeleteSeed('p1', 'A', {
      expectedSeedRevision: 2,
      expectedSelectionRevision: 0,
    })
  })

  assert.deepEqual(requests.map(item => [item.method, item.path]), [
    ['PUT', '/projects/p1/seeds/A'],
    ['POST', '/projects/p1/seeds/A/archive'],
    ['POST', '/projects/p1/seeds/A/restore'],
    ['DELETE', '/projects/p1/seeds/A'],
  ])
  assert.equal(store.seeds.length, 0)
})

test('a seed mutation supersedes an ordinary refresh without leaving its local loading state stuck', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  let releaseList
  const listResponse = new Promise(resolve => {
    releaseList = resolve
  })

  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') {
      return listResponse
    }
    if (path.endsWith('/projects/p1/selected-seed')) {
      return jsonResponse({
        activeSelection: null,
        seedReady: false,
        contractReady: false,
        reasons: ['seed_not_selected'],
      })
    }
    if (path.endsWith('/projects/p1/seeds') && options.method === 'POST') {
      return jsonResponse(seed('created'))
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const refresh = store.refresh('p1')
    await Promise.resolve()
    assert.equal(store.loading, true)

    await store.createSeed('p1', PAYLOAD, {
      idempotencyKey: 's'.repeat(64),
    })
    assert.equal(store.mutationBusy, false)
    assert.equal(store.loading, false)
    assert.equal(store.refreshing, false)

    releaseList(jsonResponse([]))
    await refresh
    assert.deepEqual(store.seeds.map(item => item.id), ['created'])
  })
})

test('late inspiration completion cannot set error or busy state in a newer project', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  let rejectOld
  const pending = new Promise((_resolve, reject) => {
    rejectOld = reject
  })

  await withFetch(async () => pending, async () => {
    const oldRequest = store.requestInspiration('p1', {
      transcript: [{ role: 'user', content: 'P1 灵感' }],
      snapshotIds: ['snapshot-1'],
      analysisId: 'analysis-1',
      idempotencyKey: 'i'.repeat(64),
    })
    await Promise.resolve()
    assert.equal(store.inspirationBusy, true)

    store.activateProject('p2')
    assert.equal(store.inspirationBusy, false)
    assert.equal(store.error, null)

    rejectOld(new Error('old project failed'))
    await assert.rejects(oldRequest)
    assert.equal(store.inspirationBusy, false)
    assert.equal(store.error, null)
  })
})
