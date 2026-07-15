import assert from 'node:assert/strict'
import test from 'node:test'
import { createPinia, setActivePinia } from 'pinia'

import { useSeedStore } from '../../src/stores/seedStore.js'

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

test('seed list and selected-seed loads ignore stale responses', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const pending = new Map()

  await withBrowserGuards((url) => {
    const key = String(url).replace('http://127.0.0.1:8000/api/', '')
    const response = deferred()
    pending.set(key, response)
    return response.promise
  }, async () => {
    const oldList = store.loadSeeds('old')
    const newList = store.loadSeeds('new')
    pending.get('projects/new/seeds').resolve(jsonResponse([{ id: 'new-seed' }]))
    await newList
    pending.get('projects/old/seeds').resolve(jsonResponse([{ id: 'old-seed' }]))
    await oldList
    assert.deepEqual(store.seeds, [{ id: 'new-seed' }])

    const oldSelected = store.loadSelectedSeed('old')
    const newSelected = store.loadSelectedSeed('new')
    pending.get('projects/new/selected-seed').resolve(jsonResponse({
      selected: { id: 'new-seed', revision: 2, selectionRevision: 3 },
      seedReady: true,
      contractReady: false,
      reasons: ['binding_not_verified'],
    }))
    await newSelected
    pending.get('projects/old/selected-seed').resolve(jsonResponse({
      selected: { id: 'old-seed' }, seedReady: true, contractReady: true, reasons: [],
    }))
    await oldSelected

    assert.equal(store.selectedSeed.id, 'new-seed')
    assert.deepEqual(store.readiness, {
      seedReady: true, contractReady: false, reasons: ['binding_not_verified'],
    })
  })
})

test('refresh atomically restores backend seed list, selection, and readiness without local storage', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const requests = []

  await withBrowserGuards(async (url, options) => {
    requests.push({ url: String(url), method: options.method })
    if (String(url).endsWith('/projects/p1/seeds')) {
      return jsonResponse([{ id: 's1', revision: 4, selectionRevision: 2, isSelected: true }])
    }
    if (String(url).endsWith('/projects/p1/selected-seed')) {
      return jsonResponse({
        selected: { id: 's1', revision: 4, selectionRevision: 2, isSelected: true },
        seedReady: true,
        contractReady: true,
        reasons: [],
      })
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const result = await store.refresh('p1')
    assert.equal(result.selected.id, 's1')
    assert.deepEqual(store.seeds.map(item => item.id), ['s1'])
    assert.equal(store.selectedSeed.id, 's1')
    assert.deepEqual(store.readiness, { seedReady: true, contractReady: true, reasons: [] })
    assert.deepEqual(requests.map(item => item.method), ['GET', 'GET'])
  })
})

test('refresh supersedes in-flight list and selected loads without leaving loading flags stuck', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const oldList = deferred()
  const oldSelected = deferred()
  let listCalls = 0
  let selectedCalls = 0

  await withBrowserGuards(async (url) => {
    const path = String(url)
    if (path.endsWith('/projects/p1/seeds')) {
      listCalls += 1
      return listCalls === 1
        ? oldList.promise
        : jsonResponse([{ id: 'fresh-seed', isSelected: true }])
    }
    if (path.endsWith('/projects/p1/selected-seed')) {
      selectedCalls += 1
      return selectedCalls === 1
        ? oldSelected.promise
        : jsonResponse({
            selected: { id: 'fresh-seed', isSelected: true },
            seedReady: true,
            contractReady: false,
            reasons: ['binding_not_verified'],
          })
    }
    throw new Error(`unexpected request ${url}`)
  }, async () => {
    const staleListLoad = store.loadSeeds('p1')
    const staleSelectedLoad = store.loadSelectedSeed('p1')
    assert.equal(store.loading, true)
    assert.equal(store.selectedLoading, true)

    await store.refresh('p1')

    assert.equal(store.loading, false)
    assert.equal(store.selectedLoading, false)
    assert.equal(store.refreshing, false)
    assert.equal(store.selectedSeed.id, 'fresh-seed')

    oldList.resolve(jsonResponse([{ id: 'stale-seed' }]))
    oldSelected.resolve(jsonResponse({
      selected: { id: 'stale-seed' }, seedReady: true, contractReady: true, reasons: [],
    }))
    await Promise.all([staleListLoad, staleSelectedLoad])

    assert.equal(store.loading, false)
    assert.equal(store.selectedLoading, false)
    assert.equal(store.selectedSeed.id, 'fresh-seed')
  })
})

