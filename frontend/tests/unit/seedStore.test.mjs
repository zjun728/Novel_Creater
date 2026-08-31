import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'
import { useSeedStore } from '../../src/stores/seedStore.js'

test('seed store names the one-time confirmation action without claiming navigation', async () => {
  const source = await readFile(new URL('../../src/stores/seedStore.js', import.meta.url), 'utf8')
  assert.match(source, /确认项目种子/)
  assert.doesNotMatch(source, /确认这个种子并进入创作契约/)
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
  targetAudience: '',
  storyPromise: '',
  longFormPotential: '',
  marketBasis: '',
})

function jsonResponse(body, status = 200) {
  return new Response(body == null ? '' : JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  })
}

function seed(id, selectionRevision = 0, overrides = {}) {
  const payload = { ...PAYLOAD, title: id, ...(overrides.payload || {}) }
  const canonicalPayload = Object.fromEntries(Object.entries(payload).sort(([left], [right]) => (left < right ? -1 : left > right ? 1 : 0)))
  const contentHash = createHash('sha256').update(JSON.stringify(canonicalPayload), 'utf8').digest('hex')
  const revision = overrides.revision ?? 1
  return {
    id,
    projectId: 'p1',
    status: 'candidate',
    revision,
    revisionId: `${id}-revision-${revision}`,
    contentHash,
    payload,
    recordedFields: ['title', 'genre', 'logline', 'protagonist', 'desire', 'coreConflict', 'worldPressure', 'openingHook', 'differentiation', 'targetAudience', 'storyPromise', 'longFormPotential', 'marketBasis'],
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

test('edit, archive, restore and eligible permanent delete are explicit writes only', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const requests = []
  let current = seed('A')

  await withFetch(async (url, options) => {
    const path = String(url).replace('http://127.0.0.1:8000/api', '')
    requests.push({ path, method: options.method })
    if (options.method === 'DELETE') return jsonResponse({ ok: true })
    const body = JSON.parse(options.body)
    const status = path.endsWith('/restore') ? 'candidate' : path.endsWith('/archive') ? 'archived' : 'candidate'
    current = seed('A', 0, {
      status,
      revision: 2,
      payload: options.method === 'PUT' ? body.payload : current.payload,
      capabilities: {
        ...seed('A').capabilities,
        canArchive: status === 'candidate',
        canRestore: status === 'archived',
      },
    })
    return jsonResponse(current)
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

test('a contradictory 2xx selection response never rewrites local selection authority', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const a = seed('A')
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([a])
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (path.endsWith('/projects/p1/selected-seed')) return jsonResponse({ ...a, isSelected: false, selectionRevision: 0 })
    throw new Error(`unexpected ${path}`)
  }, async () => {
    await store.refresh('p1')
    await assert.rejects(
      store.selectSeed('p1', { seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0 }),
      error => error?.code === 'invalid_response',
    )
    assert.equal(store.selectionHydrated, false)
    assert.equal(store.activeSelection, null)
    assert.equal(store.seeds[0].isSelected, false)
    assert.equal(store.seeds[0].selectionRevision, 0)
  })
})

test('a selected-looking create response never installs false confirmed authority', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([])
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (path.endsWith('/projects/p1/seeds') && options.method === 'POST') return jsonResponse(seed('created', 1, { isSelected: true }))
    throw new Error(`unexpected ${path}`)
  }, async () => {
    await store.refresh('p1')
    await assert.rejects(store.createSeed('p1', PAYLOAD), error => error?.code === 'invalid_response')
    assert.equal(store.selectionHydrated, false)
    assert.equal(store.activeSelection, null)
    assert.deepEqual(store.seeds, [])
  })
})

