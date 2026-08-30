import assert from 'node:assert/strict'
import test from 'node:test'

import { createPinia, setActivePinia } from 'pinia'

import { api } from '../../src/api/db/client.js'
import { createProjectStore } from '../../src/stores/projectStore.js'


let storeSequence = 0

function deferred() {
  let resolve
  let reject
  const promise = new Promise((onResolve, onReject) => {
    resolve = onResolve
    reject = onReject
  })
  return { promise, resolve, reject }
}

function preparation(nextAction, targetPath) {
  return {
    lifecycle: 'active',
    activeSelection: 'current',
    contract: 'current',
    bible: nextAction === 'continue_bible' ? 'draft' : 'current',
    modelTasks: [
      'seed', 'planning', 'writing', 'audit',
      'summary', 'extraction', 'polish', 'market',
    ].map(taskKey => ({ taskKey, readiness: 'ready', reasons: [] })),
    capabilities: {
      viewPreparation: true,
      editContract: true,
      editBible: true,
      generateBible: true,
    },
    nextAction,
    targetPath,
    reasons: [],
  }
}

function createStore(projectApi) {
  setActivePinia(createPinia())
  storeSequence += 1
  return createProjectStore(projectApi, `project-preparation-${storeSequence}`)()
}

test('the API uses the exact encoded preparation path', async () => {
  const originalFetch = global.fetch
  const calls = []
  global.fetch = async url => {
    calls.push(String(url))
    return new Response(JSON.stringify(preparation('select_seed', null)), {
      headers: { 'content-type': 'application/json' },
    })
  }
  try {
    await api.projects.preparation('project / 一')
  } finally {
    global.fetch = originalFetch
  }
  assert.deepEqual(calls, [
    'http://127.0.0.1:8000/api/projects/project%20%2F%20%E4%B8%80/preparation',
  ])
})

test('preparation has a current-project generation and rejects late A responses', async () => {
  const pendingA = deferred()
  const b = preparation('continue_bible', '/projects/B/bible')
  const store = createStore({
    preparation: projectId => (
      projectId === 'A' ? pendingA.promise : Promise.resolve(b)
    ),
  })

  const oldLoad = store.loadPreparation('A')
  await store.loadPreparation('B')
  pendingA.resolve(preparation('continue_contract', '/projects/A/contract'))
  await oldLoad

  assert.deepEqual(store.currentPreparation, b)
  assert.equal(store.preparationProjectId, 'B')
  assert.equal(store.preparationStatus, 'ready')
  assert.equal(store.preparationError, null)
})

test('a new preparation route clears stale authority and preserves a safe retryable error', async () => {
  const a = preparation('continue_contract', '/projects/A/contract')
  const store = createStore({
    preparation: async projectId => {
      if (projectId === 'B') throw new Error('preparation unavailable')
      return a
    },
  })

  await store.loadPreparation('A')
  await assert.rejects(store.loadPreparation('B'), /preparation unavailable/)

  assert.equal(store.currentPreparation, null)
  assert.equal(store.preparationProjectId, 'B')
  assert.equal(store.preparationStatus, 'error')
  assert.match(store.preparationError.message, /unavailable/)
})

test('project library reads never issue preparation N plus one requests', async () => {
  let preparationCalls = 0
  const store = createStore({
    listActive: async () => [{ id: 'A' }, { id: 'B' }, { id: 'C' }],
    listArchived: async () => [{ id: 'D' }],
    preparation: async () => {
      preparationCalls += 1
      return preparation('select_seed', null)
    },
  })

  await store.loadActiveProjects()
  await store.loadArchivedProjects()

  assert.equal(preparationCalls, 0)
  assert.equal(store.currentPreparation, null)
})

test('a lifecycle mutation clears the preparation authority identity before reload', async () => {
  const store = createStore({
    preparation: async () => preparation('continue_contract', '/projects/A/contract'),
    archive: async projectId => ({ id: projectId, lifecycleRevision: 1 }),
  })

  await store.loadPreparation('A')
  await store.archiveProject('A', 0)

  assert.equal(store.currentPreparation, null)
  assert.equal(store.preparationProjectId, '')
  assert.equal(store.preparationStatus, 'idle')
  assert.equal(store.preparationError, null)
})