test('seed CRUD and selection use only formal backend writes and never autosave', async () => {
  setActivePinia(createPinia())
  const store = useSeedStore()
  const requests = []
  const payload = {
    title: '典镇山河', genre: '穿越', logline: '一卷永乐大典镇山河', protagonist: '沈砚',
    desire: '活下去', coreConflict: '知识与皇权', worldPressure: '乱世',
    openingHook: '抄书即获罪', differentiation: '典籍能力有代价',
  }

  await withBrowserGuards(async (url, options) => {
    const path = String(url).replace('http://127.0.0.1:8000/api', '')
    const body = options.body ? JSON.parse(options.body) : undefined
    requests.push({ path, method: options.method, body })
    if (options.method === 'POST') {
      return jsonResponse({ id: 's1', revision: 1, selectionRevision: 0, payload })
    }
    if (options.method === 'PUT' && path.endsWith('/seeds/s1')) {
      return jsonResponse({ id: 's1', revision: 2, selectionRevision: 0, payload: { ...payload, title: '新题' } })
    }
    if (options.method === 'PUT' && path.endsWith('/selected-seed')) {
      return jsonResponse({
        id: 's1', revision: 2, selectionRevision: 1, isSelected: true,
        payload: { ...payload, title: '新题' },
      })
    }
    if (options.method === 'DELETE') return jsonResponse({ ok: true })
    throw new Error(`unexpected request ${options.method} ${path}`)
  }, async () => {
    await store.createSeed('p1', payload)
    await store.updateSeed('p1', 's1', {
      payload: { ...payload, title: '新题' }, expectedSeedRevision: 1, expectedSelectionRevision: 0,
    })
    await store.selectSeed('p1', {
      seedId: 's1', expectedSeedRevision: 2, expectedSelectionRevision: 0,
    })

    assert.equal(store.selectedSeed.id, 's1')
    assert.equal(store.selectedSeed.isSelected, true)
    assert.deepEqual(store.readiness, {
      seedReady: false,
      contractReady: false,
      reasons: ['selected_seed_status_not_reloaded'],
    })
    assert.equal(requests.filter(item => item.path.endsWith('/selected-seed')).length, 1)

    await store.deleteSeed('p1', 's1', {
      expectedSeedRevision: 2, expectedSelectionRevision: 1,
    })
    assert.equal(store.seeds.length, 0)
    assert.equal(store.selectedSeed, null)
    assert.deepEqual(requests.map(item => item.method), ['POST', 'PUT', 'PUT', 'DELETE'])
    assert.deepEqual(requests[2].body, {
      seedId: 's1', expectedSeedRevision: 2, expectedSelectionRevision: 0,
    })
  })

  assert.equal(requests.length, 4, 'field edits must not trigger automatic writes')
})

test('writes from an old project cannot mutate state after another project refresh wins', async (t) => {
  const payload = {
    title: '旧项目种子', genre: '穿越', logline: '旧项目', protagonist: '旧主角',
    desire: '旧欲望', coreConflict: '旧冲突', worldPressure: '旧压力',
    openingHook: '旧钩子', differentiation: '旧差异',
  }
  const cases = [
    {
      name: 'create',
      run: store => store.createSeed('project-a', payload),
      response: { id: 'late-created', projectId: 'project-a', payload },
    },
    {
      name: 'update',
      run: store => store.updateSeed('project-a', 'shared', {
        payload, expectedSeedRevision: 1, expectedSelectionRevision: 1,
      }),
      response: { id: 'shared', projectId: 'project-a', revision: 2, payload },
    },
    {
      name: 'delete',
      run: store => store.deleteSeed('project-a', 'shared', {
        expectedSeedRevision: 1, expectedSelectionRevision: 1,
      }),
      response: { ok: true },
    },
    {
      name: 'select',
      run: store => store.selectSeed('project-a', {
        seedId: 'shared', expectedSeedRevision: 1, expectedSelectionRevision: 1,
      }),
      response: {
        id: 'shared', projectId: 'project-a', revision: 1,
        selectionRevision: 2, isSelected: true, payload,
      },
    },
  ]

  for (const scenario of cases) {
    await t.test(scenario.name, async () => {
      setActivePinia(createPinia())
      const store = useSeedStore()
      const lateWrite = deferred()

      await withBrowserGuards(async (url, options) => {
        const path = String(url)
        const isWrite = options.method !== 'GET'
        if (path.includes('/projects/project-a/') && isWrite) return lateWrite.promise

        const projectId = path.includes('/projects/project-b/') ? 'project-b' : 'project-a'
        const seed = {
          id: 'shared', projectId, revision: 1, selectionRevision: 1,
          isSelected: true, payload: { ...payload, title: projectId },
        }
        if (path.endsWith('/seeds')) return jsonResponse([seed])
        if (path.endsWith('/selected-seed')) {
          return jsonResponse({ selected: seed, seedReady: true, contractReady: false, reasons: [] })
        }
        throw new Error(`unexpected request ${options.method} ${url}`)
      }, async () => {
        await store.refresh('project-a')
        const pendingWrite = scenario.run(store)
        await store.refresh('project-b')
        lateWrite.resolve(jsonResponse(scenario.response))
        await pendingWrite

        assert.deepEqual(store.seeds.map(seed => seed.projectId), ['project-b'])
        assert.equal(store.seeds[0].payload.title, 'project-b')
        assert.equal(store.selectedSeed.projectId, 'project-b')
        assert.notEqual(store.readiness.reasons[0], 'selected_seed_status_not_reloaded')
      })
    })
  }
})