test('every ambiguous write invalidates authority while preserving the displayed rows', async () => {
  for (const operation of ['update', 'create', 'delete']) {
    setActivePinia(createPinia())
    const store = useSeedStore()
    const original = seed('A')
    await withFetch(async (url, options = {}) => {
      const path = String(url)
      if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([original])
      if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
      return jsonResponse({ code: operation === 'update' ? 'SelectionConflict' : 'outcome_unknown', message: 'ambiguous' }, operation === 'update' ? 409 : 503)
    }, async () => {
      await store.refresh('p1')
      const rowsBefore = JSON.parse(JSON.stringify(store.seeds))
      const action = operation === 'update'
        ? () => store.updateSeed('p1', 'A', { payload: PAYLOAD, expectedSeedRevision: 1, expectedSelectionRevision: 0 })
        : operation === 'create'
          ? () => store.createSeed('p1', PAYLOAD, { idempotencyKey: 'k'.repeat(64) })
          : () => store.permanentlyDeleteSeed('p1', 'A', { expectedSeedRevision: 1, expectedSelectionRevision: 0 })
      await assert.rejects(action)
      assert.equal(store.selectionHydrated, false, operation)
      assert.deepEqual(store.seeds, rowsBefore, operation)
    })
  }
})

test('refresh refuses a concurrent read without invalidating completed-write authority', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const pendingUpdate = deferred()
  let reads = 0
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') { reads += 1; return jsonResponse([seed('A', 0, { revision: 1 })]) }
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (options.method === 'PUT') return pendingUpdate.promise
    if (options.method === 'POST' && path.endsWith('/seeds/A/archive')) { const current = store.seeds.find(row => row.id === 'A'); return jsonResponse({ ...current, status: 'archived', capabilities: { ...current.capabilities, canArchive: false, canRestore: true } }) }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.refresh('p1')
    const update = store.updateSeed('p1', 'A', { payload: PAYLOAD, expectedSeedRevision: 1, expectedSelectionRevision: 0 })
    await Promise.resolve()
    await assert.rejects(store.refresh('p1'), error => error?.code === 'seed_mutation_busy')
    assert.equal(reads, 1)
    assert.equal(store.selectionHydrated, true)
    pendingUpdate.resolve(jsonResponse(seed('A', 0, { revision: 2, payload: PAYLOAD })))
    await update
    assert.equal(store.seeds.find(row => row.id === 'A').revision, 2)
    assert.equal(store.selectionHydrated, true)
    await store.archiveSeed('p1', 'A', { expectedSeedRevision: 2, expectedSelectionRevision: 0 })
    assert.equal(store.seeds.find(row => row.id === 'A').status, 'archived')
  })
})

test('cross-project refresh cannot switch projects or clear a pending write lock', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const pendingUpdate = deferred()
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([seed('A')])
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (path.endsWith('/projects/p2/seeds') && options.method === 'GET') return jsonResponse([seed('B', 0, { projectId: 'p2' })])
    if (path.endsWith('/projects/p2/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (options.method === 'PUT') return pendingUpdate.promise
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.refresh('p1')
    const update = store.updateSeed('p1', 'A', { payload: PAYLOAD, expectedSeedRevision: 1, expectedSelectionRevision: 0 })
    await Promise.resolve()
    await assert.rejects(store.refresh('p2'), error => error?.code === 'seed_mutation_busy')
    assert.equal(store.mutationBusy, true)
    assert.equal(store.seeds[0].projectId, 'p1')
    pendingUpdate.resolve(jsonResponse(seed('A', 0, { revision: 2, payload: PAYLOAD })))
    await update
    await store.refresh('p2')
    assert.equal(store.mutationBusy, false)
    assert.equal(store.seeds[0].projectId, 'p2')
  })
})