test('overview has an independent current-project generation and rejects late A responses', async () => {
  const pendingA = deferred()
  const overviewB = projectOverview({ project: { ...projectOverview().project, id: 'B', title: '项目 B' } })
  const store = createStore({
    overview: projectId => (projectId === 'A' ? pendingA.promise : Promise.resolve(overviewB)),
  })

  const oldLoad = store.loadOverview('A')
  await store.loadOverview('B')
  pendingA.resolve(projectOverview({ project: { ...projectOverview().project, id: 'A', title: '项目 A' } }))
  await oldLoad

  assert.deepEqual(store.currentOverview, overviewB)
  assert.equal(store.overviewProjectId, 'B')
  assert.equal(store.overviewStatus, 'ready')
  assert.equal(store.overviewError, null)
})

test('overview retry retains the active project identity and replaces the retryable error', async () => {
  let attempts = 0
  const overviewB = projectOverview({ project: { ...projectOverview().project, id: 'B', title: '项目 B' } })
  const store = createStore({
    overview: async projectId => {
      assert.equal(projectId, 'B')
      attempts += 1
      if (attempts === 1) throw new Error('overview unavailable')
      return overviewB
    },
  })

  await assert.rejects(store.loadOverview('B'), /overview unavailable/)
  assert.equal(store.currentOverview, null)
  assert.equal(store.overviewProjectId, 'B')
  assert.equal(store.overviewStatus, 'error')
  assert.match(store.overviewError.message, /unavailable/)

  await store.loadOverview(store.overviewProjectId)
  assert.deepEqual(store.currentOverview, overviewB)
  assert.equal(store.overviewProjectId, 'B')
  assert.equal(store.overviewStatus, 'ready')
  assert.equal(store.overviewError, null)
})

test('overview request guard is independent from preparation requests', async () => {
  const pendingOverview = deferred()
  const overviewA = projectOverview({ project: { ...projectOverview().project, id: 'A' } })
  const store = createStore({
    overview: () => pendingOverview.promise,
    preparation: async () => preparation('continue_contract', '/projects/A/contract'),
  })

  const loading = store.loadOverview('A')
  await store.loadPreparation('A')
  pendingOverview.resolve(overviewA)
  await loading

  assert.deepEqual(store.currentOverview, overviewA)
  assert.equal(store.overviewStatus, 'ready')
})

test('clearOverview only clears the matching overview identity', async () => {
  const overviewA = projectOverview({ project: { ...projectOverview().project, id: 'A' } })
  const store = createStore({ overview: async () => overviewA })
  await store.loadOverview('A')

  store.clearOverview('B')
  assert.deepEqual(store.currentOverview, overviewA)
  store.clearOverview('A')
  assert.equal(store.currentOverview, null)
  assert.equal(store.overviewProjectId, '')
  assert.equal(store.overviewStatus, 'idle')
  assert.equal(store.overviewError, null)
})

for (const [name, mutation, projectApi] of [
  ['archive', store => store.archiveProject('A', 0), { archive: async id => ({ id, lifecycleRevision: 1 }) }],
  ['restore', store => store.restoreProject('A', 1), { restore: async id => ({ id, lifecycleRevision: 2 }) }],
  ['permanent delete', store => store.permanentlyDeleteProject('A', 2), { permanentlyDelete: async () => null }],
]) {
  test(`${name} lifecycle mutation clears overview authority`, async () => {
    const overviewA = projectOverview({ project: { ...projectOverview().project, id: 'A' } })
    const store = createStore({ overview: async () => overviewA, ...projectApi })
    await store.loadOverview('A')
    await mutation(store)

    assert.equal(store.currentOverview, null)
    assert.equal(store.overviewProjectId, '')
    assert.equal(store.overviewStatus, 'idle')
    assert.equal(store.overviewError, null)
  })
}

function projectOverview(overrides = {}) {
  return Object.assign({
    project: { id: 'A', title: '典镇山河' },
    progress: {},
    modules: {},
    writerCore: {},
    continuity: {},
    recentAchievements: [],
  }, overrides)
}
