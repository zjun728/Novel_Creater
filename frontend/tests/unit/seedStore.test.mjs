import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useSeedStore } from '../../src/stores/seedStore.js'

test('seed store names the one-time confirmation action', async () => {
  const source = await readFile(new URL('../../src/stores/seedStore.js', import.meta.url), 'utf8')
  assert.match(source, /确认这个种子并进入创作契约/)
})

test('unknown seed hydration and a confirmed selection fail closed before transport', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  let calls = 0
  await withFetch(async () => { calls += 1; return jsonResponse({}) }, async () => {
    for (const action of [
      () => store.createSeed('p1', PAYLOAD),
      () => store.updateSeed('p1', 'A', {}),
      () => store.selectSeed('p1', { seedId: 'A' }),
      () => store.archiveSeed('p1', 'A', {}),
      () => store.restoreSeed('p1', 'A', {}),
      () => store.permanentlyDeleteSeed('p1', 'A', {}),
      () => store.requestInspiration('p1', {}),
    ]) await assert.rejects(action)
    assert.equal(calls, 0)
  })
})

for (const failure of [
  { status: 409, code: 'SelectionConflict' },
  { status: 503, code: 'outcome_unknown' },
]) {
  test(`a ${failure.code} selection failure invalidates stale authority until refresh`, async () => {
    setActivePinia(createPinia())
    const store = useSeedStore()
    const a = seed('A')
    const b = seed('B')
    let selectCalls = 0
    let writes = 0
    await withFetch(async (url, options = {}) => {
      const path = String(url)
      if (path.endsWith('/projects/p1/seeds')) return jsonResponse([a, b])
      if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
      if (path.endsWith('/projects/p1/selected-seed')) {
        selectCalls += 1
        if (selectCalls === 1) return jsonResponse({ code: failure.code, message: 'stale' }, failure.status)
        return jsonResponse({ ...a, isSelected: true, selectionRevision: 1 })
      }
      writes += 1
      return jsonResponse({})
    }, async () => {
      await store.refresh('p1')
      const before = JSON.parse(JSON.stringify({ seeds: store.seeds, activeSelection: store.activeSelection, selectionRevision: store.selectionRevision }))
      await assert.rejects(store.selectSeed('p1', { seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0 }))
      assert.equal(selectCalls, 1)
      assert.deepEqual({ seeds: store.seeds, activeSelection: store.activeSelection, selectionRevision: store.selectionRevision }, before)
      assert.equal(store.selectionHydrated, false)
      assert.equal(store.error.status, failure.status)
      for (const action of [
        () => store.createSeed('p1', PAYLOAD),
        () => store.updateSeed('p1', 'A', {}),
        () => store.selectSeed('p1', { seedId: 'A' }),
        () => store.archiveSeed('p1', 'A', {}),
        () => store.restoreSeed('p1', 'A', {}),
        () => store.permanentlyDeleteSeed('p1', 'A', {}),
        () => store.requestInspiration('p1', {}),
      ]) await assert.rejects(action)
      assert.equal(writes, 0)

      await store.refresh('p1')
      assert.equal(store.selectionHydrated, true)
      await store.selectSeed('p1', { seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0 })
      assert.equal(selectCalls, 2)
    })
  })
}

test('a pending selection serializes same-project mutations until its authority is resolved', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const selection = deferred()
  const a = seed('A')
  let selectCalls = 0
  let otherWrites = 0
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([a])
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (path.endsWith('/projects/p1/selected-seed')) {
      selectCalls += 1
      if (JSON.parse(options.body).expectedSeedRevision === 1) return selection.promise
      return jsonResponse({ code: 'secondary_mutation' }, 418)
    }
    otherWrites += 1
    return jsonResponse({})
  }, async () => {
    await store.refresh('p1')
    const pending = store.selectSeed('p1', { seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0 })
    await Promise.resolve()
    const secondary = await Promise.allSettled([
      () => store.createSeed('p1', PAYLOAD),
      () => store.updateSeed('p1', 'A', {}),
      () => store.selectSeed('p1', { seedId: 'A' }),
      () => store.archiveSeed('p1', 'A', {}),
      () => store.restoreSeed('p1', 'A', {}),
      () => store.permanentlyDeleteSeed('p1', 'A', {}),
    ].map(action => action()))

    selection.resolve(jsonResponse({ code: 'outcome_unknown' }, 503))
    await assert.rejects(pending, error => error?.code === 'outcome_unknown')
    for (const result of secondary) {
      assert.equal(result.status, 'rejected')
      assert.equal(result.reason?.code, 'seed_mutation_busy')
    }
    assert.equal(selectCalls, 1)
    assert.equal(otherWrites, 0)
    assert.equal(store.selectionHydrated, false)
    for (const action of [
      () => store.createSeed('p1', PAYLOAD),
      () => store.updateSeed('p1', 'A', {}),
      () => store.selectSeed('p1', { seedId: 'A' }),
      () => store.archiveSeed('p1', 'A', {}),
      () => store.restoreSeed('p1', 'A', {}),
      () => store.permanentlyDeleteSeed('p1', 'A', {}),
    ]) await assert.rejects(action, error => error?.code === 'seed_hydration_unknown')
    assert.equal(selectCalls, 1)
    assert.equal(otherWrites, 0)
  })
})

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

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => { resolve = onResolve; reject = onReject })
  return { promise, resolve, reject }
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

test('confirmation does not replace a selected seed when server capabilities deny selection', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const calls = []

  await withFetch(async (url, options) => {
    const body = JSON.parse(options.body)
    calls.push({ path: String(url), body })
    return jsonResponse(seed('A', 1, {
      isSelected: true,
      selectionRevision: 1,
      capabilities: { ...seed('A').capabilities, canSelect: false, canEdit: false },
    }))
  }, async () => {
    store.activateProject('p1')
    store.$patch({ selectionHydrated: true, seeds: [seed('A')] })
    await store.selectSeed('p1', {
      seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0,
    })
    await assert.rejects(store.selectSeed('p1', {
      seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 1,
    }))
  })

  assert.equal(store.activeSelection.seedId, 'A')
  assert.equal(store.selectionRevision, 1)
  assert.equal(calls.length, 1)
  assert.ok(calls[0].path.endsWith('/projects/p1/selected-seed'))
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
    store.activateProject('p1')
    store.$patch({ selectionHydrated: true })
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
    store.activateProject('p1')
    store.$patch({ selectionHydrated: true, seeds: [seed('A')] })
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

test('a refresh in flight keeps mutations fail-closed until its authoritative selection returns', async () => {
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

    await assert.rejects(store.createSeed('p1', PAYLOAD, {
      idempotencyKey: 's'.repeat(64),
    }))
    assert.equal(store.mutationBusy, false)
    assert.equal(store.loading, true)
    assert.equal(store.refreshing, true)

    releaseList(jsonResponse([]))
    await refresh
    assert.deepEqual(store.seeds.map(item => item.id), [])
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
    store.activateProject('p1')
    store.$patch({ selectionHydrated: true })
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