test('post-dispatch uncertain write failures invalidate authority but terminal client rejections retain it', async () => {
  for (const failure of [
    { label: 'server failure', response: () => jsonResponse({ code: 'server_error' }, 503), invalidated: true },
    { label: 'transport failure', response: () => { throw new TypeError('network unavailable') }, invalidated: true },
    { label: 'malformed response', response: () => new Response('{', { headers: { 'content-type': 'application/json' } }), invalidated: true },
    { label: 'terminal validation rejection', response: () => jsonResponse({ code: 'SeedValidationError' }, 422), invalidated: false },
  ]) {
    setActivePinia(createPinia())
    const store = useSeedStore()
    let writes = 0
    await withFetch(async (url, options = {}) => {
      const path = String(url)
      if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([seed('A')])
      if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
      if (path.endsWith('/projects/p1/seeds') && options.method === 'POST') { writes += 1; return failure.response() }
      throw new Error(`unexpected request ${url}`)
    }, async () => {
      await store.refresh('p1')
      await assert.rejects(store.createSeed('p1', PAYLOAD, { idempotencyKey: 'k'.repeat(64) }), failure.label)
      assert.equal(store.selectionHydrated, !failure.invalidated, failure.label)
      if (failure.invalidated) await assert.rejects(store.createSeed('p1', PAYLOAD), error => error?.code === 'seed_hydration_unknown')
      assert.equal(writes, 1, failure.label)
    })
  }
})

test('a cross-project mutation is rejected before activation while another project write is pending', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const pendingUpdate = deferred()
  await withFetch(async (url, options = {}) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([seed('A')])
    if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
    if (options.method === 'PUT') return pendingUpdate.promise
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    await store.refresh('p1')
    const before = JSON.parse(JSON.stringify({ seeds: store.seeds, selectionHydrated: store.selectionHydrated }))
    const pending = store.updateSeed('p1', 'A', { payload: PAYLOAD, expectedSeedRevision: 1, expectedSelectionRevision: 0 })
    await Promise.resolve()
    await assert.rejects(store.createSeed('p2', PAYLOAD), error => error?.code === 'seed_mutation_busy')
    assert.equal(store.mutationBusy, true)
    assert.deepEqual({ seeds: store.seeds, selectionHydrated: store.selectionHydrated }, before)
    pendingUpdate.resolve(jsonResponse(seed('A', 0, { revision: 2, payload: PAYLOAD })))
    await pending
  })
})

test('semantic malformed write DTOs fail closed for every Seed mutation', async () => {
  const mutations = [
    ['create', store => store.createSeed('p1', PAYLOAD, { idempotencyKey: 'k'.repeat(64) })],
    ['update', store => store.updateSeed('p1', 'A', { payload: PAYLOAD, expectedSeedRevision: 1, expectedSelectionRevision: 0 })],
    ['select', store => store.selectSeed('p1', { seedId: 'A', expectedSeedRevision: 1, expectedSelectionRevision: 0 })],
    ['archive', store => store.archiveSeed('p1', 'A', { expectedSeedRevision: 1, expectedSelectionRevision: 0 })],
    ['restore', store => store.restoreSeed('p1', 'A', { expectedSeedRevision: 1, expectedSelectionRevision: 0 }), { status: 'archived', capabilities: { ...seed('A').capabilities, canArchive: false, canRestore: true } }],
    ['delete', store => store.permanentlyDeleteSeed('p1', 'A', { expectedSeedRevision: 1, expectedSelectionRevision: 0 })],
  ]
  for (const [name, mutate, overrides = {}] of mutations) {
    setActivePinia(createPinia())
    const store = useSeedStore()
    await withFetch(async (url, options = {}) => {
      const path = String(url)
      if (path.endsWith('/projects/p1/seeds') && options.method === 'GET') return jsonResponse([seed('A', 0, overrides)])
      if (path.endsWith('/projects/p1/selected-seed') && options.method === 'GET') return jsonResponse({ activeSelection: null })
      return jsonResponse(name === 'delete' ? { ok: false } : { id: 'partial' })
    }, async () => {
      await store.refresh('p1')
      await assert.rejects(mutate(store), error => error?.code === 'invalid_response', name)
      assert.equal(store.selectionHydrated, false, name)
    })
  }
})
